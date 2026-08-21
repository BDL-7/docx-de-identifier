from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml.etree import _Element

from docx_de_identifier.models import CandidateAction, ParagraphRecord, ResolvedEntity, TextRange

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
EXCLUDED_ANCESTORS = {
    f"{W}ins",
    f"{W}del",
    f"{W}moveFrom",
    f"{W}moveTo",
    f"{W}txbxContent",
}
REVISION_TAGS = {
    f"{W}ins",
    f"{W}del",
    f"{W}moveFrom",
    f"{W}moveTo",
    f"{W}moveFromRangeStart",
    f"{W}moveFromRangeEnd",
    f"{W}moveToRangeStart",
    f"{W}moveToRangeEnd",
}
REFERENCE_TAGS = {
    f"{W}commentRangeStart",
    f"{W}commentRangeEnd",
    f"{W}commentReference",
    f"{W}footnoteReference",
    f"{W}endnoteReference",
}
VISUAL_TAGS = {
    f"{W}drawing",
    f"{W}pict",
    f"{W}object",
}
REMOVED_RELATIONSHIP_TYPES = {
    RT.HEADER,
    RT.FOOTER,
    RT.COMMENTS,
    RT.FOOTNOTES,
    RT.ENDNOTES,
    RT.IMAGE,
    RT.CHART,
    RT.OLE_OBJECT,
    RT.PACKAGE,
}


@dataclass(slots=True)
class TextNodeSlice:
    node: _Element
    start: int
    end: int


@dataclass(slots=True)
class BoundParagraph:
    record: ParagraphRecord
    paragraph: Paragraph
    nodes: list[TextNodeSlice]


@dataclass(slots=True)
class DocumentContext:
    document: DocumentObject
    bindings: dict[str, BoundParagraph]
    removed_content: list[str]

    def save(self, path: Path) -> None:
        self.document.save(str(path))


def _remove_element(element: _Element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _drop_relationships(document: DocumentObject) -> list[str]:
    removed: list[str] = []
    for relationship_id, relationship in list(document.part.rels.items()):
        reltype = relationship.reltype
        should_remove = reltype in REMOVED_RELATIONSHIP_TYPES or any(
            marker in reltype for marker in ("/diagram", "/comments", "/footnotes", "/endnotes")
        )
        if should_remove:
            removed.append(reltype.rsplit("/", 1)[-1])
            document.part.drop_rel(relationship_id)
    return removed


def _sanitize_core_properties(document: DocumentObject) -> None:
    properties = document.core_properties
    for attribute in (
        "author",
        "category",
        "comments",
        "content_status",
        "identifier",
        "keywords",
        "language",
        "last_modified_by",
        "subject",
        "title",
        "version",
    ):
        setattr(properties, attribute, "")


def strip_excluded_content(document: DocumentObject) -> list[str]:
    root = document.element
    removed: list[str] = []

    for reference in list(root.xpath(".//w:headerReference | .//w:footerReference")):
        removed.append("header_or_footer_reference")
        _remove_element(reference)
    for element in list(root.iter()):
        if element.tag in REVISION_TAGS:
            removed.append("tracked_change")
            _remove_element(element)
        elif element.tag in REFERENCE_TAGS:
            removed.append(element.tag.removeprefix(W))
            _remove_element(element)
        elif element.tag in VISUAL_TAGS:
            removed.append("visual_or_embedded_content")
            _remove_element(element)

    removed.extend(_drop_relationships(document))
    _sanitize_core_properties(document)
    return sorted(set(removed))


def _is_excluded_text_node(node: _Element) -> bool:
    return any(ancestor.tag in EXCLUDED_ANCESTORS for ancestor in node.iterancestors())


def _is_hyperlink_text_node(node: _Element) -> bool:
    return any(ancestor.tag == f"{W}hyperlink" for ancestor in node.iterancestors())


def _bind_paragraph(paragraph: Paragraph, record_id: str) -> BoundParagraph:
    text_parts: list[str] = []
    nodes: list[TextNodeSlice] = []
    hyperlink_ranges: list[TextRange] = []
    hyperlink_start: int | None = None
    offset = 0

    for node in paragraph._p.xpath(".//w:t"):
        if _is_excluded_text_node(node):
            continue
        value = node.text or ""
        start = offset
        offset += len(value)
        text_parts.append(value)
        nodes.append(TextNodeSlice(node=node, start=start, end=offset))
        in_hyperlink = _is_hyperlink_text_node(node)
        if in_hyperlink and hyperlink_start is None:
            hyperlink_start = start
        elif not in_hyperlink and hyperlink_start is not None:
            hyperlink_ranges.append(TextRange(hyperlink_start, start))
            hyperlink_start = None
    if hyperlink_start is not None:
        hyperlink_ranges.append(TextRange(hyperlink_start, offset))

    record = ParagraphRecord(
        record_id=record_id,
        text="".join(text_parts),
        hyperlink_ranges=tuple(hyperlink_ranges),
    )
    return BoundParagraph(record=record, paragraph=paragraph, nodes=nodes)


def ingest_docx(path: Path) -> DocumentContext:
    document = Document(str(path))
    removed = strip_excluded_content(document)
    bindings: dict[str, BoundParagraph] = {}
    for index, paragraph_element in enumerate(document.element.body.xpath(".//w:p")):
        if any(
            ancestor.tag in EXCLUDED_ANCESTORS for ancestor in paragraph_element.iterancestors()
        ):
            continue
        record_id = f"body-{index:05d}"
        paragraph = Paragraph(paragraph_element, document.element.body)
        bindings[record_id] = _bind_paragraph(paragraph, record_id)
    return DocumentContext(document=document, bindings=bindings, removed_content=removed)


def _clear_paragraph(bound: BoundParagraph) -> None:
    paragraph_element = bound.paragraph._p
    for child in list(paragraph_element):
        if child.tag != qn("w:pPr"):
            paragraph_element.remove(child)


def _replace_span(bound: BoundParagraph, start: int, end: int, replacement: str) -> None:
    affected = [node for node in bound.nodes if node.start < end and start < node.end]
    if not affected:
        raise ValueError(f"No XML text nodes map to {bound.record.record_id}:{start}-{end}")
    first = True
    for mapped in affected:
        value = mapped.node.text or ""
        local_start = max(start, mapped.start) - mapped.start
        local_end = min(end, mapped.end) - mapped.start
        inserted = replacement if first else ""
        mapped.node.text = value[:local_start] + inserted + value[local_end:]
        first = False


def apply_resolved_entities(context: DocumentContext, entities: list[ResolvedEntity]) -> None:
    by_record: dict[str, list[ResolvedEntity]] = {}
    for entity in entities:
        by_record.setdefault(entity.candidate.record_id, []).append(entity)
    for record_id, record_entities in by_record.items():
        bound = context.bindings[record_id]
        if any(
            entity.candidate.action is CandidateAction.REMOVE_BLOCK for entity in record_entities
        ):
            _clear_paragraph(bound)
            continue
        for entity in sorted(record_entities, key=lambda item: item.candidate.start, reverse=True):
            _replace_span(
                bound,
                entity.candidate.start,
                entity.candidate.end,
                entity.placeholder,
            )
