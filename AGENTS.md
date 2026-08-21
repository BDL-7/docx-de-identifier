# Agent Instructions

## Purpose

`docx-de-identifier` is a Python CLI that removes identifying information from Word documents through a graph of specialized, independently testable agents.

## Hard Constraints

- Runtime processing is fully offline. Never add hosted APIs, telemetry, LangSmith tracing, or automatic model downloads.
- Ollama is optional and must be restricted to an explicit loopback endpoint.
- Preserve ordinary body and nested-table prose unless a resolved entity requires redaction.
- Preserve body hyperlink display text and relationship targets exactly.
- Remove headers, footers, comments, footnotes/endnotes, text boxes, all tracked-change markup and revision content, images, drawings, charts, SmartArt, and embedded objects.
- Never put raw identifying values in logs or audit files.
- Uncertain person classifications remain redacted.
- Keep agent business logic independent of LangGraph. Only `graph.py` owns orchestration.

## Development

- Target Python 3.11 or newer and use the `src` package layout.
- Add focused tests for every detector, resolver policy, XML transformation, and graph route.
- Generate synthetic DOCX fixtures; never commit real documents or personal data.
- Run Ruff, mypy, pytest with coverage, and a package build before publication.
- Update `ARCHITECTURE.md` whenever state fields, nodes, routing, or agent responsibilities change.

See `ARCHITECTURE.md` for state contracts, graph topology, and package boundaries.
