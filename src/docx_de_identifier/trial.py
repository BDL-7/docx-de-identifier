from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from docx_de_identifier.audit import file_sha256
from docx_de_identifier.cli import run
from docx_de_identifier.validation import validate_trial_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx-de-identifier-trial",
        description="Run and validate an offline DOCX de-identification trial.",
    )
    parser.add_argument("input", type=Path, help="Disposable source .docx file")
    parser.add_argument("--output", type=Path, required=True, help="Destination .docx file")
    parser.add_argument("--config", type=Path, help="YAML configuration file")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing trial artifacts")
    return parser


def run_trial(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    source = args.input.resolve()
    output_path = args.output.resolve()
    report_path = output_path.with_suffix(".validation.json")
    if report_path.exists() and not args.overwrite:
        raise FileExistsError("Validation report already exists; pass --overwrite to replace")
    source_sha256 = file_sha256(source)
    if report_path.exists():
        previous_report = json.loads(report_path.read_text(encoding="utf-8"))
        try:
            previous_source_sha256 = previous_report["source"]["sha256"]
        except (KeyError, TypeError) as error:
            raise ValueError("Existing validation report has an invalid source hash") from error
        if previous_source_sha256 != source_sha256:
            raise ValueError("Source document changed since the previous validation report")
    output, audit = run(args)
    try:
        report = validate_trial_artifacts(source, output, audit, source_sha256)
    except (OSError, TypeError, ValueError):
        output.unlink(missing_ok=True)
        audit.unlink(missing_ok=True)
        raise
    temporary_report = report_path.with_name(f".{report_path.name}.tmp")
    try:
        temporary_report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary_report, report_path)
    finally:
        temporary_report.unlink(missing_ok=True)
    return report_path, report


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        report_path, report = run_trial(parser.parse_args(argv))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Validation report: {report_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
