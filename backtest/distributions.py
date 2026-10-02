"""Reported stock distribution replay for an explicitly gross research book."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from core.events import MarketEvent
from core.types import ZERO, Symbol
from domain.portfolio import Portfolio
from domain.portfolio_accounting import share_distribution_quantity

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _total_share_rate(bonus: Decimal, capitalized: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.traps[Inexact] = True
            total = bonus + capitalized
    except DecimalException as exc:
        raise ValueError("share_distribution_terms_invalid") from exc
    if not total.is_finite() or total < ZERO:
        raise ValueError("share_distribution_terms_invalid")
    return total


@dataclass(frozen=True)
class StockDistribution:
    action_id: str
    symbol: Symbol
    record_date: date
    ex_date: date
    pay_date: date | None
    cash_per_share: Decimal
    available_at: datetime
    bonus_per_share: Decimal = ZERO
    capitalized_per_share: Decimal = ZERO
    listing_date: date | None = None

    def __post_init__(self) -> None:
        if (
            not self.action_id
            or not self.symbol
            or not self.record_date < self.ex_date
            or not self.cash_per_share.is_finite()
            or self.cash_per_share < ZERO
            or self.available_at.tzinfo is None
            or any(
                not rate.is_finite() or rate < ZERO
                for rate in (self.bonus_per_share, self.capitalized_per_share)
            )
            or (self.cash_per_share == ZERO and self.shares_per_share == ZERO)
            or (
                self.cash_per_share > ZERO
                and (self.pay_date is None or self.pay_date < self.ex_date)
            )
            or (
                self.shares_per_share > ZERO
                and (self.listing_date is None or self.listing_date < self.ex_date)
            )
        ):
            raise ValueError("cash_dividend_terms_invalid")

    @property
    def shares_per_share(self) -> Decimal:
        return _total_share_rate(self.bonus_per_share, self.capitalized_per_share)


def distributions_from_evidence(
    evidence: Mapping[str, Any] | None,
    *,
    include_shares: bool = False,
) -> tuple[StockDistribution, ...]:
    """Read frozen implemented terms; never infer missing allocations or dates."""
    if (
        not evidence
        or evidence.get("schema_version") != "karkinos.corporate_action_evidence.v1"
        or evidence.get("status") != "observed"
        or evidence.get("coverage_status") != "provider_reported_only"
    ):
        raise ValueError("cash_dividend_evidence_required")
    if evidence.get("undated_event_count"):
        raise ValueError("cash_dividend_event_dates_incomplete")
    result = []
    implementations: set[tuple[str, str, str]] = set()
    for event in evidence["events"]:
        if event.get("instrument_type") != "stock" or event.get("div_proc") != "实施":
            raise ValueError("cash_dividend_implemented_stock_required")
        rates: dict[str, Decimal] = {}
        for field in ("stk_div", "stk_bo_rate", "stk_co_rate"):
            if event.get(field) is None:
                if field == "stk_div" or rates["stk_div"] > ZERO:
                    raise ValueError("cash_dividend_share_terms_missing")
                # An explicitly zero total already establishes no share award;
                # missing subtype breakdowns do not invent an additional award.
                rates[field] = ZERO
                continue
            value = Decimal(event[field])
            if not value.is_finite() or value < ZERO:
                raise ValueError("share_distribution_terms_invalid")
            if not include_shares and value != ZERO:
                raise ValueError("cash_dividend_share_distribution_unsupported")
            rates[field] = value
        if rates["stk_div"] != _total_share_rate(
            rates["stk_bo_rate"], rates["stk_co_rate"]
        ):
            raise ValueError("share_distribution_terms_conflicting")
        if event.get("cash_div_tax") is None:
            raise ValueError("cash_dividend_gross_amount_missing")
        value = Decimal(event["cash_div_tax"])
        if not value.is_finite() or value < ZERO:
            raise ValueError("cash_dividend_gross_amount_invalid")
        if event.get("record_date") and event.get("ex_date"):
            implementation = (event["symbol"], event["record_date"], event["ex_date"])
            if implementation in implementations:
                raise ValueError("cash_dividend_conflicting_implementation")
            implementations.add(implementation)
        if value == ZERO and rates["stk_div"] == ZERO:
            continue
        required_dates = ["record_date", "ex_date"]
        if value > ZERO:
            required_dates.append("pay_date")
        if rates["stk_div"] > ZERO:
            required_dates.append("div_listdate")
        if any(not event.get(field) for field in required_dates):
            raise ValueError("cash_dividend_event_dates_incomplete")
        identity = {
            key: event[key]
            for key in (
                "source_revision_id",
                "symbol",
                "end_date",
                "ann_date",
                "imp_ann_date",
                "record_date",
                "ex_date",
                "pay_date",
                "cash_div_tax",
            )
        }
        if include_shares:
            identity.update(
                {
                    key: event.get(key)
                    for key in ("stk_div", "stk_bo_rate", "stk_co_rate", "div_listdate")
                }
            )
        action_id = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        result.append(
            StockDistribution(
                action_id=action_id,
                symbol=Symbol(event["symbol"]),
                record_date=date.fromisoformat(event["record_date"]),
                ex_date=date.fromisoformat(event["ex_date"]),
                pay_date=(
                    date.fromisoformat(event["pay_date"])
                    if event.get("pay_date")
                    else None
                ),
                cash_per_share=value,
                available_at=datetime.fromisoformat(event["available_at"]),
                bonus_per_share=rates["stk_bo_rate"],
                capitalized_per_share=rates["stk_co_rate"],
                listing_date=(
                    date.fromisoformat(event["div_listdate"])
                    if event.get("div_listdate")
                    else None
                ),
            )
        )
    return tuple(result)


class DistributionReplay:
    """Schedule entitlement and settlement; Portfolio owns all money arithmetic."""

    def __init__(
        self,
        distributions: Sequence[StockDistribution],
        *,
        include_shares: bool = False,
    ) -> None:
        self.distributions = tuple(distributions)
        self.include_shares = include_shares
        if not include_shares and any(
            item.shares_per_share > ZERO for item in distributions
        ):
            raise ValueError("cash_dividend_share_distribution_unsupported")
        if len({item.action_id for item in distributions}) != len(distributions):
            raise ValueError("cash_dividend_duplicate_action")
        if len(
            {(item.symbol, item.record_date, item.ex_date) for item in distributions}
        ) != len(distributions):
            raise ValueError("cash_dividend_conflicting_implementation")
        self.eligible: dict[str, Decimal] = {}
        self.accrued: dict[str, Decimal] = {}
        self.paid: set[str] = set()
        self.shares: dict[str, Decimal] = {}
        self.listed: set[str] = set()
        self.execution_blocked_count = 0

    def validate_events(self, events: Sequence[MarketEvent], *, observed: bool) -> None:
        sessions: set[tuple[Symbol, date]] = set()
        for event in events:
            if event.timestamp.tzinfo is None:
                raise ValueError("cash_dividend_daily_close_required")
            local = event.timestamp.astimezone(_SHANGHAI)
            key = (event.symbol, local.date())
            if local.time() != time(15) or key in sessions:
                raise ValueError("cash_dividend_daily_close_required")
            sessions.add(key)
        if not sessions:
            raise ValueError("cash_dividend_bars_required")
        start, end = min(day for _, day in sessions), max(day for _, day in sessions)
        symbols = {symbol for symbol, _ in sessions}
        for item in self.distributions:
            if item.symbol not in symbols:
                raise ValueError("cash_dividend_symbol_missing")
            for day in (item.record_date, item.ex_date, item.listing_date):
                if day is None:
                    continue
                if start <= day <= end and (item.symbol, day) not in sessions:
                    raise ValueError("cash_dividend_required_session_missing")
            if observed and start <= item.ex_date <= end:
                decision_at = datetime.combine(item.ex_date, time(15), _SHANGHAI)
                if item.available_at > decision_at:
                    raise ValueError("cash_dividend_historical_availability_unverified")

    def before_session(self, day: date, portfolio: Portfolio) -> None:
        for item in self.distributions:
            if item.ex_date <= day and item.action_id not in self.accrued:
                amount = portfolio.accrue_cash_dividend(
                    item.action_id,
                    symbol=item.symbol,
                    eligible_quantity=self.eligible.get(item.action_id, ZERO),
                    cash_per_share=item.cash_per_share,
                )
                self.accrued[item.action_id] = amount
                if item.shares_per_share > ZERO:
                    self.shares[item.action_id] = portfolio.accrue_share_distribution(
                        item.action_id,
                        symbol=item.symbol,
                        eligible_quantity=self.eligible.get(item.action_id, ZERO),
                        shares_per_share=item.shares_per_share,
                    )
            if (
                item.cash_per_share > ZERO
                and item.pay_date is not None
                and item.pay_date <= day
                and item.action_id not in self.paid
            ):
                portfolio.pay_cash_dividend(item.action_id)
                self.paid.add(item.action_id)
            if (
                item.shares_per_share > ZERO
                and item.listing_date is not None
                and item.listing_date <= day
                and item.action_id not in self.listed
            ):
                portfolio.release_share_distribution(item.action_id)
                self.listed.add(item.action_id)

    def after_session(self, day: date, portfolio: Portfolio) -> None:
        for item in self.distributions:
            if item.record_date == day:
                position = portfolio.positions.get(item.symbol)
                quantity = position.quantity if position else ZERO
                # Fractional allocations depend on the registrar's account-level
                # process. Do not round either award component into invented stock.
                for rate in (item.bonus_per_share, item.capitalized_per_share):
                    share_distribution_quantity(
                        eligible_quantity=quantity, shares_per_share=rate
                    )
                self.eligible[item.action_id] = quantity

    def blocks_execution(self, symbol: Symbol, day: date) -> bool:
        # The dividend table does not supply an authoritative ex-date price-limit
        # reference. Never compare its unadjusted close to the prior raw close.
        blocked = any(
            item.symbol == symbol and item.ex_date == day for item in self.distributions
        )
        if blocked:
            self.execution_blocked_count += 1
        return blocked

    def evidence(self, portfolio: Portfolio) -> dict[str, Any]:
        result = {
            "schema_version": "karkinos.backtest_cash_dividends.v1",
            "mode": "cash_dividends_gross",
            "gross_income": str(portfolio.dividend_income),
            "cash_paid": str(portfolio.dividend_income - portfolio.dividend_receivable),
            "receivable": str(portfolio.dividend_receivable),
            "taxes_modeled": False,
            "coverage_verified": False,
            "historical_availability_verified": False,
            "ex_date_execution_blocked_count": self.execution_blocked_count,
            "distributions": [
                {
                    "action_id": item.action_id,
                    "symbol": str(item.symbol),
                    "record_date": item.record_date.isoformat(),
                    "ex_date": item.ex_date.isoformat(),
                    "pay_date": item.pay_date.isoformat() if item.pay_date else None,
                    "cash_per_share": str(item.cash_per_share),
                    "eligible_quantity": str(self.eligible.get(item.action_id, ZERO)),
                    "gross_amount": str(self.accrued.get(item.action_id, ZERO)),
                    "paid": item.action_id in self.paid,
                }
                for item in self.distributions
            ],
            "limitations": [
                "Only reported cash distributions are modeled; source completeness is unverified.",
                "Gross decimal entitlements omit investor-specific withholding tax and payment rounding.",
                "Share distributions and historical information availability are not modeled.",
                "Orders on a distribution's ex-date are blocked without a verified price-limit reference.",
            ],
        }
        if self.include_shares:
            result.update(
                {
                    "schema_version": "karkinos.backtest_cash_dividends.v2",
                    "mode": "reported_distributions_gross",
                    "share_quantity": str(sum(self.shares.values(), ZERO)),
                    "unlisted_quantity": str(
                        sum(
                            (
                                position.unlisted_qty
                                for position in portfolio.positions.values()
                            ),
                            ZERO,
                        )
                    ),
                    "limitations": [
                        "Only reported distributions are modeled; completeness and historical availability remain unverified.",
                        "Gross entitlements omit investor-specific tax and cash payment rounding; fractional share allocations are rejected.",
                        "New shares preserve the total cost basis and cannot be sold before their reported listing date.",
                        "Strategy features still use unadjusted prices; ex-date orders are blocked without a verified price-limit reference.",
                    ],
                }
            )
            for item, row in zip(
                self.distributions, result["distributions"], strict=True
            ):
                row.update(
                    {
                        "shares_per_share": str(item.shares_per_share),
                        "share_quantity": str(self.shares.get(item.action_id, ZERO)),
                        "listing_date": item.listing_date.isoformat()
                        if item.listing_date
                        else None,
                        "shares_listed": item.action_id in self.listed,
                    }
                )
        return result
