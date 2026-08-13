"""Fail-closed real-account capital constraint for strategy research."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

RESEARCH_ACCOUNT_CAPITAL_EVIDENCE_SCHEMA_VERSION = (
    "karkinos.research_account_capital_constraint.v1"
)

_FINGERPRINT = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")


def build_research_account_capital_evidence(
    *,
    initial_cash: Any,
    account_evidence: Mapping[str, Any] | None,
    fee_schedule_evidence: Mapping[str, Any] | None,
    expected_valuation_snapshot_id: str | None,
    expected_ledger_cutoff_id: int | None,
) -> dict[str, Any]:
    """Prove research capital is bounded by one reconciled account snapshot.

    The returned artifact deliberately omits cash, positions, total equity, and
    private account identifiers.  It grants no strategy, capital, order, or
    execution authority.
    """

    cash = _decimal(initial_cash)
    account = dict(account_evidence or {})
    fee_binding = dict(fee_schedule_evidence or {})
    payload = account.get("payload")
    summary = payload.get("summary") if isinstance(payload, Mapping) else None
    snapshot = payload.get("snapshot") if isinstance(payload, Mapping) else None
    issues: list[str] = []

    if cash is None or cash <= 0:
        issues.append("research_initial_cash_invalid")
    if not expected_valuation_snapshot_id or expected_ledger_cutoff_id is None:
        issues.append("research_account_binding_required")
    if (
        account.get("status") != "complete"
        or account.get("persisted_facts_only") is not True
        or not _valid_fingerprint(account.get("record_fingerprint"))
        or not isinstance(summary, Mapping)
        or not isinstance(snapshot, Mapping)
    ):
        issues.append("research_account_evidence_not_authoritative")

    identity_matches = (
        bool(expected_valuation_snapshot_id)
        and (
            str(account.get("valuation_snapshot_id") or "")
            == str(expected_valuation_snapshot_id)
            and _integer(account.get("ledger_cutoff_id")) == expected_ledger_cutoff_id
            and str(summary.get("valuation_snapshot_id") or "")
            == str(expected_valuation_snapshot_id)
            and _integer(summary.get("ledger_cutoff_id")) == expected_ledger_cutoff_id
            and str(snapshot.get("valuation_snapshot_id") or "")
            == str(expected_valuation_snapshot_id)
            and _integer(snapshot.get("ledger_cutoff_id")) == expected_ledger_cutoff_id
            and summary.get("valuation_status") == "complete"
            and snapshot.get("valuation_status") == "complete"
        )
        if isinstance(summary, Mapping) and isinstance(snapshot, Mapping)
        else False
    )
    if not identity_matches:
        issues.append("research_account_evidence_identity_mismatch")

    summary_equity = (
        _decimal(summary.get("total_equity")) if isinstance(summary, Mapping) else None
    )
    snapshot_equity = (
        _decimal(snapshot.get("total_equity"))
        if isinstance(snapshot, Mapping)
        else None
    )
    equity_valid = (
        summary_equity is not None
        and summary_equity > 0
        and snapshot_equity is not None
        and snapshot_equity == summary_equity
    )
    if not equity_valid:
        issues.append("research_account_total_equity_invalid")

    source_fingerprint = fee_binding.get("account_truth_source_fingerprint")
    scope_fingerprint = fee_binding.get("account_truth_scope_fingerprint")
    account_truth_reconciled = (
        fee_binding.get("account_specific") is True
        and fee_binding.get("broker_statement_reconciled") is True
        and _valid_fingerprint(source_fingerprint)
        and _valid_fingerprint(scope_fingerprint)
    )
    if not account_truth_reconciled:
        issues.append("research_account_truth_binding_not_reconciled")

    within_equity = bool(
        cash is not None
        and cash > 0
        and summary_equity is not None
        and summary_equity > 0
        and cash <= summary_equity
    )
    if cash is not None and cash > 0 and equity_valid and not within_equity:
        issues.append("research_initial_cash_exceeds_current_account_equity")

    unique_issues = list(dict.fromkeys(issues))
    passed = not unique_issues
    core = {
        "schema_version": RESEARCH_ACCOUNT_CAPITAL_EVIDENCE_SCHEMA_VERSION,
        "status": "pass" if passed else "blocked",
        "research_initial_cash": format(cash, "f") if cash is not None else None,
        "account_fact_binding_present": bool(
            expected_valuation_snapshot_id and expected_ledger_cutoff_id is not None
        ),
        "account_evidence_identity_matches": identity_matches,
        "account_truth_reconciled": account_truth_reconciled,
        "initial_cash_within_current_account_equity": within_equity,
        "account_truth_source_fingerprint": (
            str(source_fingerprint) if _valid_fingerprint(source_fingerprint) else None
        ),
        "account_truth_scope_fingerprint": (
            str(scope_fingerprint) if _valid_fingerprint(scope_fingerprint) else None
        ),
        "account_state_record_fingerprint": (
            str(account.get("record_fingerprint"))
            if _valid_fingerprint(account.get("record_fingerprint"))
            else None
        ),
        "valuation_snapshot_id": expected_valuation_snapshot_id,
        "ledger_cutoff_id": expected_ledger_cutoff_id,
        "issues": unique_issues,
        "current_account_cash_redacted": True,
        "current_account_positions_redacted": True,
        "current_account_total_equity_redacted": True,
        "persisted_account_facts_only": True,
        "human_review_required": True,
        "authorizes_strategy_promotion": False,
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def is_valid_passed_research_account_capital_evidence(
    value: Any,
    *,
    expected_initial_cash: Any | None = None,
    expected_valuation_snapshot_id: str | None = None,
    expected_ledger_cutoff_id: int | None = None,
) -> bool:
    """Validate a persisted pass artifact and its optional exact bindings."""

    if not isinstance(value, Mapping):
        return False
    payload = dict(value)
    evidence_fingerprint = payload.pop("evidence_fingerprint", None)
    research_cash = _decimal(payload.get("research_initial_cash"))
    expected_cash = _decimal(expected_initial_cash)
    return (
        payload.get("schema_version")
        == RESEARCH_ACCOUNT_CAPITAL_EVIDENCE_SCHEMA_VERSION
        and payload.get("status") == "pass"
        and payload.get("issues") == []
        and research_cash is not None
        and research_cash > 0
        and payload.get("account_fact_binding_present") is True
        and payload.get("account_evidence_identity_matches") is True
        and payload.get("account_truth_reconciled") is True
        and payload.get("initial_cash_within_current_account_equity") is True
        and _valid_fingerprint(payload.get("account_truth_source_fingerprint"))
        and _valid_fingerprint(payload.get("account_truth_scope_fingerprint"))
        and _valid_fingerprint(payload.get("account_state_record_fingerprint"))
        and bool(str(payload.get("valuation_snapshot_id") or "").strip())
        and _integer(payload.get("ledger_cutoff_id")) is not None
        and payload.get("current_account_cash_redacted") is True
        and payload.get("current_account_positions_redacted") is True
        and payload.get("current_account_total_equity_redacted") is True
        and payload.get("persisted_account_facts_only") is True
        and payload.get("human_review_required") is True
        and payload.get("authorizes_strategy_promotion") is False
        and payload.get("authorizes_execution") is False
        and payload.get("does_not_change_capital_authority") is True
        and _valid_fingerprint(evidence_fingerprint)
        and str(evidence_fingerprint).lower() == _fingerprint(payload)
        and (expected_cash is None or research_cash == expected_cash)
        and (
            expected_valuation_snapshot_id is None
            or payload.get("valuation_snapshot_id") == expected_valuation_snapshot_id
        )
        and (
            expected_ledger_cutoff_id is None
            or _integer(payload.get("ledger_cutoff_id")) == expected_ledger_cutoff_id
        )
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _valid_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and _FINGERPRINT.fullmatch(value.lower()) is not None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
