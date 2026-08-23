from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.routing import APIRoute

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.broker_statement_roll_forward import (
    roll_forward_daily_broker_statement,
)
from account_truth.evidence_scope_review import EvidenceScopeReviewRepository
from core.types import CommissionType, OrderSide
from server.config import BrokerFeeScheduleConfig
from server.db import AppDatabase
from server.services.account_truth_evidence_readiness import (
    build_account_truth_evidence_scope,
    project_account_truth_evidence_scope,
)
from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown
from server.services.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReviewRepository,
    active_review_matches_fee_evidence,
    build_reviewed_fee_schedule_preview,
    build_reviewed_fee_schedule_review_status,
    resolve_reviewed_fee_schedule,
    reviewed_cost_model_reference,
)

_BROKER_TRADES = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,600000.SH,synthetic stock,stock,CNY,1000,10.00,10000.00,5.00,0.00,-10005.10,89994.90,1000,10.01,synthetic buy,0.10,broker_remaining_cost
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,600000.SH,synthetic stock,stock,CNY,1000,10.00,10000.00,5.00,5.00,9989.90,99984.80,0,0,synthetic sell,0.10,broker_remaining_cost
"""

_BROKER_FUND_TRADES = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-fund-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,510300.SH,synthetic fund,fund,CNY,1000,10.00,10000.00,5.00,0.00,-10005.10,89994.90,1000,10.01,synthetic buy,0.10,broker_remaining_cost
synthetic-fund-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,510300.SH,synthetic fund,fund,CNY,1000,10.00,10000.00,5.00,0.00,9994.90,99989.80,0,0,synthetic sell,0.10,broker_remaining_cost
"""

_BROKER_FUND_TRADES_WITHOUT_TRANSFER_FEE = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-fund-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,510300.SH,synthetic fund,fund,CNY,1000,10.00,10000.00,5.00,0.00,-10005.00,89995.00,1000,10.01,synthetic buy,0.00,broker_remaining_cost
synthetic-fund-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,510300.SH,synthetic fund,fund,CNY,1000,10.00,10000.00,5.00,0.00,9995.00,99990.00,0,0,synthetic sell,0.00,broker_remaining_cost
"""

_BROKER_MIXED_ONE_SIDE_PER_ASSET = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-stock-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,600000.SH,synthetic stock,stock,CNY,1000,10.00,10000.00,5.00,0.00,-10005.10,89994.90,1000,10.01,synthetic buy,0.10,broker_remaining_cost
synthetic-fund-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,510300.SH,synthetic fund,fund,CNY,1000,10.00,10000.00,5.00,0.00,9994.90,99989.80,0,0,synthetic sell,0.10,broker_remaining_cost
"""


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _schedule(
    *,
    rounded: bool = False,
    fund_etf_transfer_fee_rate: Decimal = Decimal("0.00001"),
) -> BrokerFeeScheduleConfig:
    return BrokerFeeScheduleConfig(
        schedule_id="synthetic_reviewed_schedule",
        account_profile_id="synthetic_account",
        broker_name="synthetic_broker",
        stock_a_commission_rate=Decimal("0.0001"),
        stock_a_min_commission=Decimal("5"),
        fund_etf_commission_rate=Decimal("0.0001"),
        fund_etf_min_commission=Decimal("5"),
        stamp_tax_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        fund_etf_transfer_fee_rate=fund_etf_transfer_fee_rate,
        exchange_transfer_fee_rates={"shanghai": Decimal("0.00001")},
        other_fee_rate=Decimal("0"),
        money_precision=Decimal("0.01") if rounded else None,
        money_rounding_mode="half_up" if rounded else "none",
        limitations=(),
    )


