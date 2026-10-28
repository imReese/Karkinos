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
from server.ai_runtime.formula_dsl import evaluate_formula, evaluate_formula_universe
from server.services.backtest.backtest_costs import quote_formula_purchase


def prepare_formula_sessions(
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    universe_size: int,
) -> dict[str, pd.DataFrame]:
    """Compute causal DSL series once; consumers select only their known date."""
    ordered_frames = {
        str(symbol): frame.sort_values("timestamp").reset_index(drop=True)
        for symbol, frame in frames.items()
    }
    entries, exits, _ = evaluate_formula_universe(
        formula_ast,
        ordered_frames,
        universe_size=universe_size,
    )
    prepared = {}
    for symbol, ordered in ordered_frames.items():
        amount = pd.to_numeric(
            ordered["amount"]
            if "amount" in ordered
            else ordered["close"] * ordered["volume"],
            errors="coerce",
        )
        prepared[symbol] = pd.DataFrame(
            {
                "session": pd.to_datetime(ordered["timestamp"]).dt.date,
                "close": ordered["close"],
                "volume": ordered["volume"],
                "history_rows": range(1, len(ordered) + 1),
                "entry": entries[symbol].fillna(False).astype(bool),
                "exit": exits[symbol].fillna(False).astype(bool),
                "liquidity": amount.rolling(20, min_periods=1).median(),
            }
        ).set_index("session", verify_integrity=True)
    return prepared


def formula_session_candidates(
    *,
    prepared: Mapping[str, pd.DataFrame],
    decision_session: date,
    held_symbols: set[str] | Sequence[str] | None = None,
    eligible_symbols: Sequence[str] | None = None,
    minimum_history_rows: int = 120,
    entry_board_policy: Mapping[str, Any] | None = None,
    nontrading_symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Extract verified session observations and entry/exit candidates from prepared sessions."""
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
    held = set(held_symbols) if held_symbols is not None else set()
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
    entries, exits, prices, liquidity = [], [], {}, {}
    forecasts = []
    for symbol in sorted(eligible | held):
        observations = prepared.get(symbol)
        if observations is None:
            raise ValueError(f"formula_session_observation_missing:{symbol}")
        current_observation = decision_session in observations.index
        if current_observation:
            row = observations.loc[decision_session]
            observation_session = decision_session
        else:
            available = observations.loc[observations.index <= decision_session]
            if available.empty:
                raise ValueError(f"formula_session_observation_missing:{symbol}")
            row = available.iloc[-1]
            observation_session = available.index[-1]
        if (
            symbol in held
            and not current_observation
            and nontrading_symbols is not None
            and symbol not in nontrading_symbols
        ):
            raise ValueError(f"formula_session_holding_valuation_missing:{symbol}")
        price = Decimal(str(row["close"]))
        if not price.is_finite() or price <= 0:
            raise ValueError(f"formula_session_instrument_invalid:{symbol}")
        prices[symbol] = price
        liq = Decimal(str(row["liquidity"]))
        if not liq.is_finite():
            raise ValueError(f"formula_session_liquidity_invalid:{symbol}")
        liquidity[symbol] = liq
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
                "observation_session": observation_session.isoformat(),
                "data_available": current_observation,
                **(
                    {"valuation_basis": "last_observed_close_bound_nontrading"}
                    if symbol in held
                    and not current_observation
                    and nontrading_symbols is not None
                    else {}
                ),
            }
        )
    return {
        "decision_session": decision_session,
        "eligible": eligible,
        "permitted_entries": permitted_entries,
        "entries": entries,
        "exits": exits,
        "prices": prices,
        "liquidity": liquidity,
        "forecasts": sorted(forecasts, key=lambda item: item["symbol"]),
    }


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
    nontrading_symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """One session decision shared by backtest, paper and account adapters."""
    held = {str(s): q for s, q in quantities.items() if q > 0}
    candidates = formula_session_candidates(
        prepared=prepared,
        decision_session=decision_session,
        held_symbols=set(held),
        eligible_symbols=eligible_symbols,
        minimum_history_rows=minimum_history_rows,
        entry_board_policy=entry_board_policy,
        nontrading_symbols=nontrading_symbols,
    )
    entries = candidates["entries"]
    exits = candidates["exits"]
    prices = candidates["prices"]
    liquidity = candidates["liquidity"]
    forecasts = candidates["forecasts"]
    permitted_entries = candidates["permitted_entries"]
    values, lots = {}, {}
    for symbol in sorted(candidates["eligible"] | set(held)):
        instrument = instruments.get(Symbol(symbol))
        if instrument is None:
            raise ValueError(f"formula_session_instrument_invalid:{symbol}")
        lots[symbol] = instrument.lot_size
        if symbol in held:
            values[symbol] = held[symbol] * prices[symbol]

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
