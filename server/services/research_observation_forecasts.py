"""Run frozen research rules over known history without creating orders or fills."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import Symbol
from data.market.model import DailyBarObservation
from server.ai_runtime.formula_dsl import evaluate_formula
from strategy.builtins.dual_ma import DualMAStrategy

FORECAST_POLICY_ID = "karkinos.research.forward_directional_forecast.v1"


def build_observation_forecasts(
    source: Mapping[str, Any],
    bars: Sequence[DailyBarObservation],
    *,
    decision_session: date,
    previous_targets: Mapping[str, Decimal],
) -> list[dict[str, Any]]:
    """Publish only the latest rule decision; warmup never becomes a forecast.

    Formula entry/exit state refers to the previous approved shadow target. It
    never masquerades as an actual position or sends a position update to a
    strategy. Portfolio policy, separately, owns the resulting target weights.
    """
    symbols = [item["symbol"] for item in source["instruments"]]
    if set(previous_targets) != set(symbols):
        raise ValueError("observation_previous_target_universe_mismatch")
    if len(set(symbols)) != len(symbols):
        raise ValueError("observation_symbol_namespace_ambiguous")
    instrument_types = {
        item["symbol"]: item["instrument_type"] for item in source["instruments"]
    }
    by_symbol: dict[str, list[DailyBarObservation]] = {symbol: [] for symbol in symbols}
    for bar in bars:
        if (
            bar.instrument.symbol not in by_symbol
            or bar.session_date > decision_session
            or bar.instrument.instrument_type.value
            != instrument_types[bar.instrument.symbol]
        ):
            raise ValueError("observation_forecast_bar_outside_scope")
        by_symbol[bar.instrument.symbol].append(bar)
    forecasts = []
    for symbol in symbols:
        history = sorted(by_symbol[symbol], key=lambda bar: bar.session_date)
        if (
            len(history) < source["minimum_bars"]
            or history[-1].session_date != decision_session
            or len({bar.session_date for bar in history}) != len(history)
        ):
            raise ValueError("observation_forecast_history_incomplete")
        if source["strategy_kind"] == "dual_ma":
            action = _dual_ma_action(source["parameters"], history)
        elif source["strategy_kind"] == "formula":
            action = _formula_action(
                source["formula_binding"]["formula_ast"],
                history,
                universe_size=len(symbols),
                active=previous_targets[symbol] > 0,
            )
        else:
            raise ValueError("observation_strategy_unsupported")
        forecasts.append(
            {
                "symbol": symbol,
                "instrument_type": history[-1].instrument.instrument_type.value,
                "action": action,
                "decision_session": decision_session.isoformat(),
                "data_available_at": max(
                    bar.available_at for bar in history
                ).isoformat(),
                "data_captured_at": max(bar.captured_at for bar in history).isoformat(),
                "reference_close": str(history[-1].close),
                "policy_id": FORECAST_POLICY_ID,
                "consumer": "independent_target_shadow",
            }
        )
    return forecasts


def _dual_ma_action(
    parameters: Mapping[str, Any], history: list[DailyBarObservation]
) -> str:
    bus = EventBus()
    emitted: list[SignalEvent] = []
    bus.subscribe(SignalEvent, emitted.append)
    strategy = DualMAStrategy(bus, **parameters)
    strategy.on_init([Symbol(history[0].instrument.symbol)])
    for bar in history:
        emitted.clear()
        strategy.on_data(
            MarketEvent(
                timestamp=bar.event_time,
                symbol=Symbol(bar.instrument.symbol),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                instrument_type=bar.instrument.instrument_type,
                available_at=bar.available_at,
            )
        )
        bus.drain()
    if not emitted:
        return "hold"
    return "enter" if emitted[-1].target_weight > 0 else "exit"


def _formula_action(
    formula_ast: Mapping[str, Any],
    history: list[DailyBarObservation],
    *,
    universe_size: int,
    active: bool,
) -> str:
    frame = pd.DataFrame(
        [
            {
                "timestamp": bar.event_time,
                **{
                    name: float(getattr(bar, name))
                    for name in ("open", "high", "low", "close", "volume")
                },
            }
            for bar in history
        ]
    )
    entry, exit_signal, _provider_sizing_ignored = evaluate_formula(
        formula_ast, frame, universe_size=universe_size
    )
    if active and bool(exit_signal.iloc[-1]):
        return "exit"
    if not active and bool(entry.iloc[-1]) and not bool(exit_signal.iloc[-1]):
        return "enter"
    return "hold"
