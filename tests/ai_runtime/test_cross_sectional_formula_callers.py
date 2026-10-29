"""Full-market forecast inputs remain separate from tradable entry funds."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import Symbol
from data.handler import DataHandler
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.ai_runtime.formula_portfolio import FormulaCrossSectionInputs
from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy
from server.contracts.strategy_research import StrategyResearchRejected
from server.services.strategy_scan.universe.evaluation import (
    active_action_blockers,
    evaluate_strategy_signals,
    formula_history_rows,
)

pytestmark = pytest.mark.unit
DAY = date(2026, 8, 21)
NOW = datetime(2026, 8, 21, 8, tzinfo=timezone.utc)


def formula():
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "gte",
            "left": {
                "op": "cross_sectional_rank",
                "input": {"op": "field", "name": "close"},
            },
            "right": {"op": "constant", "value": 0.9},
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 2},
        },
        "position_size": {"op": "equal_weight"},
    }


def frame(price):
    stamps = pd.date_range("2026-08-20 07:00", periods=2, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1_000_000,
            "amount": price * 1_000_000,
            "available_at": stamps + pd.Timedelta(minutes=5),
            "captured_at": stamps + pd.Timedelta(minutes=5),
        }
    )


def context():
    return FormulaCrossSectionInputs(
        declared_symbols=("600000", "300001"),
        session_memberships={
            DAY - timedelta(days=1): ("600000", "300001"),
            DAY: ("600000", "300001"),
        },
        minimum_history_rows=2,
        as_of=NOW,
    )


def test_scan_ranks_full_pool_before_main_cash_eligible_entries():
    # The non-main leader must remain in the reference pool even though only
    # the main-board name is permitted for entry. No main-board fallback.
    signals = evaluate_strategy_signals(
        strategy_id="rank-fixture",
        formula_ast=formula(),
        universe_size=2,
        target_weight=0.25,
        frames={"600000": frame(10), "300001": frame(20)},
        eligible_symbols=["600000"],
        maintenance_symbols=[],
        held_symbols=set(),
        market_date=DAY.isoformat(),
        cross_section=context(),
    )
    assert signals == []


def test_missing_joint_context_still_emits_independent_held_exit():
    signals = evaluate_strategy_signals(
        strategy_id="rank-fixture",
        formula_ast=formula(),
        universe_size=2,
        target_weight=0.25,
        frames={"600000": frame(1), "300001": frame(20)},
        eligible_symbols=[],
        maintenance_symbols=["600000"],
        held_symbols={"600000"},
        market_date=DAY.isoformat(),
    )
    assert [(row["symbol"], row["direction"]) for row in signals] == [
        ("600000", "sell")
    ]


def test_native_rejects_missing_global_inputs_before_any_replay():
    strategy = _FormulaSignalStrategy(
        formula(), 2, portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID
    )
    engine = SimpleNamespace()
    with pytest.raises(
        StrategyResearchRejected, match="formula_cross_section_inputs_blocked"
    ):
        strategy.bind_portfolio_engine(
            engine,
            {Symbol("600000"): DataHandler(frame(1), Symbol("600000"))},
            minimum_history_rows=2,
        )
    assert not hasattr(engine, "_session_decision")


@pytest.mark.parametrize("joint", [False, True])
def test_legacy_portfolio_none_rejects_only_cross_sectional_formulas(joint):
    ast = formula()
    if not joint:
        ast["entry"] = {"op": "constant", "value": 1}
    strategy = _FormulaSignalStrategy(ast, 2)
    engine = SimpleNamespace()
    if joint:
        with pytest.raises(
            StrategyResearchRejected,
            match="formula_cross_section_portfolio_policy_required",
        ):
            strategy.bind_portfolio_engine(engine, {})
    else:
        strategy.bind_portfolio_engine(engine, {})
    assert not hasattr(engine, "_session_decision")


def test_native_complete_shared_context_binds_without_running_an_engine():
    strategy = _FormulaSignalStrategy(
        formula(), 2, portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID
    )
    engine = SimpleNamespace()
    strategy.bind_portfolio_engine(
        engine,
        {
            Symbol(symbol): DataHandler(frame(price), Symbol(symbol))
            for symbol, price in (("600000", 10), ("300001", 20))
        },
        minimum_history_rows=2,
        cross_section=context(),
    )
    assert callable(engine._session_decision)
    assert not bool(strategy._prepared_sessions["600000"].loc[DAY, "entry"])
    assert bool(strategy._prepared_sessions["300001"].loc[DAY, "entry"])


@pytest.mark.parametrize(
    "direction,strategy_id,blocked",
    [
        ("sell", "rank-fixture:child", False),
        ("buy", "other-fixture", False),
        ("buy", "rank-fixture:child", True),
        ("buy", "rank-fixture", False),
    ],
)
def test_joint_input_blocker_affects_only_that_strategys_buys(
    direction, strategy_id, blocked
):
    reason = 'strategy_cross_section_inputs:"rank-fixture:child":missing-context'
    actual = active_action_blockers(
        [reason],
        [{"strategy_id": strategy_id, "symbol": "600000", "direction": direction}],
    )
    assert actual == ([reason] if blocked else [])


def test_existing_history_owners_only_add_the_new_operator_case():
    from server.services.research.research_observation_inputs import _warmup

    node = {
        "op": "cross_sectional_rank",
        "input": {
            "op": "lag",
            "period": 2,
            "input": {"op": "field", "name": "close"},
        },
    }
    assert _warmup(node) == 3
    assert formula_history_rows({"entry": node, "exit": node}) == 3


def test_outer_rank_history_accumulates_after_the_original_membership_floor():
    from server.services.research.research_observation_inputs import _warmup

    node = {
        "op": "rolling_mean",
        "window": 20,
        "input": {
            "op": "cross_sectional_rank",
            "input": {"op": "field", "name": "close"},
        },
    }
    assert _warmup(node, minimum_history_rows=60) == 79
    assert (
        formula_history_rows(
            {"entry": node, "exit": {"op": "constant", "value": 0}},
            minimum_history_rows=60,
        )
        == 79
    )
    legacy = {
        "op": "ema",
        "window": 20,
        "input": {"op": "field", "name": "close"},
    }
    assert _warmup(legacy) == 1
    assert formula_history_rows({"entry": legacy, "exit": legacy}) == 20


def test_observation_passes_actual_cutoff_and_bar_availability(monkeypatch):
    from data.dataset import reader
    from server.ai_runtime import formula_portfolio
    from server.persistence import research_paper_books
    from server.services.research import research_observations as module

    keys = tuple(SimpleNamespace(symbol=s) for s in ("600000", "300001"))
    snapshot = SimpleNamespace(instruments=keys, instruments_for_session=lambda _: keys)
    book = {"lifecycle": "active", "evaluation_start": "2027-01-01"}
    monkeypatch.setattr(
        research_paper_books,
        "ResearchPaperBooksRepository",
        lambda *_a, **_k: SimpleNamespace(get=lambda _: book),
    )
    monkeypatch.setattr(
        module,
        "observation_deployment_scope",
        lambda _: {"universe_policy": {"minimum_history_rows": 2}},
    )

    def membership(_objects, actual_snapshot, *, as_of):
        assert actual_snapshot is snapshot and as_of == NOW
        return {DAY: keys}

    monkeypatch.setattr(reader, "dataset_cross_section_memberships", membership)

    class PreparedBoundaryReached(Exception):
        pass

    def inspect_prepare(_ast, frames, *, universe_size, cross_section):
        assert universe_size == 2 and cross_section.as_of == NOW
        assert set(cross_section.declared_symbols) == {"600000", "300001"}
        assert frames["600000"]["available_at"].iloc[0] == NOW
        assert frames["600000"]["captured_at"].iloc[0] == NOW
        raise PreparedBoundaryReached

    monkeypatch.setattr(formula_portfolio, "prepare_formula_sessions", inspect_prepare)
    service = object.__new__(module.ResearchObservationService)
    service.db, service.clock, service.objects = (
        SimpleNamespace(path=None),
        lambda: NOW,
        object(),
    )
    bar = SimpleNamespace(
        instrument=keys[0],
        event_time=NOW - timedelta(hours=1),
        available_at=NOW,
        captured_at=NOW,
        amount=Decimal(10),
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        volume=Decimal(10),
    )
    with pytest.raises(PreparedBoundaryReached):
        service._portfolio_publication(
            {
                "id": "fixture",
                "source": {
                    "formula_binding": {"formula_ast": formula()},
                    "instruments": [1, 2],
                },
            },
            [bar],
            "unused-fixture",
            DAY,
            DAY,
            DAY,
            snapshot=snapshot,
            as_of=NOW,
        )


def test_scan_service_passes_verified_receipts_and_actual_decision_clock(monkeypatch):
    from server.services.strategy_scan.universe import service as module

    receipts = [{"trade_date": DAY.isoformat(), "receipt_fingerprint": "fixture"}]
    frames = {"600000": frame(10)}
    seen = {}

    def load_windows(**kwargs):
        seen.update(kwargs)
        return frames

    service = object.__new__(module.PromotedStrategyUniverseScanService)
    service._db, service._config, service._policy = object(), object(), object()
    service._data_store = SimpleNamespace(
        get_market_universe_snapshot=lambda **_: {"members": [{"symbol": "600000"}]},
        load_market_bar_windows=load_windows,
    )
    monkeypatch.setattr(module, "promoted_history_start", lambda *_: "2026-08-20")
    monkeypatch.setattr(
        module, "verified_trading_dates", lambda *_a, **_k: [DAY.isoformat()]
    )
    monkeypatch.setattr(module, "resolve_daily_bar_receipts", lambda **_: receipts)
    market, blockers = service._load_market_evidence(
        market_date=DAY.isoformat(), promoted=[{}], portfolio_stock_symbols=[]
    )
    assert blockers == [] and seen["receipts"] is receipts

    def inspect_evaluation(**kwargs):
        assert kwargs["decision_at"] == NOW
        assert kwargs["frames"] is frames
        assert kwargs["receipts"] is receipts
        return {}, [], []

    monkeypatch.setattr(module, "evaluate_promoted_strategy_market", inspect_evaluation)
    assert service._evaluate_promoted_strategies(
        promoted=[{}],
        market_date=DAY.isoformat(),
        market=market,
        total_equity=100_000,
        decision_at=NOW,
    ) == ({}, [], [])
