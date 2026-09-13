"""Overview composition over the canonical account projection and Operations."""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import datetime

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
        daily_pnl = overview_position_pnl_update(
            [*snapshot.positions, *snapshot.closed_positions]
        )
        # Missing daily attribution does not invalidate the current mark.
        daily_pnl.pop("quote_status", None)
        daily_pnl.pop("stale_reason", None)
        daily_marks = [
            *snapshot.positions,
            *(
                position
                for position in snapshot.closed_positions
                if position.today_change
            ),
        ]
        daily_dates = {
            stamp.date().isoformat() if stamp is not None else None
            for position in daily_marks
            for stamp in [
                parse_quote_timestamp(
                    position.pricing_as_of
                    or position.nav_date
                    or position.quote_timestamp
                )
            ]
        }
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
        attention = build_overview_attention_items(
            operations=operations or {},
            market_evidence_review=build_current_holding_market_evidence_review(
                snapshot
            ),
            trading_plan=(operations or {}).get("daily_plan"),
        )
        account.overview = build_overview_state(
            snapshot,
            market_session=session,
            refresh_health=refresh_health,
            operations=operations,
            user_attention=attention,
        )
        return account
