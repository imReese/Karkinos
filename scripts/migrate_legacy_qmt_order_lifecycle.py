#!/usr/bin/env python3
"""Explicitly migrate the retired QMT lifecycle export v1 schema."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from account_truth.adapters.legacy_qmt_order_lifecycle_v1 import (
    LegacyQmtOrderLifecycleMigrationRejected,
    migrate_legacy_qmt_order_lifecycle_export_v1,
)
from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRejected,
    BrokerOrderLifecycleEvidenceRepository,
    preview_broker_order_lifecycle_export,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compatibility-only migration for "
            "karkinos.qmt_order_lifecycle_export.v1. The legacy file is "
            "converted in memory to the broker-neutral canonical schema. "
            "No QMT SDK is imported and no broker is contacted."
        )
    )
    parser.add_argument("--file", required=True, help="Legacy local UTF-8 JSON path.")
    parser.add_argument(
        "--db",
        default=os.getenv("KARKINOS_DB_PATH", "data/store/karkinos.db"),
        help="Karkinos SQLite path used only when --record is supplied.",
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
        help="Persist the migrated canonical evidence after acknowledgement.",
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
        migrated = migrate_legacy_qmt_order_lifecycle_export_v1(content)
    except OSError as exc:
        result = {
            "status": "blocked",
            "blockers": ["legacy_qmt_order_lifecycle_local_file_unavailable"],
            "error_type": type(exc).__name__,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    except LegacyQmtOrderLifecycleMigrationRejected as exc:
        result = {
            "status": "blocked",
            "blockers": exc.blockers,
            "legacy_schema": "karkinos.qmt_order_lifecycle_export.v1",
            "canonical_schema": "karkinos.broker_order_lifecycle_export.v1",
            "provider_contacted": False,
            "broker_submission_enabled": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    preview = preview_broker_order_lifecycle_export(
        migrated,
        source_name="legacy QMT lifecycle v1 explicit migration",
        max_snapshot_age_seconds=args.max_snapshot_age_seconds,
    )
    legacy_migration = {
        "source_schema": "karkinos.qmt_order_lifecycle_export.v1",
        "canonical_schema": "karkinos.broker_order_lifecycle_export.v1",
        "compatibility_only": True,
        "qmt_runtime_supported": False,
    }
    if not args.record:
        output = {**preview, "legacy_migration": legacy_migration}
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if preview["ready_to_record"] else 2
    try:
        recorded = BrokerOrderLifecycleEvidenceRepository(args.db).record(
            preview,
            acknowledgement=args.acknowledgement,
        )
    except BrokerOrderLifecycleEvidenceRejected as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    recorded["legacy_migration"] = legacy_migration
    print(json.dumps(recorded, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if recorded["validation_status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
