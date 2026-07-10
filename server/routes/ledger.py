"""Ledger write routes — /api/ledger/*"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

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
    LedgerTradeSettlementCreate,
    LedgerTradeSettlementResponse,
)
from server.services.manual_trade_fees import (
    MANUAL_FEE_INPUT_RULE_ID,
    MANUAL_FEE_INPUT_RULE_VERSION,
    manual_fee_input_payload,
    resolve_manual_trade_fee_breakdown,
)


def _manual_fee_breakdown(fee: float) -> dict[str, str]:
    return manual_fee_input_payload(fee)


def _net_cash_impact(direction: str, gross_amount: float, fee: float) -> float:
    if direction == "buy":
        return -(gross_amount + fee)
    return gross_amount - fee


def _build_trade_entry(body: LedgerTradeCreate, *, config=None) -> LedgerEntry:
    direction = body.direction.strip().lower()
    if direction not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="direction must be buy or sell")

    gross_amount = body.quantity * body.unit_price
    fee_was_provided = "fee" in getattr(body, "model_fields_set", set())
    configured_fee = (
        None
        if fee_was_provided
        else resolve_manual_trade_fee_breakdown(
            config,
            asset_class=body.asset_class,
            direction=direction,
            quantity=body.quantity,
            price=body.unit_price,
            symbol=body.symbol,
        )
    )
    if configured_fee is None:
        commission = body.fee
        total_fee = body.fee
        fee_breakdown = _manual_fee_breakdown(body.fee)
        fee_rule_id = MANUAL_FEE_INPUT_RULE_ID
        fee_rule_version = MANUAL_FEE_INPUT_RULE_VERSION
    else:
        commission = float(configured_fee.commission)
        total_fee = float(configured_fee.total_fee)
        fee_breakdown = configured_fee.fee_breakdown_json
        fee_rule_id = configured_fee.fee_rule_id
        fee_rule_version = configured_fee.fee_rule_version

    return LedgerEntry(
        entry_type=f"trade_{direction}",
        timestamp=body.occurred_at,
        symbol=body.symbol,
        direction=direction,
        quantity=body.quantity,
        price=body.unit_price,
        amount=gross_amount,
        commission=commission,
        gross_amount=gross_amount,
        net_cash_impact=_net_cash_impact(direction, gross_amount, total_fee),
        fee_breakdown=fee_breakdown,
        fee_rule_id=fee_rule_id,
        fee_rule_version=fee_rule_version,
        cost_basis_method="moving_average_buy_cost",
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


def _settled_fee_breakdown(body: LedgerTradeSettlementCreate) -> dict[str, str]:
    components = {
        "commission": Decimal(str(body.commission)),
        "stamp_tax": Decimal(str(body.stamp_tax)),
        "transfer_fee": Decimal(str(body.transfer_fee)),
        "other_fees": Decimal(str(body.other_fees)),
    }
    total_fee = sum(components.values(), Decimal("0"))
    return {
        **{key: format(value, "f") for key, value in components.items()},
        "total_fee": format(total_fee, "f"),
        "confirmation_source": body.source.strip(),
    }


def _cash_adjustment(settled: float, estimated: float | None) -> float | None:
    if estimated is None:
        return None
    return float(Decimal(str(settled)) - Decimal(str(estimated)))


def _validate_trade_settlement(
    entry: LedgerEntry,
    body: LedgerTradeSettlementCreate,
    fee_breakdown: dict[str, str],
) -> None:
    if not body.source.strip() or not body.source_ref.strip():
        raise HTTPException(
            status_code=422,
            detail="broker settlement source and source_ref are required",
        )
    if entry.entry_type not in {"trade_buy", "trade_sell"}:
        raise HTTPException(
            status_code=422,
            detail="only trade ledger entries can receive broker settlement",
        )
    gross_amount = entry.gross_amount
    if gross_amount is None and entry.quantity is not None and entry.price is not None:
        gross_amount = entry.quantity * entry.price
    if gross_amount is None:
        raise HTTPException(
            status_code=422,
            detail="trade gross amount is required before broker settlement",
        )

    gross = Decimal(str(gross_amount))
    total_fee = Decimal(fee_breakdown["total_fee"])
    expected_net = (
        -(gross + total_fee) if entry.entry_type == "trade_buy" else gross - total_fee
    )
    actual_net = Decimal(str(body.net_cash_impact))
    if abs(expected_net - actual_net) > Decimal("0.005"):
        raise HTTPException(
            status_code=422,
            detail=(
                "broker net cash impact does not match gross amount and "
                "settled fee components"
            ),
        )


def _ledger_display_name(db, entry: LedgerEntry) -> str | None:
    if not entry.symbol:
        return None
    get_metadata = getattr(db, "get_instrument_metadata_sync", None)
    if not callable(get_metadata):
        return None
    metadata = get_metadata(entry.symbol, entry.asset_class)
    if not metadata:
        return None
    display_name = str(metadata.get("display_name") or "").strip()
    return display_name or None


def _entry_response(db, entry: LedgerEntry) -> LedgerEntryResponse:
    payload = asdict(entry)
    payload["display_name"] = _ledger_display_name(db, entry)
    return LedgerEntryResponse(**payload)


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/ledger", tags=["ledger"])

    @r.get("/entries", response_model=list[LedgerEntryResponse])
    async def list_entries(
        limit: int = 50, offset: int = 0
    ) -> list[LedgerEntryResponse]:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entries = repo.list_entries(limit=limit, offset=offset)
        return [_entry_response(state.db, entry) for entry in entries]

    @r.post("/trades", response_model=LedgerEntryCreatedResponse)
    async def create_trade_entry(body: LedgerTradeCreate) -> LedgerEntryCreatedResponse:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entry = _build_trade_entry(body, config=getattr(state, "config", None))
        entry_id = repo.insert_entry(entry)
        return LedgerEntryCreatedResponse(id=entry_id, entry_type=entry.entry_type)

    @r.post(
        "/trades/{entry_id}/settlement",
        response_model=LedgerTradeSettlementResponse,
    )
    async def confirm_trade_settlement(
        entry_id: int,
        body: LedgerTradeSettlementCreate,
    ) -> LedgerTradeSettlementResponse:
        from server.app import get_app_state

        state = get_app_state()
        repo = LedgerRepository(state.db)
        entry = repo.get_entry(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="ledger entry not found")

        fee_breakdown = _settled_fee_breakdown(body)
        _validate_trade_settlement(entry, body, fee_breakdown)
        try:
            settled = repo.confirm_trade_settlement(
                entry_id=entry_id,
                commission=body.commission,
                net_cash_impact=body.net_cash_impact,
                fee_breakdown=fee_breakdown,
                settled_at=body.settled_at,
                settlement_source=body.source.strip(),
                settlement_source_ref=body.source_ref.strip(),
                settlement_note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        estimated_net = settled.estimated_net_cash_impact
        return LedgerTradeSettlementResponse(
            id=entry_id,
            entry_type=settled.entry_type,
            settlement_status=settled.settlement_status or "confirmed",
            estimated_net_cash_impact=estimated_net,
            settled_net_cash_impact=settled.net_cash_impact or 0.0,
            cash_adjustment=_cash_adjustment(
                settled.net_cash_impact or 0.0,
                estimated_net,
            ),
            fee_breakdown=settled.fee_breakdown or {},
        )

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
