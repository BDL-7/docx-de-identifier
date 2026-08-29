from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from docx import Document
from lxml import etree

from docx_de_identifier.audit import file_sha256
from docx_de_identifier.docx_xml import ingest_docx

FORBIDDEN_PART_PREFIXES = (
    "word/header",
    "word/footer",
    "word/comments",
    "word/footnotes",
    "word/endnotes",
    "word/media/",
    "word/embeddings/",
    "word/charts/",
    "word/diagrams/",
)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
FORBIDDEN_XML_TAGS = {
    f"{W}ins",
    f"{W}del",
    f"{W}moveFrom",
    f"{W}moveTo",
    f"{W}txbxContent",
    f"{W}drawing",
    f"{W}pict",
    f"{W}object",
    f"{W}commentReference",
    f"{W}footnoteReference",
    f"{W}endnoteReference",
}
AUDIT_KEYS = {
    "tool",
    "version",
    "spacy_model",
    "source_sha256",
    "output_sha256",
    "removed_content",
    "events",
}
AUDIT_EVENT_KEYS = {
    "entity_type",
    "record_id",
    "start",
    "end",
    "source",
    "confidence",
    "canonical_id",
    "action",
    "placeholder",
    "value_hash",
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SAFE_CATEGORY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


def body_hyperlinks(path: Path) -> tuple[tuple[str, str, str, str], ...]:
    with ZipFile(path) as archive:
        document = etree.fromstring(archive.read("word/document.xml"))
        relationship_name = "word/_rels/document.xml.rels"
        relationships = (
            etree.fromstring(archive.read(relationship_name))
            if relationship_name in archive.namelist()
            else None
        )

    targets = {
        relationship.get("Id", ""): (
            relationship.get("Target", ""),
            relationship.get("TargetMode", ""),
        )
        for relationship in (
            relationships.iter(f"{PR}Relationship") if relationships is not None else ()
        )
    }
    body = document.find(f"{W}body")
    if body is None:
        raise ValueError("DOCX main document has no body")

    result: list[tuple[str, str, str, str]] = []
    for hyperlink in body.iter(f"{W}hyperlink"):
        relationship_id = hyperlink.get(f"{R}id", "")
        if relationship_id and relationship_id not in targets:
            raise ValueError("Body hyperlink has no relationship target")
        target, target_mode = targets.get(relationship_id, ("", ""))
        anchor = hyperlink.get(f"{W}anchor", "")
        display_text = "".join(node.text or "" for node in hyperlink.iter(f"{W}t"))
        result.append((display_text, target, target_mode, anchor))
    return tuple(result)


def _require_object(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(message)
    return value


def _validate_audit(source: Path, output: Path, audit: Path, expected_source_sha256: str) -> int:
    audit_text = audit.read_text(encoding="utf-8")
    document = _require_object(json.loads(audit_text), "Audit must be a JSON object")
    if set(document) != AUDIT_KEYS:
        raise ValueError("Audit contains unexpected or missing fields")
    if document["tool"] != "docx-de-identifier":
        raise ValueError("Audit tool identifier is invalid")
    if document["source_sha256"] != expected_source_sha256:
        raise ValueError("Audit source hash does not match the source")
    if document["output_sha256"] != file_sha256(output):
        raise ValueError("Audit output hash does not match the output")

    removed_content = document["removed_content"]
    if not isinstance(removed_content, list) or not all(
        isinstance(item, str) and SAFE_CATEGORY_PATTERN.fullmatch(item) for item in removed_content
    ):
        raise ValueError("Audit removed-content categories are invalid")

    events = document["events"]
    if not isinstance(events, list):
        raise ValueError("Audit events must be a list")
    context = ingest_docx(source)
    for raw_event in events:
        event = _require_object(raw_event, "Audit event must be an object")
        if set(event) != AUDIT_EVENT_KEYS:
            raise ValueError("Audit event contains unexpected or missing fields")
        record_id = event["record_id"]
        start = event["start"]
        end = event["end"]
        value_hash = event["value_hash"]
        if (
            not isinstance(record_id, str)
            or type(start) is not int
            or type(end) is not int
            or not isinstance(value_hash, str)
            or SHA256_PATTERN.fullmatch(value_hash) is None
        ):
            raise ValueError("Audit event location or hash is invalid")
        binding = context.bindings.get(record_id)
        if binding is None or not 0 <= start < end <= len(binding.record.text):
            raise ValueError("Audit event does not map to a source span")
        detected_value = binding.record.text[start:end]
        if detected_value in audit_text:
            raise ValueError("Audit contains a raw detected value")
    return len(events)


def validate_trial_artifacts(
    source: Path,
    output: Path,
    audit: Path,
    expected_source_sha256: str,
) -> dict[str, object]:
    current_source_sha256 = file_sha256(source)
    if current_source_sha256 != expected_source_sha256:
        raise ValueError("Source document changed during the trial")
    validate_sanitized_docx(output)
    source_hyperlinks = body_hyperlinks(source)
    if body_hyperlinks(output) != source_hyperlinks:
        raise ValueError("Body hyperlink display text or targets changed")
    event_count = _validate_audit(source, output, audit, expected_source_sha256)

    temporary_outputs = list(output.parent.glob(f".{output.stem}.*.docx"))
    if temporary_outputs or audit.with_name(f".{audit.name}.tmp").exists():
        raise ValueError("Temporary trial artifacts remain")
    return {
        "source": {
            "name": source.name,
            "size_bytes": source.stat().st_size,
            "sha256": current_source_sha256,
        },
        "output": {
            "name": output.name,
            "size_bytes": output.stat().st_size,
            "sha256": file_sha256(output),
        },
        "audit_name": audit.name,
        "audit_event_count": event_count,
        "body_hyperlink_count": len(source_hyperlinks),
        "source_unchanged": True,
        "sanitized_package_valid": True,
        "body_hyperlinks_preserved": True,
        "audit_privacy_valid": True,
        "temporary_artifacts_absent": True,
    }


def validate_sanitized_docx(path: Path) -> None:
    try:
        Document(str(path))
        with ZipFile(path) as archive:
            names = archive.namelist()
            forbidden_parts = [name for name in names if name.startswith(FORBIDDEN_PART_PREFIXES)]
            if forbidden_parts:
                raise ValueError(f"Sanitized DOCX retains forbidden parts: {forbidden_parts}")
            for name in names:
                if not name.endswith(".xml"):
                    continue
                root = etree.fromstring(archive.read(name))
                forbidden_tag = next(
                    (element.tag for element in root.iter() if element.tag in FORBIDDEN_XML_TAGS),
                    None,
                )
                if forbidden_tag is not None:
                    raise ValueError(
                        f"Sanitized DOCX retains {forbidden_tag} in package part {name}"
                    )
    except (BadZipFile, KeyError) as error:
        raise ValueError("Output is not a valid DOCX package") from error
