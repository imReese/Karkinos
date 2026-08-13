from __future__ import annotations

from types import SimpleNamespace

from analytics.backtest_fee_tax_evidence import build_backtest_fee_tax_evidence


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
