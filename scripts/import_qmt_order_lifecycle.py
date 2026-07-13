#!/usr/bin/env python3
"""Preview or explicitly record a local QMT order-lifecycle JSON export."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRejected,
    BrokerOrderLifecycleEvidenceRepository,
    preview_qmt_order_lifecycle_export,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one normalized local QMT exact-order lifecycle export. "
            "Preview is the default. Recording requires --record and the exact "
            "acknowledgement; this command never contacts QMT or submits/cancels "
            "a broker order."
        )
    )
    parser.add_argument("--file", required=True, help="Local UTF-8 JSON export path.")
    parser.add_argument(
        "--db",
        default=os.getenv("KARKINOS_DB_PATH", "data/store/karkinos.db"),
        help="Karkinos SQLite path used only when --record is supplied.",
    )
    parser.add_argument(
        "--source-name",
        default="qmt local exact-order lifecycle export",
        help="Sanitized provenance label; local paths are not persisted.",
    )
    parser.add_argument(
        "--max-snapshot-age-seconds",
        type=int,
        default=120,
        help="Accepted capture age, clamped to 30..3600 seconds.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Persist validated evidence after the explicit acknowledgement.",
    )
    parser.add_argument(
        "--acknowledgement",
        default="",
        help=(
            "Required with --record: "
            f"{BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        content = Path(args.file).read_bytes()
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blockers": ["qmt_order_lifecycle_local_file_unavailable"],
                    "error_type": type(exc).__name__,
                    "provider_contacted": False,
                    "broker_submission_enabled": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    preview = preview_qmt_order_lifecycle_export(
        content,
        source_name=args.source_name,
        max_snapshot_age_seconds=args.max_snapshot_age_seconds,
    )
    if not args.record:
        print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if preview["ready_to_record"] else 2
    try:
        recorded = BrokerOrderLifecycleEvidenceRepository(args.db).record(
            preview,
            acknowledgement=args.acknowledgement,
        )
    except BrokerOrderLifecycleEvidenceRejected as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(recorded, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if recorded["validation_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