def _state(
    tmp_path,
    *,
    rounded: bool = False,
    broker_trades: str = _BROKER_TRADES,
    asset_classes: list[str] | None = None,
    fund_etf_transfer_fee_rate: Decimal = Decimal("0.00001"),
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    preview = parse_broker_statement_csv(broker_trades)
    imported = BrokerEvidenceRepository(db._path).save_preview(
        preview,
        source_name="synthetic-only.csv",
    )
    EvidenceScopeReviewRepository(db._path).record_review(
        import_run_id=imported.import_run_id,
        import_file_fingerprint=imported.file_fingerprint,
        observed_scope_fingerprint="sha256:" + "9" * 64,
        provider="synthetic_broker",
        account_alias="synthetic_account",
        account_reference_hash="sha256:" + "a" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
        asset_classes=asset_classes or ["stock"],
        full_account_scope_attested=True,
        reviewer="synthetic_owner",
    )
    state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(
            broker_fee_schedule=_schedule(
                rounded=rounded,
                fund_etf_transfer_fee_rate=fund_etf_transfer_fee_rate,
            )
        ),
    )
    return state, imported


def _patch_ready_account_truth(monkeypatch, imported) -> None:
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_account_truth_evidence_readiness",
        lambda state: {
            "status": "ready",
            "account_truth_import_run_id": imported.import_run_id,
            "evidence_scope": {
                "account_binding": {
                    "account_alias": "synthetic_account",
                    "account_reference_hash": "sha256:" + "a" * 64,
                },
                "evidence_fingerprint": "sha256:" + "b" * 64,
            },
        },
    )
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_latest_account_truth_promotion_evidence",
        lambda state: {
            "status": "clear",
            "import_run_id": imported.import_run_id,
            "source_fingerprint": "sha256:" + "c" * 64,
        },
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_reviewed_schedule_preview_binds_exact_reconciled_trade_components(
    tmp_path, monkeypatch
) -> None:
    state, imported = _state(tmp_path)
    _patch_ready_account_truth(monkeypatch, imported)

    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )

    assert preview["status"] == "ready"
    assert preview["issues"] == []
    assert preview["component_reconciliation"]["trade_count"] == 2
    assert preview["component_reconciliation"]["matched_trade_count"] == 2
    assert preview["component_reconciliation"]["side_counts"] == {
        "buy": 1,
        "sell": 1,
    }
    assert preview["component_reconciliation"]["asset_side_counts"] == {
        "stock": {"buy": 1, "sell": 1}
    }
    assert preview["component_reconciliation"]["reconciled_notional_envelope"][
        "limits"
    ] == {
        "stock": {
            "maximum_gross_amount": "10000.00",
            "matched_trade_count": 2,
        }
    }
    assert (
        preview["component_reconciliation"]["mismatch_counts_by_asset_and_side"] == []
    )
    assert preview["stores_broker_event_details"] is False
    assert preview["authorizes_execution"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_stock_only_review_excludes_etf_mismatches_and_rejects_etf_resolution(
    tmp_path, monkeypatch
) -> None:
    mixed_trades = (
        _BROKER_TRADES.rstrip()
        + "\n"
        + "\n".join(_BROKER_FUND_TRADES_WITHOUT_TRANSFER_FEE.splitlines()[1:])
    )
    state, imported = _state(
        tmp_path,
        broker_trades=mixed_trades,
        asset_classes=["stock", "fund"],
    )
    _patch_ready_account_truth(monkeypatch, imported)

    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
        reviewed_asset_classes=["stock"],
    )

    assert preview["status"] == "ready"
    assert preview["issues"] == []
    assert preview["reviewed_asset_classes"] == ["stock"]
    comparison = preview["component_reconciliation"]
    assert comparison["source_trade_count"] == 4
    assert comparison["trade_count"] == 2
    assert comparison["matched_trade_count"] == 2
    assert comparison["excluded_trade_count"] == 2
    assert comparison["excluded_asset_class_counts"] == {"etf": 2}
    assert comparison["mismatch_counts"] == {
        "fee": 0,
        "tax": 0,
        "transfer_fee": 0,
    }

    review = ReviewedFeeScheduleReviewRepository(state.db._path).record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    stock_resolution = resolve_reviewed_fee_schedule(
        state,
        start_date="2026-01-01",
        end_date="2026-12-31",
        universe=("600000.SH",),
        asset_classes=("stock",),
        expected_cost_model_reference=reviewed_cost_model_reference(review),
    )
    assert stock_resolution.fee_evidence["fee_schedule_reviewed_asset_classes"] == [
        "stock"
    ]
    with pytest.raises(
        ReviewedFeeScheduleRejected,
        match="reviewed_fee_schedule_backtest_assets_outside_reviewed_scope:etf",
    ):
        resolve_reviewed_fee_schedule(
            state,
            start_date="2026-01-01",
            end_date="2026-12-31",
            universe=("510300.SH",),
            asset_classes=("etf",),
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_reviewed_schedule_accepts_canonical_fund_alias_for_etf_costs(
    tmp_path, monkeypatch
) -> None:
    state, imported = _state(
        tmp_path,
        broker_trades=_BROKER_FUND_TRADES,
        asset_classes=["fund"],
    )
    _patch_ready_account_truth(monkeypatch, imported)
    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )

    assert preview["status"] == "ready"
    assert preview["issues"] == []
    assert preview["component_reconciliation"]["asset_class_counts"] == {"etf": 2}
    assert (
        preview["component_reconciliation"]["mismatch_counts_by_asset_and_side"] == []
    )

    review = ReviewedFeeScheduleReviewRepository(state.db._path).record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    resolution = resolve_reviewed_fee_schedule(
        state,
        start_date="2026-01-01",
        end_date="2026-12-31",
        universe=("510300.SH",),
        asset_classes=("fund",),
        expected_cost_model_reference=reviewed_cost_model_reference(review),
    )

    assert resolution.fee_evidence["broker_statement_reconciled"] is True
    assert resolution.fee_evidence["fee_notional_envelope_enforced"] is True
    assert resolution.fee_evidence["fee_notional_covered_asset_classes"] == ["etf"]
    assert resolution.commission_calc.breakdown_for(
        CommissionType.FUND_ETF,
        OrderSide.SELL,
        Decimal("10"),
        Decimal("1000"),
        symbol="510300.SH",
    ).stamp_tax == Decimal("0")
    with pytest.raises(
        ReviewedFeeScheduleRejected,
        match="reviewed_fee_schedule_notional_envelope_exceeded:etf",
    ):
        resolution.commission_calc.breakdown_for(
            CommissionType.FUND_ETF,
            OrderSide.BUY,
            Decimal("10"),
            Decimal("1001"),
            symbol="510300.SH",
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_reviewed_schedule_reconciles_explicit_zero_etf_transfer_fee(
    tmp_path, monkeypatch
) -> None:
    state, imported = _state(
        tmp_path,
        broker_trades=_BROKER_FUND_TRADES_WITHOUT_TRANSFER_FEE,
        asset_classes=["fund"],
        fund_etf_transfer_fee_rate=Decimal("0"),
    )
    _patch_ready_account_truth(monkeypatch, imported)

    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )

    assert preview["status"] == "ready"
    assert preview["schedule"]["transfer_fee_rate"] == "0.00001"
    assert preview["schedule"]["fund_etf_transfer_fee_rate"] == "0"
    assert preview["component_reconciliation"]["matched_trade_count"] == 2
    assert preview["component_reconciliation"]["mismatch_counts"] == {
        "fee": 0,
        "tax": 0,
        "transfer_fee": 0,
    }


