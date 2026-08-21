from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from docx_de_identifier.docx_xml import DocumentContext, apply_resolved_entities
from docx_de_identifier.models import AuditEvent, ResolvedEntity


def redact_agent(state: dict[str, object]) -> dict[str, object]:
    context = state.get("document_context")
    entities = state.get("resolved_entities", [])
    output_path = state.get("output_path")
    if not isinstance(context, DocumentContext):
        raise TypeError("state.document_context must be a DocumentContext")
    if not isinstance(entities, list) or not all(
        isinstance(item, ResolvedEntity) for item in entities
    ):
        raise TypeError("state.resolved_entities must contain ResolvedEntity values")
    if not isinstance(output_path, str):
        raise TypeError("state.output_path must be a string")

    apply_resolved_entities(context, entities)
    context.save(Path(output_path))
    salt = secrets.token_bytes(16)
    events = [
        AuditEvent(
            entity_type=item.candidate.entity_type,
            record_id=item.candidate.record_id,
            start=item.candidate.start,
            end=item.candidate.end,
            source=item.candidate.source,
            confidence=item.candidate.confidence,
            canonical_id=item.canonical_id,
            action=item.candidate.action,
            placeholder=item.placeholder,
            value_hash=hashlib.sha256(salt + item.candidate.text.encode("utf-8")).hexdigest(),
        )
        for item in entities
    ]
    return {"audit_events": events}
