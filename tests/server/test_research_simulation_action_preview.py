"""Account what-if uses exact research lineage and verified read inputs only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey
from data.dataset.model import (
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.dataset.reader import DailyBarDatasetReadResult
from data.market.normalize import normalize_daily_bar
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.storage.objects import ObjectRef
from data.store import DataStore
from server.contracts.content_identity import content_fingerprint
from server.projections.account_action_recommendation import (
    build_research_simulation_action_preview,
)
from server.services.market.market_universe_truth import normalize_a_share_members
from tests.ai_runtime.test_research_simulation_source import (
    lineage as lineage,
)
from tests.ai_runtime.test_research_simulation_source import (
    native_exploratory_report as native_exploratory_report,
)


@pytest.fixture
def preview_inputs(lineage, tmp_path):
    """Synthetic typed read contract, not evidence of a real cold Dataset read."""
    source = lineage.service.resolve_research_simulation_source(lineage.source)
    assert source["status"] == "ready"
    days = (date(2026, 8, 27), date(2026, 8, 28))
    symbols = ("600001", "600002")
    instruments = tuple(InstrumentKey.from_values(s, "stock") for s in symbols)
    captured = datetime(2026, 8, 28, 8, tzinfo=timezone.utc)
    snapshot = DailyBarDatasetSnapshot(
        start_date=days[0],
        end_date=days[-1],
        cutoff=captured,
        instruments=instruments,
        resolver_policy_id="fixture.verified_read.v1",
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=tuple(
            DailyBarDatasetPartition(
                day,
                "fixture",
                "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
                verification_id="sha256:" + "c" * 64,
            )
            for day in days
        ),
    )
    bars = tuple(
        normalize_daily_bar(
            instrument=key,
            session_date=day,
            event_time=datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc),
            available_at=captured,
            captured_at=captured,
            open_value=str(value),
            high_value=str(value),
            low_value=str(value),
            close_value=str(value),
            volume="1000000",
            amount=str(value * 1000000),
            suspended=False,
        )
        for offset, day in enumerate(days)
        for key in instruments
        for value in ([10, 11] if key.symbol == "600001" else [12, 11])[
            offset : offset + 1
        ]
    )
    read = DailyBarDatasetReadResult(
        ref=DatasetRef(ObjectRef("sha256:" + "d" * 64, 1)),
        snapshot=snapshot,
        bars=bars,
    )
    master = DataStore(tmp_path / "synthetic-market").save_market_universe_snapshot(
        trade_date=days[-1].isoformat(),
        provider_name="fixture",
        members=normalize_a_share_members(symbols),
        capture_started_at=captured,
        capture_completed_at=captured,
        source_metadata=[
            {
                "symbol": s,
                "display_name": "合成公司",
                "list_status": "L",
                "list_date": "20100101",
            }
            for s in symbols
        ],
    )
    portfolio = {
        "fact_authority": "persisted_valuation_snapshot",
        "valuation_status": "complete",
        "valuation_snapshot_id": "fixture-valuation",
        "ledger_cutoff_id": 7,
        "symbols": ["600002"],
        "instrument_types": {"600002": "stock"},
        "cash": 67000,
        "total_equity": 100000,
        "stock_position_market_values": {"600002": 33000},
    }
    return {
        "research_source": source,
        "decision_payload": {
            "summary": {
                "portfolio": portfolio,
                "account_truth": {
                    "reconciliation_status": "pass",
                    "unresolved_mismatch_count": 0,
                    "ledger_coverage": {"status": "covered"},
                    "import_run_id": "fixture-import",
                    "source_fingerprint": "e" * 64,
                },
            }
        },
        "account_fact_blockers": [],
        "positions": {
            "600002": SimpleNamespace(quantity=3000, available_quantity=3000)
        },
        "position_values": {"600002": Decimal("33000")},
        "market_session": {
            "calendar_verified": True,
            "calendar_evidence_refs": ["fixture-calendar"],
            "status": "non_trading_day",
            "market_date": "2026-08-29",
            "next_trading_date": "2026-08-31",
            "latest_completed_trade_date": "2026-08-28",
        },
        "market_snapshot": master,
        "verified_dataset_read": read,
        "receipts": [
            {
                "schema_version": "karkinos.market_daily_ingestion_receipt.v3",
                "storage_authority": "sqlite_market_bars_v2:stock",
                "units": {"volume": "shares", "amount": "CNY"},
                "price_basis": "unadjusted",
                "trade_date": d.isoformat(),
                "provider_name": "fixture",
                "receipt_fingerprint": "sha256:" + str(i + 1) * 64,
            }
            for i, d in enumerate(days)
        ],
        "trading_dates": [d.isoformat() for d in days],
        "history_start": "2026-08-27",
        "target_market_date": "2026-08-31",
    }


def test_closed_market_keeps_explicit_research_asof_and_no_authority(preview_inputs):
    original = deepcopy(preview_inputs["research_source"])
    result = build_research_simulation_action_preview(**preview_inputs)
    assert result["status"] == "available", result["blockers"]
    assert {(r["symbol"], r["side"]) for r in result["actions"]} == {
        ("600001", "buy"),
        ("600002", "sell"),
    }
    assert result["as_of_market_date"] == "2026-08-28"
    assert result["target_market_date"] == "2026-08-31"
    assert (
        result["price_basis"] == "verified_daily_close"
        and result["uses_current_quotes"] is False
    )
    assert result["manual_confirmation_required"] is True
    assert result["human_review_status"] == "not_recorded"
    assert result["cost_basis"] == "saved_research_assumptions"
    assert result["account_fee_schedule_evaluated"] is False
    assert result["cost_assumptions"]["source"] == "research_simulation"
    for key in (
        "executable",
        "creates_action_task",
        "creates_order_intent",
        "creates_oms_order",
        "authorizes_account_publication",
        "authorizes_execution",
        "changes_capital_authority",
    ):
        assert result[key] is False
    assert result["authority_effect"] == "none"
    assert all(
        r["action_id"] is None and r["executable"] is False for r in result["actions"]
    )
    assert result["source"]["research_evidence_bundle"]["gate_status"] == "blocked"
    assert result["hypothetical_exit_proceeds_available"] is False
    assert preview_inputs["research_source"] == original


@pytest.mark.parametrize(
    "missing",
    [
        "research_source",
        "account_fact_blockers",
        "positions",
        "position_values",
        "market_session",
        "market_snapshot",
        "verified_dataset_read",
        "history_start",
        "target_market_date",
    ],
)
def test_missing_inputs_do_not_become_actions(preview_inputs, missing):
    result = build_research_simulation_action_preview(
        **(preview_inputs | {missing: None})
    )
    assert result["status"] == "blocked"
    assert result["actions"] == [] and result["blockers"]


def test_single_source_sql_receipts_are_not_cross_source_evidence(preview_inputs):
    result = build_research_simulation_action_preview(
        **(preview_inputs | {"verified_dataset_read": None})
    )
    assert "research_latest_cross_source_dataset_unavailable" in result["blockers"]
    read = preview_inputs["verified_dataset_read"]
    unverified = replace(
        read,
        snapshot=replace(
            read.snapshot,
            partitions=tuple(
                replace(p, verification_id=None) for p in read.snapshot.partitions
            ),
        ),
    )
    result = build_research_simulation_action_preview(
        **(preview_inputs | {"verified_dataset_read": unverified})
    )
    assert "research_latest_cross_source_dataset_unavailable" in result["blockers"]


def test_old_dataset_is_not_retimestamped_to_latest_market_date(preview_inputs):
    read = preview_inputs["verified_dataset_read"]
    old = replace(
        read,
        snapshot=replace(
            read.snapshot,
            end_date=date(2026, 8, 27),
            partitions=read.snapshot.partitions[:1],
        ),
    )
    result = build_research_simulation_action_preview(
        **(preview_inputs | {"verified_dataset_read": old})
    )
    assert result["actions"] == []
    assert "research_latest_cross_source_dataset_unavailable" in result["blockers"]


def test_actual_account_blocker_is_not_stripped(preview_inputs):
    result = build_research_simulation_action_preview(
        **(preview_inputs | {"account_fact_blockers": ["account_truth_not_fresh"]})
    )
    assert result["actions"] == [] and "account_truth_not_fresh" in result["blockers"]


def test_research_source_drift_and_incomplete_market_fail_closed(preview_inputs):
    preview_inputs["research_source"]["draft_id"] = "changed"
    result = build_research_simulation_action_preview(**preview_inputs)
    assert "research_simulation_source_fingerprint_mismatch" in result["blockers"]
    assert result["actions"] == []


def test_missing_daily_coverage_and_bars_are_not_no_signal(preview_inputs):
    result = build_research_simulation_action_preview(
        **(preview_inputs | {"receipts": preview_inputs["receipts"][:1]})
    )
    assert result["status"] == "blocked" and result["actions"] == []
    read = preview_inputs["verified_dataset_read"]
    result = build_research_simulation_action_preview(
        **(
            preview_inputs
            | {
                "verified_dataset_read": replace(
                    read,
                    bars=tuple(
                        b for b in read.bars if b.session_date < read.snapshot.end_date
                    ),
                )
            }
        )
    )
    assert result["status"] == "blocked" and result["actions"] == []


def test_cashless_exit_is_not_used_to_finance_entry(preview_inputs):
    preview_inputs["decision_payload"]["summary"]["portfolio"]["cash"] = 0
    result = build_research_simulation_action_preview(**preview_inputs)
    assert [r["side"] for r in result["actions"]] == ["sell"]
    assert any(
        r["reason"] == "cash_or_lot_constraint" for r in result["blocked_candidates"]
    )


def test_unsellable_position_is_not_presented_as_available_exit(preview_inputs):
    preview_inputs["positions"]["600002"].available_quantity = 0
    result = build_research_simulation_action_preview(**preview_inputs)
    assert all(r["side"] != "sell" for r in result["actions"])
    assert any(
        r["reason"] == "research_sellable_quantity_insufficient_or_missing"
        for r in result["blocked_candidates"]
    )


@pytest.mark.parametrize("field", ["quantity", "available_quantity"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_nonfinite_or_negative_position_quantity_never_becomes_exit(
    preview_inputs, field, value
):
    setattr(preview_inputs["positions"]["600002"], field, value)
    result = build_research_simulation_action_preview(**preview_inputs)
    assert all(row["side"] != "sell" for row in result["actions"])
    assert any(
        row["reason"] == "research_sellable_quantity_insufficient_or_missing"
        for row in result["blocked_candidates"]
    )


def test_sql_receipt_cannot_fill_missing_cross_source_partition(preview_inputs):
    read = preview_inputs["verified_dataset_read"]
    preview_inputs["verified_dataset_read"] = replace(
        read, snapshot=replace(read.snapshot, start_date=date(2026, 8, 26))
    )
    preview_inputs["history_start"] = "2026-08-26"
    preview_inputs["trading_dates"].insert(0, "2026-08-26")
    preview_inputs["receipts"].insert(
        0, {**preview_inputs["receipts"][0], "trade_date": "2026-08-26"}
    )
    result = build_research_simulation_action_preview(**preview_inputs)
    assert result["status"] == "blocked" and result["actions"] == []
    assert "research_cross_source_session_coverage_incomplete" in result["blockers"]


def test_position_values_must_match_the_bound_stock_valuation(preview_inputs):
    preview_inputs["position_values"]["600002"] = Decimal(0)
    result = build_research_simulation_action_preview(**preview_inputs)
    assert result["status"] == "blocked" and result["actions"] == []


def test_target_session_must_match_canonical_calendar_projection(preview_inputs):
    result = build_research_simulation_action_preview(
        **(preview_inputs | {"target_market_date": "2026-08-30"})
    )
    assert result["actions"] == []
    assert "research_latest_verified_daily_window_unavailable" in result["blockers"]


def test_other_asset_holdings_keep_their_slots_and_are_not_rebalanced(preview_inputs):
    p = preview_inputs["decision_payload"]["summary"]["portfolio"]
    for symbol in ("159901", "159902", "159903"):
        p["symbols"].append(symbol)
        p["instrument_types"][symbol] = "etf"
        preview_inputs["position_values"][symbol] = Decimal("10000")
        preview_inputs["positions"][symbol] = SimpleNamespace(
            quantity=1000, available_quantity=1000
        )
    result = build_research_simulation_action_preview(**preview_inputs)
    assert [r["side"] for r in result["actions"]] == ["sell"]
    assert any(r["reason"] == "position_limit" for r in result["blocked_candidates"])
    assert all(
        result["target_weights"][s] == "0.1" for s in ("159901", "159902", "159903")
    )


@pytest.fixture
def preview_route(preview_inputs, lineage, monkeypatch):
    """Bind real projection and gate owners to synthetic request inputs."""
    from server.routes import decision

    payload = deepcopy(preview_inputs["decision_payload"])
    payload.update(decision_date="2026-08-29", generated_at="2026-08-29T01:30:00Z")
    payload["summary"]["account_truth"].update(
        schema_version="karkinos.account_truth.promotion_evidence.v1",
        promotion_status="clear",
        gate_status="pass",
        data_freshness_status="fresh",
        captured_at="2026-08-29T01:20:00Z",
        current_age_seconds=600,
        max_age_seconds=3600,
    )
    # Formal strategy and reviewed-window gates do not authorize this what-if.
    plan = {
        "schema_version": "karkinos.daily_trading_plan.v1",
        "plan_date": "2026-08-29",
        "generated_at": "2026-08-29T01:30:00Z",
        "status": "blocked",
        "blockers": ["forward_evidence_not_ready"],
        "order_intents": [],
    }
    positions = preview_inputs["positions"]
    positions["600002"].market_value = 33000
    context = {
        "authority": "persisted_valuation_snapshot",
        "portfolio": SimpleNamespace(positions=positions),
        "valuation_snapshot": {
            "status": "complete",
            "snapshot_id": "fixture-valuation",
            "ledger_cutoff_id": 7,
        },
    }
    state = SimpleNamespace(
        config=SimpleNamespace(research_simulation_source=lineage.source)
    )
    monkeypatch.setattr(
        "server.composition.ai_application_services.build_strategy_research_read_service",
        lambda _: lineage.service,
    )
    monkeypatch.setattr(
        "server.services.market.calendar.project_market_session",
        lambda _: preview_inputs["market_session"],
    )
    monkeypatch.setattr(
        "server.services.market.asset_metadata.resolve_asset_metadata",
        lambda *_a, **_k: SimpleNamespace(display_name="合成公司"),
    )
    kwargs = {
        name: preview_inputs[name]
        for name in (
            "verified_dataset_read",
            "market_snapshot",
            "receipts",
            "trading_dates",
            "history_start",
            "target_market_date",
        )
    }
    monkeypatch.setattr(
        "server.services.research.datasets.resolve_research_simulation_market_inputs",
        lambda *_a: {"kwargs": kwargs, "blockers": []},
        raising=False,
    )
    return SimpleNamespace(
        read=lambda: decision._research_simulation_preview_for_state(
            state,
            decision_payload=payload,
            trading_plan=plan,
            portfolio_context=context,
        ),
        state=state,
        payload=payload,
        plan=plan,
        context=context,
    )


def test_route_has_real_account_sizing_without_forward_or_order_authority(
    preview_route,
):
    original = deepcopy(preview_route.plan)
    result = preview_route.read()
    assert result["status"] == "available", result["blockers"]
    assert {r["side"] for r in result["actions"]} == {"buy", "sell"}
    assert result["valuation_snapshot_id"] == "fixture-valuation"
    assert result["ledger_cutoff_id"] == 7
    assert result["creates_order_intent"] is False
    assert result["executable"] is False
    assert preview_route.plan == original


@pytest.mark.parametrize("invalid", ["account_truth", "valuation_binding"])
def test_route_preserves_actual_account_and_valuation_blockers(preview_route, invalid):
    if invalid == "account_truth":
        preview_route.payload["summary"]["account_truth"]["data_freshness_status"] = (
            "stale"
        )
        expected = "account_truth_not_fresh"
    else:
        preview_route.context["valuation_snapshot"]["snapshot_id"] = "different"
        expected = "research_current_valuation_binding_mismatch"
    result = preview_route.read()
    assert result["status"] == "blocked" and result["actions"] == []
    assert expected in result["blockers"]


def test_unconfigured_route_does_not_select_a_strategy_or_load_data(
    preview_route, monkeypatch
):
    preview_route.state.config.research_simulation_source = None

    def forbidden(*_a):
        raise AssertionError(
            "unconfigured source must not load research or market data"
        )

    monkeypatch.setattr(
        "server.composition.ai_application_services.build_strategy_research_read_service",
        forbidden,
    )
    monkeypatch.setattr(
        "server.services.research.datasets.resolve_research_simulation_market_inputs",
        forbidden,
    )
    result = preview_route.read()
    assert result["actions"] == []
    assert "research_simulation_source_not_configured" in result["blockers"]


def test_weekend_permissions_are_checked_for_the_target_session(
    preview_inputs, preview_route, monkeypatch, tmp_path
):
    from server.services.account.account_board_permissions import (
        BOARD_PERMISSION_SOURCE,
        resolve_board_buy_permissions,
    )

    config = SimpleNamespace(
        account_board_permissions={
            "source": BOARD_PERMISSION_SOURCE,
            "reviewed_by": "synthetic-owner",
            "reviewed_at": "2026-08-28T01:00:00Z",
            "boards": {"chinext": "enabled"},
        }
    )
    resolved_dates = []

    def resolve(_config, target):
        resolved_dates.append(target)
        return resolve_board_buy_permissions(config, target)

    monkeypatch.setattr(
        "server.services.account.account_board_permissions.resolve_board_buy_permissions",
        resolve,
    )
    assert preview_route.read()["status"] == "available"
    assert resolved_dates == ["2026-08-31"]
    old, new = "600001", "300001"
    source = preview_inputs["research_source"]
    source["selection"]["universe"] = [
        new if s == old else s for s in source["selection"]["universe"]
    ]
    source["source_fingerprint"] = "sha256:" + content_fingerprint(
        {k: v for k, v in source.items() if k != "source_fingerprint"}
    )
    read = preview_inputs["verified_dataset_read"]
    key = InstrumentKey.from_values(new, "stock")
    preview_inputs["verified_dataset_read"] = replace(
        read,
        snapshot=replace(
            read.snapshot,
            instruments=tuple(
                key if k.symbol == old else k for k in read.snapshot.instruments
            ),
        ),
        bars=tuple(
            replace(b, instrument=key) if b.instrument.symbol == old else b
            for b in read.bars
        ),
    )
    captured = read.snapshot.cutoff
    preview_inputs["market_snapshot"] = DataStore(
        tmp_path / "board-market"
    ).save_market_universe_snapshot(
        trade_date="2026-08-28",
        provider_name="fixture",
        members=normalize_a_share_members((new, "600002")),
        capture_started_at=captured,
        capture_completed_at=captured,
        source_metadata=[
            {
                "symbol": s,
                "display_name": "合成公司",
                "list_status": "L",
                "list_date": "20100101",
            }
            for s in (new, "600002")
        ],
    )
    preview_inputs["decision_payload"]["summary"]["portfolio"][
        "board_buy_permissions"
    ] = resolve_board_buy_permissions(config, "2026-08-29")
    before = build_research_simulation_action_preview(**preview_inputs)
    assert any(
        r["symbol"] == new and r["reason"] == "board_permission_unknown"
        for r in before["blocked_candidates"]
    )
    after = build_research_simulation_action_preview(
        **preview_inputs,
        target_board_buy_permissions=resolve_board_buy_permissions(
            config, "2026-08-31"
        ),
    )
    assert any(r["symbol"] == new and r["side"] == "buy" for r in after["actions"])
    assert after["executable"] is False and after["creates_order_intent"] is False
