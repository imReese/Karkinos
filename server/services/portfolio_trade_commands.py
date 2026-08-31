"""Typed application commands for manual and pending-fund portfolio trades."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Protocol

from server.contracts.portfolio_trades import (
    ManualTradeCorrectionResult,
    ManualTradeCorrectionWrite,
    ManualTradeWrite,
    ManualTradeWriteResult,
    PendingFundConfirmationResult,
    PendingFundConfirmationWrite,
    PendingFundOrderWrite,
    PendingFundOrderWriteResult,
)
from server.services.asset_metadata import resolve_asset_metadata
from server.services.manual_trade_fees import (
    MANUAL_FEE_INPUT_RULE_ID,
    MANUAL_FEE_INPUT_RULE_VERSION,
    manual_fee_input_payload,
    resolve_manual_trade_fee_breakdown,
)
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

logger = logging.getLogger(__name__)

_FUND_SUBSCRIPTION_CUTOFF = time(15, 0)


class PortfolioTradeDatabase(Protocol):
    def record_manual_trade_sync(
        self, command: ManualTradeWrite
    ) -> ManualTradeWriteResult: ...

    def correct_manual_trade_sync(
        self, command: ManualTradeCorrectionWrite
    ) -> ManualTradeCorrectionResult: ...

    def create_pending_fund_order_sync(
        self, command: PendingFundOrderWrite
    ) -> PendingFundOrderWriteResult: ...

    def confirm_pending_fund_order_sync(
        self, command: PendingFundConfirmationWrite
    ) -> PendingFundConfirmationResult: ...


class RuntimePortfolioInstaller(Protocol):
    @property
    def is_running(self) -> bool: ...

    @property
    def latest_quotes(self) -> dict[str, dict[str, Any]]: ...

    def install_runtime_portfolio(self, portfolio: Any) -> None: ...


class PortfolioTradeState(Protocol):
    config: Any
    db: PortfolioTradeDatabase
    scheduler: RuntimePortfolioInstaller | None


@dataclass(frozen=True, slots=True)
class ManualTradeRequest:
    command_id: str
    operator_id: str
    timestamp: str
    symbol: str
    direction: str
    quantity: float | None = None
    price: float | None = None
    amount: float | None = None
    commission: float | None = None
    asset_class: str = "stock"
    note: str = ""


@dataclass(frozen=True, slots=True)
class CreatedManualTrade:
    trade: dict[str, object]
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CreatedPendingFundOrder:
    order: dict[str, object]
    detail: str
    replayed: bool = False


class PortfolioTradeCommandService:
    """Prepare one command and delegate every mutation to an explicit UoW."""

    def __init__(self, state: PortfolioTradeState) -> None:
        if state.db is None:
            raise RuntimeError("application database is not initialized")
        if state.config is None:
            raise RuntimeError("runtime configuration is not initialized")
        self._state = state
        self._db = state.db

    def create(
        self,
        request: ManualTradeRequest,
    ) -> CreatedManualTrade | CreatedPendingFundOrder:
        """Persist a manual trade or a restart-stable pending fund intent."""

        symbol = request.symbol.strip()
        if not symbol:
            raise ValueError("symbol is required")
        if request.direction not in {"buy", "sell"}:
            raise ValueError("direction must be buy or sell")

        quantity = request.quantity
        price = request.price
        note = request.note
        commission = request.commission
        display_name: str | None = None

        if (
            request.asset_class == "fund"
            and request.direction == "buy"
            and request.amount is not None
        ):
            display_name = resolve_display_name(self._state, symbol, fallback=symbol)
            pending = self._db.create_pending_fund_order_sync(
                PendingFundOrderWrite(
                    command_id=request.command_id,
                    operator_id=request.operator_id,
                    submitted_at=request.timestamp,
                    symbol=symbol,
                    display_name=display_name,
                    amount=float(request.amount),
                    commission=float(commission or 0.0),
                    asset_class="fund",
                    target_trade_date=fund_target_trade_date(request.timestamp),
                    note=request.note,
                )
            )
            return CreatedPendingFundOrder(
                order=pending.order,
                detail=(
                    "Fund subscription is pending explicit confirmation against a "
                    "persisted confirmed-NAV ingestion run."
                ),
                replayed=pending.replayed,
            )
        elif quantity is None or price is None:
            raise ValueError(
                "quantity and price are required unless this is a fund buy with amount"
            )

        display_name = display_name or resolve_display_name(
            self._state,
            symbol,
            fallback=symbol,
        )
        write = _manual_trade_write(
            self._state.config,
            request=request,
            symbol=symbol,
            display_name=display_name,
            quantity=float(quantity),
            price=float(price),
            commission=commission,
            note=note,
        )
        result = self._db.record_manual_trade_sync(write)
        self._refresh_runtime_projection()
        return CreatedManualTrade(trade=result.trade, replayed=result.replayed)

    def correct(
        self,
        *,
        trade_id: int,
        command_id: str,
        operator_id: str,
    ) -> ManualTradeCorrectionResult:
        """Append one correction and refresh only the runtime projection."""

        result = self._db.correct_manual_trade_sync(
            ManualTradeCorrectionWrite(
                command_id=command_id,
                operator_id=operator_id,
                trade_id=trade_id,
            )
        )
        self._refresh_runtime_projection()
        return result

    def confirm_pending(
        self,
        *,
        order_id: int,
        command_id: str,
        operator_id: str,
        evidence_fetch_run_id: str,
        confirmation_note: str = "",
    ) -> PendingFundConfirmationResult:
        """Confirm only from persisted NAV evidence explicitly chosen by a human."""

        result = self._db.confirm_pending_fund_order_sync(
            PendingFundConfirmationWrite(
                command_id=command_id,
                operator_id=operator_id,
                order_id=order_id,
                evidence_fetch_run_id=evidence_fetch_run_id,
                confirmation_note=confirmation_note,
            )
        )
        self._refresh_runtime_projection()
        return result

    def _refresh_runtime_projection(self) -> None:
        scheduler = self._state.scheduler
        if scheduler is None or not scheduler.is_running:
            return
        try:
            rebuilt = rebuild_portfolio_from_ledger(
                self._state.config,
                self._db,
                scheduler.latest_quotes,
            )
            scheduler.install_runtime_portfolio(rebuilt.portfolio)
        except Exception:
            logger.exception(
                "Canonical trade committed but runtime portfolio refresh failed"
            )


def resolve_display_name(state: Any, symbol: str, fallback: str | None = None) -> str:
    return resolve_asset_metadata(
        state,
        symbol,
        fallback_name=fallback,
    ).display_name


def fund_target_trade_date(timestamp: str) -> str:
    submitted_at = datetime.fromisoformat(timestamp)
    target_date = submitted_at.date()
    if submitted_at.time() >= _FUND_SUBSCRIPTION_CUTOFF:
        target_date += timedelta(days=1)
    return target_date.isoformat()


def _manual_trade_write(
    config: Any,
    *,
    request: ManualTradeRequest,
    symbol: str,
    display_name: str,
    quantity: float,
    price: float,
    commission: float | None,
    note: str,
) -> ManualTradeWrite:
    configured_fee = None
    if commission is None:
        configured_fee = resolve_manual_trade_fee_breakdown(
            config,
            asset_class=request.asset_class,
            direction=request.direction,
            quantity=quantity,
            price=price,
            symbol=symbol,
        )
        if configured_fee is None:
            commission = 0.0
        else:
            commission = configured_fee.commission
            if not note.strip():
                note = configured_fee.note
    gross_amount = quantity * price
    total_fee = (
        configured_fee.total_fee if configured_fee is not None else float(commission)
    )
    fee_breakdown = (
        configured_fee.fee_breakdown_json
        if configured_fee is not None
        else manual_fee_input_payload(commission)
    )
    return ManualTradeWrite(
        command_id=request.command_id,
        operator_id=request.operator_id,
        timestamp=request.timestamp,
        symbol=symbol,
        display_name=display_name,
        direction=request.direction,
        quantity=quantity,
        price=price,
        commission=float(commission),
        gross_amount=gross_amount,
        net_cash_impact=(
            -(gross_amount + total_fee)
            if request.direction == "buy"
            else gross_amount - total_fee
        ),
        fee_breakdown_json=json.dumps(
            fee_breakdown,
            ensure_ascii=False,
            sort_keys=True,
        ),
        fee_rule_id=(
            configured_fee.fee_rule_id
            if configured_fee is not None
            else MANUAL_FEE_INPUT_RULE_ID
        ),
        fee_rule_version=(
            configured_fee.fee_rule_version
            if configured_fee is not None
            else MANUAL_FEE_INPUT_RULE_VERSION
        ),
        asset_class=request.asset_class,
        note=note,
    )


__all__ = [
    "CreatedManualTrade",
    "CreatedPendingFundOrder",
    "ManualTradeRequest",
    "PortfolioTradeCommandService",
    "fund_target_trade_date",
    "resolve_display_name",
]
