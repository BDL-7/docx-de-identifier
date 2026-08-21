from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from lxml import etree

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
