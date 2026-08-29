from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from docx_de_identifier.config import AppConfig
from docx_de_identifier.models import (
    CandidateAction,
    DetectionResult,
    EntityCandidate,
    EntityType,
    ParagraphRecord,
    TextRange,
)

URL_PATTERN = re.compile(r"\b(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
)
REACTION_PATTERN = re.compile(r"^.*\breacted\s+with\b.*$", re.IGNORECASE | re.MULTILINE)
HEADER_PATTERN = re.compile(
    r"^(?P<name>[A-Z][A-Za-z'’-]+,\s*[A-Z][A-Za-z'’-]+)"
    r"(?P<codes>(?:\s*\([^()\r\n]+\))+)",
    re.MULTILINE,
)
ALIAS_PATTERN = re.compile(r"\([^()\r\n]+\)")
ABSOLUTE_TIMESTAMP_PATTERNS = (
    re.compile(
        r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:19|20)\d{2}"
        r"(?:\s+(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?[AP]M)?)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|"
        r"November|December)\s+\d{1,2},\s+(?:19|20)\d{2}"
        r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}\s?[AP]M)?\b",
        re.IGNORECASE,
    ),
)
DURATION_PATTERN = re.compile(
    r"\b\d+\s*(?:hours?|hrs?|minutes?|mins?|seconds?|secs?)"
    r"(?:\s+\d+\s*(?:minutes?|mins?|seconds?|secs?))?\b",
    re.IGNORECASE,
)
RELATIVE_TIMESTAMP_PATTERNS = (
    re.compile(r"\b(?:Yesterday|Today)(?:\s+at\s+\d{1,2}:\d{2}\s?[AP]M)?\b", re.I),
    re.compile(r"\b\d+\s*(?:hours?|days?|weeks?)\s+ago\b", re.I),
)


class SpanMatch(Protocol):
    def span(self) -> tuple[int, int]: ...

    def group(self) -> str: ...


def _overlaps_any(span: TextRange, exclusions: Iterable[TextRange]) -> bool:
    return any(span.overlaps(exclusion) for exclusion in exclusions)


def _candidate(
    record: ParagraphRecord,
    match: SpanMatch,
    entity_type: EntityType,
    confidence: float,
    source: str,
    exclusions: tuple[TextRange, ...],
    action: CandidateAction = CandidateAction.REPLACE,
) -> EntityCandidate | None:
    span = TextRange(*match.span())
    if _overlaps_any(span, exclusions):
        return None
    return EntityCandidate(
        record_id=record.record_id,
        start=span.start,
        end=span.end,
        text=match.group(),
        entity_type=entity_type,
        confidence=confidence,
        source=source,
        action=action,
    )


def detect_record(record: ParagraphRecord, config: AppConfig) -> DetectionResult:
    plaintext_urls = tuple(TextRange(*match.span()) for match in URL_PATTERN.finditer(record.text))
    exclusions = tuple(
        sorted((*record.hyperlink_ranges, *plaintext_urls), key=lambda span: span.start)
    )
    candidates: list[EntityCandidate] = []

    for match in REACTION_PATTERN.finditer(record.text):
        item = _candidate(
            record,
            match,
            EntityType.REACTION_LINE,
            1.0,
            "regex.reaction",
            exclusions,
            CandidateAction.REMOVE_BLOCK,
        )
        if item:
            candidates.append(item)

    for pattern, entity_type, confidence, source in (
        (EMAIL_PATTERN, EntityType.EMAIL, 0.99, "regex.email"),
        (PHONE_PATTERN, EntityType.PHONE, 0.98, "regex.phone"),
    ):
        for match in pattern.finditer(record.text):
            item = _candidate(record, match, entity_type, confidence, source, exclusions)
            if item:
                candidates.append(item)

    for match in HEADER_PATTERN.finditer(record.text):
        local_name_match = re.match(r".+", match.group("name"))
        assert local_name_match is not None
        name_match = _OffsetMatch(local_name_match, match.start("name"))
        item = _candidate(record, name_match, EntityType.PERSON, 1.0, "regex.header", exclusions)
        if item:
            candidates.append(item)
        if config.redact_alias_codes:
            for alias in ALIAS_PATTERN.finditer(match.group("codes")):
                offset_match = _OffsetMatch(alias, match.start("codes"))
                item = _candidate(
                    record, offset_match, EntityType.ALIAS, 0.98, "regex.header_alias", exclusions
                )
                if item:
                    candidates.append(item)

    if config.redact_absolute_timestamps:
        for pattern in ABSOLUTE_TIMESTAMP_PATTERNS:
            for match in pattern.finditer(record.text):
                item = _candidate(
                    record,
                    match,
                    EntityType.ABSOLUTE_TIMESTAMP,
                    0.97,
                    "regex.absolute_timestamp",
                    exclusions,
                )
                if item:
                    candidates.append(item)

    if config.redact_relative_timestamps:
        for match in DURATION_PATTERN.finditer(record.text):
            item = _candidate(
                record, match, EntityType.DURATION, 0.95, "regex.duration", exclusions
            )
            if item:
                candidates.append(item)
        for pattern in RELATIVE_TIMESTAMP_PATTERNS:
            for match in pattern.finditer(record.text):
                item = _candidate(
                    record,
                    match,
                    EntityType.RELATIVE_TIMESTAMP,
                    0.96,
                    "regex.relative_timestamp",
                    exclusions,
                )
                if item:
                    candidates.append(item)

    return DetectionResult(candidates=candidates, url_ranges={record.record_id: exclusions})


class _OffsetMatch:
    def __init__(self, match: re.Match[str], offset: int) -> None:
        self._match = match
        self._offset = offset

    def span(self) -> tuple[int, int]:
        start, end = self._match.span()
        return start + self._offset, end + self._offset

    def group(self) -> str:
        return self._match.group()


def regex_detection_agent(state: dict[str, object], config: AppConfig) -> dict[str, object]:
    records = state.get("paragraphs", [])
    if not isinstance(records, list) or not all(
        isinstance(item, ParagraphRecord) for item in records
    ):
        raise TypeError("state.paragraphs must contain ParagraphRecord values")
    candidates: list[EntityCandidate] = []
    for record in records:
        candidates.extend(detect_record(record, config).candidates)
    return {"candidates": candidates}
