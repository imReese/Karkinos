from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from server.ai_runtime.provider_call_window import (
    DEEPSEEK_PEAK_WINDOW_FAILURE_CODE,
    DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
    DEEPSEEK_RUNWAY_FAILURE_CODE,
    ProviderCallDeferred,
    ProviderCallWindowConfigurationError,
    ProviderSendAdmission,
    provider_send_admission_for,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("hour", "minute", "allowed", "next_hour"),
    [
        (8, 59, True, None),
        (9, 0, False, 12),
        (11, 59, False, 12),
        (12, 0, True, None),
        (13, 59, True, None),
        (14, 0, False, 18),
        (17, 59, False, 18),
        (18, 0, True, None),
    ],
)
def test_deepseek_weekday_peak_boundaries_are_half_open(
    hour: int,
    minute: int,
    allowed: bool,
    next_hour: int | None,
) -> None:
    decision = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
        datetime(2026, 8, 31, hour, minute, tzinfo=SHANGHAI)
    )

    assert decision.allowed is allowed
    if next_hour is None:
        assert decision.next_eligible_at is None
        assert decision.failure_code is None
    else:
        assert datetime.fromisoformat(str(decision.next_eligible_at)).hour == next_hour
        assert decision.failure_code == DEEPSEEK_PEAK_WINDOW_FAILURE_CODE


@pytest.mark.unit
@pytest.mark.parametrize("day", [5, 6])
def test_deepseek_weekends_are_off_peak(day: int) -> None:
    decision = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
        datetime(2026, 9, day, 10, 0, tzinfo=SHANGHAI),
        minimum_runway=timedelta(seconds=7_500),
    )

    assert decision.allowed is True


@pytest.mark.unit
def test_utc_input_is_classified_in_shanghai_time() -> None:
    decision = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
        datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc)
    )

    assert decision.allowed is False
    assert decision.evaluated_at.startswith("2026-08-31T09:00:00+08:00")


@pytest.mark.unit
def test_batch_runway_must_finish_before_the_next_0900_peak() -> None:
    runway = timedelta(seconds=7_500)

    early = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
        datetime(2026, 8, 31, 6, 54, tzinfo=SHANGHAI),
        minimum_runway=runway,
    )
    too_late = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
        datetime(2026, 8, 31, 6, 55, tzinfo=SHANGHAI),
        minimum_runway=runway,
    )

    assert early.allowed is True
    assert too_late.allowed is False
    assert too_late.failure_code == DEEPSEEK_RUNWAY_FAILURE_CODE
    assert too_late.next_eligible_at == "2026-08-31T18:00:00+08:00"


@pytest.mark.unit
def test_full_batch_does_not_use_the_two_hour_lunch_window() -> None:
    decision = DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(
        datetime(2026, 8, 31, 12, 0, tzinfo=SHANGHAI),
        minimum_runway=timedelta(seconds=7_500),
    )

    assert decision.allowed is False
    assert decision.failure_code == DEEPSEEK_RUNWAY_FAILURE_CODE
    assert decision.next_eligible_at == "2026-08-31T18:00:00+08:00"


@pytest.mark.unit
def test_naive_clock_fails_closed() -> None:
    with pytest.raises(
        ProviderCallWindowConfigurationError,
        match="provider_call_window_requires_timezone_aware_clock",
    ):
        DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY.evaluate(datetime(2026, 8, 31, 8, 0))


@pytest.mark.unit
def test_send_admission_raises_before_the_caller_can_enter_transport() -> None:
    admission = ProviderSendAdmission(
        policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=lambda: datetime(2026, 8, 31, 14, 0, tzinfo=SHANGHAI),
    )

    with pytest.raises(ProviderCallDeferred) as caught:
        admission.require_allowed()

    assert caught.value.decision.next_eligible_at == "2026-08-31T18:00:00+08:00"


@pytest.mark.unit
def test_only_deepseek_receives_the_versioned_pricing_profile() -> None:
    assert provider_send_admission_for("DeepSeek") is not None
    assert provider_send_admission_for("fixture-provider") is None