@pytest.mark.unit
@pytest.mark.trading_safety
def test_reviewed_schedule_requires_buy_and_sell_coverage_per_asset(
    tmp_path, monkeypatch
) -> None:
    state, imported = _state(
        tmp_path,
        broker_trades=_BROKER_MIXED_ONE_SIDE_PER_ASSET,
        asset_classes=["stock", "fund"],
    )
    _patch_ready_account_truth(monkeypatch, imported)

    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )

    assert preview["status"] == "blocked"
    assert preview["component_reconciliation"]["side_counts"] == {
        "buy": 1,
        "sell": 1,
    }
    assert {
        "reviewed_fee_schedule_asset_side_coverage_missing:etf:buy",
        "reviewed_fee_schedule_asset_side_coverage_missing:stock:sell",
    }.issubset(preview["issues"])


@pytest.mark.unit
@pytest.mark.trading_safety
def test_review_resolution_uses_same_rounding_and_revocation_fails_closed(
    tmp_path, monkeypatch
) -> None:
    state, imported = _state(tmp_path, rounded=True)
    _patch_ready_account_truth(monkeypatch, imported)
    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )
    repository = ReviewedFeeScheduleReviewRepository(state.db._path)
    review = repository.record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    reference = reviewed_cost_model_reference(review)
    resolution = resolve_reviewed_fee_schedule(
        state,
        start_date="2026-01-01",
        end_date="2026-08-12",
        universe=("600000.SH",),
        asset_classes=("stock",),
        expected_cost_model_reference=reference,
    )
    breakdown = resolution.commission_calc.breakdown_for(
        CommissionType.STOCK_A,
        OrderSide.SELL,
        Decimal("10.123"),
        Decimal("900"),
        symbol="600000.SH",
    )
    expected = resolve_manual_trade_fee_breakdown(
        state.config,
        asset_class="stock",
        direction="sell",
        quantity=900,
        price=10.123,
        symbol="600000.SH",
    )

    assert expected is not None
    assert breakdown.commission == Decimal(expected.fee_breakdown_json["commission"])
    assert breakdown.stamp_tax == Decimal(expected.fee_breakdown_json["stamp_tax"])
    assert breakdown.transfer_fee == Decimal(
        expected.fee_breakdown_json["transfer_fee"]
    )
    assert resolution.commission_calc.fee_rule_version == reference
    assert resolution.fee_evidence["broker_statement_reconciled"] is True
    assert (
        active_review_matches_fee_evidence(
            state.db,
            resolution.fee_evidence,
            as_of_date="2026-08-12",
        )
        == []
    )
    EvidenceScopeReviewRepository(state.db._path).revoke_latest(
        import_run_id=imported.import_run_id,
        expected_observed_scope_fingerprint="sha256:" + "9" * 64,
        reviewer="synthetic_owner",
    )
    assert (
        "reviewed_fee_schedule_account_truth_scope_review_revoked"
        in active_review_matches_fee_evidence(
            state.db,
            resolution.fee_evidence,
            as_of_date="2026-08-12",
        )
    )

    repository.revoke_latest(
        expected_review_id=review.review_id,
        expected_review_fingerprint=review.review_fingerprint,
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    )
    with pytest.raises(
        ReviewedFeeScheduleRejected,
        match="reviewed_fee_schedule_review_revoked",
    ):
        resolve_reviewed_fee_schedule(
            state,
            start_date="2026-01-01",
            end_date="2026-08-12",
            universe=("600000.SH",),
            asset_classes=("stock",),
            expected_cost_model_reference=reference,
        )


