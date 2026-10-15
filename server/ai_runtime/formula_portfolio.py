"""Formula observations adapted to the canonical shared-capital allocation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from backtest.costs import RESEARCH_SLIPPAGE_BPS
from core.types import Symbol
from domain.instrument import Instrument
from domain.research_targets import allocate_formula_targets
from server.ai_runtime.formula_dsl import evaluate_formula
from server.services.backtest_costs import quote_formula_purchase


def prepare_formula_sessions(
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    universe_size: int,
) -> dict[str, pd.DataFrame]:
    """Compute causal DSL series once; consumers select only their known date."""
    prepared = {}
    for symbol, frame in frames.items():
        ordered = frame.sort_values("timestamp").reset_index(drop=True)
        entry, exit_signal, _ = evaluate_formula(
            formula_ast, ordered, universe_size=universe_size
        )
        amount = pd.to_numeric(
            ordered.get("amount", ordered["close"] * ordered["volume"]),
            errors="coerce",
        )
        prepared[str(symbol)] = pd.DataFrame(
            {
                "session": pd.to_datetime(ordered["timestamp"]).dt.date,
                "close": ordered["close"],
                "volume": ordered["volume"],
                "history_rows": range(1, len(ordered) + 1),
                "entry": entry.fillna(False).astype(bool),
                "exit": exit_signal.fillna(False).astype(bool),
                "liquidity": amount.rolling(20, min_periods=1).median(),
            }
        ).set_index("session", verify_integrity=True)
    return prepared


def formula_session_targets(
    *,
    prepared: Mapping[str, pd.DataFrame],
    decision_session: date,
    quantities: Mapping[str, Decimal],
    cash: Decimal,
    equity: Decimal,
    instruments: Mapping[Symbol, Instrument],
    commission_calc: Any = None,
    eligible_symbols: Sequence[str] | None = None,
    max_positions: int = 4,
    max_symbol_weight: Decimal = Decimal("0.25"),
    max_gross_weight: Decimal = Decimal("0.97"),
    cash_buffer_ratio: Decimal = Decimal("0.03"),
    slippage_bps: Decimal = RESEARCH_SLIPPAGE_BPS,
    minimum_history_rows: int = 120,
    entry_board_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One session decision shared by backtest, paper and account adapters."""
    if type(minimum_history_rows) is not int or minimum_history_rows < 1:
        raise ValueError("formula_session_minimum_history_invalid")
    eligible = {
        symbol
        for symbol in (eligible_symbols if eligible_symbols is not None else prepared)
        if symbol in prepared
        and decision_session in prepared[symbol].index
        and int(prepared[symbol].loc[decision_session, "history_rows"])
        >= minimum_history_rows
        and Decimal(str(prepared[symbol].loc[decision_session, "volume"])) > 0
    }
    held = {str(s): q for s, q in quantities.items() if q > 0}
    permitted_entries = eligible
    if entry_board_policy is not None:
        from domain.instrument import entry_board_symbols
        from server.contracts.recommendation_publication import (
            validate_entry_board_policy,
        )

        permitted_entries = entry_board_symbols(
            validate_entry_board_policy(entry_board_policy)["allowed_boards"],
            sorted(eligible),
        )
    entries, exits, prices, liquidity, values, lots = [], [], {}, {}, {}, {}
    forecasts = []
    for symbol in sorted(eligible | set(held)):
        observations = prepared.get(symbol)
        if observations is None:
            raise ValueError(f"formula_session_observation_missing:{symbol}")
        available = observations.loc[observations.index <= decision_session]
        if available.empty:
            raise ValueError(f"formula_session_observation_missing:{symbol}")
        current_observation = decision_session in observations.index
        row = available.iloc[-1]
        price = Decimal(str(row["close"]))
        instrument = instruments.get(Symbol(symbol))
        if instrument is None or not price.is_finite() or price <= 0:
            raise ValueError(f"formula_session_instrument_invalid:{symbol}")
        prices[symbol] = price
        lots[symbol] = instrument.lot_size
        liquidity[symbol] = Decimal(str(row["liquidity"]))
        if not liquidity[symbol].is_finite():
            raise ValueError(f"formula_session_liquidity_invalid:{symbol}")
        if symbol in held:
            values[symbol] = held[symbol] * price
        should_exit = current_observation and bool(row["exit"])
        if symbol in held and should_exit:
            exits.append(symbol)
            action = "exit"
        elif (
            symbol not in held
            and symbol in eligible
            and bool(row["entry"])
            and not should_exit
        ):
            if symbol in permitted_entries:
                entries.append(symbol)
            action = "enter"
        else:
            action = "hold"
        forecasts.append(
            {
                "symbol": symbol,
                "action": action,
                "reference_close": str(price),
                "observation_session": available.index[-1].isoformat(),
                "data_available": current_observation,
            }
        )

    def buy_cost(symbol: str, price: Decimal, quantity: Decimal) -> Decimal | None:
        return quote_formula_purchase(
            commission_calc,
            instruments[Symbol(symbol)],
            symbol,
            price,
            quantity,
            slippage_bps=slippage_bps,
        )

    decision = allocate_formula_targets(
        entries=entries,
        exits=exits,
        position_values=values,
        prices=prices,
        liquidity=liquidity,
        lot_sizes=lots,
        cash=cash,
        equity=equity,
        buy_cost=buy_cost,
        max_positions=max_positions,
        max_symbol_weight=max_symbol_weight,
        max_gross_weight=max_gross_weight,
        cash_buffer_ratio=cash_buffer_ratio,
    )
    cast(dict[str, str], decision["rejected_entries"]).update(
        {
            forecast["symbol"]: "frozen_entry_board_policy"
            for forecast in forecasts
            if forecast["action"] == "enter"
            and forecast["symbol"] not in permitted_entries
        }
    )
    return {
        **decision,
        "forecasts": forecasts,
        "decision_session": decision_session.isoformat(),
    }
