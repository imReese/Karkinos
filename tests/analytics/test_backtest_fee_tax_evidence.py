from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from analytics.backtest_fee_tax_evidence import (
    build_backtest_fee_tax_evidence,
    is_valid_complete_backtest_fee_tax_evidence,
)


def _fill(**overrides):
    values = {
        "commission": "5.60",
        "slippage": "0.20",
        "fee_rule_id": "cn_stock_a_default_v1",
        "fee_rule_version": "backtest_commission_model",
        "fee_breakdown": {
            "commission": "5.00",
            "stamp_tax": "0.50",
            "transfer_fee": "0.10",
            "other_fees": "0.00",
            "total_fee": "5.60",
            "fee_rule_id": "cn_stock_a_default_v1",
            "limitations": ["broker_regulatory_fees_assumed_absorbed"],
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_backtest_fee_tax_evidence_reconciles_exact_fill_components() -> None:
    evidence = build_backtest_fee_tax_evidence(
        fills=[_fill(), _fill(commission="5.60", slippage="0.10")],
        cost_model_reference="karkinos.backtest.multi_asset_commission.default.v1",
    )

    assert evidence["status"] == "complete"
    assert evidence["account_specific"] is False
    assert evidence["broker_statement_reconciled"] is False
    assert "not reviewed Account Truth" in evidence["limitations"][-1]
    assert evidence["includes_taxes"] is True
    assert evidence["components"] == {
        "commission": "10.00",
        "stamp_tax": "1.00",
        "transfer_fee": "0.20",
        "other_fees": "0.00",
        "slippage": "0.30",
    }
    assert evidence["component_reconciliation_status"] == "pass"
    assert evidence["issues"] == []
    assert len(evidence["evidence_fingerprint"]) == 64
    assert evidence["does_not_recalculate_backtest_pnl"] is True
    assert evidence["authorizes_execution"] is False
    assert (
        is_valid_complete_backtest_fee_tax_evidence(
            evidence,
            expected_total_commission="11.20",
            expected_total_slippage="0.30",
            expected_total_cost="11.50",
            expected_fill_count=2,
        )
        is True
    )


def test_backtest_fee_tax_evidence_fails_closed_for_missing_or_conflicting_fields() -> (
    None
):
    evidence = build_backtest_fee_tax_evidence(
        fills=[_fill(commission="9.99", fee_rule_version=None)],
        cost_model_reference="karkinos.backtest.multi_asset_commission.default.v1",
    )

    assert evidence["status"] == "incomplete"
    assert evidence["includes_taxes"] is False
    assert set(evidence["issues"]) == {
        "fill_recorded_fee_total_mismatch:0",
        "fill_fee_rule_version_missing:0",
    }


def test_fee_tax_validator_rejects_rehashed_component_or_fill_count_conflict() -> None:
    evidence = build_backtest_fee_tax_evidence(
        fills=[_fill()],
        cost_model_reference="karkinos.backtest.multi_asset_commission.default.v1",
    )
    core = {
        key: value for key, value in evidence.items() if key != "evidence_fingerprint"
    }
    component_conflict = _refingerprint(
        {
            **core,
            "components": {**evidence["components"], "stamp_tax": "0.00"},
        }
    )
    count_conflict = _refingerprint({**core, "fill_count": 2})

    for value in (component_conflict, count_conflict):
        assert (
            is_valid_complete_backtest_fee_tax_evidence(
                value,
                expected_total_commission="5.60",
                expected_total_slippage="0.20",
                expected_total_cost="5.80",
                expected_fill_count=1,
            )
            is False
        )


def _refingerprint(payload: dict) -> dict:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **payload,
        "evidence_fingerprint": hashlib.sha256(encoded).hexdigest(),
    }