@pytest.mark.unit
def test_review_repository_missing_read_is_zero_write_and_tamper_blocks(
    tmp_path,
) -> None:
    missing_path = tmp_path / "missing" / "app.db"
    missing = ReviewedFeeScheduleReviewRepository(missing_path)

    assert missing.get_latest_review() is None
    assert not missing_path.parent.exists()

    schedule = {
        "schedule_id": "fixture",
        "account_profile_id": "fixture_account",
        "broker_name": "",
        "stock_a_commission_rate": "0.0001",
        "stock_a_min_commission": "5",
        "fund_etf_commission_rate": "0.0001",
        "fund_etf_min_commission": "5",
        "stamp_tax_rate": "0.0005",
        "transfer_fee_rate": "0.00001",
        "fund_etf_transfer_fee_rate": "0.00001",
        "exchange_transfer_fee_rates": {},
        "other_fee_rate": "0",
        "money_precision": None,
        "money_rounding_mode": "none",
        "limitations": [],
    }
    core = {
        "schema_version": REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
        "status": "ready",
        "schedule": schedule,
        "schedule_fingerprint": _fingerprint(schedule),
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-12-31",
        "reviewed_asset_classes": ["etf", "stock"],
        "account_truth_import_run_id": "import_fixture",
        "account_truth_source_fingerprint": "sha256:" + "1" * 64,
        "account_truth_scope_fingerprint": "sha256:" + "2" * 64,
        "account_reference_hash": "sha256:" + "3" * 64,
        "account_truth_readiness_status": "ready",
        "account_truth_promotion_status": "clear",
        "component_reconciliation": {"status": "pass"},
        "issues": [],
        "persisted_broker_events_only": True,
        "stores_broker_event_details": False,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    preview = {**core, "preview_fingerprint": _fingerprint(core)}
    review = missing.record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="fixture_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    with sqlite3.connect(missing_path) as conn:
        conn.execute(
            "UPDATE reviewed_fee_schedule_reviews SET schedule_json=? WHERE review_id=?",
            ("{}", review.review_id),
        )
        conn.commit()

    with pytest.raises(ReviewedFeeScheduleReadRejected):
        missing.get_latest_review()


@pytest.mark.unit
def test_legacy_review_without_etf_transfer_term_is_readable_but_drifts(
    tmp_path,
) -> None:
    repository = ReviewedFeeScheduleReviewRepository(tmp_path / "legacy.db")
    schedule = {
        "schedule_id": "legacy_fixture",
        "account_profile_id": "fixture_account",
        "broker_name": "",
        "stock_a_commission_rate": "0.0001",
        "stock_a_min_commission": "5",
        "fund_etf_commission_rate": "0.0001",
        "fund_etf_min_commission": "5",
        "stamp_tax_rate": "0.0005",
        "transfer_fee_rate": "0.00001",
        "exchange_transfer_fee_rates": {},
        "other_fee_rate": "0",
        "money_precision": None,
        "money_rounding_mode": "none",
        "limitations": [],
    }
    core = {
        "schema_version": REVIEWED_FEE_SCHEDULE_PREVIEW_SCHEMA_VERSION,
        "status": "ready",
        "schedule": schedule,
        "schedule_fingerprint": _fingerprint(schedule),
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-12-31",
        "reviewed_asset_classes": ["etf", "stock"],
        "account_truth_import_run_id": "import_fixture",
        "account_truth_source_fingerprint": "sha256:" + "1" * 64,
        "account_truth_scope_fingerprint": "sha256:" + "2" * 64,
        "account_reference_hash": "sha256:" + "3" * 64,
        "account_truth_readiness_status": "ready",
        "account_truth_promotion_status": "clear",
        "component_reconciliation": {"status": "pass"},
        "issues": [],
        "persisted_broker_events_only": True,
        "stores_broker_event_details": False,
        "provider_contacted": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    preview = {**core, "preview_fingerprint": _fingerprint(core)}
    recorded = repository.record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="fixture_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )

    loaded = repository.get_latest_review()

    assert loaded is not None
    assert loaded.review_id == recorded.review_id
    normalized_schedule = {
        **schedule,
        "fund_etf_transfer_fee_rate": schedule["transfer_fee_rate"],
    }
    assert _fingerprint(normalized_schedule) != loaded.schedule_fingerprint


@pytest.mark.unit
@pytest.mark.trading_safety
def test_legacy_review_requires_reacceptance_before_cost_resolution(
    tmp_path, monkeypatch
) -> None:
    state, imported = _state(tmp_path)
    _patch_ready_account_truth(monkeypatch, imported)
    current_preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )
    legacy_schedule = dict(current_preview["schedule"])
    legacy_schedule.pop("fund_etf_transfer_fee_rate")
    legacy_core = {
        key: value
        for key, value in current_preview.items()
        if key != "preview_fingerprint"
    }
    legacy_core["schedule"] = legacy_schedule
    legacy_core["schedule_fingerprint"] = _fingerprint(legacy_schedule)
    legacy_preview = {
        **legacy_core,
        "preview_fingerprint": _fingerprint(legacy_core),
    }
    review = ReviewedFeeScheduleReviewRepository(state.db._path).record_review(
        preview=legacy_preview,
        expected_preview_fingerprint=legacy_preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )

    with pytest.raises(
        ReviewedFeeScheduleRejected,
        match="reviewed_fee_schedule_source_drift",
    ):
        resolve_reviewed_fee_schedule(
            state,
            start_date="2026-01-01",
            end_date="2026-12-31",
            universe=("600000.SH",),
            asset_classes=("stock",),
            expected_cost_model_reference=reviewed_cost_model_reference(review),
        )


@pytest.mark.unit
def test_review_status_route_read_does_not_initialize_review_table(
    tmp_path, monkeypatch
) -> None:
    from server.routes import account_truth as account_truth_routes

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    with sqlite3.connect(db._path) as conn:
        before = conn.execute(
            "SELECT name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    router = account_truth_routes.create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/account-truth/fee-schedule/review"
        and "GET" in route.methods
    )

    response = asyncio.run(endpoint())

    with sqlite3.connect(db._path) as conn:
        after = conn.execute(
            "SELECT name, sql FROM sqlite_master ORDER BY name"
        ).fetchall()
    assert response["status"] == "missing"
    assert response["blockers"] == ["reviewed_fee_schedule_review_missing"]
    assert response["authorizes_execution"] is False
    assert before == after


@pytest.mark.unit
@pytest.mark.trading_safety
def test_fee_schedule_http_workflow_rechecks_drift_and_revokes_exact_review(
    tmp_path, monkeypatch
) -> None:
    from server.routes import account_truth as account_truth_routes

    state, imported = _state(tmp_path)
    _patch_ready_account_truth(monkeypatch, imported)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    router = account_truth_routes.create_router()

    def endpoint(path: str, method: str):
        return next(
            route.endpoint
            for route in router.routes
            if isinstance(route, APIRoute)
            and route.path == path
            and method in route.methods
        )

    preview = asyncio.run(
        endpoint("/api/account-truth/fee-schedule/preview", "POST")(
            account_truth_routes.ReviewedFeeSchedulePreviewCreate(
                effective_start_date="2026-01-01",
                effective_end_date="2026-12-31",
            )
        )
    )
    assert preview["status"] == "ready"
    accepted = asyncio.run(
        endpoint("/api/account-truth/fee-schedule/reviews", "POST")(
            account_truth_routes.ReviewedFeeScheduleReviewCreate(
                effective_start_date="2026-01-01",
                effective_end_date="2026-12-31",
                expected_preview_fingerprint=preview["preview_fingerprint"],
                reviewer="synthetic_owner",
                confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
            )
        )
    )
    assert accepted["status"] == "accepted"
    assert accepted["authorizes_execution"] is False
    assert accepted["changes_capital_authority"] is False

    get_status = endpoint("/api/account-truth/fee-schedule/review", "GET")
    active = asyncio.run(get_status())
    assert active["status"] == "active"
    assert active["blockers"] == []
    assert active["current_preview_fingerprint"] == preview["preview_fingerprint"]
    outside_action_window = build_reviewed_fee_schedule_review_status(
        state,
        as_of_date="2027-01-02",
    )
    assert outside_action_window["status"] == "blocked"
    assert outside_action_window["blockers"] == [
        "reviewed_fee_schedule_action_date_not_covered"
    ]
    assert outside_action_window["database_writes_performed"] is False
    assert outside_action_window["provider_contacted"] is False

    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_latest_account_truth_promotion_evidence",
        lambda state: {
            "status": "clear",
            "import_run_id": imported.import_run_id,
            "source_fingerprint": "sha256:" + "d" * 64,
        },
    )
    blocked = asyncio.run(get_status())
    assert blocked["status"] == "blocked"
    assert "reviewed_fee_schedule_source_drift" in blocked["blockers"]

    review = accepted["review"]
    revoked = asyncio.run(
        endpoint("/api/account-truth/fee-schedule/reviews/revoke", "POST")(
            account_truth_routes.ReviewedFeeScheduleReviewRevoke(
                expected_review_id=review["review_id"],
                expected_review_fingerprint=review["review_fingerprint"],
                reviewer="synthetic_owner",
                confirmation=REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
            )
        )
    )
    assert revoked["status"] == "revoked"
    assert revoked["authorizes_execution"] is False
    assert asyncio.run(get_status())["status"] == "revoked"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_reviewed_fee_schedule_survives_only_valid_daily_snapshot_lineage(
    tmp_path,
    monkeypatch,
) -> None:
    statement_path = tmp_path / "broker_statement.csv"
    statement_path.write_text(_BROKER_TRADES, encoding="utf-8")
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    broker_repository = BrokerEvidenceRepository(db._path)
    state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(broker_fee_schedule=_schedule()),
    )

    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-21",
        max_file_bytes=1024 * 1024,
    )
    reviewed_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    observed = project_account_truth_evidence_scope(
        score={"import_run_id": reviewed_import.import_run_id},
        import_run=reviewed_import,
        events=broker_repository.list_events(reviewed_import.import_run_id),
    )
    scope_repository = EvidenceScopeReviewRepository(db._path)
    scope_review = scope_repository.record_review(
        import_run_id=reviewed_import.import_run_id,
        import_file_fingerprint=reviewed_import.file_fingerprint,
        observed_scope_fingerprint=str(observed["observed_scope_fingerprint"]),
        provider="synthetic_broker",
        account_alias="synthetic_account",
        account_reference_hash="sha256:" + "a" * 64,
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
        asset_classes=["stock"],
        full_account_scope_attested=True,
        reviewer="synthetic_owner",
    )
    reviewed_scope = build_account_truth_evidence_scope(
        db_path=db._path,
        score={"import_run_id": reviewed_import.import_run_id},
    )
    context = {
        "readiness": {
            "status": "ready",
            "account_truth_import_run_id": reviewed_import.import_run_id,
            "evidence_scope": reviewed_scope,
        },
        "promotion": {
            "status": "clear",
            "import_run_id": reviewed_import.import_run_id,
            "source_fingerprint": "sha256:" + "c" * 64,
        },
    }
    account_truth_clock_observations: list[tuple[str, datetime]] = []

    def readiness_at_clock(state, *, clock=None):
        if clock is not None:
            account_truth_clock_observations.append(("readiness", clock()))
        return context["readiness"]

    def promotion_at_clock(state, *, clock=None):
        if clock is not None:
            account_truth_clock_observations.append(("promotion", clock()))
        return context["promotion"]

    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_account_truth_evidence_readiness",
        readiness_at_clock,
    )
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_latest_account_truth_promotion_evidence",
        promotion_at_clock,
    )
    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )
    assert preview["status"] == "ready"
    assert preview["account_truth_binding_mode"] == "stable_source_fact_lineage"
    fee_repository = ReviewedFeeScheduleReviewRepository(db._path)
    fee_review = fee_repository.record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    stored_v3_core = {
        **{
            key: value for key, value in preview.items() if key != "preview_fingerprint"
        },
        "schema_version": "karkinos.account_truth.reviewed_fee_schedule_preview.v3",
    }
    stored_v3 = {
        **stored_v3_core,
        "preview_fingerprint": _fingerprint(stored_v3_core),
    }
    review_core = {
        "schema_version": fee_review.schema_version,
        "decision": fee_review.decision,
        "schedule_fingerprint": fee_review.schedule_fingerprint,
        "preview_fingerprint": stored_v3["preview_fingerprint"],
        "account_truth_import_run_id": fee_review.account_truth_import_run_id,
        "account_truth_source_fingerprint": fee_review.account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": fee_review.account_truth_scope_fingerprint,
        "account_reference_hash": fee_review.account_reference_hash,
        "effective_start_date": fee_review.effective_start_date,
        "effective_end_date": fee_review.effective_end_date,
        "reviewer": fee_review.reviewer,
    }
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            """
            UPDATE reviewed_fee_schedule_reviews
            SET preview_json=?, preview_fingerprint=?, review_fingerprint=?
            WHERE review_id=?
            """,
            (
                json.dumps(stored_v3, sort_keys=True, separators=(",", ":")),
                stored_v3["preview_fingerprint"],
                _fingerprint(review_core),
                fee_review.review_id,
            ),
        )
        conn.commit()
    fee_review = fee_repository.get_latest_review()
    assert fee_review is not None
    assert fee_review.preview["schema_version"].endswith(".v3")

    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-24",
        max_file_bytes=1024 * 1024,
    )
    current_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    current_scope = build_account_truth_evidence_scope(
        db_path=db._path,
        score={"import_run_id": current_import.import_run_id},
    )
    context["readiness"] = {
        "status": "ready",
        "account_truth_import_run_id": current_import.import_run_id,
        "evidence_scope": current_scope,
    }
    context["promotion"] = {
        "status": "clear",
        "import_run_id": current_import.import_run_id,
        "source_fingerprint": "sha256:" + "d" * 64,
    }

    replayed_preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
    )
    status = build_reviewed_fee_schedule_review_status(
        state,
        as_of_date="2026-08-24",
    )
    frozen_market_close = datetime(
        2026,
        8,
        24,
        15,
        30,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    resolution = resolve_reviewed_fee_schedule(
        state,
        start_date="2026-01-01",
        end_date="2026-08-24",
        universe=("600000.SH",),
        asset_classes=("stock",),
        expected_cost_model_reference=reviewed_cost_model_reference(fee_review),
        account_truth_as_of=frozen_market_close,
    )

    assert current_scope["review"]["review_id"] == scope_review.review_id
    assert current_scope["review"]["binding_mode"] == ("inherited_source_fact_lineage")
    assert replayed_preview["schema_version"].endswith(".v4")
    assert replayed_preview["preview_fingerprint"] == preview["preview_fingerprint"]
    assert status["status"] == "active"
    assert status["blockers"] == []
    assert resolution.fee_evidence["account_truth_freshness_as_of"] == (
        frozen_market_close.isoformat()
    )
    assert account_truth_clock_observations[-4:] == [
        ("readiness", frozen_market_close),
        ("promotion", frozen_market_close),
        ("promotion", frozen_market_close),
        ("readiness", frozen_market_close),
    ]
    assert (
        active_review_matches_fee_evidence(
            db,
            resolution.fee_evidence,
            as_of_date="2026-08-24",
        )
        == []
    )

    statement_path.write_text(
        statement_path.read_text(encoding="utf-8")
        + "synthetic-buy-002,trade_buy,2026-08-24T10:00:00+08:00,"
        "2026-08-25,600000.SH,synthetic stock,stock,CNY,1000,20.00,"
        "20000.00,5.00,0.00,-20005.20,79979.60,1000,20.01,"
        "synthetic buy 2,0.20,broker_remaining_cost\n",
        encoding="utf-8",
    )
    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-25",
        max_file_bytes=1024 * 1024,
    )
    appended_import = broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    appended_scope = build_account_truth_evidence_scope(
        db_path=db._path,
        score={"import_run_id": appended_import.import_run_id},
    )
    context["readiness"] = {
        "status": "ready",
        "account_truth_import_run_id": appended_import.import_run_id,
        "evidence_scope": appended_scope,
    }
    context["promotion"] = {
        "status": "clear",
        "import_run_id": appended_import.import_run_id,
        "source_fingerprint": "sha256:" + "e" * 64,
    }
    appended_status = build_reviewed_fee_schedule_review_status(
        state,
        as_of_date="2026-08-25",
    )
    appended_resolution = resolve_reviewed_fee_schedule(
        state,
        start_date="2026-01-01",
        end_date="2026-08-25",
        universe=("600000.SH",),
        asset_classes=("stock",),
        expected_cost_model_reference=reviewed_cost_model_reference(fee_review),
    )

    assert appended_scope["source_fact_continuity"]["added_activity_count"] == 1
    assert appended_status["status"] == "active"
    with pytest.raises(
        ReviewedFeeScheduleRejected,
        match="reviewed_fee_schedule_notional_envelope_exceeded",
    ):
        appended_resolution.commission_calc.calculate_for(
            CommissionType.STOCK_A,
            OrderSide.BUY,
            Decimal("20"),
            Decimal("1000"),
        )

    scope_repository.revoke_latest(
        import_run_id=reviewed_import.import_run_id,
        expected_observed_scope_fingerprint=str(observed["observed_scope_fingerprint"]),
        reviewer="synthetic_owner",
    )
    blockers = active_review_matches_fee_evidence(
        db,
        resolution.fee_evidence,
        as_of_date="2026-08-24",
    )
    assert "reviewed_fee_schedule_account_truth_scope_review_revoked" in blockers

    changed = statement_path.read_text(encoding="utf-8").replace(
        "synthetic sell,0.10",
        "synthetic sell,0.11",
    )
    statement_path.write_text(changed, encoding="utf-8")
    roll_forward_daily_broker_statement(
        path=statement_path,
        run_date="2026-08-25",
        max_file_bytes=1024 * 1024,
    )
    broker_repository.save_preview(
        parse_broker_statement_csv(statement_path.read_bytes())
    )
    drift_blockers = active_review_matches_fee_evidence(
        db,
        resolution.fee_evidence,
        as_of_date="2026-08-25",
    )
    assert "reviewed_fee_schedule_account_truth_import_drift" in drift_blockers
