from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal, Inexact, localcontext
from zoneinfo import ZoneInfo

import pytest

from analytics.forward_target_outcomes import evaluate_forward_target_outcome
from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REFERENCE = date(2026, 9, 16)
_END = date(2026, 9, 17)
_PUBLISHED = datetime(2026, 9, 15, 16, tzinfo=_SHANGHAI)
_EVALUATED = datetime(2026, 9, 18, 16, tzinfo=_SHANGHAI)


def _bar(
    symbol: str, session: date, close: str, *, suspended: bool = False
) -> DailyBarObservation:
    event = datetime(session.year, session.month, session.day, 15, tzinfo=_SHANGHAI)
    price = Decimal(close)
    return DailyBarObservation(
        instrument=InstrumentKey(symbol, InstrumentType.STOCK),
        session_date=session,
        event_time=event,
        available_at=event + timedelta(minutes=1),
        captured_at=event + timedelta(minutes=2),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("0") if suspended else Decimal("1000"),
        amount=Decimal("0") if suspended else price * 1000,
        suspended=suspended,
    )


def _evaluate(bars, *, targets=None, **changes):
    arguments = {
        "publication_at": _PUBLISHED,
        "reference_session": _REFERENCE,
        "end_session": _END,
        "target_weights": targets or {"600001": Decimal("0.5")},
        "bars": bars,
        "evaluated_at": _EVALUATED,
    }
    arguments.update(changes)
    return evaluate_forward_target_outcome(**arguments)


def test_measures_frozen_weighted_price_response_without_fills_or_nav() -> None:
    result = _evaluate(
        [
            _bar("600001", _REFERENCE, "10"),
            _bar("600001", _END, "12"),
            _bar("600002", _REFERENCE, "20"),
            _bar("600002", _END, "18"),
        ],
        targets={"600001": Decimal("0.5"), "600002": Decimal("0.2")},
    )

    assert result["status"] == "measured"
    assert result["weighted_price_response"] == "0.08"
    assert [row["price_return"] for row in result["observations"]] == ["0.2", "-0.1"]
    assert [row["weighted_price_response"] for row in result["observations"]] == [
        "0.1",
        "-0.02",
    ]
    assert result["reference_session_open_at"] == "2026-09-16T01:30:00+00:00"
    assert result["return_basis"] == "unadjusted_price_only"
    assert result["is_nav_return"] is result["assumes_fills"] is False
    assert result["includes_fees"] is result["includes_distributions"] is False
    assert (
        result["observations"][0]["reference"]["captured_at"]
        == "2026-09-16T07:02:00+00:00"
    )


@pytest.mark.parametrize(
    "offset", [timedelta(0), timedelta(microseconds=1), timedelta(hours=3)]
)
def test_reference_session_must_not_already_have_opened_at_publication(offset) -> None:
    opening = datetime(2026, 9, 16, 9, 30, tzinfo=_SHANGHAI)
    with pytest.raises(
        ValueError, match="forward_target_reference_not_after_publication"
    ):
        _evaluate([], publication_at=opening + offset)


def test_publication_before_open_may_measure_that_days_subsequent_close() -> None:
    result = _evaluate(
        [_bar("600001", _REFERENCE, "10"), _bar("600001", _END, "11")],
        publication_at=datetime(2026, 9, 16, 9, 29, 59, 999999, tzinfo=_SHANGHAI),
    )
    assert result["status"] == "measured"


def test_missing_exact_endpoint_never_uses_a_later_available_session() -> None:
    result = _evaluate(
        [
            _bar("600001", _REFERENCE, "10"),
            _bar("600001", _END + timedelta(days=1), "13"),
        ]
    )

    assert result["blockers"] == ["forward_target_bar_missing:600001:2026-09-17"]
    assert result["status"] == "unavailable"
    assert result["observations"] == []
    assert result["weighted_price_response"] is None


def test_duplicate_endpoint_is_ambiguous_even_if_prices_agree() -> None:
    end = _bar("600001", _END, "11")
    result = _evaluate([_bar("600001", _REFERENCE, "10"), end, end])

    assert result["blockers"] == ["forward_target_bar_ambiguous:600001:2026-09-17"]
    assert result["weighted_price_response"] is None


