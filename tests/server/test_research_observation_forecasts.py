from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import SignalEvent
from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.db import AppDatabase
from server.services.research_observation_forecasts import build_observation_forecasts
from strategy.base import Strategy

_START = date(2026, 9, 14)


def _bars(prices: list[int], symbol: str = "600001") -> list[DailyBarObservation]:
    bars = []
    for index, price in enumerate(prices):
        session = _START + timedelta(days=index)
        event = datetime(
            session.year, session.month, session.day, 7, tzinfo=timezone.utc
        )
        bars.append(
            DailyBarObservation(
                instrument=InstrumentKey(symbol, InstrumentType.STOCK),
                session_date=session,
                event_time=event,
                available_at=event + timedelta(minutes=1),
                captured_at=event + timedelta(minutes=2),
                open=Decimal(price),
                high=Decimal(price),
                low=Decimal(price),
                close=Decimal(price),
                volume=Decimal("1000"),
                amount=Decimal(price * 1000),
            )
        )
    return bars


def _source(
    kind: str = "dual_ma", *, entry: int = 1, exit: int = 0, weight: float = 0.5
) -> dict:
    return {
        "instruments": [{"symbol": "600001", "instrument_type": "stock"}],
        "strategy_kind": kind,
        "minimum_bars": 4,
        "parameters": {"short_period": 1, "long_period": 3},
        "formula_binding": {
            "formula_ast": {
                "schema_version": FORMULA_AST_CONTRACT,
                "entry": {"op": "constant", "value": entry},
                "exit": {"op": "constant", "value": exit},
                "position_size": {
                    "op": "max_weight",
                    "input": {"op": "equal_weight"},
                    "value": weight,
                },
            }
        },
    }


def _forecast(source, bars, *, previous: Decimal = Decimal("0"), **changes):
    arguments = {
        "decision_session": max(bar.session_date for bar in bars),
        "previous_targets": {"600001": previous},
    }
    arguments.update(changes)
    return build_observation_forecasts(source, bars, **arguments)


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ([10, 9, 8, 12], "enter"),
        ([10, 11, 12, 8], "exit"),
        ([10, 9, 8, 12, 13], "hold"),
        ([10, 11, 12, 13], "hold"),
    ],
)
def test_dual_ma_publishes_only_a_canonical_cross_on_the_decision_session(
    prices, expected
) -> None:
    bars = _bars(prices)
    result = _forecast(_source(), list(reversed(bars)))

    assert len(result) == 1
    assert result[0]["action"] == expected
    assert result[0]["decision_session"] == bars[-1].session_date.isoformat()
    assert result[0]["reference_close"] == str(prices[-1])
    assert result[0]["data_available_at"] == bars[-1].available_at.isoformat()
    assert result[0]["data_captured_at"] == bars[-1].captured_at.isoformat()


@pytest.mark.parametrize(
    ("entry", "exit", "previous", "expected"),
    [
        (1, 1, Decimal("0.2"), "exit"),
        (1, 1, Decimal("0"), "hold"),
        (1, 0, Decimal("0"), "enter"),
        (1, 0, Decimal("0.2"), "hold"),
        (0, 1, Decimal("0.2"), "exit"),
        (0, 1, Decimal("0"), "hold"),
        (0, 0, Decimal("0.2"), "hold"),
    ],
)
def test_formula_state_uses_previous_approved_target_and_exit_has_priority(
    entry, exit, previous, expected
) -> None:
    result = _forecast(
        _source("formula", entry=entry, exit=exit),
        _bars([10, 9, 8, 12]),
        previous=previous,
    )

    assert result[0]["action"] == expected


def test_formula_provider_sizing_cannot_become_a_portfolio_weight() -> None:
    bars = _bars([10, 9, 8, 12])
    small = _forecast(_source("formula", weight=0.01), bars)
    large = _forecast(_source("formula", weight=1), bars)

    assert small == large
    assert small[0]["action"] == "enter"
    assert "target_weight" not in small[0]
    assert "quantity" not in small[0]


