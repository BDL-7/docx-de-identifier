from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from docx_de_identifier import __version__
from docx_de_identifier.models import AuditEvent


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_audit_document(
    source_path: Path,
    output_path: Path,
    removed_content: list[str],
    events: list[AuditEvent],
    spacy_model: str,
) -> dict[str, Any]:
    return {
        "tool": "docx-de-identifier",
        "version": __version__,
        "spacy_model": spacy_model,
        "source_sha256": file_sha256(source_path),
        "output_sha256": file_sha256(output_path),
        "removed_content": sorted(set(removed_content)),
        "events": [asdict(event) for event in events],
    }


def write_audit(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
