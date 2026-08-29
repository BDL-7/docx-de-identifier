from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from docx_de_identifier.audit import build_audit_document, write_audit
from docx_de_identifier.config import load_config
from docx_de_identifier.graph import build_graph
from docx_de_identifier.models import AuditEvent
from docx_de_identifier.validation import validate_sanitized_docx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx-de-identifier",
        description="De-identify a DOCX using a fully offline multi-agent pipeline.",
    )
    parser.add_argument("input", type=Path, help="Source .docx file")
    parser.add_argument("--output", type=Path, help="Destination .docx file")
    parser.add_argument("--config", type=Path, help="YAML configuration file")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing output and audit files"
    )
    return parser


def _validate_paths(source: Path, output: Path, audit: Path, overwrite: bool) -> None:
    if source.suffix.casefold() != ".docx" or not source.is_file():
        raise ValueError("Input must be an existing .docx file")
    if source.resolve() == output.resolve():
        raise ValueError("Output path must differ from input path")
    if not overwrite and (output.exists() or audit.exists()):
        raise FileExistsError("Output or audit file already exists; pass --overwrite to replace")
    output.parent.mkdir(parents=True, exist_ok=True)


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    source = args.input.resolve()
    output = (args.output or source.with_name(f"{source.stem}.deidentified.docx")).resolve()
    config = load_config(args.config)
    audit = output.with_suffix(config.audit_suffix)
    _validate_paths(source, output, audit, args.overwrite)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".docx", dir=output.parent
    )
    os.close(descriptor)
    temporary_output = Path(temporary_name)
    temporary_audit = audit.with_name(f".{audit.name}.tmp")
    try:
        result = build_graph(config).invoke(
            {"docx_path": str(source), "output_path": str(temporary_output)}
        )
        validate_sanitized_docx(temporary_output)
        events = result.get("audit_events", [])
        if not isinstance(events, list) or not all(isinstance(item, AuditEvent) for item in events):
            raise TypeError("Pipeline returned invalid audit events")
        removed = result.get("removed_content", [])
        if not isinstance(removed, list) or not all(isinstance(item, str) for item in removed):
            raise TypeError("Pipeline returned invalid removed-content values")
        audit_document = build_audit_document(
            source, temporary_output, removed, events, config.spacy_model
        )
        write_audit(temporary_audit, audit_document)
        os.replace(temporary_output, output)
        os.replace(temporary_audit, audit)
    finally:
        temporary_output.unlink(missing_ok=True)
        temporary_audit.unlink(missing_ok=True)
    return output, audit


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        output, audit = run(parser.parse_args(argv))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Redacted document: {output}")
    print(f"Audit log: {audit}")
    return 0
