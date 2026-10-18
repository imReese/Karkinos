"""Overview composition over the canonical account projection and Operations."""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import datetime

from server.contracts.http.ledger_models import EquitySeriesPoint
from server.contracts.http.portfolio_models import (
    AccountStateResponse,
    OverviewRefreshHealth,
    PortfolioSnapshot,
)
from server.dependencies import (
    bind_portfolio_read_request_state,
    get_portfolio_read_request_state,
)
from server.projections.portfolio_application import build_account_state_response
from server.projections.portfolio_views.historical_ledger_series import (
    build_daily_equity_series_from_ledger_history,
)
from server.projections.portfolio_views.historical_series import (
    historical_performance_from_series,
)
from server.projections.portfolio_views.intraday_series import (
    append_current_equity_series_point,
)
from server.projections.portfolio_views.overview import overview_position_pnl_update
from server.projections.quote_status import parse_quote_timestamp
from server.services.account_state import (
    build_overview_state,
    read_overview_refresh_health,
)
from server.services.current_holding_market_evidence_review import (
    build_current_holding_market_evidence_review,
)
from server.services.market_calendar_dates import project_market_session
from server.services.market_hours import get_shanghai_now
from server.services.operations_projection import build_today_operations_payload
from server.services.operations_today import build_overview_attention_items
from server.services.risk_workspace import build_risk_workspace


async def build_overview_account_state_response(
    state,
    *,
    snapshot: PortfolioSnapshot | None = None,
    now: datetime | None = None,
) -> AccountStateResponse:
    frozen_now = get_shanghai_now(now)
    scope = (
        bind_portfolio_read_request_state()
        if get_portfolio_read_request_state() is None
        else nullcontext()
    )
    with scope:
        account = await build_account_state_response(
            state, snapshot=snapshot, now=frozen_now
        )
        snapshot = account.snapshot
        session = project_market_session(getattr(state, "db", None), frozen_now)
        open_dates = {_performance_date(position) for position in snapshot.positions}
        session_date = (
            next(iter(open_dates))
            if len(open_dates) == 1 and None not in open_dates
            else session.get("expected_quote_date")
        )
        daily_positions = [
            *snapshot.positions,
            *(
                position
                for position in snapshot.closed_positions
                if session_date is not None
                and (
                    _date(position.closed_at) == session_date
                    or (
                        position.today_change
                        and _performance_date(position) == session_date
                    )
                )
            ),
        ]
        daily_pnl = overview_position_pnl_update(daily_positions)
        # Missing daily attribution does not invalidate the current mark.
        daily_pnl.pop("quote_status", None)
        daily_pnl.pop("stale_reason", None)
        daily_dates = {_performance_date(position) for position in daily_positions}
        latest_session_date = session.get("expected_quote_date")
        if daily_dates:
            latest_session_date = (
                next(iter(daily_dates)) if len(daily_dates) == 1 else None
            )
            if len(daily_dates) != 1 or latest_session_date is None:
                daily_pnl.update(
                    today_pnl=None, today_pnl_breakdown=None, today_contributors=[]
                )
        account.summary = account.summary.model_copy(
            update={
                **daily_pnl,
                "latest_session_date": latest_session_date,
            }
        )
        try:
            drawdown_update = await asyncio.to_thread(
                _overview_drawdown_update, state, snapshot, frozen_now
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Overview performance history unavailable", exc_info=True
            )
            drawdown_update = {"drawdown_blockers": ["drawdown_history_unavailable"]}
        account.summary = account.summary.model_copy(update=drawdown_update)
        operations = None
        try:
            operations = await build_today_operations_payload(state)
        except Exception:
            logging.getLogger(__name__).warning(
                "Overview attention projection unavailable", exc_info=True
            )
        try:
            refresh_health = await asyncio.to_thread(
                read_overview_refresh_health, getattr(state, "db", None)
            )
        except Exception:
            refresh_health = OverviewRefreshHealth(
                status="unknown", blockers=["refresh_history_unavailable"]
            )
        attention_available = operations is not None
        try:
            attention = build_overview_attention_items(
                operations=operations or {},
                market_evidence_review=build_current_holding_market_evidence_review(
                    snapshot
                ),
                trading_plan=(operations or {}).get("daily_plan"),
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Overview attention items unavailable", exc_info=True
            )
            attention = []
            attention_available = False
        account.overview = build_overview_state(
            snapshot,
            market_session=session,
            refresh_health=refresh_health,
            operations=operations,
            user_attention=attention,
        )
        if not attention_available:
            account.overview.attention_status = "unavailable"
        return account


def _date(value: str | None) -> str | None:
    parsed = parse_quote_timestamp(value)
    return parsed.date().isoformat() if parsed is not None else None


def _performance_date(position) -> str | None:
    return _date(
        position.performance_session_date
        or position.pricing_as_of
        or position.nav_date
        or position.quote_timestamp
    )


def _overview_drawdown_update(
    state, snapshot: PortfolioSnapshot, now: datetime
) -> dict:
    current = EquitySeriesPoint(
        timestamp=snapshot.valuation_as_of or now.isoformat(),
        total=snapshot.total_equity,
        cash=snapshot.cash,
        stocks=None,
        funds=None,
        others=None,
        valuation_snapshot_id=snapshot.valuation_snapshot_id,
        valuation_status=snapshot.valuation_status,
        missing_price_symbols=snapshot.missing_price_symbols,
    )
    points = build_daily_equity_series_from_ledger_history(
        state, selected_range="all", current_point=current, now=now
    )
    history = historical_performance_from_series(
        state,
        append_current_equity_series_point(points, current),
        valuation_snapshot_id=snapshot.valuation_snapshot_id,
    )
    risk = build_risk_workspace(
        snapshot, history.equity_curve, historical_blockers=history.blockers
    )
    drawdown = risk.drawdown
    return {
        "current_drawdown": None if drawdown is None else drawdown.current_drawdown,
        "current_drawdown_amount": (
            None
            if drawdown is None
            else max(drawdown.peak_equity - drawdown.latest_equity, 0.0)
        ),
        "drawdown_peak_equity": None if drawdown is None else drawdown.peak_equity,
        "drawdown_latest_equity": None if drawdown is None else drawdown.latest_equity,
        "drawdown_peak_timestamp": None
        if drawdown is None
        else drawdown.peak_timestamp,
        "drawdown_blockers": risk.blockers,
    }