@pytest.mark.parametrize("field", ["available_at", "captured_at"])
def test_endpoint_is_unavailable_until_information_and_capture_are_observed(
    field,
) -> None:
    end = _bar("600001", _END, "11")
    changes = {field: _EVALUATED + timedelta(microseconds=1)}
    if field == "available_at":
        changes["captured_at"] = changes[field]
    result = _evaluate([_bar("600001", _REFERENCE, "10"), replace(end, **changes)])

    assert result["blockers"] == ["forward_target_bar_not_available:600001:2026-09-17"]
    assert result["status"] == "unavailable"


def test_endpoint_close_cannot_come_from_an_incomplete_intraday_bar() -> None:
    end = _bar("600001", _END, "11")
    end = replace(end, event_time=end.event_time - timedelta(hours=1))
    result = _evaluate([_bar("600001", _REFERENCE, "10"), end])

    assert result["blockers"] == [
        "forward_target_bar_before_session_close:600001:2026-09-17"
    ]


def test_future_endpoint_does_not_become_a_measurement_early() -> None:
    result = _evaluate(
        [_bar("600001", _REFERENCE, "10"), _bar("600001", _END, "11")],
        evaluated_at=datetime(2026, 9, 17, 14, 59, tzinfo=_SHANGHAI),
    )

    assert result["blockers"] == ["forward_target_bar_in_future:600001:2026-09-17"]


def test_typed_instrument_cannot_change_between_endpoints() -> None:
    end = replace(
        _bar("600001", _END, "11"),
        instrument=InstrumentKey("600001", InstrumentType.ETF),
    )
    result = _evaluate([_bar("600001", _REFERENCE, "10"), end])

    assert result["blockers"] == ["forward_target_instrument_identity_changed:600001"]


def test_missing_zero_weight_symbol_still_makes_frozen_coverage_unavailable() -> None:
    result = _evaluate(
        [_bar("600001", _REFERENCE, "10"), _bar("600001", _END, "11")],
        targets={"600001": Decimal("0.5"), "600002": Decimal("0")},
    )

    assert result["blockers"] == [
        "forward_target_bar_missing:600002:2026-09-16",
        "forward_target_bar_missing:600002:2026-09-17",
    ]
    assert result["observations"] == []


def test_suspended_bar_remains_price_evidence_without_claiming_tradability() -> None:
    result = _evaluate(
        [
            _bar("600001", _REFERENCE, "10"),
            _bar("600001", _END, "10", suspended=True),
        ]
    )

    assert result["status"] == "measured"
    assert result["weighted_price_response"] == "0"
    assert result["observations"][0]["end"]["suspended"] is True
    assert result["assumes_fills"] is False


def test_ratio_rounding_is_stable_under_the_callers_decimal_context() -> None:
    bars = [_bar("600001", _REFERENCE, "3"), _bar("600001", _END, "4")]
    expected = _evaluate(bars)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        actual = _evaluate(bars)

    assert actual == expected
    assert actual["weighted_price_response"] == "0.1666666666666666666666666666666667"


@pytest.mark.parametrize("field", ["publication_at", "evaluated_at"])
def test_naive_instants_are_rejected(field) -> None:
    with pytest.raises(ValueError, match=f"forward_target_{field}_timezone_required"):
        _evaluate([], **{field: datetime(2026, 9, 15)})


def test_evaluation_cannot_precede_publication() -> None:
    with pytest.raises(
        ValueError, match="forward_target_evaluation_before_publication"
    ):
        _evaluate(
            [],
            evaluated_at=_PUBLISHED.astimezone(timezone.utc)
            - timedelta(microseconds=1),
        )


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"end_session": _REFERENCE}, "forward_target_sessions_invalid"),
        ({"reference_session": _PUBLISHED}, "forward_target_sessions_invalid"),
        ({"target_weights": {}}, "forward_target_weights_invalid"),
        (
            {"target_weights": {"600001": Decimal("NaN")}},
            "forward_target_weights_invalid",
        ),
        (
            {"target_weights": {"600001": Decimal("-0.1")}},
            "forward_target_weights_invalid",
        ),
        ({"target_weights": {"600001": 0.5}}, "forward_target_weights_invalid"),
        (
            {"target_weights": {"600001": Decimal("0.7"), "600002": Decimal("0.5")}},
            "forward_target_gross_weight_invalid",
        ),
    ],
)
def test_invalid_frozen_inputs_are_rejected(changes, error) -> None:
    with pytest.raises(ValueError, match=error):
        _evaluate([], **changes)


def test_provider_objects_cannot_replace_canonical_bars() -> None:
    with pytest.raises(ValueError, match="forward_target_bar_invalid"):
        _evaluate([object()])
