"""Real immutable datasets and saved research definitions at forward publication."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from core.types import AssetClass, InstrumentKey, InstrumentType, Symbol
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DailyBarDatasetPartition, DailyBarDatasetSnapshot
from data.handler import DataHandler
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import publish_market_quality_evidence
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    reconcile_daily_bar_revisions,
)
from data.market.revision import publish_daily_bar_revision
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import publish_market_verification_evidence
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR
from data.providers.tushare import TUSHARE_DAILY_BAR_DESCRIPTOR
from data.source_policy import FREE_CN_RESEARCH_V1
from data.storage.objects import ContentAddressedObjectStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
    FormulaBinding,
)
from server.services.research_observation_inputs import (
    ResearchObservationInputError,
    latest_closed_session,
    load_research_observation_source,
    observation_outcome_sessions,
    read_research_observation_dataset,
)
from server.services.verified_daily_market_data import verified_daily_resolver_policy_id

STOCK = InstrumentKey("600000", InstrumentType.STOCK)
DAYS = tuple(date(2026, 9, n) for n in (14, 15, 16, 17, 18, 21, 22, 23))
NOW = datetime(2026, 9, 18, 8, tzinfo=timezone.utc)


def calendar(*, year=2026, trading_days=DAYS):
    day = date(year, 1, 1)
    days = []
    while day.year == year:
        days.append({"date": day.isoformat(), "is_trading_day": day in trading_days})
        day += timedelta(days=1)
    trading = sum(item["is_trading_day"] for item in days)
    return {
        "year": year,
        "exchange": "SSE",
        "days": days,
        "trading_day_count": trading,
        "closed_day_count": len(days) - trading,
        "source_fingerprint": "a" * 64,
        "verification_source_fingerprint": "a" * 64,
        "official_source_fingerprint": "b" * 64,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": "2026-09-01T00:00:00Z",
        "fetched_at": "2026-09-01T00:00:00Z",
        "official_verified_by": "fixture",
        "official_verification_status": "verified",
    }


def side(store, day, descriptor, *, captured_at=None, event_hour=7, close="10.5"):
    captured = captured_at or datetime.combine(
        day, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=7, minutes=1)
    checked = datetime.combine(
        day, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=7, minutes=5)
    capture = capture_provider_payload(
        store,
        provider=descriptor.provider,
        operation="daily_bars",
        request={"day": day.isoformat()},
        raw_payload=json.dumps({"fixture": True, "close": close}).encode(),
        payload_format="fixture.v1",
        adapter_version=descriptor.adapter_version,
        started_at=captured - timedelta(seconds=1),
        completed_at=captured,
        record_count=1,
    )
    bar = normalize_daily_bar(
        instrument=STOCK,
        session_date=day,
        event_time=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        + timedelta(hours=event_hour),
        available_at=min(captured, checked - timedelta(minutes=4)),
        captured_at=captured,
        open_value=close,
        high_value=str(Decimal(close) + 1),
        low_value=str(Decimal(close) - 1),
        close_value=close,
        volume="100000",
        amount=str(Decimal(close) * 100000),
        suspended=False,
    )
    revision, materialization = publish_daily_bar_revision(
        store, capture=capture, bars=(bar,), normalizer_version="fixture.v1"
    )
    quality = publish_market_quality_evidence(
        store,
        evaluate_daily_bar_revision(
            store,
            revision=revision,
            materialization=materialization,
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=(STOCK,),
            checked_at=checked,
        ),
    )
    return revision, materialization, quality


def dataset(
    tmp_path,
    *,
    days=DAYS[:5],
    comparison_capture=None,
    cutoff=NOW,
    event_hour=7,
    verified=True,
    closes=None,
):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    partitions = []
    for day in days:
        close = closes.get(day, "10.5") if closes else "10.5"
        primary = side(
            objects, day, TDX_PROVIDER_DESCRIPTOR, event_hour=event_hour, close=close
        )
        comparison = side(
            objects,
            day,
            TUSHARE_DAILY_BAR_DESCRIPTOR,
            captured_at=comparison_capture if day == days[-1] else None,
            event_hour=event_hour,
            close=close,
        )
        verification = publish_market_verification_evidence(
            objects,
            report=reconcile_daily_bar_revisions(
                objects,
                primary_revision=primary[0],
                primary_materialization=primary[1],
                comparison_revision=comparison[0],
                comparison_materialization=comparison[1],
                policy=STRICT_DAILY_RECONCILIATION,
            ),
            primary_quality=primary[2],
            comparison_quality=comparison[2],
            primary_descriptor=TDX_PROVIDER_DESCRIPTOR,
            comparison_descriptor=TUSHARE_DAILY_BAR_DESCRIPTOR,
            policy=STRICT_DAILY_RECONCILIATION,
            checked_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(hours=7, minutes=5),
        )
        partitions.append(
            DailyBarDatasetPartition(
                partition_date=day,
                provider=primary[0].provider,
                revision_id=primary[0].ref.revision_id,
                materialization_id=primary[1].materialization_id,
                verification_id=verification.verification_id if verified else None,
            )
        )
    snapshot = DailyBarDatasetSnapshot(
        start_date=days[0],
        end_date=days[-1],
        cutoff=cutoff,
        instruments=(STOCK,),
        resolver_policy_id=verified_daily_resolver_policy_id(
            FREE_CN_RESEARCH_V1.policy_id
        )
        if verified
        else "karkinos.dataset.pit.strict.v1",
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=tuple(partitions),
    )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    return objects, ref


def read(objects, ref, **changes):
    return read_research_observation_dataset(
        objects,
        ref.dataset_id,
        **{
            "instruments": (STOCK,),
            "start_date": DAYS[0],
            "now": NOW,
            "calendar_rows": [calendar()],
            "minimum_bars": 4,
            **changes,
        },
    )


def source(ref):
    return {
        "id": 7,
        "config_json": json.dumps(
            {
                "strategy": "dual_ma",
                "params": {"short_period": 2, "long_period": 3},
                "dataset_id": ref.dataset_id,
                "start_date": DAYS[0].isoformat(),
                "end_date": DAYS[4].isoformat(),
                "assets": [{"symbol": STOCK.symbol, "asset_class": "stock"}],
            }
        ),
        "metrics_json": json.dumps(
            {
                "dataset_binding": {"dataset_id": ref.dataset_id},
                "cost_assumptions": {"slippage_bps": "12.5"},
            }
        ),
    }


def test_formal_forward_read_accepts_after_close_capture_and_preserves_exact_ref(
    tmp_path,
):
    objects, ref = dataset(tmp_path)
    result = read(objects, ref)
    assert result.ref == ref
    assert result.row_count == 5
    assert result.bars[-1].captured_at > result.bars[-1].event_time
    assert result.bars[-1].captured_at < NOW


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"minimum_bars": 6}, "warmup_incomplete"),
        ({"start_date": DAYS[1]}, "start_mismatch"),
        (
            {"instruments": (InstrumentKey("000001", InstrumentType.STOCK),)},
            "universe_mismatch",
        ),
        ({"now": NOW + timedelta(days=3)}, "not_latest_closed"),
    ],
)
def test_forward_read_rejects_changed_boundary(tmp_path, changes, error):
    objects, ref = dataset(tmp_path)
    with pytest.raises(ResearchObservationInputError, match=error):
        read(objects, ref, **changes)


@pytest.mark.parametrize(
    "options,error",
    [
        ({"days": (DAYS[0], DAYS[1], DAYS[3], DAYS[4])}, "prefix_incomplete"),
        ({"cutoff": NOW + timedelta(seconds=1)}, "cutoff_in_future"),
        (
            {"comparison_capture": NOW + timedelta(seconds=1)},
            "bound_evidence_not_available",
        ),
        ({"event_hour": 6}, "bar_not_available"),
        ({"verified": False}, "dataset_unverified"),
    ],
)
def test_forward_read_rejects_missing_or_future_evidence(tmp_path, options, error):
    objects, ref = dataset(tmp_path, **options)
    with pytest.raises(ResearchObservationInputError, match=error):
        read(objects, ref)


def test_dual_ma_source_freezes_original_parameters_costs_and_explicit_limits(tmp_path):
    objects, ref = dataset(tmp_path)
    restored = load_research_observation_source(source(ref), objects)
    assert restored["parameters"] == {"short_period": 2, "long_period": 3}
    assert restored["minimum_bars"] == 4
    assert restored["entry_target_weight"] == "1"
    assert restored["dataset_id"] == ref.dataset_id
    assert restored["cost_assumptions"]["slippage_bps"] == "12.5"
    assert restored["source_code_verified"] is False
    assert restored["source_historical_pit_verified"] is False


@pytest.mark.parametrize(
    "change,error",
    [
        ({"dataset_id": None}, "formal_dataset_required"),
        ({"params": {"short_period": 2}}, "parameters_not_normalized"),
        ({"assets": [{"symbol": "600000", "asset_class": "etf"}]}, "universe_mismatch"),
        ({"strategy": "bollinger"}, "strategy_unsupported"),
    ],
)
def test_saved_source_rejects_unbound_or_changed_inputs(tmp_path, change, error):
    objects, ref = dataset(tmp_path)
    row = source(ref)
    row["config_json"] = {**json.loads(row["config_json"]), **change}
    with pytest.raises(ResearchObservationInputError, match=error):
        load_research_observation_source(row, objects)


def formula_source(*, research_dataset_binding=None):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-09-14", periods=5),
            "open": [10] * 5,
            "high": [11] * 5,
            "low": [9] * 5,
            "close": [10.5] * 5,
            "volume": [100000] * 5,
        }
    )
    handler = DataHandler(
        frame,
        Symbol(STOCK.symbol),
        asset_class=AssetClass.STOCK,
        instrument_type=InstrumentType.STOCK,
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[4].isoformat(),
        configured_source="fixture",
        source_names=["fixture"],
        store=None,
        data_handlers={Symbol(STOCK.symbol): handler},
        research_dataset_binding=research_dataset_binding,
    )
    field = {"op": "field", "name": "close"}
    binding = FormulaBinding(
        formula_ast={
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {
                "op": "cross",
                "left": field,
                "right": {"op": "rolling_mean", "input": field, "window": 3},
            },
            "exit": {
                "op": "lt",
                "left": field,
                "right": {"op": "constant", "value": 9},
            },
            "position_size": {
                "op": "max_weight",
                "input": {"op": "equal_weight"},
                "value": 0.02,
            },
        },
        universe=(STOCK.symbol,),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[4].isoformat(),
        frequency="1d",
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
        anti_lookahead_assumptions=("completed bars",),
        parameter_values={},
        parameter_ranges={},
        initial_cash=100000,
    )
    row = {
        "id": 8,
        "config_json": {
            "strategy": "ai_formula_research",
            "start_date": binding.start_date,
            "end_date": binding.end_date,
            "params": {"formula_fingerprint": binding.fingerprint},
            "assets": [{"symbol": STOCK.symbol, "asset_class": "stock"}],
        },
        "metrics_json": {
            "formula_binding": binding.to_dict(),
            "formula_fingerprint": binding.fingerprint,
            "dataset_snapshot": snapshot,
            "signal_execution_evidence": {
                "schema_version": "karkinos.ai.formula_signal_execution.v1",
                "allocation_slots": 1,
                "canonical_target_weight": 1.0,
                "model_position_size_ignored": True,
            },
        },
    }

    execution = row["metrics_json"]["signal_execution_evidence"]
    execution["evidence_fingerprint"] = content_fingerprint(execution)
    return row


def test_formula_uses_actual_saved_snapshot_and_canonical_sizing_without_account(
    tmp_path,
):
    row = formula_source()
    restored = load_research_observation_source(
        row, ContentAddressedObjectStore(tmp_path / "empty")
    )
    assert restored["source_dataset_kind"] == "analytics_snapshot"
    assert restored["minimum_bars"] == 4
    assert Decimal(restored["entry_target_weight"]) == 1
    assert restored["formula_binding"]["formula_ast"]["position_size"]["value"] == 0.02
    assert restored["source_historical_pit_verified"] is False


def test_formula_keeps_existing_immutable_input_identity_without_upgrading_authority(
    tmp_path,
):
    dataset_id = "sha256:" + "a" * 64
    row = formula_source(
        research_dataset_binding={
            "dataset_id": dataset_id,
            "cutoff": NOW.isoformat(),
            "price_basis": "unadjusted",
            "cross_source_verified": True,
            "point_in_time_verified": False,
            "limitations": ["Historical availability unverified", "Price-only returns"],
        }
    )
    restored = load_research_observation_source(
        row, ContentAddressedObjectStore(tmp_path / "empty")
    )
    assert restored["immutable_dataset_id"] == dataset_id
    assert (
        restored["dataset_id"] == row["metrics_json"]["dataset_snapshot"]["snapshot_id"]
    )
    assert restored["source_dataset_kind"] == "analytics_snapshot"
    assert restored["source_historical_pit_verified"] is False


@pytest.mark.parametrize(
    "mutation,error",
    [
        (
            lambda r: r["metrics_json"]["formula_binding"]["formula_ast"][
                "entry"
            ].update(op="gt"),
            "fingerprint_mismatch",
        ),
        (
            lambda r: r["metrics_json"]["dataset_snapshot"]["symbol_universe"][
                0
            ].update(instrument_type="etf"),
            "snapshot_invalid",
        ),
        (
            lambda r: r["metrics_json"]["signal_execution_evidence"].update(
                canonical_target_weight=0.02
            ),
            "sizing_unbound",
        ),
        (
            lambda r: r["config_json"]["params"].update(formula_fingerprint="changed"),
            "source_mismatch",
        ),
    ],
)
def test_formula_rejects_changed_definition_or_sizing(tmp_path, mutation, error):
    row = copy.deepcopy(formula_source())
    mutation(row)
    with pytest.raises(ResearchObservationInputError, match=error):
        load_research_observation_source(
            row, ContentAddressedObjectStore(tmp_path / "empty")
        )


def test_outcome_sessions_are_strictly_after_publication_open_and_exact_horizon():
    rows = [calendar()]
    before_open = datetime(2026, 9, 18, 1, 29, 59, tzinfo=timezone.utc)
    assert observation_outcome_sessions(
        rows, published_at=before_open, horizon_sessions=1, now=before_open
    ) == (DAYS[4], DAYS[5])
    at_open = before_open + timedelta(seconds=1)
    assert observation_outcome_sessions(
        rows, published_at=at_open, horizon_sessions=1, now=at_open
    ) == (DAYS[5], DAYS[6])
    assert latest_closed_session(rows, now=before_open) == DAYS[3]
    assert (
        latest_closed_session(rows, now=datetime(2026, 9, 18, 7, tzinfo=timezone.utc))
        == DAYS[4]
    )


@pytest.mark.parametrize(
    "change,error",
    [
        ({"official_verification_status": "unverified"}, "calendar_unverified"),
        ({"official_verified_at": "2026-09-19T00:00:00Z"}, "calendar_not_available"),
        ({"fetched_at": "2026-09-19T00:00:00Z"}, "calendar_not_available"),
        ({"fetched_at": "2026-09-01T00:00:00"}, "timestamp_invalid"),
    ],
)
def test_calendar_evidence_requires_real_available_timestamps(change, error):
    with pytest.raises(ResearchObservationInputError, match=error):
        latest_closed_session([{**calendar(), **change}], now=NOW)


def test_calendar_rejects_missing_year_duplicate_and_horizon():
    with pytest.raises(ResearchObservationInputError, match="current_year_missing"):
        latest_closed_session([], now=NOW)
    with pytest.raises(ResearchObservationInputError, match="ambiguous"):
        latest_closed_session([calendar(), calendar()], now=NOW)
    with pytest.raises(ResearchObservationInputError, match="horizon_missing"):
        observation_outcome_sessions(
            [calendar()], published_at=NOW, horizon_sessions=10, now=NOW
        )
    with pytest.raises(ResearchObservationInputError, match="year_missing"):
        observation_outcome_sessions(
            [calendar(year=2028, trading_days=(date(2028, 1, 3), date(2028, 1, 4)))],
            published_at=NOW,
            horizon_sessions=1,
            now=NOW,
        )
