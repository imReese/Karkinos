"""Default-read-only CLI for the bounded legacy fund duplicate repair."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from server.runtime_paths import resolve_data_dir
from server.services.legacy_fund_trade_duplicate_repair import (
    LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION,
    LegacyFundTradeDuplicateRepairBlocked,
    LegacyFundTradeDuplicateRepairCommand,
    LegacyFundTradeDuplicateRepairService,
)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    output = stdout or sys.stdout
    service = LegacyFundTradeDuplicateRepairService(args.database)
    try:
        if not args.apply:
            report = service.preview()
            exit_code = 0 if report["status"] == "ready" else 2
        else:
            _require_apply_arguments(args)
            result = service.apply(
                LegacyFundTradeDuplicateRepairCommand(
                    command_id=args.command_id,
                    operator_id=args.operator_id,
                    preview_fingerprint=args.preview_fingerprint,
                    confirmation=args.confirm,
                )
            )
            report = result.to_public_dict()
            exit_code = 0
    except LegacyFundTradeDuplicateRepairBlocked as exc:
        report = _blocked_report(list(exc.blockers))
        exit_code = 2
    except (FileNotFoundError, OSError, ValueError) as exc:
        report = _blocked_report([_public_error_code(exc)])
        exit_code = 2

    output.write(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
        + "\n"
    )
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview the fingerprint-bound legacy fund duplicate repair. "
            "No database write occurs unless --apply and every authorization "
            "argument are supplied."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(resolve_data_dir()) / "app.db",
        help="Existing Karkinos SQLite app.db path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Append the preview-bound correction batch atomically.",
    )
    parser.add_argument("--command-id", default="")
    parser.add_argument("--operator-id", default="")
    parser.add_argument("--preview-fingerprint", default="")
    parser.add_argument(
        "--confirm",
        default="",
        help=(
            "Exact required phrase from preview: "
            f"{LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION}"
        ),
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def _require_apply_arguments(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, value in (
            ("command_id", args.command_id),
            ("operator_id", args.operator_id),
            ("preview_fingerprint", args.preview_fingerprint),
            ("confirm", args.confirm),
        )
        if not str(value).strip()
    ]
    if missing:
        raise ValueError("apply arguments are incomplete")


def _public_error_code(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "legacy_fund_trade_duplicate_database_missing"
    if isinstance(exc, ValueError):
        return "legacy_fund_trade_duplicate_apply_authorization_invalid"
    return "legacy_fund_trade_duplicate_database_unavailable"


def _blocked_report(blockers: list[str]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "blockers": sorted(set(blockers)),
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "original_rows_updated_or_deleted": False,
        "authorizes_execution": False,
    }


__all__ = ["main"]
