"""Export acceptance audit manifests as CI-friendly JSON."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analytics.acceptance_audit import (
    AcceptanceAudit,
    build_acceptance_audit,
    build_account_truth_acceptance_audit,
    build_account_truth_review_acceptance_audit,
    build_broker_fee_cost_basis_acceptance_audit,
    build_market_data_reliability_acceptance_audit,
    build_research_evidence_acceptance_audit,
    build_strategy_assignment_acceptance_audit,
    build_strategy_lab_acceptance_audit,
)

AuditBuilder = Callable[[], AcceptanceAudit]

AUDIT_REGISTRY: dict[str, tuple[str, AuditBuilder]] = {
    "profit_discipline": ("Profit Discipline acceptance audit", build_acceptance_audit),
    "strategy_lab": (
        "Strategy Lab acceptance audit",
        build_strategy_lab_acceptance_audit,
    ),
    "research_evidence": (
        "Research Evidence acceptance audit",
        build_research_evidence_acceptance_audit,
    ),
    "account_truth": (
        "Account Truth acceptance audit",
        build_account_truth_acceptance_audit,
    ),
    "account_truth_review": (
        "Account Truth Review Center acceptance audit",
        build_account_truth_review_acceptance_audit,
    ),
    "strategy_assignment": (
        "Strategy Assignment acceptance audit",
        build_strategy_assignment_acceptance_audit,
    ),
    "market_data_reliability": (
        "Market Data Reliability acceptance audit",
        build_market_data_reliability_acceptance_audit,
    ),
    "broker_fee_cost_basis": (
        "Broker Fee & Cost Basis Fidelity acceptance audit",
        build_broker_fee_cost_basis_acceptance_audit,
    ),
}


def build_acceptance_audit_export(
    *,
    selected_audit: str = "all",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a stable JSON-serializable acceptance audit export."""
    if selected_audit == "all":
        selected_keys = tuple(AUDIT_REGISTRY)
    else:
        selected_keys = (selected_audit,)

    audits = [
        _audit_to_export(
            key=key, name=AUDIT_REGISTRY[key][0], audit=AUDIT_REGISTRY[key][1]()
        )
        for key in selected_keys
    ]
    return {
        "generated_at": generated_at or _utc_timestamp(),
        "selected_audit": selected_audit,
        "audits": audits,
        "overall_is_complete": all(audit["is_complete"] for audit in audits),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    payload = build_acceptance_audit_export(selected_audit=args.audit)
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    if args.pretty:
        text = f"{text}\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")

    return 0 if payload["overall_is_complete"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export Karkinos acceptance audit manifests as JSON.",
    )
    parser.add_argument(
        "--audit",
        choices=("all", *AUDIT_REGISTRY.keys()),
        default="all",
        help="Acceptance audit manifest to export.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file path. Defaults to stdout and writes no artifact.",
    )
    return parser


def _audit_to_export(
    *,
    key: str,
    name: str,
    audit: AcceptanceAudit,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "required_count": audit.required_count,
        "completed_count": audit.completed_count,
        "is_complete": audit.is_complete,
        "criteria": [criterion.to_json_dict() for criterion in audit.criteria],
        "limitations": audit.limitations,
    }


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
