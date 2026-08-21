from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol, cast

import spacy

from docx_de_identifier.config import AppConfig
from docx_de_identifier.models import EntityCandidate, EntityType, ParagraphRecord, TextRange


class EntityLike(Protocol):
    text: str
    label_: str
    start_char: int
    end_char: int


class DocLike(Protocol):
    @property
    def ents(self) -> Iterable[EntityLike]: ...


NlpCallable = Callable[[str], DocLike]


def _overlaps_hyperlink(start: int, end: int, ranges: tuple[TextRange, ...]) -> bool:
    candidate = TextRange(start, end)
    return any(candidate.overlaps(item) for item in ranges)


def detect_people(record: ParagraphRecord, nlp: NlpCallable) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    for entity in nlp(record.text).ents:
        if entity.label_ != "PERSON" or _overlaps_hyperlink(
            entity.start_char, entity.end_char, record.hyperlink_ranges
        ):
            continue
        candidates.append(
            EntityCandidate(
                record_id=record.record_id,
                start=entity.start_char,
                end=entity.end_char,
                text=entity.text,
                entity_type=EntityType.PERSON,
                confidence=0.85,
                source="spacy.ner",
            )
        )
    return candidates


def ner_detection_agent(
    state: dict[str, object], config: AppConfig, nlp: NlpCallable | None = None
) -> dict[str, object]:
    records = state.get("paragraphs", [])
    if not isinstance(records, list) or not all(
        isinstance(item, ParagraphRecord) for item in records
    ):
        raise TypeError("state.paragraphs must contain ParagraphRecord values")
    if nlp is None:
        try:
            loaded_nlp = spacy.load(config.spacy_model)
        except OSError as error:
            raise RuntimeError(
                f"Local spaCy model '{config.spacy_model}' is not installed. "
                f"Install it before running: python -m spacy download {config.spacy_model}"
            ) from error
        nlp = cast(NlpCallable, loaded_nlp)
    assert nlp is not None
    existing = state.get("candidates", [])
    if not isinstance(existing, list):
        raise TypeError("state.candidates must be a list")
    candidates = list(existing)
    for record in records:
        candidates.extend(detect_people(record, nlp))
    return {"candidates": candidates}
