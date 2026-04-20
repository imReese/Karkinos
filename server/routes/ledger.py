"""Ledger write routes — /api/ledger/*"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from server.ledger.models import LedgerEntry
from server.ledger.repository import LedgerRepository
from server.models import (
    LedgerAdjustmentCreate,
    LedgerCashFlowCreate,
    LedgerDividendCreate,
    LedgerEntryCreatedResponse,
    LedgerEntryResponse,
    LedgerTradeCreate,
)


def _build_trade_entry(body: LedgerTradeCreate) -> LedgerEntry:
    direction = body.direction.strip().lower()
    if direction not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="direction must be buy or sell")

    return LedgerEntry(
        entry_type=f"trade_{direction}",
        timestamp=body.occurred_at,
        symbol=body.symbol,
        direction=direction,
        quantity=body.quantity,
        price=body.unit_price,
        amount=body.quantity * body.unit_price,
        commission=body.fee,
        asset_class=body.asset_class,
        note=body.note,
        source=body.source,
        source_ref=body.source_ref,
    )


def _build_cash_flow_entry(body: LedgerCashFlowCreate) -> LedgerEntry:
    flow_type = body.flow_type.strip().lower()
    if flow_type == "deposit":
        entry_type = "cash_deposit"
    elif flow_type == "withdrawal":
        entry_type = "cash_withdrawal"
    else:
        raise HTTPException(
            status_code=400, detail="flow_type must be deposit or withdrawal"
        )

    return LedgerEntry(
        entry_type=entry_type,
        timestamp=body.occurred_at,
        amount=body.amount,
        note=body.note,
        source=body.source,
        source_ref=body.source_ref,
    )


def _build_dividend_entry(body: LedgerDividendCreate) -> LedgerEntry:
    return LedgerEntry(
        entry_type="dividend",
        timestamp=body.occurred_at,
        amount=body.amount,
        symbol=body.symbol,
        asset_class=body.asset_class,
        note=body.note,
        source=body.source,
        source_ref=body.source_ref,
    )


def _build_adjustment_entry(body: LedgerAdjustmentCreate) -> LedgerEntry:
    if body.amount is None and body.quantity is None:
        raise HTTPException(
            status_code=400, detail="amount or quantity must be provided"
        )

    return LedgerEntry(
        entry_type="manual_adjustment",
        timestamp=body.occurred_at,
        amount=body.amount,
        symbol=body.symbol,
        quantity=body.quantity,
        price=body.price,
        asset_class=body.asset_class,
        note=body.note,
        source=body.source,
        source_ref=body.source_ref,
    )


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/ledger", tags=["ledger"])

    @r.get("/entries", response_model=list[LedgerEntryResponse])
    async def list_entries(limit: int = 50, offset: int = 0) -> list[LedgerEntryResponse]:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entries = repo.list_entries(limit=limit, offset=offset)
        return [LedgerEntryResponse(**asdict(entry)) for entry in entries]

    @r.post("/trades", response_model=LedgerEntryCreatedResponse)
    async def create_trade_entry(body: LedgerTradeCreate) -> LedgerEntryCreatedResponse:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entry = _build_trade_entry(body)
        entry_id = repo.insert_entry(entry)
        return LedgerEntryCreatedResponse(id=entry_id, entry_type=entry.entry_type)

    @r.post("/cash-flows", response_model=LedgerEntryCreatedResponse)
    async def create_cash_flow_entry(
        body: LedgerCashFlowCreate,
    ) -> LedgerEntryCreatedResponse:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entry = _build_cash_flow_entry(body)
        entry_id = repo.insert_entry(entry)
        return LedgerEntryCreatedResponse(id=entry_id, entry_type=entry.entry_type)

    @r.post("/dividends", response_model=LedgerEntryCreatedResponse)
    async def create_dividend_entry(
        body: LedgerDividendCreate,
    ) -> LedgerEntryCreatedResponse:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entry = _build_dividend_entry(body)
        entry_id = repo.insert_entry(entry)
        return LedgerEntryCreatedResponse(id=entry_id, entry_type=entry.entry_type)

    @r.post("/adjustments", response_model=LedgerEntryCreatedResponse)
    async def create_adjustment_entry(
        body: LedgerAdjustmentCreate,
    ) -> LedgerEntryCreatedResponse:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entry = _build_adjustment_entry(body)
        entry_id = repo.insert_entry(entry)
        return LedgerEntryCreatedResponse(id=entry_id, entry_type=entry.entry_type)

    return r
