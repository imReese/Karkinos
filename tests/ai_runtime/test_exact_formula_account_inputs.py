"""Exact recommendation Dataset lineage and cold recheck, without database IO."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from server.ai_runtime.contracts import content_fingerprint
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
)
from server.services.strategy_scan.universe import formula_inputs as module


def fixture(monkeypatch, tmp_path):
    start, end = date(2026, 1, 5), date(2026, 1, 6)
    now = datetime(2026, 1, 7, 1, 40, tzinfo=timezone.utc)
    keys = (
        InstrumentKey("600000", InstrumentType.STOCK),
        InstrumentKey("600001", InstrumentType.STOCK),
    )
    scope = market_deployment_scope(MarketUniversePolicy(minimum_history_rows=2))
    ratio = {"op": "rolling_max_close_ratio", "window": 1}
    ast = {"entry": {"op": "equal", "left": ratio, "right": ratio}}
    anchor = {
        "dataset_id": "anchor",
        "formula_fingerprint": "sha256:" + content_fingerprint(ast),
        "deployment_scope": scope,
        "final_evidence_fingerprint": "sealed-final",
        "final_evaluation_id": "one-final",
    }
    item = {
        "strategy_id": "bk",
        "strategy": {
            "formula_ast": ast,
            "selected_universe": [key.symbol for key in keys],
        },
        "history_start": start.isoformat(),
        "formula_dataset_anchor": anchor,
    }
    membership = lambda day: SimpleNamespace(
        partition_date=day, source_observation_ids=("master",), instruments=keys
    )
    shared = dict(
        start_date=start,
        instruments=keys,
        universe_policy_id=scope["deployment_scope_fingerprint"],
        verification_bound=True,
        resolver_policy_id="resolver",
        market_schema_version="bars",
    )
    original = SimpleNamespace(
        ref=SimpleNamespace(dataset_id="anchor"),
        snapshot=SimpleNamespace(
            **shared,
            end_date=start,
            partitions=(1,),
            session_memberships=(membership(start),),
        ),
    )
    snapshot = SimpleNamespace(
        **shared,
        end_date=end,
        partitions=(1, 2),
        session_memberships=(*original.snapshot.session_memberships, membership(end)),
    )
    bars = tuple(
        SimpleNamespace(
            instrument=key,
            event_time=now,
            available_at=now,
            captured_at=now,
            **{
                name: Decimal("1.10000000")
                for name in ("open", "high", "low", "close", "volume", "amount")
            },
        )
        for key in keys
    )
    result = SimpleNamespace(
        ref=SimpleNamespace(dataset_id="current"), snapshot=snapshot, bars=bars
    )
    calls = []
    objects = SimpleNamespace(
        resolve_ref=lambda value: value,
        read_bytes_by_id=lambda value: (
            b'{"schema_version":"karkinos.market_universe_snapshot.v3"}'
        ),
    )
    monkeypatch.setattr(module, "ContentAddressedObjectStore", lambda _: objects)
    monkeypatch.setattr(module, "DatasetRef", lambda value: value)
    monkeypatch.setattr(module, "read_daily_bar_dataset", lambda actual, ref: original)
    entries = [
        SimpleNamespace(
            start_date=start, end_date=end, ref=SimpleNamespace(dataset_id="current")
        )
    ]

    class Catalog:
        def list_daily_bar_datasets(self, **kwargs):
            calls.append(("discover", kwargs))
            return entries

    monkeypatch.setattr(module, "DatasetCatalog", lambda _: Catalog())
    monkeypatch.setattr(module, "read_daily_bar_dataset_manifest", lambda *_: snapshot)

    def read(_objects, identity, **kwargs):
        calls.append(("read", identity, kwargs))
        assert kwargs["now"] == now
        assert kwargs["deployment_scope"] == scope
        assert kwargs["membership_after"] == end
        assert kwargs["minimum_bars"] == 2
        return result

    monkeypatch.setattr(module, "read_research_observation_dataset", read)
    monkeypatch.setattr(module, "market_master_buy_instruments", lambda *_: keys)

    def context(_objects, actual, **kwargs):
        assert actual is snapshot and kwargs == {"as_of": now}
        return {start: keys, end: keys}

    monkeypatch.setattr(module, "dataset_cross_section_memberships", context)
    db = SimpleNamespace(
        path=tmp_path / "unused.sqlite",
        get_market_calendar_snapshot_sync=lambda **_: {"fixture": True},
    )
    return db, item, now, end.isoformat(), calls, entries, result, snapshot, original


def test_exact_scan_preserves_original_decimal_and_reopens_same_ref(
    monkeypatch, tmp_path
):
    db, item, now, day, calls, *_ = fixture(monkeypatch, tmp_path)
    frames, contexts, bindings, blockers = module.load_exact_formula_market_inputs(
        db, [item], market_date=day, decision_at=now
    )
    assert blockers == []
    assert type(frames["bk"]["600000"]["close"].iloc[0]) is Decimal
    assert contexts["bk"].declared_symbols == ("600000", "600001")
    assert contexts["bk"].as_of == now and not contexts["bk"].historical_snapshot
    assert len([call for call in calls if call[0] == "discover"]) == 1
    result = module.load_exact_formula_market_inputs(
        db,
        [item],
        market_date=day,
        decision_at=now.replace(minute=41),
        saved_bindings=bindings,
    )
    assert result[2] == bindings and result[3] == []
    assert len([call for call in calls if call[0] == "discover"]) == 1
    assert [call[1] for call in calls if call[0] == "read"] == ["current", "current"]
    assert not db.path.exists()


@pytest.mark.parametrize(
    "change", ["prefix", "pool", "scope", "formula", "future_cutoff", "missing_saved"]
)
def test_exact_scan_rejects_changed_input_binding(monkeypatch, tmp_path, change):
    db, item, now, day, _calls, _entries, result, snapshot, original = fixture(
        monkeypatch, tmp_path
    )
    saved = None
    if change == "prefix":
        snapshot.partitions = (9, 2)
    elif change == "pool":
        snapshot.session_memberships[-1].instruments = snapshot.instruments[:1]
    elif change == "scope":
        original.snapshot.universe_policy_id = "other"
    elif change == "formula":
        item["formula_dataset_anchor"]["formula_fingerprint"] = "other"
    elif change == "future_cutoff":
        saved = {
            "bk": {
                "anchor": item["formula_dataset_anchor"],
                "market_date": day,
                "as_of": now.replace(hour=2).isoformat(),
                "dataset_id": "current",
            }
        }
    else:
        saved = {}
    frames, contexts, bindings, blockers = module.load_exact_formula_market_inputs(
        db, [item], market_date=day, decision_at=now, saved_bindings=saved
    )
    assert frames == contexts == bindings == {}
    assert blockers and not db.path.exists()


def test_first_matching_corrupt_dataset_never_falls_back(monkeypatch, tmp_path):
    db, item, now, day, calls, entries, *_ = fixture(monkeypatch, tmp_path)
    entries.append(
        SimpleNamespace(
            **{**vars(entries[0]), "ref": SimpleNamespace(dataset_id="older")}
        )
    )

    def unreadable(*_args, **_kwargs):
        raise ValueError("corrupt_fixture")

    monkeypatch.setattr(module, "read_research_observation_dataset", unreadable)
    result = module.load_exact_formula_market_inputs(
        db, [item], market_date=day, decision_at=now
    )
    assert result[0] == {} and "corrupt_fixture" in result[3][0]
    assert len([call for call in calls if call[0] == "discover"]) == 1


def test_real_scan_adapter_passes_per_strategy_frames_and_binds_selected_dataset(
    monkeypatch,
):
    from server.services.strategy_scan.universe import service as scan_module

    now = datetime(2026, 1, 7, 1, 40, tzinfo=timezone.utc)
    exact_frames, contexts, bindings = (
        {"bk": {"600000": object()}},
        {"bk": object()},
        {"bk": {"dataset_id": "frozen"}},
    )
    seen = []

    def load(db, promoted, **kwargs):
        seen.append(kwargs)
        return exact_frames, contexts, bindings, []

    def evaluate(**kwargs):
        assert kwargs["formula_frames"] is exact_frames
        assert kwargs["cross_sections"] is contexts
        assert kwargs["decision_at"] == now
        return {}, [], []

    monkeypatch.setattr(scan_module, "load_exact_formula_market_inputs", load)
    monkeypatch.setattr(scan_module, "evaluate_promoted_strategy_market", evaluate)
    scanner = object.__new__(scan_module.PromotedStrategyUniverseScanService)
    scanner._db, scanner._policy = object(), object()
    market = {
        "history_start": "2026-01-05",
        "snapshot": {},
        "frames": {},
        "receipts": [],
        "trading_dates": [],
        "held_symbols": [],
    }
    assert scanner._evaluate_promoted_strategies(
        promoted=[],
        market_date="2026-01-06",
        market=market,
        total_equity=100,
        decision_at=now,
    ) == ({}, [], [])
    assert market["formula_dataset_bindings"] is bindings
    assert seen == [{"market_date": "2026-01-06", "decision_at": now}]


def test_current_input_guard_reopens_saved_ref_with_original_clock(monkeypatch):
    from server.services.strategy_scan.universe import validation

    now = datetime(2026, 1, 7, 1, 41, tzinfo=timezone.utc)
    original = now.replace(minute=40)
    saved = {"dataset_id": "exact-frozen", "as_of": original.isoformat()}
    promoted = [{"strategy_id": "bk"}]
    for name, value in {
        "prior_verified_trading_date": "2026-01-06",
        "promoted_history_start": "2026-01-05",
        "automation_safety_blockers": [],
        "promoted_scan_evaluation_policy_fingerprint": "policy",
        "resolve_daily_bar_receipts": [],
        "verified_trading_dates": ["2026-01-05", "2026-01-06"],
        "require_complete_market_universe_snapshot": {"members": []},
        "portfolio_scan_binding": {},
    }.items():
        monkeypatch.setattr(validation, name, lambda *_a, _value=value, **_k: _value)
    seen = []

    def load(_db, actual_promoted, **kwargs):
        assert actual_promoted is promoted
        assert kwargs == {
            "market_date": "2026-01-06",
            "decision_at": now,
            "saved_bindings": {"bk": saved},
        }
        seen.append("reopened")
        return {"bk": {}}, {"bk": SimpleNamespace(as_of=original)}, {"bk": saved}, []

    def evaluate(**kwargs):
        assert kwargs["decision_at"] == original
        assert kwargs["formula_frames"] == {"bk": {}}
        seen.append("evaluated")
        return {}, [], []

    monkeypatch.setattr(validation, "load_exact_formula_market_inputs", load)
    monkeypatch.setattr(validation, "evaluate_promoted_strategy_market", evaluate)
    monkeypatch.setattr(
        validation, "account_eligible_signals", lambda *_a, **_k: ([], [])
    )
    monkeypatch.setattr(
        validation, "aggregate_ranked_signals", lambda *_a, **_k: ([], [])
    )
    scan = {
        "decision_date": "2026-01-07",
        "market_date": "2026-01-06",
        "strategy_bindings": [{"strategy_id": "bk", "formula_dataset_binding": saved}],
        "evaluation_policy_fingerprint": "policy",
        "portfolio_binding": {},
        "safety_gate_fingerprint": "sha256:" + content_fingerprint({}),
        "signal_selection_fingerprint": "sha256:"
        + content_fingerprint(
            {
                "decision_date": "2026-01-07",
                "market_date": "2026-01-06",
                "raw_signals": [],
                "account_blocked_buys": [],
                "signals": [],
            }
        ),
    }
    blockers = validation.current_scan_input_blockers(
        db=object(),
        config=object(),
        data_store=SimpleNamespace(
            get_market_universe_snapshot=lambda **_: {},
            load_market_bar_windows=lambda **_: {},
        ),
        policy=SimpleNamespace(allocation_slots=4),
        scan=scan,
        portfolio_summary={},
        portfolio_reader=lambda _: ({"stock_symbols": [], "total_equity": 100}, []),
        promoted_reader=lambda _: (promoted, []),
        safety_reader=lambda: {},
        current_time=now,
    )
    assert seen == ["reopened", "evaluated"] and blockers == []


@pytest.mark.parametrize(
    "exact,verified", [(True, False), (True, True), (False, False)]
)
def test_real_market_evaluator_never_falls_back_to_sql_for_exact_exit(
    monkeypatch, exact, verified
):
    import pandas as pd

    from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
    from server.services.strategy_scan.universe import evaluation

    ratio = {"op": "rolling_max_close_ratio", "window": 1}
    ast = {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {"op": "equal", "left": ratio, "right": ratio}
        if exact
        else {"op": "constant", "value": 0},
        "exit": {"op": "constant", "value": 1},
        "position_size": {"op": "equal_weight"},
    }
    stamps = pd.date_range("2026-01-05T07:00:00Z", periods=2)
    sql_frames = {
        "600000": pd.DataFrame(
            {
                "timestamp": stamps,
                "close": [1.0, 1.1],
                "volume": [1000, 1000],
                "amount": [1000, 1100],
            }
        )
    }
    exact_frames = {
        "600000": sql_frames["600000"].assign(
            close=[Decimal("1"), Decimal("1.1")],
            available_at=stamps,
            captured_at=stamps,
        )
    }
    seen = []

    def truth(**kwargs):
        seen.append(kwargs["frames"])
        return {
            "status": "complete",
            "eligible_symbols": [],
            "maintenance_symbols": ["600000"],
        }

    monkeypatch.setattr(evaluation, "build_full_market_universe_truth", truth)
    truths, signals, blockers = evaluation.evaluate_promoted_strategy_market(
        promoted=[
            {
                "strategy_id": "fixture",
                "strategy": {"formula_ast": ast, "selected_universe": ["600000"]},
            }
        ],
        market_date="2026-01-06",
        snapshot={},
        frames=sql_frames,
        receipts=[],
        trading_dates=["2026-01-05", "2026-01-06"],
        start_date="2026-01-05",
        total_equity=100,
        held_stock_symbols=["600000"],
        policy=MarketUniversePolicy(minimum_history_rows=2),
        formula_frames={"fixture": exact_frames} if verified else None,
    )
    if exact and not verified:
        assert truths == {} and signals == [] and seen == []
        assert blockers == [
            'strategy_cross_section_inputs:"fixture":exact_dataset_unavailable'
        ]
        # A missing exact source cannot consume SQL even for exits, and cannot
        # suppress another strategy's independently valid maintenance action.
        legacy = {**ast, "entry": {"op": "constant", "value": 0}}
        _, mixed_signals, mixed_blockers = evaluation.evaluate_promoted_strategy_market(
            promoted=[
                {
                    "strategy_id": "fixture",
                    "strategy": {"formula_ast": ast, "selected_universe": ["600000"]},
                },
                {
                    "strategy_id": "legacy",
                    "strategy": {
                        "formula_ast": legacy,
                        "selected_universe": ["600000"],
                    },
                },
            ],
            market_date="2026-01-06",
            snapshot={},
            frames=sql_frames,
            receipts=[],
            trading_dates=["2026-01-05", "2026-01-06"],
            start_date="2026-01-05",
            total_equity=100,
            held_stock_symbols=["600000"],
            policy=MarketUniversePolicy(minimum_history_rows=2),
        )
        assert len(mixed_signals) == 1 and mixed_signals[0]["strategy_id"] == "legacy"
        assert mixed_signals[0]["direction"] == "sell"
        assert evaluation.active_action_blockers(mixed_blockers, mixed_signals) == []
        assert evaluation.active_action_blockers(blockers, []) == blockers
    else:
        assert blockers == [] and signals[0]["direction"] == "sell"
        assert seen == [exact_frames if verified else sql_frames]
