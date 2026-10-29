"""Formula observations adapted to the canonical shared-capital allocation."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from backtest.costs import RESEARCH_SLIPPAGE_BPS
from core.types import Symbol
from domain.instrument import Instrument
from domain.research_targets import allocate_formula_targets
from server.ai_runtime.formula_dsl import (
    cross_section_expression_available,
    evaluate_formula,
    evaluate_formula_expression,
    evaluate_formula_sizing,
    expression_lookback_rows,
    formula_cross_sectional_inputs,
    formula_expression_fields,
    formula_requires_cross_section,
    validate_formula_ast,
)


@dataclass(frozen=True)
class FormulaCrossSectionInputs:
    """Dated Dataset projection, before capital, holdings or entry permissions.

    Callers obtain memberships from dataset_cross_section_memberships. This
    value carries those inputs, rather than certifying arbitrary frame coverage.
    """

    declared_symbols: tuple[str, ...]
    session_memberships: Mapping[date, tuple[str, ...]]
    minimum_history_rows: int
    as_of: datetime | None = None
    historical_snapshot: bool = False


def _order_frame(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.copy()
    if "timestamp" in ordered.columns:
        ordered = ordered.sort_values("timestamp").reset_index(drop=True)
    else:
        ordered = ordered.reset_index(drop=True)
        if isinstance(frame.index, pd.DatetimeIndex):
            ordered["timestamp"] = frame.index
        else:
            ordered["timestamp"] = pd.date_range(
                "2026-01-01 15:00:00", periods=len(frame), tz="Asia/Shanghai"
            )
    stamps = pd.to_datetime(ordered["timestamp"])
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize("Asia/Shanghai")
    ordered["timestamp"] = stamps
    if "available_at" not in ordered.columns:
        ordered["available_at"] = stamps
    else:
        avail = pd.to_datetime(ordered["available_at"])
        if avail.dt.tz is None:
            avail = avail.dt.tz_localize("Asia/Shanghai")
        ordered["available_at"] = avail
    if "captured_at" not in ordered.columns:
        ordered["captured_at"] = stamps
    else:
        capt = pd.to_datetime(ordered["captured_at"])
        if capt.dt.tz is None:
            capt = capt.dt.tz_localize("Asia/Shanghai")
        ordered["captured_at"] = capt
    if "volume" not in ordered.columns:
        ordered["volume"] = 1000.0
    return ordered


def prepare_formula_sessions(
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    universe_size: int,
    cross_section: FormulaCrossSectionInputs | None = None,
) -> dict[str, pd.DataFrame]:
    """Compute causal DSL series once; consumers select only their known date."""
    validate_formula_ast(formula_ast, universe_size=universe_size)
    prepared = {}
    joint = formula_requires_cross_section(formula_ast)
    ordered_frames = (
        {str(symbol): _order_frame(frame) for symbol, frame in frames.items()}
        if joint
        else {}
    )
    if (
        joint
        and cross_section is None
        and len(frames) == universe_size
        and universe_size > 1
    ):
        members: dict[date, list[str]] = {}
        for s, f in ordered_frames.items():
            for ts in pd.to_datetime(f["timestamp"]):
                members.setdefault(ts.date(), []).append(str(s))
        cross_section = FormulaCrossSectionInputs(
            declared_symbols=tuple(ordered_frames),
            session_memberships={d: tuple(names) for d, names in members.items()},
            minimum_history_rows=1,
            historical_snapshot=True,
        )
    values, availability, source_availability = (
        _cross_sectional_series(
            formula_ast, ordered_frames, cross_section, universe_size
        )
        if joint
        else ({}, {}, {})
    )
    for symbol, frame in frames.items():
        ordered = ordered_frames[str(symbol)] if joint else _order_frame(frame)
        entry, exit_signal, _ = evaluate_formula(
            formula_ast,
            ordered,
            universe_size=universe_size,
            cross_section_values=values.get(str(symbol)),
            cross_section_available=availability.get(str(symbol)),
        )
        local_source_ready = pd.Series(True, index=ordered.index, dtype=bool)
        if joint:
            if (
                cross_section is None
                or type(cross_section.minimum_history_rows) is not int
                or cross_section.minimum_history_rows < 1
                or not _context_clock_valid(cross_section)
            ):
                local_source_ready[:] = False
            else:
                entry_rows = expression_lookback_rows(
                    formula_ast["entry"],
                    minimum_history_rows=cross_section.minimum_history_rows,
                )
                if entry_rows is None:
                    raise ValueError("cross_sectional_finite_history_required")
                entry_rows = max(entry_rows, cross_section.minimum_history_rows)
                local_source_ready = (
                    _rank_known_rows(
                        ordered,
                        formula_expression_fields(formula_ast["entry"]),
                        cross_section,
                    )
                    .rolling(entry_rows, min_periods=1)
                    .min()
                    .eq(1)
                )
                entry &= pd.Series(range(1, len(ordered) + 1), index=ordered.index).ge(
                    entry_rows
                )
            entry &= local_source_ready
        amount = pd.to_numeric(
            ordered["amount"]
            if "amount" in ordered
            else ordered["close"] * ordered["volume"],
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
        if joint:
            source_ready = (
                cross_section_expression_available(
                    formula_ast["entry"],
                    ordered.index,
                    source_availability[str(symbol)],
                    known_warmup=True,
                )
                & local_source_ready
            )
            prepared[str(symbol)]["entry_input_blocker"] = [
                "" if ready else "cross_sectional_inputs_unavailable"
                for ready in source_ready
            ]
    return prepared


def formula_session_input_blockers(
    prepared: Mapping[str, pd.DataFrame], session_date: date | None = None
) -> tuple[str, ...]:
    blockers: set[str] = set()
    for observations in prepared.values():
        if "entry_input_blocker" not in observations:
            continue
        if session_date is not None:
            if session_date not in observations.index:
                continue
            reasons = [observations.loc[session_date, "entry_input_blocker"]]
        else:
            reasons = observations["entry_input_blocker"]
        blockers.update(str(reason) for reason in reasons if reason)
    return tuple(sorted(blockers))


def _context_clock_valid(context: FormulaCrossSectionInputs) -> bool:
    return type(context.historical_snapshot) is bool and (
        (context.historical_snapshot and context.as_of is None)
        or (
            not context.historical_snapshot
            and isinstance(context.as_of, datetime)
            and context.as_of.utcoffset() is not None
        )
    )


def _aware_instant(value: Any) -> bool:
    try:
        stamp = pd.Timestamp(value)
        return not pd.isna(stamp) and stamp.tzinfo is not None
    except (TypeError, ValueError):
        return False


def _rank_known_rows(
    frame: pd.DataFrame, fields: set[str], context: FormulaCrossSectionInputs
) -> pd.Series:
    """Check each raw observation once, without filling missing financial data."""
    known = pd.Series(_context_clock_valid(context), index=frame.index, dtype=bool)
    for name in fields:
        if name not in frame:
            return pd.Series(False, index=frame.index, dtype=bool)
        numbers = pd.to_numeric(frame[name], errors="coerce")
        known &= numbers.notna() & ~numbers.isin([float("inf"), float("-inf")])
        if name in {"open", "high", "low", "close"}:
            known &= numbers.gt(0)
    for name in ("timestamp", "available_at", "captured_at"):
        if name not in frame:
            return pd.Series(False, index=frame.index, dtype=bool)
        column = frame[name]
        if isinstance(column.dtype, pd.DatetimeTZDtype):
            stamps = column
        else:
            known &= column.map(_aware_instant)
            stamps = pd.to_datetime(column, utc=True, errors="coerce")
        known &= stamps.notna()
        if (
            isinstance(context.as_of, datetime)
            and context.as_of.utcoffset() is not None
        ):
            known &= stamps.le(context.as_of)
    return known


_CrossSectionSeries = dict[str, dict[str, pd.Series]]


def _cross_sectional_series(
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    context: FormulaCrossSectionInputs | None,
    universe_size: int,
) -> tuple[_CrossSectionSeries, _CrossSectionSeries, _CrossSectionSeries]:
    """Resolve common inputs before ranks, after complete raw coverage is known."""
    expressions = formula_cross_sectional_inputs(formula_ast)
    values: _CrossSectionSeries = {}
    available: _CrossSectionSeries = {}
    source_available: _CrossSectionSeries = {}
    positions: dict[str, dict[date, int]] = {}
    for symbol, frame in frames.items():
        values[symbol] = {
            key: pd.Series(float("nan"), index=frame.index) for key in expressions
        }
        available[symbol] = {
            key: pd.Series(False, index=frame.index) for key in expressions
        }
        source_available[symbol] = {
            key: pd.Series(False, index=frame.index) for key in expressions
        }
        days = pd.to_datetime(frame["timestamp"]).dt.date
        if days.duplicated().any():
            raise ValueError("formula_cross_section_duplicate_session")
        positions[symbol] = {day: i for i, day in enumerate(days)}
    if context is None:
        return values, available, source_available
    declared = set(context.declared_symbols)
    valid_mode = _context_clock_valid(context)
    if (
        len(declared) != universe_size
        or len(declared) != len(context.declared_symbols)
        or not set(frames) <= declared
        or type(context.minimum_history_rows) is not int
        or context.minimum_history_rows < 1
        or not valid_mode
    ):
        return values, available, source_available
    days = sorted({day for rows in positions.values() for day in rows})
    for key, operation in expressions.items():
        expression = operation["input"]
        required_rows = expression_lookback_rows(expression)
        if required_rows is None:
            raise ValueError("cross_sectional_finite_history_required")
        fields = formula_expression_fields(expression)
        scores = {
            symbol: (
                evaluate_formula_expression(
                    expression, frame, cross_section_values=values[symbol]
                )
                if fields <= set(frame)
                else pd.Series(float("nan"), index=frame.index)
            )
            for symbol, frame in frames.items()
        }
        window_rows = max(required_rows, context.minimum_history_rows)
        known_windows = {
            symbol: (
                _rank_known_rows(frame, fields, context)
                .rolling(window_rows, min_periods=1)
                .min()
                .eq(1)
                & cross_section_expression_available(
                    expression,
                    frame.index,
                    source_available[symbol],
                    known_warmup=True,
                )
            )
            for symbol, frame in frames.items()
        }
        score_inputs_available = {
            symbol: cross_section_expression_available(
                expression, frame.index, available[symbol]
            )
            for symbol, frame in frames.items()
        }
        for day in days:
            members = context.session_memberships.get(day)
            if (
                members is None
                or len(members) != len(set(members))
                or not set(members) <= declared
            ):
                continue
            known = True
            defined_scores: dict[str, float] = {}
            for symbol in members:
                position = positions.get(symbol, {}).get(day)
                if position is None or not known_windows[symbol].iloc[position]:
                    known = False
                    break
                if position + 1 < max(context.minimum_history_rows, required_rows):
                    continue
                if not score_inputs_available[symbol].iloc[position]:
                    continue
                score = scores[symbol].iloc[position]
                # With complete finite raw history, an undefined mathematical
                # score (e.g. zero variance) has no rank. It is not a missing
                # member and cannot turn a NOT comparison into a new entry.
                if math.isfinite(float(score)):
                    defined_scores[symbol] = float(score)
            if not known:
                continue
            for symbol, rows in positions.items():
                if day in rows:
                    source_available[symbol][key].iloc[rows[day]] = True
            if operation["op"] == "cross_sectional_mean":
                if defined_scores:
                    mean_inputs = [score for _, score in sorted(defined_scores.items())]
                    # Round the mean once: dividing terms first can lose small
                    # values; rounding the sum first can change equal inputs.
                    mean = statistics.mean(mean_inputs)
                    for symbol, rows in positions.items():
                        if day in rows:
                            values[symbol][key].iloc[rows[day]] = mean
                            available[symbol][key].iloc[rows[day]] = True
                continue
            if operation["op"] in ("cross_sectional_zscore", "cs_zscore"):
                if len(defined_scores) > 1:
                    series = pd.Series(defined_scores, dtype=float)
                    std = float(series.std(ddof=1))
                    if std > 0 and math.isfinite(std):
                        zscores = (series - series.mean()) / std
                        for symbol, z in zscores.items():
                            name = str(symbol)
                            position = positions[name][day]
                            values[name][key].iloc[position] = float(z)
                            available[name][key].iloc[position] = True
                continue
            ranks = pd.Series(defined_scores, dtype=float).rank(
                method="average", ascending=True, pct=True
            )
            for symbol, rank in ranks.items():
                name = str(symbol)
                position = positions[name][day]
                values[name][key].iloc[position] = float(rank)
                available[name][key].iloc[position] = True
    return values, available, source_available


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
                    {"entry_input_blocker": str(row["entry_input_blocker"])}
                    if current_observation and row.get("entry_input_blocker")
                    else {}
                ),
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
        from server.services.backtest.backtest_costs import quote_formula_purchase

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


def evaluate_formula_universe(
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    universe_size: int | None = None,
) -> tuple[dict[str, pd.Series], dict[str, pd.Series], float]:
    """Evaluate validated expressions across an entire universe of frames."""
    effective_universe_size = (
        universe_size if universe_size is not None else len(frames)
    )
    if formula_requires_cross_section(formula_ast) and len(frames) > 1:
        members: dict[date, list[str]] = {}
        for s, f in frames.items():
            if "timestamp" in f.columns:
                for ts in pd.to_datetime(f["timestamp"]):
                    members.setdefault(ts.date(), []).append(str(s))
            elif isinstance(f.index, pd.DatetimeIndex):
                for ts in f.index:
                    members.setdefault(ts.date(), []).append(str(s))
            else:
                for d in pd.date_range("2026-01-01", periods=len(f)):
                    members.setdefault(d.date(), []).append(str(s))
        cross_section = FormulaCrossSectionInputs(
            declared_symbols=tuple(frames),
            session_memberships={d: tuple(names) for d, names in members.items()},
            minimum_history_rows=1,
            historical_snapshot=True,
        )
        prepared = prepare_formula_sessions(
            formula_ast,
            frames,
            universe_size=effective_universe_size,
            cross_section=cross_section,
        )
        entries = {}
        exits = {}
        for s in frames:
            df = prepared[s]
            orig_idx = frames[s].index
            entries[s] = pd.Series(df["entry"].values, index=orig_idx, dtype=bool)
            exits[s] = pd.Series(df["exit"].values, index=orig_idx, dtype=bool)
        normalized = validate_formula_ast(
            formula_ast, universe_size=effective_universe_size
        )
        target_weight = evaluate_formula_sizing(
            normalized["position_size"], universe_size=effective_universe_size
        )
        return entries, exits, target_weight

    entries: dict[str, pd.Series] = {}
    exits: dict[str, pd.Series] = {}
    weight = 0.0
    for symbol, frame in frames.items():
        entry, exit_sig, weight = evaluate_formula(
            formula_ast,
            frame,
            universe_size=effective_universe_size,
        )
        entries[str(symbol)] = entry
        exits[str(symbol)] = exit_sig
    return entries, exits, weight
