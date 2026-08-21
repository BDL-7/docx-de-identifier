from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, NotRequired, TypedDict


class EntityType(StrEnum):
    PERSON = "PERSON"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ALIAS = "ALIAS"
    ABSOLUTE_TIMESTAMP = "ABSOLUTE_TIMESTAMP"
    RELATIVE_TIMESTAMP = "RELATIVE_TIMESTAMP"
    DURATION = "DURATION"
    REACTION_LINE = "REACTION_LINE"


class CandidateAction(StrEnum):
    REPLACE = "replace"
    REMOVE_BLOCK = "remove_block"


@dataclass(frozen=True, slots=True)
class TextRange:
    start: int
    end: int

    def overlaps(self, other: TextRange) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True, slots=True)
class ParagraphRecord:
    record_id: str
    text: str
    part_name: str = "/word/document.xml"
    hyperlink_ranges: tuple[TextRange, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    record_id: str
    start: int
    end: int
    text: str
    entity_type: EntityType
    confidence: float
    source: str
    action: CandidateAction = CandidateAction.REPLACE

    @property
    def span(self) -> TextRange:
        return TextRange(self.start, self.end)


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    candidate: EntityCandidate
    canonical_id: str
    placeholder: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    entity_type: EntityType
    record_id: str
    start: int
    end: int
    source: str
    confidence: float
    canonical_id: str
    action: CandidateAction
    placeholder: str
    value_hash: str


class PipelineState(TypedDict):
    docx_path: str
    output_path: str
    paragraphs: NotRequired[list[ParagraphRecord]]
    candidates: NotRequired[list[EntityCandidate]]
    resolved_entities: NotRequired[list[ResolvedEntity]]
    removed_content: NotRequired[list[str]]
    audit_events: NotRequired[list[AuditEvent]]
    document_context: NotRequired[Any]


@dataclass(slots=True)
class DetectionResult:
    candidates: list[EntityCandidate] = field(default_factory=list)
    url_ranges: dict[str, tuple[TextRange, ...]] = field(default_factory=dict)
