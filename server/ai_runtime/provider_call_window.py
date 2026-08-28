"""Pure provider pricing-window policy and send admission.

The policy owns calendar arithmetic only.  Workflows decide whether to defer a
batch, provider adapters enforce the final send boundary, and HTTP transports
remain unaware of providers or pricing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from server.ai_runtime.contracts import content_fingerprint

PROVIDER_CALL_WINDOW_SCHEMA = "karkinos.ai.provider_call_window.v1"
DEEPSEEK_CALL_WINDOW_POLICY_ID = "deepseek.beijing_weekday_peak.v1"
DEEPSEEK_PEAK_WINDOW_FAILURE_CODE = "deepseek_peak_pricing_window"
DEEPSEEK_RUNWAY_FAILURE_CODE = "deepseek_off_peak_runway_insufficient"
PROVIDER_CALL_COMPLETION_GUARD_SECONDS = 5


class ProviderCallWindowConfigurationError(ValueError):
    """Raised when a call-window decision cannot be made safely."""


class ProviderCallDeferred(ValueError):
    """Raised before provider contact when the pricing window is not eligible."""

    def __init__(self, decision: ProviderCallWindowDecision) -> None:
        super().__init__(decision.failure_code or "provider_call_window_deferred")
        self.decision = decision


@dataclass(frozen=True)
class WeeklyPeakWindow:
    weekdays: tuple[int, ...]
    starts_at: time
    ends_at: time

    def __post_init__(self) -> None:
        if not self.weekdays or any(day < 0 or day > 6 for day in self.weekdays):
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_weekdays_invalid"
            )
        if self.starts_at >= self.ends_at:
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_must_not_cross_midnight"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekdays": list(self.weekdays),
            "starts_at": self.starts_at.isoformat(timespec="minutes"),
            "ends_at": self.ends_at.isoformat(timespec="minutes"),
        }


@dataclass(frozen=True)
class ProviderCallWindowDecision:
    policy_id: str
    policy_fingerprint: str
    provider_id: str
    timezone_name: str
    status: str
    pricing_period: str
    failure_code: str | None
    evaluated_at: str
    next_eligible_at: str | None
    minimum_runway_seconds: int

    @property
    def allowed(self) -> bool:
        return self.status == "eligible_off_peak"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROVIDER_CALL_WINDOW_SCHEMA,
            "policy_id": self.policy_id,
            "policy_fingerprint": self.policy_fingerprint,
            "provider_id": self.provider_id,
            "timezone": self.timezone_name,
            "status": self.status,
            "pricing_period": self.pricing_period,
            "failure_code": self.failure_code,
            "evaluated_at": self.evaluated_at,
            "next_eligible_at": self.next_eligible_at,
            "minimum_runway_seconds": self.minimum_runway_seconds,
            "provider_call_performed": False,
            "authority_effect": "none",
        }

    def stable_evidence(self) -> dict[str, Any]:
        """Return polling-stable evidence for an idempotent defer record."""

        return {
            key: value for key, value in self.to_dict().items() if key != "evaluated_at"
        }


def provider_call_deferred_payload(
    decision: ProviderCallWindowDecision,
) -> dict[str, Any]:
    """Build the shared non-authorizing HTTP/application defer projection."""

    return {
        "schema_version": PROVIDER_CALL_WINDOW_SCHEMA,
        "status": "deferred",
        "failure_code": decision.failure_code,
        "next_eligible_at": decision.next_eligible_at,
        "provider_call_window": decision.to_dict(),
        "provider_call_performed": False,
        "authority_effect": "none",
    }


@dataclass(frozen=True)
class ProviderCallWindowPolicy:
    policy_id: str
    provider_id: str
    timezone_name: str
    peak_windows: tuple[WeeklyPeakWindow, ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.provider_id.strip():
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_identity_missing"
            )
        try:
            ZoneInfo(self.timezone_name)
        except Exception as exc:
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_timezone_invalid"
            ) from exc
        if not self.peak_windows:
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_peak_windows_missing"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROVIDER_CALL_WINDOW_SCHEMA,
            "policy_id": self.policy_id,
            "provider_id": self.provider_id,
            "timezone": self.timezone_name,
            "peak_windows": [window.to_dict() for window in self.peak_windows],
            "boundary_semantics": "half_open",
        }

    def evaluate(
        self,
        observed_at: datetime,
        *,
        minimum_runway: timedelta = timedelta(0),
    ) -> ProviderCallWindowDecision:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_requires_timezone_aware_clock"
            )
        if minimum_runway < timedelta(0):
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_runway_must_not_be_negative"
            )

        local_now = observed_at.astimezone(ZoneInfo(self.timezone_name))
        active = self._active_peak_window(local_now)
        candidate = active[1] if active is not None else local_now
        failure_code = DEEPSEEK_PEAK_WINDOW_FAILURE_CODE if active is not None else None

        # Find the first off-peak instant with enough uninterrupted runway.  A
        # bounded weekly schedule always resolves within two weeks.
        for _ in range(32):
            active_candidate = self._active_peak_window(candidate)
            if active_candidate is not None:
                candidate = active_candidate[1]
                continue
            next_peak = self._next_peak_window(candidate)
            if next_peak is None or candidate + minimum_runway < next_peak[0]:
                break
            candidate = next_peak[1]
            if failure_code is None:
                failure_code = DEEPSEEK_RUNWAY_FAILURE_CODE
        else:
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_next_eligible_unresolved"
            )

        allowed = candidate == local_now
        return ProviderCallWindowDecision(
            policy_id=self.policy_id,
            policy_fingerprint=self.fingerprint,
            provider_id=self.provider_id,
            timezone_name=self.timezone_name,
            status=(
                "eligible_off_peak" if allowed else "deferred_for_provider_off_peak"
            ),
            pricing_period="peak" if active is not None else "off_peak",
            failure_code=None if allowed else failure_code,
            evaluated_at=local_now.isoformat(),
            next_eligible_at=None if allowed else candidate.isoformat(),
            minimum_runway_seconds=int(minimum_runway.total_seconds()),
        )

    def eligible_until(self, observed_at: datetime) -> datetime | None:
        """Return the next peak boundary for the current off-peak segment."""

        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ProviderCallWindowConfigurationError(
                "provider_call_window_requires_timezone_aware_clock"
            )
        local_now = observed_at.astimezone(ZoneInfo(self.timezone_name))
        if self._active_peak_window(local_now) is not None:
            return None
        next_peak = self._next_peak_window(local_now)
        return next_peak[0] if next_peak is not None else None

    def _active_peak_window(self, moment: datetime) -> tuple[datetime, datetime] | None:
        for window in self.peak_windows:
            if moment.weekday() not in window.weekdays:
                continue
            starts_at, ends_at = self._window_datetimes(moment.date(), window)
            if starts_at <= moment < ends_at:
                return starts_at, ends_at
        return None

    def _next_peak_window(self, moment: datetime) -> tuple[datetime, datetime] | None:
        for offset in range(15):
            candidate_date = moment.date() + timedelta(days=offset)
            for window in self.peak_windows:
                if candidate_date.weekday() not in window.weekdays:
                    continue
                starts_at, ends_at = self._window_datetimes(candidate_date, window)
                if ends_at <= moment:
                    continue
                return starts_at, ends_at
        return None

    def _window_datetimes(
        self, local_date: date, window: WeeklyPeakWindow
    ) -> tuple[datetime, datetime]:
        zone = ZoneInfo(self.timezone_name)
        return (
            datetime.combine(local_date, window.starts_at, tzinfo=zone),
            datetime.combine(local_date, window.ends_at, tzinfo=zone),
        )


class ProviderSendAdmission:
    """Evaluate the shared policy immediately before a provider send."""

    def __init__(
        self,
        *,
        policy: ProviderCallWindowPolicy,
        now: Callable[[], datetime] | None = None,
        minimum_runway: timedelta = timedelta(0),
    ) -> None:
        self._policy = policy
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._minimum_runway = minimum_runway

    @property
    def policy(self) -> ProviderCallWindowPolicy:
        return self._policy

    def decision(self) -> ProviderCallWindowDecision:
        return self._policy.evaluate(self._now(), minimum_runway=self._minimum_runway)

    def require_allowed(self) -> ProviderCallWindowDecision:
        decision = self.decision()
        if not decision.allowed:
            raise ProviderCallDeferred(decision)
        return decision


DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY = ProviderCallWindowPolicy(
    policy_id=DEEPSEEK_CALL_WINDOW_POLICY_ID,
    provider_id="deepseek",
    timezone_name="Asia/Shanghai",
    peak_windows=(
        WeeklyPeakWindow(
            weekdays=(0, 1, 2, 3, 4),
            starts_at=time(9, 0),
            ends_at=time(12, 0),
        ),
        WeeklyPeakWindow(
            weekdays=(0, 1, 2, 3, 4),
            starts_at=time(14, 0),
            ends_at=time(18, 0),
        ),
    ),
)


def provider_send_admission_for(
    provider_id: str,
    *,
    now: Callable[[], datetime] | None = None,
    minimum_runway: timedelta = timedelta(0),
) -> ProviderSendAdmission | None:
    if provider_id.strip().casefold() != "deepseek":
        return None
    return ProviderSendAdmission(
        policy=DEEPSEEK_PROVIDER_CALL_WINDOW_POLICY,
        now=now,
        minimum_runway=minimum_runway,
    )
