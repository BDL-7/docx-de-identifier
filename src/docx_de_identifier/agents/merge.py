from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from docx_de_identifier.config import AppConfig
from docx_de_identifier.models import CandidateAction, EntityCandidate, EntityType, ResolvedEntity

PRIORITY = {
    CandidateAction.REMOVE_BLOCK: 100,
    EntityType.PERSON: 80,
    EntityType.EMAIL: 70,
    EntityType.PHONE: 70,
    EntityType.ABSOLUTE_TIMESTAMP: 60,
    EntityType.RELATIVE_TIMESTAMP: 60,
    EntityType.DURATION: 60,
    EntityType.ALIAS: 50,
}


def _priority(candidate: EntityCandidate) -> int:
    if candidate.action is CandidateAction.REMOVE_BLOCK:
        return PRIORITY[CandidateAction.REMOVE_BLOCK]
    return PRIORITY[candidate.entity_type]


def normalize_person(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s,'’-]", "", normalized)
    if "," in normalized:
        last, first = normalized.split(",", 1)
        normalized = f"{first.strip()} {last.strip()}"
    return " ".join(normalized.replace("’", "'").split())


def _canonical_key(candidate: EntityCandidate) -> tuple[EntityType, str]:
    if candidate.entity_type is EntityType.PERSON:
        return candidate.entity_type, normalize_person(candidate.text)
    if candidate.entity_type in {EntityType.EMAIL, EntityType.PHONE, EntityType.ALIAS}:
        compact = re.sub(r"\W", "", candidate.text).casefold()
        return candidate.entity_type, compact
    return candidate.entity_type, f"{candidate.record_id}:{candidate.start}:{candidate.end}"


def resolve_candidates(
    candidates: list[EntityCandidate], config: AppConfig
) -> list[ResolvedEntity]:
    grouped: dict[str, list[EntityCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.record_id].append(candidate)

    accepted: list[EntityCandidate] = []
    for record_candidates in grouped.values():
        ordered = sorted(
            record_candidates,
            key=lambda item: (
                -_priority(item),
                -item.confidence,
                item.start,
                -(item.end - item.start),
            ),
        )
        chosen: list[EntityCandidate] = []
        for candidate in ordered:
            if any(candidate.span.overlaps(existing.span) for existing in chosen):
                continue
            chosen.append(candidate)
        accepted.extend(chosen)

    accepted.sort(key=lambda item: (item.record_id, item.start, item.end))
    identifiers: dict[tuple[EntityType, str], str] = {}
    type_counts: dict[EntityType, int] = defaultdict(int)
    resolved: list[ResolvedEntity] = []
    for candidate in accepted:
        key = _canonical_key(candidate)
        canonical_id = identifiers.get(key)
        if canonical_id is None:
            type_counts[candidate.entity_type] += 1
            canonical_id = (
                f"{candidate.entity_type.value.lower()}-{type_counts[candidate.entity_type]:02d}"
            )
            identifiers[key] = canonical_id
        placeholder = config.placeholders[candidate.entity_type].format(
            n=int(canonical_id.rsplit("-", 1)[1])
        )
        resolved.append(
            ResolvedEntity(
                candidate=candidate,
                canonical_id=canonical_id,
                placeholder=placeholder,
            )
        )
    return resolved


def merge_agent(state: dict[str, object], config: AppConfig) -> dict[str, object]:
    candidates = state.get("candidates", [])
    if not isinstance(candidates, list) or not all(
        isinstance(item, EntityCandidate) for item in candidates
    ):
        raise TypeError("state.candidates must contain EntityCandidate values")
    return {"resolved_entities": resolve_candidates(candidates, config)}
