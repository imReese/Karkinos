#!/usr/bin/env python3
"""Preview or explicitly ingest one broker-neutral collector batch."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleCollectorRejected,
    BrokerOrderLifecycleCollectorRepository,
    preview_broker_order_lifecycle_collector_batch,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate one local broker-neutral collector batch. Preview is the "
            "default and does not create a database. --record persists only "
            "collector/lifecycle evidence; it never contacts a broker or "
            "changes OMS, fills, ledger, risk, kill switch, or authority."
        )
    )
    parser.add_argument("--file", required=True, help="Local UTF-8 JSON batch path.")
    parser.add_argument(
        "--db",
        default=os.getenv("KARKINOS_DB_PATH", "data/store/karkinos.db"),
        help="Karkinos SQLite path used only when --record is supplied.",
    )
    parser.add_argument(
        "--source-name",
        default="broker order lifecycle collector batch",
        help="Sanitized provenance label; local paths are not persisted.",
    )
    parser.add_argument(
        "--max-snapshot-age-seconds",
        type=int,
        default=120,
        help="Accepted lifecycle snapshot age, clamped to 30..3600 seconds.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Persist run evidence and advance the cursor only if all gates pass.",
    )
    parser.add_argument(
        "--acknowledgement",
        default="",
        help=(
            "Required with --record: "
            f"{BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT}"
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
                    "blockers": [
                        "broker_order_lifecycle_collector_local_file_unavailable"
                    ],
                    "error_type": type(exc).__name__,
                    "provider_contacted": False,
                    "broker_submission_enabled": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    preview = preview_broker_order_lifecycle_collector_batch(
        content,
        source_name=args.source_name,
        max_snapshot_age_seconds=args.max_snapshot_age_seconds,
    )
    if not args.record:
        print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if preview["ready_to_advance_cursor"] else 2
    try:
        recorded = BrokerOrderLifecycleCollectorRepository(args.db).ingest(
            preview,
            acknowledgement=args.acknowledgement,
        )
    except BrokerOrderLifecycleCollectorRejected as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(recorded, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if recorded["run_status"] in {"recorded", "duplicate"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
