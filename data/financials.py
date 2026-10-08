"""In-memory selection of explicitly timed financial research observations.

This module does not fetch, persist, verify, or admit financial statements as a
PIT Dataset. ``event_time`` is the reported disclosure event; ``end_date`` is the
fiscal period end. Availability and capture are separate, caller-supplied facts.
Queries conservatively require both availability and capture by the decision
instant, so a report collected today is not silently admitted to an old backtest.
Source, statement scope, units and revision provenance remain the caller's duty.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import Symbol

_FACTOR_FIELDS = (
    "roe",
    "net_profit_yoy",
    "revenue_yoy",
    "debt_to_assets",
    "gross_margin",
    "operating_cash_flow",
    "eps",
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _instant(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("financial_observation_timezone_required")
    return value.astimezone(timezone.utc)


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("financial_observation_identity_invalid")


@dataclass(frozen=True)
class FinancialStatementObservation:
    """One supplied statement version in an explicit source/accounting scope.

    ``scope`` must distinguish incompatible definitions, for example consolidated
    annual versus parent-company quarterly statements. Percent fields use percent
    units (32.5 means 32.5%); cash flow is CNY and EPS is CNY per share. Disclosure
    event time is not inferred from a provider's date-only announcement field.
    """

    symbol: Symbol
    end_date: date
    event_time: datetime
    available_at: datetime
    captured_at: datetime
    source: str
    scope: str
    revision_id: str
    roe: float | None = None
    net_profit_yoy: float | None = None
    revenue_yoy: float | None = None
    debt_to_assets: float | None = None
    gross_margin: float | None = None
    operating_cash_flow: float | None = None
    eps: float | None = None

    def __post_init__(self) -> None:
        for value in (self.symbol, self.source, self.scope, self.revision_id):
            _text(value)
        if not isinstance(self.end_date, date) or isinstance(self.end_date, datetime):
            raise ValueError("financial_observation_period_end_invalid")
        for name in ("event_time", "available_at", "captured_at"):
            object.__setattr__(self, name, _instant(getattr(self, name)))
        if self.end_date > self.event_time.astimezone(_SHANGHAI).date():
            raise ValueError("financial_observation_disclosure_before_period_end")
        if not self.event_time <= self.available_at <= self.captured_at:
            raise ValueError("financial_observation_time_order_invalid")
        for name in _FACTOR_FIELDS:
            value = getattr(self, name)
            if value is not None:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError("financial_observation_value_invalid")
                object.__setattr__(self, name, float(value))

    def to_json_dict(self) -> dict:
        payload = asdict(self)
        for name in ("end_date", "event_time", "available_at", "captured_at"):
            payload[name] = getattr(self, name).isoformat()
        return payload


class FinancialResearchStore:
    """A local research helper; no persistence, source validation or PIT authority."""

    def __init__(
        self, observations: Iterable[FinancialStatementObservation] = ()
    ) -> None:
        self._records: list[FinancialStatementObservation] = []
        for observation in observations:
            self.add_observation(observation)

    def add_observation(self, observation: FinancialStatementObservation) -> None:
        if not isinstance(observation, FinancialStatementObservation):
            raise TypeError("financial_statement_observation_required")
        for prior in self._records:
            if (prior.symbol, prior.source, prior.scope) != (
                observation.symbol,
                observation.source,
                observation.scope,
            ):
                continue
            if prior == observation:
                return
            if prior.revision_id == observation.revision_id or (
                prior.end_date == observation.end_date
                and prior.available_at == observation.available_at
            ):
                raise ValueError("financial_observation_revision_conflict")
        self._records.append(observation)

    def get_latest_as_of(
        self, symbol: Symbol, as_of: datetime, *, source: str, scope: str
    ) -> FinancialStatementObservation | None:
        """Choose the latest fiscal period, then its latest visible revision.

        A later restatement of an older period never replaces a newer period.
        Backfilled or not-yet-available versions are excluded, without fallback
        across providers or incompatible statement scopes.
        """
        cutoff = _instant(as_of)
        for value in (symbol, source, scope):
            _text(value)
        return max(
            (
                row
                for row in self._records
                if (row.symbol, row.source, row.scope) == (symbol, source, scope)
                and row.available_at <= cutoff
                and row.captured_at <= cutoff
            ),
            key=lambda row: (row.end_date, row.available_at),
            default=None,
        )

    def to_cross_sectional_dataframe(
        self,
        symbols: Sequence[Symbol],
        decision_times: Sequence[datetime],
        *,
        source: str,
        scope: str,
        field: str = "roe",
    ) -> pd.DataFrame:
        """Return an explicitly scoped research factor panel; missing stays NaN."""
        for value in (source, scope, *symbols):
            _text(value)
        if field not in _FACTOR_FIELDS:
            raise ValueError("financial_observation_field_unsupported")
        if len(set(symbols)) != len(symbols):
            raise ValueError("financial_observation_duplicate_symbol")
        instants = [_instant(value) for value in decision_times]
        if instants != sorted(set(instants)):
            raise ValueError("financial_observation_decisions_not_unique_increasing")
        values = []
        for instant in instants:
            row = []
            for symbol in symbols:
                observation = self.get_latest_as_of(
                    symbol, instant, source=source, scope=scope
                )
                row.append(getattr(observation, field) if observation else None)
            values.append(row)
        return pd.DataFrame(
            values,
            index=pd.DatetimeIndex(instants, name="as_of"),
            columns=list(symbols),
            dtype=float,
        )
