from __future__ import annotations

from pathlib import Path

from docx_de_identifier.docx_xml import ingest_docx


def ingestion_agent(state: dict[str, object]) -> dict[str, object]:
    docx_path = state.get("docx_path")
    if not isinstance(docx_path, str):
        raise TypeError("state.docx_path must be a string")
    context = ingest_docx(Path(docx_path))
    return {
        "document_context": context,
        "paragraphs": [binding.record for binding in context.bindings.values()],
        "removed_content": context.removed_content,
    }
