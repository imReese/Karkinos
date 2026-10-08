"""Bounded replay of actually published targets into an independent paper book.

The caller binds immutable bars and their availability at settlement. This is a
future-session close execution model, not strict historical-PIT admission.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from backtest.distributions import StockDistribution
from backtest.engine import BacktestEngine, BacktestExecutionConfig
from core.event_bus import EventBus
from core.events import FillEvent, MarketEvent, OrderEvent, SignalEvent
from core.types import ZERO, BarFrequency, Symbol
from domain.instrument import Instrument
from strategy.base import Strategy

_SHANGHAI = ZoneInfo("Asia/Shanghai")
PAPER_REPLAY_POLICY_ID = "karkinos.paper.forward_published_target_daily_close.v1"


@dataclass(frozen=True)
class PublishedPaperTarget:
    id: str
    published_at: datetime
    reference_session: date
    target_weights: Mapping[str, Decimal]


class _NoForecastStrategy(Strategy):
    """The engine consumes persisted publications; no predictions are generated."""

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        pass


def _identity(kind: str, *parts: str) -> str:
    encoded = json.dumps(parts, separators=(",", ":")).encode()
    return f"paper-{kind}-" + hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Decimal) -> str:
    """Preserve exact value while making zero awards irrelevant to a prefix."""
    if value == ZERO:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class _PublishedTargetReplay(BacktestEngine):
    """Adapt published targets and collect facts around canonical execution."""

    def __init__(self, *, book_id, schedule, **kwargs):
        self.book_id = book_id
        self.schedule = schedule
        self.sessions: list[dict[str, Any]] = []
        self.paper_fills: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self._session_fill_start = 0
        self._session_attempt_start = 0
        self._publication: PublishedPaperTarget | None = None
        self._requested_order: OrderEvent | None = None
        super().__init__(
            strategy=_NoForecastStrategy(book_id, EventBus()),
            db=None,
            strict_event_errors=True,
            session_completed=self._capture_session,
            **kwargs,
        )

    def _on_market_event(self, event: MarketEvent) -> None:
        session = event.timestamp.astimezone(_SHANGHAI).date()
        publication = self.schedule.get(session) if not self._warming_up else None
        self._publication = publication
        self._requested_order = None
        if publication is not None:
            self._pending_signals[event.symbol] = SignalEvent(
                timestamp=publication.published_at,
                strategy_id=publication.id,
                symbol=event.symbol,
                target_weight=publication.target_weights[str(event.symbol)],
            )
        previous_fills = len(self.paper_fills)
        cash_resized = self._cash_resized_count
        capacity_resized = self._capacity_resized_count
        blocked = dict(self._execution_blocked)
        ca_blocked = (
            self._dividend_replay.execution_blocked_count
            if self._dividend_replay is not None
            else 0
        )
        super()._on_market_event(event)
        if publication is not None:
            fill = (
                self.paper_fills[-1] if len(self.paper_fills) > previous_fills else None
            )
            reason = next(
                (
                    key
                    for key, value in self._execution_blocked.items()
                    if value > blocked[key]
                ),
                None,
            )
            if (
                self._dividend_replay is not None
                and self._dividend_replay.execution_blocked_count > ca_blocked
            ):
                reason = "corporate_action_price_limit_reference_missing"
            if fill and self._capacity_resized_count > capacity_resized:
                reason = "volume_participation_partial_fill"
            elif fill and self._cash_resized_count > cash_resized:
                reason = "cash_resized_partial_fill"
            self.attempts.append(
                {
                    "publication_id": publication.id,
                    "symbol": str(event.symbol),
                    "session": session.isoformat(),
                    "status": "filled" if fill else "blocked" if reason else "no_order",
                    "reason": reason
                    or ("filled" if fill else "target_sizing_no_order"),
                    "fill_id": fill["fill_id"] if fill else None,
                    "target_weight": _decimal_text(
                        publication.target_weights[str(event.symbol)]
                    ),
                    "actual_weight": _decimal_text(
                        self.portfolio.positions[event.symbol].market_value
                        / self.portfolio.total_equity
                    )
                    if event.symbol in self.portfolio.positions
                    and self.portfolio.total_equity > 0
                    else "0",
                    "requested_quantity": _decimal_text(self._requested_order.quantity)
                    if self._requested_order
                    else None,
                    "filled_quantity": fill["fill_quantity"] if fill else "0",
                    "cash_after_attempt": _decimal_text(self.portfolio.cash),
                    "partially_filled": bool(
                        fill
                        and self._requested_order
                        and Decimal(fill["fill_quantity"])
                        < self._requested_order.quantity
                    ),
                }
            )
        self._publication = None

    def _on_order_event(self, event: OrderEvent) -> None:
        publication = self._publication
        if publication is None:
            raise ValueError("paper_replay_unpublished_order")
        self._requested_order = event
        parts = (
            self.book_id,
            publication.id,
            str(event.symbol),
            publication.reference_session.isoformat(),
            event.side.value,
        )
        super()._on_order_event(
            replace(
                event,
                order_id=_identity("order", *parts),
                intent_id=_identity("intent", *parts),
                risk_decision_id=_identity("risk", *parts),
            )
        )

    def _resolve_fill(self, event: OrderEvent) -> FillEvent | None:
        fill = super()._resolve_fill(event)
        if fill is None:
            return None
        return replace(fill, fill_id=_identity("fill", event.order_id))

    def _record_fill_event(self, fill: FillEvent, order: OrderEvent) -> None:
        super()._record_fill_event(fill, order)
        if self._publication is None:
            raise ValueError("paper_replay_unpublished_fill")
        breakdown = dict(fill.fee_breakdown) if fill.fee_breakdown is not None else None
        if breakdown is not None:
            for field in (
                "gross_amount",
                "commission",
                "stamp_tax",
                "transfer_fee",
                "other_fees",
                "total_fee",
            ):
                if field in breakdown:
                    breakdown[field] = _decimal_text(Decimal(str(breakdown[field])))
        self.paper_fills.append(
            {
                "fill_id": fill.fill_id,
                "order_id": fill.order_id,
                "publication_id": self._publication.id,
                "session": self._publication.reference_session.isoformat(),
                "timestamp": fill.timestamp.isoformat(),
                "symbol": str(fill.symbol),
                "side": fill.side.value,
                "fill_price": _decimal_text(fill.fill_price),
                "fill_quantity": _decimal_text(fill.fill_quantity),
                "commission": _decimal_text(fill.commission),
                "slippage": _decimal_text(fill.slippage),
                "fee_breakdown": breakdown,
                "fee_rule_id": fill.fee_rule_id,
                "fee_rule_version": fill.fee_rule_version,
            }
        )

    def _capture_session(self, session: date) -> None:
        positions = {
            str(symbol): {
                field: _decimal_text(getattr(position, field))
                for field in (
                    "quantity",
                    "frozen_qty",
                    "unlisted_qty",
                    "available_qty",
                    "avg_cost",
                    "realized_pnl",
                    "unrealized_pnl",
                    "commission_paid",
                    "market_value",
                )
            }
            for symbol, position in sorted(self.portfolio.positions.items())
        }
        corporate_actions = []
        replay = self._dividend_replay
        if replay is not None:
            for item in replay.distributions:
                if item.action_id not in replay.accrued:
                    continue
                # Future terms and zero holdings do not change a financial prefix.
                quantity = replay.eligible.get(item.action_id, ZERO)
                if quantity == ZERO:
                    continue
                corporate_actions.append(
                    {
                        "action_id": item.action_id,
                        "symbol": str(item.symbol),
                        "eligible_quantity": _decimal_text(quantity),
                        "accrued": item.action_id in replay.accrued,
                        "gross_amount": _decimal_text(
                            replay.accrued.get(item.action_id, ZERO)
                        ),
                        "paid": item.action_id in replay.paid,
                        "share_quantity": _decimal_text(
                            replay.shares.get(item.action_id, ZERO)
                        ),
                        "shares_listed": item.action_id in replay.listed,
                    }
                )
        self.sessions.append(
            {
                "session": session.isoformat(),
                "cash": _decimal_text(self.portfolio.cash),
                "equity": _decimal_text(self.portfolio.total_equity),
                "dividend_receivable": _decimal_text(
                    self.portfolio.dividend_receivable
                ),
                "dividend_income": _decimal_text(self.portfolio.dividend_income),
                "positions": positions,
                "fills": self.paper_fills[self._session_fill_start :],
                "attempts": self.attempts[self._session_attempt_start :],
                "corporate_actions": sorted(
                    corporate_actions, key=lambda item: item["action_id"]
                ),
            }
        )
        self._session_fill_start = len(self.paper_fills)
        self._session_attempt_start = len(self.attempts)


def replay_paper_book(
    *,
    book_id: str,
    initial_cash: Decimal,
    instruments: Mapping[Symbol, Instrument],
    bars: Sequence[MarketEvent],
    publications: Sequence[PublishedPaperTarget],
    evaluation_start: date,
    through_session: date,
    cost_config: BacktestExecutionConfig | None = None,
    distributions: Sequence[StockDistribution] = (),
    include_share_distributions: bool = True,
) -> dict[str, Any]:
    """Replay a complete bounded paper prefix; never access a DB or providers.

    Earlier bars only warm the preceding-close limit reference. Every included
    book session must have a close for every frozen instrument. The caller owns
    verified calendar continuity, capture/availability and CA revision admission.
    """
    if (
        not isinstance(book_id, str)
        or not book_id.strip()
        or not isinstance(initial_cash, Decimal)
        or not initial_cash.is_finite()
        or initial_cash <= ZERO
        or type(evaluation_start) is not date
        or type(through_session) is not date
        or evaluation_start > through_session
        or not 1 <= len(instruments) <= 50
        or not 1 <= len(bars) <= 200_000
        or len(publications) > 10_000
        or len(distributions) > 10_000
    ):
        raise ValueError("paper_replay_input_invalid")
    universe = set(instruments)
    if any(symbol != instrument.symbol for symbol, instrument in instruments.items()):
        raise ValueError("paper_replay_instrument_identity_invalid")
    grouped: dict[Symbol, list[MarketEvent]] = {symbol: [] for symbol in instruments}
    sessions: dict[date, set[Symbol]] = {}
    for event in bars:
        if event.timestamp.tzinfo is None or event.timestamp.utcoffset() is None:
            raise ValueError("paper_replay_bar_timezone_required")
        local = event.timestamp.astimezone(_SHANGHAI)
        day = local.date()
        if (
            event.symbol not in universe
            or event.instrument_type != instruments[event.symbol].instrument_type
            or event.frequency is not BarFrequency.DAILY
            or local.time() != time(15)
            or day > through_session
        ):
            raise ValueError("paper_replay_daily_close_required")
        if any(
            not value.is_finite() or value <= ZERO
            for value in (event.open, event.high, event.low, event.close)
        ) or (
            not event.volume.is_finite()
            or event.volume < ZERO
            or event.high < max(event.open, event.close, event.low)
            or event.low > min(event.open, event.close, event.high)
        ):
            raise ValueError("paper_replay_bar_invalid")
        seen = sessions.setdefault(day, set())
        if event.symbol in seen:
            raise ValueError("paper_replay_duplicate_bar")
        seen.add(event.symbol)
        # Normalize only timezone representation; availability is preserved.
        grouped[event.symbol].append(replace(event, timestamp=local))
    active_days = [day for day in sorted(sessions) if day >= evaluation_start]
    warmup_days = [day for day in sessions if day < evaluation_start]
    if (
        not active_days
        or active_days[0] != evaluation_start
        or active_days[-1] != through_session
        or not warmup_days
        or sessions[max(warmup_days)] != universe
        or any(sessions[day] != universe for day in active_days)
    ):
        raise ValueError("paper_replay_session_bars_missing")
    schedule = {}
    identities = set()
    for publication in publications:
        if (
            not isinstance(publication.id, str)
            or not publication.id.strip()
            or publication.id in identities
            or type(publication.reference_session) is not date
            or publication.reference_session < evaluation_start
            or publication.reference_session in schedule
        ):
            raise ValueError("paper_replay_publication_invalid")
        if (
            publication.published_at.tzinfo is None
            or publication.published_at.utcoffset() is None
            or publication.published_at
            >= datetime.combine(publication.reference_session, time(9, 30), _SHANGHAI)
        ):
            raise ValueError("paper_replay_publication_too_late")
        if (
            set(publication.target_weights) != universe
            or any(
                not isinstance(weight, Decimal)
                or not weight.is_finite()
                or not ZERO <= weight <= Decimal(1)
                for weight in publication.target_weights.values()
            )
            or sum(publication.target_weights.values(), ZERO) > Decimal(1)
        ):
            raise ValueError("paper_replay_target_weights_invalid")
        if (
            publication.reference_session <= through_session
            and publication.reference_session not in sessions
        ):
            raise ValueError("paper_replay_target_close_missing")
        identities.add(publication.id)
        schedule[publication.reference_session] = publication
    config = cost_config or BacktestExecutionConfig()
    if config.availability_mode != "historical_snapshot":
        raise ValueError("paper_replay_availability_mode_unsupported")
    engine = _PublishedTargetReplay(
        book_id=book_id,
        schedule=schedule,
        instruments=dict(instruments),
        data_handlers=grouped,
        initial_cash=initial_cash,
        execution_config=config,
        cash_dividends=tuple(distributions),
        include_share_distributions=include_share_distributions,
        evaluation_start=evaluation_start,
    )
    engine.run()
    return {
        "schema_version": "karkinos.paper_book_replay.v1",
        "book_id": book_id,
        "policy_id": PAPER_REPLAY_POLICY_ID,
        "execution_model": "forward_published_target_daily_close",
        "ordering": "session_then_symbol_single_attempt",
        "historical_pit_verified": False,
        "contains_simulated_fills": True,
        "account_authority": False,
        "initial_cash": _decimal_text(initial_cash),
        "evaluation_start": evaluation_start.isoformat(),
        "through_session": through_session.isoformat(),
        "sessions": engine.sessions,
        "fills": engine.paper_fills,
        "attempts": engine.attempts,
        "pending_targets": [
            {"publication_id": publication.id, "reference_session": day.isoformat()}
            for day, publication in sorted(schedule.items())
            if day > through_session
        ],
    }
