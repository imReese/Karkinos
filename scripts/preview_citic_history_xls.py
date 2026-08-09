#!/usr/bin/env python3
"""Produce privacy-minimized previews for local CITIC history XLS exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from account_truth.broker_statement import BrokerStatementPreview
from account_truth.citic_broker_soak_candidate import (
    build_citic_broker_soak_candidate,
)
from account_truth.citic_history_xls import (
    parse_citic_history_xls,
    recognized_non_financial_activity_count,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one local CITIC 历史成交 .xls file or every .xls file "
            "directly inside a directory. Output excludes events, positions, "
            "amounts, names, symbols, account identifiers, and absolute paths. "
            "The command never persists evidence or contacts a broker."
        )
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Local .xls file or directory containing CITIC history exports.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requested = Path(args.path).expanduser()
    paths, discovery_blocker = _discover_paths(requested)
    if discovery_blocker:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blockers": [discovery_blocker],
                    "files": [],
                    "privacy_minimized": True,
                    "evidence_persisted": False,
                    "provider_contacted": False,
                    "broker_submission_enabled": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    summaries: list[dict[str, object]] = []
    for path in paths:
        try:
            content = path.read_bytes()
        except OSError:
            summaries.append(
                {
                    "source_name_hash": _name_hash(path.name),
                    "validation_status": "blocked",
                    "errors": [
                        {
                            "row_number": None,
                            "code": "citic_history_xls_local_file_unavailable",
                            "message": "Local XLS file could not be read.",
                        }
                    ],
                }
            )
            continue
        preview = parse_citic_history_xls(content)
        summaries.append(_summary(path=path, preview=preview))

    blocked = any(summary.get("validation_status") != "pass" for summary in summaries)
    print(
        json.dumps(
            {
                "status": "blocked" if blocked else "pass",
                "file_count": len(summaries),
                "files": summaries,
                "events_included": False,
                "privacy_minimized": True,
                "evidence_persisted": False,
                "production_ledger_mutated": False,
                "provider_contacted": False,
                "broker_submission_enabled": False,
                "capital_authority_changed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if blocked else 0


def _discover_paths(path: Path) -> tuple[list[Path], str]:
    if path.is_file():
        if path.suffix.lower() != ".xls":
            return [], "citic_history_xls_path_must_be_legacy_xls"
        return [path], ""
    if not path.is_dir():
        return [], "citic_history_xls_path_unavailable"
    paths = sorted(candidate for candidate in path.iterdir() if candidate.is_file())
    paths = [candidate for candidate in paths if candidate.suffix.lower() == ".xls"]
    if not paths:
        return [], "citic_history_xls_directory_has_no_xls_files"
    return paths, ""


def _summary(*, path: Path, preview: BrokerStatementPreview) -> dict[str, object]:
    return {
        "source_name_hash": _name_hash(path.name),
        "schema_version": preview.schema_version,
        "source_type": preview.source_type,
        "file_fingerprint": preview.file_fingerprint,
        "row_count": preview.row_count,
        "valid_row_count": preview.valid_row_count,
        "invalid_row_count": preview.invalid_row_count,
        "recognized_non_financial_activity_count": (
            recognized_non_financial_activity_count(preview)
        ),
        "duplicate_row_count": preview.duplicate_row_count,
        "validation_status": preview.validation_status,
        "errors": [
            {
                "row_number": error.row_number,
                "code": error.code,
                "message": error.message,
            }
            for error in preview.errors
        ],
        "limitations": list(preview.limitations),
        "broker_soak_candidate": build_citic_broker_soak_candidate(preview),
    }


def _name_hash(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