@pytest.mark.parametrize("kind", ["dual_ma", "formula"])
def test_forecasts_do_not_create_account_positions_orders_or_fills(
    kind, monkeypatch
) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("forecast evaluation touched an account, fill or position update")

    monkeypatch.setattr(AppDatabase, "__init__", forbidden)
    monkeypatch.setattr(Strategy, "on_fill", forbidden)
    monkeypatch.setattr(Strategy, "on_position_update", forbidden)
    published = []
    original_publish = EventBus.publish

    def publish(bus, event):
        published.append(event)
        original_publish(bus, event)

    monkeypatch.setattr(EventBus, "publish", publish)
    result = _forecast(_source(kind), _bars([10, 9, 8, 12]))

    assert result[0]["action"] == "enter"
    assert all(isinstance(event, SignalEvent) for event in published)
    assert result[0]["consumer"] == "independent_target_shadow"


@pytest.mark.parametrize("second_type", ["stock", "etf"])
def test_symbol_collisions_are_rejected_even_across_instrument_namespaces(
    second_type,
) -> None:
    source = _source()
    source["instruments"].append({"symbol": "600001", "instrument_type": second_type})

    with pytest.raises(ValueError, match="observation_symbol_namespace_ambiguous"):
        _forecast(source, _bars([10, 9, 8, 12]))


def test_a_bar_cannot_change_the_frozen_instrument_namespace() -> None:
    bars = _bars([10, 9, 8, 12])
    bars[-1] = replace(bars[-1], instrument=InstrumentKey("600001", InstrumentType.ETF))

    with pytest.raises(ValueError, match="observation_forecast_bar_outside_scope"):
        _forecast(_source(), bars)


@pytest.mark.parametrize(
    "previous_targets", [{}, {"600001": Decimal("0"), "600002": Decimal("0")}]
)
def test_previous_target_universe_must_match_exactly(previous_targets) -> None:
    with pytest.raises(
        ValueError, match="observation_previous_target_universe_mismatch"
    ):
        _forecast(_source(), _bars([10, 9, 8, 12]), previous_targets=previous_targets)


def test_duplicate_session_cannot_count_as_history_or_choose_a_revision() -> None:
    bars = _bars([10, 9, 8, 12])
    with pytest.raises(ValueError, match="observation_forecast_history_incomplete"):
        _forecast(_source(), [*bars, bars[-1]])


@pytest.mark.parametrize(
    "problem", ["warmup", "decision_session_missing", "future_bar", "foreign_symbol"]
)
def test_insufficient_or_out_of_scope_history_is_rejected(problem) -> None:
    bars = _bars([10, 9, 8, 12])
    decision = bars[-1].session_date
    error = "observation_forecast_history_incomplete"
    if problem == "warmup":
        bars = bars[1:]
    elif problem == "decision_session_missing":
        decision += timedelta(days=1)
    elif problem == "future_bar":
        decision -= timedelta(days=1)
        error = "observation_forecast_bar_outside_scope"
    else:
        bars += _bars([10], symbol="600002")
        error = "observation_forecast_bar_outside_scope"

    with pytest.raises(ValueError, match=error):
        _forecast(_source(), bars, decision_session=decision)


def test_each_symbol_gets_its_own_history_and_previous_target() -> None:
    source = _source("formula")
    source["instruments"].append({"symbol": "600002", "instrument_type": "stock"})
    result = _forecast(
        source,
        [*_bars([10, 9, 8, 12]), *_bars([5, 6, 7, 8], "600002")],
        previous_targets={"600001": Decimal("0.2"), "600002": Decimal("0")},
    )

    assert [(row["symbol"], row["action"]) for row in result] == [
        ("600001", "hold"),
        ("600002", "enter"),
    ]
