#!/usr/bin/env python3
"""Run and optionally record broker-neutral execution-edge fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from account_truth.broker_execution_edge_conformance import (
    BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerExecutionEdgeConformanceRejected,
    BrokerExecutionEdgeConformanceRepository,
    preview_broker_execution_edge_manifest,
)
from account_truth.broker_execution_edge_conformance_fixtures import (
    run_deterministic_broker_execution_edge_conformance,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run local deterministic execution-edge contract fixtures. "
            "This does not load or register an adapter, contact a provider, "
            "or grant submit/cancel authority."
        )
    )
    parser.add_argument("--file", required=True, help="Execution-edge manifest JSON.")
    parser.add_argument("--db", required=True, help="Karkinos evidence database.")
    parser.add_argument("--run-id", required=True, help="Unique conformance run id.")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Persist the local fixture report after running the suite.",
    )
    parser.add_argument("--acknowledgement", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.file)
    try:
        content = source.read_bytes()
    except OSError as exc:
        print(
            json.dumps(
                _rejection(
                    [
                        "broker_execution_edge_manifest_read_failed:"
                        f"{type(exc).__name__}"
                    ]
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    manifest = preview_broker_execution_edge_manifest(
        content,
        source_name=source.name,
    )
    if not manifest.get("recordable") or manifest.get("validation_status") != "pass":
        print(
            json.dumps(
                _rejection(
                    [
                        "broker_execution_edge_manifest_blocked",
                        *[str(item) for item in manifest.get("blockers") or []],
                    ]
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    preview = run_deterministic_broker_execution_edge_conformance(
        manifest,
        run_id=args.run_id,
    )
    if not args.record:
        print(json.dumps(preview, ensure_ascii=False, sort_keys=True))
        return 0 if preview["validation_status"] == "passed" else 2

    try:
        result = BrokerExecutionEdgeConformanceRepository(Path(args.db)).record_report(
            preview,
            acknowledgement=args.acknowledgement,
        )
    except BrokerExecutionEdgeConformanceRejected as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


def _rejection(blockers: list[str]) -> dict[str, object]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "deterministic_local": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "production_broker_contacted": False,
        "broker_submission_enabled": False,
        "broker_cancellation_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT",
    "main",
    "parse_args",
]
