"""Canonical fingerprints for daily decision evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
    PRODUCTION_RECORD_FIELDS,
)
from server.services.daily_decision_evidence_values import object_dict, object_list


def evidence_fingerprint(
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
) -> str:
    summary = object_dict(decision_payload.get("summary"))
    portfolio = object_dict(summary.get("portfolio"))
    account_truth = object_dict(summary.get("account_truth"))
    market = object_dict(summary.get("market_data"))
    payload = {
        "decision_date": decision_payload.get("decision_date"),
        "decision": decision_payload.get("decision"),
        "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
        "ledger_cutoff_id": portfolio.get("ledger_cutoff_id"),
        "account_truth": {
            "schema_version": account_truth.get("schema_version"),
            "promotion_status": account_truth.get("promotion_status"),
            "gate_status": account_truth.get("gate_status"),
            "data_freshness_status": account_truth.get("data_freshness_status"),
            "unresolved_mismatch_count": account_truth.get("unresolved_mismatch_count"),
            "import_run_id": account_truth.get("import_run_id"),
            "source_fingerprint": account_truth.get("source_fingerprint"),
            "captured_at": account_truth.get("captured_at"),
            "max_age_seconds": account_truth.get("max_age_seconds"),
            "reconciliation_status": account_truth.get("reconciliation_status"),
            "ledger_coverage": object_dict(account_truth.get("ledger_coverage")),
        },
        "market_data": {
            "source_health": market.get("source_health"),
            "latest_quote_timestamp": market.get("latest_quote_timestamp"),
        },
        "candidates": [
            {
                "action_id": item.get("action_id"),
                "symbol": item.get("symbol"),
                "action": item.get("action"),
                "risk_gate_status": item.get("risk_gate_status"),
                "manual_confirmation_status": item.get("manual_confirmation_status"),
            }
            for item in object_list(decision_payload.get("candidates"))
        ],
        "trading_plan": {
            "schema_version": trading_plan.get("schema_version"),
            "plan_date": trading_plan.get("plan_date"),
            "conclusion_status": trading_plan.get("conclusion_status"),
            "order_intents": object_list(trading_plan.get("order_intents")),
            "blockers": object_list(trading_plan.get("blockers")),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def daily_candidate_input_fingerprint(payload: dict[str, Any]) -> str:
    """Bind every outcome-relevant source while ignoring wall-clock-only age drift."""

    input_snapshot = object_dict(payload.get("input_snapshot"))
    production_gate = object_dict(payload.get("production_gate"))
    paper_shadow = object_dict(payload.get("paper_shadow"))
    execution_closure = object_dict(payload.get("execution_closure"))
    risk = object_dict(payload.get("risk"))
    identity = {
        "schema_version": DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
        "decision_plan_fingerprint": input_snapshot.get("decision_plan_fingerprint"),
        "production_gate": {
            "status": production_gate.get("status"),
            "blockers": list(production_gate.get("blockers") or []),
        },
        "decision_outcome": payload.get("decision_outcome"),
        "risk": {
            "status": risk.get("status"),
            "error_type": risk.get("error_type"),
            "error_fingerprint": risk.get("error_fingerprint"),
            "blockers": object_list(risk.get("blockers")),
        },
        "strategy_gate_bindings": object_list(
            input_snapshot.get("strategy_gate_bindings")
        ),
        "paper_shadow": {
            "run_id": paper_shadow.get("run_id"),
            "input_fingerprint": paper_shadow.get("input_fingerprint"),
            "status": paper_shadow.get("status"),
            "divergence_status": paper_shadow.get("divergence_status"),
            "simulated_order_count": paper_shadow.get("simulated_order_count"),
            "simulated_fill_count": paper_shadow.get("simulated_fill_count"),
        },
        "execution_closure": {
            "status": execution_closure.get("status"),
            "evidence_fingerprint": execution_closure.get("evidence_fingerprint"),
        },
    }
    return fingerprint_json(identity)


def manual_ticket_candidate_fingerprint(payload: dict[str, Any]) -> str:
    """Hash a read-only ticket candidate without trusting its stored digest."""

    core = {
        key: value
        for key, value in payload.items()
        if key != "ticket_candidate_fingerprint"
    }
    return fingerprint_json(core)


def fingerprint_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def daily_candidate_record_fingerprint(payload: dict[str, Any]) -> str:
    """Hash the complete safe production decision record for replay checks."""

    stable = {key: payload.get(key) for key in PRODUCTION_RECORD_FIELDS}
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
