from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from docx_de_identifier.models import EntityType

DEFAULT_PLACEHOLDERS = {
    EntityType.PERSON: "[PERSON_{n:02d}]",
    EntityType.EMAIL: "[EMAIL_{n:02d}]",
    EntityType.PHONE: "[PHONE_{n:02d}]",
    EntityType.ALIAS: "[ALIAS_{n:02d}]",
    EntityType.ABSOLUTE_TIMESTAMP: "[TIMESTAMP_{n:02d}]",
    EntityType.RELATIVE_TIMESTAMP: "[TIMESTAMP_{n:02d}]",
    EntityType.DURATION: "[DURATION_{n:02d}]",
    EntityType.REACTION_LINE: "",
}
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"


@dataclass(frozen=True, slots=True)
class LlmConfig:
    enabled: bool = False
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT
    model: str = ""
    reject_threshold: float = 0.9


@dataclass(frozen=True, slots=True)
class AppConfig:
    redact_alias_codes: bool = True
    redact_relative_timestamps: bool = True
    redact_absolute_timestamps: bool = True
    spacy_model: str = "en_core_web_sm"
    placeholders: dict[EntityType, str] = field(default_factory=lambda: dict(DEFAULT_PLACEHOLDERS))
    url_allowlist_patterns: tuple[str, ...] = ()
    audit_suffix: str = ".audit.json"
    llm: LlmConfig = field(default_factory=LlmConfig)


def _require_loopback(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Ollama endpoint must be an HTTP URL")
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.casefold() == "localhost"
    if not is_loopback:
        raise ValueError("Ollama endpoint must resolve explicitly to localhost or loopback")


def load_config(path: Path | None = None) -> AppConfig:
    raw: dict[str, Any] = {}
    if path is not None:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is not None and not isinstance(loaded, dict):
            raise ValueError("Configuration root must be a mapping")
        raw = loaded or {}

    llm_raw = raw.get("llm", {})
    if not isinstance(llm_raw, dict):
        raise ValueError("llm configuration must be a mapping")
    llm = LlmConfig(
        enabled=bool(raw.get("enable_llm_disambiguation", llm_raw.get("enabled", False))),
        endpoint=str(llm_raw.get("endpoint", DEFAULT_OLLAMA_ENDPOINT)),
        model=str(llm_raw.get("model", "")),
        reject_threshold=float(llm_raw.get("reject_threshold", 0.9)),
    )
    _require_loopback(llm.endpoint)
    if not 0.5 <= llm.reject_threshold <= 1.0:
        raise ValueError("llm.reject_threshold must be between 0.5 and 1.0")

    placeholders = dict(DEFAULT_PLACEHOLDERS)
    for key, value in raw.get("placeholder_format", {}).items():
        placeholders[EntityType(key)] = str(value)

    return AppConfig(
        redact_alias_codes=bool(raw.get("redact_alias_codes", True)),
        redact_relative_timestamps=bool(raw.get("redact_relative_timestamps", True)),
        redact_absolute_timestamps=bool(raw.get("redact_absolute_timestamps", True)),
        spacy_model=str(raw.get("spacy_model", "en_core_web_sm")),
        placeholders=placeholders,
        url_allowlist_patterns=tuple(map(str, raw.get("url_allowlist_patterns", []))),
        audit_suffix=str(raw.get("audit_suffix", ".audit.json")),
        llm=llm,
    )
