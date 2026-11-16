"""Pure mathematical calculation engine for A-share corporate action adjustments.

Formulas strictly adhere to Shanghai (SSE) and Shenzhen (SZSE) exchange standards:
1. Reference ex-dividend / ex-rights price:
       P_ex = (P_prev - D + p * P_r) / (1 + s + p)
   where:
       P_prev = closing price on record date (previous trading day)
       D      = cash dividend per share (税前每股派现)
       s      = bonus shares + capitalization shares per share (送转比例)
       p      = rights issue shares per share (配股比例)
       P_r    = rights issue price (配股价格)

2. Single-day adjustment multiplier:
       alpha_t = P_ex,t / P_prev,t  (1.0 on non-ex dates)

3. Forward-adjusted (QFQ) cumulative factor with cutoff T:
       f_qfq,T = 1.0
       f_qfq,t = prod_{tau=t+1}^T alpha_tau  (for t < T)
       P_qfq,t = P_raw,t * f_qfq,t

4. Backward-adjusted (HFQ) cumulative factor:
       f_hfq,1 = 1.0
       f_hfq,t = prod_{tau=2}^t (1 / alpha_tau)
       P_hfq,t = P_raw,t * f_hfq,t

5. Volume adjustment multiplier (share-dilution scaling):
       v_qfq,t = prod_{tau=t+1}^T ((1 + s_tau + p_tau) * split_ratio_tau)
       V_qfq,t = V_raw,t * v_qfq,t  (retains float64 precision; optional UI integer rounding)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import Any

from core.types import ZERO, Symbol
from data.corporate_actions.models import (
    AdjustmentFactor,
    AdjustmentFactorSeries,
    CorporateActionEvent,
    PriceBasis,
)

ONE = Decimal("1.0")
TEN = Decimal("10.0")


def compute_ex_reference_price(
    pre_close: Decimal,
    *,
    cash_dividend: Decimal = ZERO,
    bonus_ratio: Decimal = ZERO,
    capitalization_ratio: Decimal = ZERO,
    rights_ratio: Decimal = ZERO,
    rights_price: Decimal = ZERO,
    split_ratio: Decimal = ONE,
) -> Decimal:
    """Calculate the theoretical ex-rights/ex-dividend price P_ex.

    Formula:
        P_ex = (P_prev - D + p * P_r) / ( (1 + s + p) * split_ratio )
    """
    if (
        not isinstance(pre_close, Decimal)
        or not pre_close.is_finite()
        or pre_close <= ZERO
    ):
        raise ValueError("pre_close_must_be_positive_decimal")

    share_addition = bonus_ratio + capitalization_ratio + rights_ratio
    denominator = (ONE + share_addition) * split_ratio
    if denominator <= ZERO:
        raise ValueError("ex_price_denominator_must_be_positive")

    numerator = pre_close - cash_dividend + (rights_ratio * rights_price)
    if numerator <= ZERO:
        # In rare boundary events where dividend exceeds pre_close, floor at 0.01
        return Decimal("0.01")

    p_ex = numerator / denominator
    return p_ex


def compute_daily_alpha(
    pre_close: Decimal,
    ex_price: Decimal,
) -> Decimal:
    """Calculate the single-day adjustment ratio alpha = P_ex / P_prev."""
    if pre_close <= ZERO or ex_price <= ZERO:
        raise ValueError("prices_must_be_positive_for_alpha")
    return ex_price / pre_close


class CorporateActionAdjustmentEngine:
    """Stateless mathematical engine to generate adjustment factor series."""

    @staticmethod
    def calculate_factors(
        symbol: Symbol | str,
        trading_dates: Sequence[date],
        closing_prices: Sequence[Decimal],
        events: Sequence[CorporateActionEvent],
        *,
        cutoff_date: date | None = None,
        as_of_time: datetime | None = None,
    ) -> AdjustmentFactorSeries:
        """Compute full factor series for a security over the specified trading dates.

        Parameters:
        - symbol: Security symbol.
        - trading_dates: Sorted sequence of trading dates.
        - closing_prices: Corresponding unadjusted daily closing prices.
        - events: Observed corporate actions.
        - cutoff_date: Base date for QFQ (defaults to latest trading date).
        - as_of_time: Point-in-time filter; only events available on or before this time are included.
        """
        if len(trading_dates) != len(closing_prices):
            raise ValueError("trading_dates_and_closing_prices_length_mismatch")
        if not trading_dates:
            raise ValueError("trading_dates_cannot_be_empty")
        dates_list = list(trading_dates)
        if dates_list != sorted(dates_list) or len(dates_list) != len(set(dates_list)):
            raise ValueError("trading_dates_must_be_strictly_ascending")

        sym = Symbol(str(symbol))
        date_to_close = dict(zip(dates_list, closing_prices))

        # Filter events by point-in-time availability
        admitted_events: list[CorporateActionEvent] = []
        for ev in events:
            if ev.symbol != sym:
                continue
            if as_of_time is not None and ev.available_at is not None:
                if ev.available_at > as_of_time:
                    continue
            admitted_events.append(ev)

        # Group admitted events by ex_date
        events_by_ex_date: dict[date, list[CorporateActionEvent]] = defaultdict(list)
        for ev in admitted_events:
            events_by_ex_date[ev.ex_date].append(ev)

        # Single-day alphas and volume multipliers for each trading date
        daily_alphas: dict[date, Decimal] = {}
        daily_volume_mults: dict[date, Decimal] = {}
        daily_pre_closes: dict[date, Decimal | None] = {}
        daily_ex_prices: dict[date, Decimal | None] = {}
        daily_event_ids: dict[date, tuple[str, ...]] = {}

        for i, trade_date in enumerate(dates_list):
            day_events = events_by_ex_date.get(trade_date, [])
            if not day_events:
                daily_alphas[trade_date] = ONE
                daily_volume_mults[trade_date] = ONE
                daily_pre_closes[trade_date] = None
                daily_ex_prices[trade_date] = None
                daily_event_ids[trade_date] = ()
                continue

            # Corporate action occurred on trade_date (ex_date)
            # Find pre-close price on record date (or previous trading day)
            pre_close: Decimal | None = None
            if i > 0:
                pre_close = closing_prices[i - 1]
            else:
                # If first date in sample is ex-date, use first day close as fallback
                pre_close = closing_prices[0]

            # Aggregate all events on this ex-date
            tot_cash = sum((e.cash_dividend_per_share for e in day_events), ZERO)
            tot_bonus = sum((e.bonus_ratio for e in day_events), ZERO)
            tot_capital = sum((e.capitalization_ratio for e in day_events), ZERO)
            tot_rights = sum((e.rights_ratio for e in day_events), ZERO)
            tot_rights_val = sum(
                (e.rights_ratio * e.rights_price for e in day_events), ZERO
            )
            rights_p = (tot_rights_val / tot_rights) if tot_rights > ZERO else ZERO

            # Split ratio product
            split_mult = ONE
            for e in day_events:
                if e.split_ratio != ONE:
                    split_mult *= e.split_ratio

            ex_price = compute_ex_reference_price(
                pre_close,
                cash_dividend=tot_cash,
                bonus_ratio=tot_bonus,
                capitalization_ratio=tot_capital,
                rights_ratio=tot_rights,
                rights_price=rights_p,
                split_ratio=split_mult,
            )

            alpha = compute_daily_alpha(pre_close, ex_price)
            daily_alphas[trade_date] = alpha
            daily_volume_mults[trade_date] = (
                ONE + tot_bonus + tot_capital + tot_rights
            ) * split_mult
            daily_pre_closes[trade_date] = pre_close
            daily_ex_prices[trade_date] = ex_price
            daily_event_ids[trade_date] = tuple(e.event_id for e in day_events)

        # Determine cutoff date for QFQ
        if cutoff_date is not None:
            qfq_cutoff = cutoff_date
        elif as_of_time is not None:
            as_of_date = as_of_time.date()
            valid_as_of = [d for d in dates_list if d <= as_of_date]
            qfq_cutoff = valid_as_of[-1] if valid_as_of else dates_list[0]
        else:
            qfq_cutoff = dates_list[-1]

        if qfq_cutoff not in date_to_close:
            # If cutoff not directly in trading dates, use latest date <= cutoff
            valid_cutoffs = [d for d in dates_list if d <= qfq_cutoff]
            qfq_cutoff = valid_cutoffs[-1] if valid_cutoffs else dates_list[-1]

        cutoff_idx = dates_list.index(qfq_cutoff)

        # Cumulative QFQ calculation:
        # f_qfq,cutoff = 1.0
        # for t from cutoff_idx - 1 down to 0:
        #   f_qfq,t = f_qfq,t+1 * alpha_{t+1}
        qfq_factors: dict[date, Decimal] = {qfq_cutoff: ONE}
        current_qfq = ONE
        for t in range(cutoff_idx - 1, -1, -1):
            next_date = dates_list[t + 1]
            current_qfq = current_qfq * daily_alphas[next_date]
            qfq_factors[dates_list[t]] = current_qfq

        # For dates after cutoff (if any):
        current_after = ONE
        for t in range(cutoff_idx + 1, len(dates_list)):
            curr_date = dates_list[t]
            current_after = current_after / daily_alphas[curr_date]
            qfq_factors[curr_date] = current_after

        # Cumulative HFQ calculation:
        # f_hfq,0 = 1.0
        # for t from 1 to N-1:
        #   f_hfq,t = f_hfq,t-1 * (1 / alpha_t)
        hfq_factors: dict[date, Decimal] = {dates_list[0]: ONE}
        current_hfq = ONE
        for t in range(1, len(dates_list)):
            curr_date = dates_list[t]
            current_hfq = current_hfq / daily_alphas[curr_date]
            hfq_factors[curr_date] = current_hfq

        # Cumulative volume dilution factor (relative to cutoff)
        # v_qfq,cutoff = 1.0
        # for t from cutoff_idx - 1 down to 0:
        #   v_qfq,t = v_qfq,t+1 * volume_mult_{t+1}
        volume_factors: dict[date, Decimal] = {qfq_cutoff: ONE}
        current_vol = ONE
        for t in range(cutoff_idx - 1, -1, -1):
            next_date = dates_list[t + 1]
            current_vol = current_vol * daily_volume_mults[next_date]
            volume_factors[dates_list[t]] = current_vol

        current_vol_after = ONE
        for t in range(cutoff_idx + 1, len(dates_list)):
            curr_date = dates_list[t]
            current_vol_after = current_vol_after / daily_volume_mults[curr_date]
            volume_factors[curr_date] = current_vol_after

        # Build AdjustmentFactor records
        factor_records: list[AdjustmentFactor] = []
        for trade_date in dates_list:
            factor_records.append(
                AdjustmentFactor(
                    trade_date=trade_date,
                    pre_close=daily_pre_closes[trade_date],
                    ex_price=daily_ex_prices[trade_date],
                    alpha=daily_alphas[trade_date],
                    qfq_factor=qfq_factors[trade_date],
                    hfq_factor=hfq_factors[trade_date],
                    volume_factor=volume_factors[trade_date],
                    event_ids=daily_event_ids[trade_date],
                )
            )

        return AdjustmentFactorSeries(
            symbol=sym,
            cutoff_date=qfq_cutoff,
            factors=tuple(factor_records),
        )
