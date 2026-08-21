from __future__ import annotations

from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from docx_de_identifier.agents.ingestion import ingestion_agent
from docx_de_identifier.agents.llm_disambiguate import Classifier, llm_disambiguation_agent
from docx_de_identifier.agents.merge import merge_agent
from docx_de_identifier.agents.ner_detect import NlpCallable, ner_detection_agent
from docx_de_identifier.agents.redact import redact_agent
from docx_de_identifier.agents.regex_detect import regex_detection_agent
from docx_de_identifier.config import AppConfig
from docx_de_identifier.models import EntityType, PipelineState, ResolvedEntity


def route_after_merge(state: PipelineState, config: AppConfig) -> Literal["llm", "redact"]:
    if not config.llm.enabled:
        return "redact"
    entities = state.get("resolved_entities", [])
    has_low_confidence_person = any(
        isinstance(item, ResolvedEntity)
        and item.candidate.entity_type is EntityType.PERSON
        and item.candidate.confidence < 0.9
        for item in entities
    )
    return "llm" if has_low_confidence_person else "redact"


def build_graph(
    config: AppConfig,
    *,
    nlp: NlpCallable | None = None,
    classifier: Classifier | None = None,
) -> CompiledStateGraph:  # type: ignore[type-arg]
    builder = StateGraph(PipelineState)
    builder.add_node("ingestion", cast(Any, ingestion_agent))
    builder.add_node("regex", lambda state: regex_detection_agent(state, config))
    builder.add_node("ner", lambda state: ner_detection_agent(state, config, nlp))
    builder.add_node("merge", lambda state: merge_agent(state, config))
    builder.add_node("llm", lambda state: llm_disambiguation_agent(state, config, classifier))
    builder.add_node("redact", cast(Any, redact_agent))
    builder.add_edge(START, "ingestion")
    builder.add_edge("ingestion", "regex")
    builder.add_edge("regex", "ner")
    builder.add_edge("ner", "merge")
    builder.add_conditional_edges(
        "merge",
        lambda state: route_after_merge(state, config),
        {"llm": "llm", "redact": "redact"},
    )
    builder.add_edge("llm", "redact")
    builder.add_edge("redact", END)
    return builder.compile()
