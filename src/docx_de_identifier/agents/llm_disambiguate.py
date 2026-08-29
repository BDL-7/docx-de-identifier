from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import Request, urlopen

from docx_de_identifier.config import AppConfig
from docx_de_identifier.models import EntityType, ResolvedEntity


@dataclass(frozen=True, slots=True)
class Classification:
    is_person: bool
    confidence: float


Classifier = Callable[[str], Classification]


def ollama_classifier(config: AppConfig) -> Classifier:
    def classify(text: str) -> Classification:
        schema = {
            "type": "object",
            "properties": {
                "is_person": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["is_person", "confidence"],
            "additionalProperties": False,
        }
        payload = {
            "model": config.llm.model,
            "stream": False,
            "format": schema,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify whether the supplied span is a person's name. "
                        "Return only the requested structured output."
                    ),
                },
                {"role": "user", "content": text},
            ],
        }
        request = Request(
            f"{config.llm.endpoint.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:  # noqa: S310 - endpoint is validated loopback
            response_payload = json.loads(response.read().decode("utf-8"))
        content = json.loads(response_payload["message"]["content"])
        result = Classification(
            is_person=content["is_person"], confidence=float(content["confidence"])
        )
        if not isinstance(result.is_person, bool) or not 0 <= result.confidence <= 1:
            raise ValueError("Ollama returned an invalid classification")
        return result

    return classify


def disambiguate_entities(
    entities: list[ResolvedEntity], config: AppConfig, classifier: Classifier
) -> list[ResolvedEntity]:
    retained: list[ResolvedEntity] = []
    for entity in entities:
        candidate = entity.candidate
        if candidate.entity_type is not EntityType.PERSON or candidate.confidence >= 0.9:
            retained.append(entity)
            continue
        try:
            result = classifier(candidate.text)
        except (OSError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            retained.append(entity)
            continue
        if result.is_person or result.confidence < config.llm.reject_threshold:
            retained.append(entity)
    return retained


def llm_disambiguation_agent(
    state: dict[str, object], config: AppConfig, classifier: Classifier | None = None
) -> dict[str, object]:
    entities = state.get("resolved_entities", [])
    if not isinstance(entities, list) or not all(
        isinstance(item, ResolvedEntity) for item in entities
    ):
        raise TypeError("state.resolved_entities must contain ResolvedEntity values")
    active_classifier = classifier or ollama_classifier(config)
    return {"resolved_entities": disambiguate_entities(entities, config, active_classifier)}
