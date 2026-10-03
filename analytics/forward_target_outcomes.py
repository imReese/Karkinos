"""Future raw-price responses to frozen targets, never simulated book returns."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

from data.market.model import DailyBarObservation

FORWARD_TARGET_OUTCOME_POLICY_ID = "karkinos.research.forward_target.price_response.v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def evaluate_forward_target_outcome(
    *,
    publication_at: datetime,
    reference_session: date,
    end_session: date,
    target_weights: Mapping[str, Decimal],
    bars: Iterable[DailyBarObservation],
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Measure only the two preselected, fully observed future sessions.

    Calendar selection and Dataset integrity remain the caller's responsibility.
    An absent or ambiguous bar never shifts either endpoint to a later session.
    A zero-weight symbol still requires evidence: missing data cannot change the
    frozen observation universe or the outcome's coverage claim.
    """

    publication_at = _utc(publication_at, "publication_at")
    evaluated_at = _utc(evaluated_at, "evaluated_at")
    if evaluated_at < publication_at:
        raise ValueError("forward_target_evaluation_before_publication")
    if (
        any(
            isinstance(value, datetime) or not isinstance(value, date)
            for value in (reference_session, end_session)
        )
        or reference_session >= end_session
    ):
        raise ValueError("forward_target_sessions_invalid")
    reference_open = datetime.combine(reference_session, time(9, 30), _SHANGHAI)
    if reference_open <= publication_at:
        raise ValueError("forward_target_reference_not_after_publication")
    if not target_weights or any(
        not isinstance(symbol, str)
        or not symbol
        or symbol.strip() != symbol
        or not isinstance(weight, Decimal)
        or not weight.is_finite()
        or not 0 <= weight <= 1
        for symbol, weight in target_weights.items()
    ):
        raise ValueError("forward_target_weights_invalid")
    if sum((Fraction(weight) for weight in target_weights.values()), Fraction(0)) > 1:
        raise ValueError("forward_target_gross_weight_invalid")
    selected: dict[tuple[str, date], list[DailyBarObservation]] = {}
    for bar in bars:
        if not isinstance(bar, DailyBarObservation):
            raise ValueError("forward_target_bar_invalid")
        if bar.instrument.symbol in target_weights and bar.session_date in {
            reference_session,
            end_session,
        }:
            selected.setdefault((bar.instrument.symbol, bar.session_date), []).append(
                bar
            )
    blockers = []
    observations = []
    weighted_response = Fraction(0)
    for symbol in sorted(target_weights):
        pair = []
        for session in (reference_session, end_session):
            candidates = selected.get((symbol, session), [])
            suffix = f"{symbol}:{session.isoformat()}"
            if not candidates:
                blockers.append(f"forward_target_bar_missing:{suffix}")
                continue
            if len(candidates) != 1:
                blockers.append(f"forward_target_bar_ambiguous:{suffix}")
                continue
            bar = candidates[0]
            session_close = datetime.combine(session, time(15), _SHANGHAI)
            if bar.event_time < session_close:
                blockers.append(f"forward_target_bar_before_session_close:{suffix}")
            elif bar.event_time <= publication_at:
                blockers.append(f"forward_target_bar_not_after_publication:{suffix}")
            elif bar.event_time > evaluated_at:
                blockers.append(f"forward_target_bar_in_future:{suffix}")
            elif bar.available_at > evaluated_at or bar.captured_at > evaluated_at:
                blockers.append(f"forward_target_bar_not_available:{suffix}")
            else:
                pair.append(bar)
        if len(pair) != 2:
            continue
        reference, end = pair
        if reference.instrument != end.instrument:
            blockers.append(f"forward_target_instrument_identity_changed:{symbol}")
            continue
        if end.event_time <= reference.event_time:
            blockers.append(f"forward_target_event_order_invalid:{symbol}")
            continue
        price_return = Fraction(end.close) / Fraction(reference.close) - 1
        contribution = Fraction(target_weights[symbol]) * price_return
        weighted_response += contribution
        observations.append(
            {
                "symbol": symbol,
                "instrument_type": reference.instrument.instrument_type.value,
                "target_weight": format(target_weights[symbol], "f"),
                "reference": _bar_binding(reference),
                "end": _bar_binding(end),
                "price_return": _decimal_string(price_return),
                "weighted_price_response": _decimal_string(contribution),
            }
        )
    return {
        "policy_id": FORWARD_TARGET_OUTCOME_POLICY_ID,
        "status": "unavailable" if blockers else "measured",
        "blockers": blockers,
        "publication_at": publication_at.isoformat(),
        "evaluated_at": evaluated_at.isoformat(),
        "reference_session": reference_session.isoformat(),
        "reference_session_open_at": reference_open.astimezone(
            timezone.utc
        ).isoformat(),
        "end_session": end_session.isoformat(),
        "target_weights": {
            key: format(target_weights[key], "f") for key in sorted(target_weights)
        },
        "observations": [] if blockers else observations,
        "weighted_price_response": None
        if blockers
        else _decimal_string(weighted_response),
        "return_basis": "unadjusted_price_only",
        "is_nav_return": False,
        "includes_fees": False,
        "includes_distributions": False,
        "assumes_fills": False,
        "limitations": [
            "Target-weighted price changes do not establish executable fills or investment returns.",
            "Unadjusted prices omit corporate-action cash and share entitlements, fees and taxes.",
            "This observation does not authorize account publication or trading.",
        ],
    }


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"forward_target_{name}_timezone_required")
    return value.astimezone(timezone.utc)


def _bar_binding(bar: DailyBarObservation) -> dict[str, str | bool]:
    return {
        "session_date": bar.session_date.isoformat(),
        "event_time": bar.event_time.isoformat(),
        "available_at": bar.available_at.isoformat(),
        "captured_at": bar.captured_at.isoformat(),
        "close": format(bar.close, "f"),
        "suspended": bar.suspended,
    }


def _decimal_string(value: Fraction) -> str:
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        return format(Decimal(value.numerator) / Decimal(value.denominator), "f")
