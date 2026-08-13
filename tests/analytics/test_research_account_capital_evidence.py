from __future__ import annotations

from copy import deepcopy

from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
    is_valid_passed_research_account_capital_evidence,
)


def _account_evidence(*, total_equity: str = "20000") -> dict:
    identity = {
        "valuation_snapshot_id": "valuation-fixture",
        "ledger_cutoff_id": 42,
        "valuation_status": "complete",
    }
    return {
        "status": "complete",
        "persisted_facts_only": True,
        "record_fingerprint": "a" * 64,
        "valuation_snapshot_id": "valuation-fixture",
        "ledger_cutoff_id": 42,
        "payload": {
            "summary": {**identity, "total_equity": total_equity},
            "snapshot": {**identity, "total_equity": total_equity},
        },
    }


def _fee_evidence() -> dict:
    return {
        "account_specific": True,
        "broker_statement_reconciled": True,
        "account_truth_source_fingerprint": "sha256:" + "b" * 64,
        "account_truth_scope_fingerprint": "sha256:" + "c" * 64,
    }


def _build(**overrides) -> dict:
    values = {
        "initial_cash": "15000",
        "account_evidence": _account_evidence(),
        "fee_schedule_evidence": _fee_evidence(),
        "expected_valuation_snapshot_id": "valuation-fixture",
        "expected_ledger_cutoff_id": 42,
    }
    values.update(overrides)
    return build_research_account_capital_evidence(**values)


def test_real_account_capital_evidence_passes_without_persisting_account_values() -> (
    None
):
    evidence = _build()

    assert evidence["status"] == "pass"
    assert evidence["initial_cash_within_current_account_equity"] is True
    assert evidence["account_truth_reconciled"] is True
    assert evidence["current_account_total_equity_redacted"] is True
    assert "20000" not in str(evidence)
    assert len(evidence["evidence_fingerprint"]) == 64
    assert evidence["authorizes_execution"] is False
    assert evidence["does_not_change_capital_authority"] is True
    assert is_valid_passed_research_account_capital_evidence(
        evidence,
        expected_initial_cash="15000",
        expected_valuation_snapshot_id="valuation-fixture",
        expected_ledger_cutoff_id=42,
    )

    drifted = deepcopy(evidence)
    drifted["research_initial_cash"] = "15001"
    assert is_valid_passed_research_account_capital_evidence(drifted) is False


def test_real_account_capital_evidence_blocks_oversized_or_unreconciled_research() -> (
    None
):
    oversized = _build(initial_cash="20000.01")
    fee_evidence = deepcopy(_fee_evidence())
    fee_evidence["broker_statement_reconciled"] = False
    unreconciled = _build(fee_schedule_evidence=fee_evidence)

    assert oversized["status"] == "blocked"
    assert oversized["issues"] == [
        "research_initial_cash_exceeds_current_account_equity"
    ]
    assert unreconciled["status"] == "blocked"
    assert unreconciled["issues"] == ["research_account_truth_binding_not_reconciled"]


def test_real_account_capital_evidence_blocks_identity_or_equity_conflict() -> None:
    conflicting = _account_evidence()
    conflicting["payload"]["snapshot"]["total_equity"] = "19999"
    conflicting["payload"]["snapshot"]["ledger_cutoff_id"] = 41

    evidence = _build(account_evidence=conflicting)

    assert evidence["status"] == "blocked"
    assert evidence["issues"] == [
        "research_account_evidence_identity_mismatch",
        "research_account_total_equity_invalid",
    ]
