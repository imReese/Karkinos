"""Portfolio trades HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    Decimal = dependency("Decimal")
    HTTPException = dependency("HTTPException")
    MANUAL_FEE_INPUT_RULE_ID = dependency("MANUAL_FEE_INPUT_RULE_ID")
    MANUAL_FEE_INPUT_RULE_VERSION = dependency("MANUAL_FEE_INPUT_RULE_VERSION")
    PendingFundOrderResponse = dependency("PendingFundOrderResponse")
    Symbol = dependency("Symbol")
    TradeCreate = dependency("TradeCreate")
    TradeResponse = dependency("TradeResponse")
    _ensure_asset_config = dependency("_ensure_asset_config")
    _fund_target_trade_date = dependency("_fund_target_trade_date")
    _manual_trade_fee_breakdown = dependency("_manual_trade_fee_breakdown")
    _manual_trade_net_cash_impact = dependency("_manual_trade_net_cash_impact")
    _resolve_display_name = dependency("_resolve_display_name")
    _resolve_fund_buy_fill = dependency("_resolve_fund_buy_fill")
    _resolve_fund_identity = dependency("_resolve_fund_identity")
    json = dependency("json")
    resolve_manual_trade_fee_breakdown = dependency(
        "resolve_manual_trade_fee_breakdown"
    )

    @r.post("/trade", response_model=TradeResponse)
    async def create_trade(body: TradeCreate) -> TradeResponse:
        """记录手动交易，同步更新 Portfolio 持仓。"""
        import uuid
        from datetime import datetime as dt

        from core.events import FillEvent
        from core.types import OrderSide, Symbol
        from server.dependencies import get_app_state

        state = get_app_state()
        db = state.db

        symbol = body.symbol.strip()
        quantity = body.quantity
        price = body.price
        note = body.note
        commission = body.commission
        configured_fee = None

        if (
            body.asset_class == "fund"
            and body.direction == "buy"
            and body.amount is not None
        ):
            try:
                resolved = _resolve_fund_buy_fill(
                    state,
                    symbol=symbol,
                    timestamp=body.timestamp,
                    gross_amount=body.amount,
                    commission=commission or 0.0,
                )
            except LookupError as exc:
                from fastapi.responses import JSONResponse

                identity = _resolve_fund_identity(state, symbol)
                _ensure_asset_config(
                    state,
                    symbol=identity["symbol"],
                    asset_class=body.asset_class,
                    display_name=identity["display_name"],
                )
                pending_id = db.add_pending_fund_order_sync(
                    submitted_at=body.timestamp,
                    symbol=identity["symbol"],
                    display_name=identity["display_name"],
                    amount=body.amount,
                    commission=commission or 0.0,
                    asset_class=body.asset_class,
                    target_trade_date=_fund_target_trade_date(body.timestamp),
                    note=body.note,
                )
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "pending",
                        "id": pending_id,
                        "symbol": identity["symbol"],
                        "display_name": identity["display_name"],
                        "amount": body.amount,
                        "commission": commission or 0.0,
                        "asset_class": body.asset_class,
                        "target_trade_date": _fund_target_trade_date(body.timestamp),
                        "detail": str(exc),
                    },
                )
            except ValueError as exc:
                from fastapi import HTTPException

                raise HTTPException(status_code=400, detail=str(exc)) from exc

            symbol = resolved["symbol"]
            quantity = resolved["quantity"]
            price = resolved["price"]
            fund_note_parts = [
                body.note.strip() if body.note.strip() else "",
                f"Auto-confirmed fund subscription: gross_amount={resolved['gross_amount']:.2f}",
                f"confirmed_trade_date={resolved['confirmed_trade_date']}",
                f"confirmed_nav={resolved['price']:.6f}",
            ]
            note = " | ".join(part for part in fund_note_parts if part)
            _ensure_asset_config(
                state,
                symbol=symbol,
                asset_class=body.asset_class,
                display_name=resolved["display_name"],
            )
        elif quantity is None or price is None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="quantity and price are required unless this is a fund buy with amount",
            )

        _ensure_asset_config(
            state,
            symbol=symbol,
            asset_class=body.asset_class,
            display_name=_resolve_display_name(state, symbol, fallback=symbol),
        )

        if commission is None:
            configured_fee = resolve_manual_trade_fee_breakdown(
                state.config,
                asset_class=body.asset_class,
                direction=body.direction,
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

        gross_amount = float(quantity) * float(price)
        total_fee = (
            configured_fee.total_fee
            if configured_fee is not None
            else float(commission)
        )
        fee_breakdown_json = (
            configured_fee.fee_breakdown_json
            if configured_fee is not None
            else _manual_trade_fee_breakdown(commission)
        )
        fee_rule_id = (
            configured_fee.fee_rule_id
            if configured_fee is not None
            else MANUAL_FEE_INPUT_RULE_ID
        )
        fee_rule_version = (
            configured_fee.fee_rule_version
            if configured_fee is not None
            else MANUAL_FEE_INPUT_RULE_VERSION
        )

        trade_id = await db.add_trade(
            timestamp=body.timestamp,
            symbol=symbol,
            direction=body.direction,
            quantity=quantity,
            price=price,
            commission=commission,
            asset_class=body.asset_class,
            note=note,
        )
        db.insert_ledger_entry_sync(
            entry_type=f"trade_{body.direction}",
            timestamp=body.timestamp,
            amount=gross_amount,
            symbol=symbol,
            direction=body.direction,
            quantity=float(quantity),
            price=float(price),
            commission=commission,
            gross_amount=gross_amount,
            net_cash_impact=_manual_trade_net_cash_impact(
                direction=body.direction,
                gross_amount=gross_amount,
                total_fee=total_fee,
            ),
            fee_breakdown_json=json.dumps(
                fee_breakdown_json,
                ensure_ascii=False,
                sort_keys=True,
            ),
            fee_rule_id=fee_rule_id,
            fee_rule_version=fee_rule_version,
            cost_basis_method="moving_average_buy_cost",
            asset_class=body.asset_class,
            note=note,
            source="portfolio_trade",
            source_ref=f"trade:{trade_id}",
        )

        # If live is running, synthesize FillEvent to update portfolio
        scheduler = state.scheduler
        if scheduler and scheduler.is_running:
            with scheduler._lock:
                portfolio = scheduler._portfolio
                if portfolio is not None:
                    side = OrderSide.BUY if body.direction == "buy" else OrderSide.SELL
                    fill = FillEvent(
                        timestamp=(
                            dt.fromisoformat(body.timestamp)
                            if isinstance(body.timestamp, str)
                            else body.timestamp
                        ),
                        fill_id=f"MANUAL-{uuid.uuid4().hex[:8]}",
                        order_id=f"MANUAL-ORD-{uuid.uuid4().hex[:8]}",
                        symbol=Symbol(symbol),
                        side=side,
                        fill_price=Decimal(str(price)),
                        fill_quantity=Decimal(str(quantity)),
                        commission=Decimal(str(total_fee)),
                        slippage=Decimal("0"),
                        fee_breakdown=fee_breakdown_json,
                        fee_rule_id=fee_rule_id,
                        fee_rule_version=fee_rule_version,
                    )
                    portfolio.on_fill(fill)

        trades = await db.get_trades(limit=1)
        return TradeResponse(**trades[0])

    @r.get("/trades", response_model=list[TradeResponse])
    async def list_trades(limit: int = 50, offset: int = 0) -> list[TradeResponse]:
        """列出交易记录。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        trades = await state.db.get_trades(limit, offset)
        return [TradeResponse(**t) for t in trades]

    @r.get("/pending-fund-orders", response_model=list[PendingFundOrderResponse])
    async def list_pending_fund_orders() -> list[PendingFundOrderResponse]:
        """列出等待确认净值的基金申购。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "get_pending_fund_orders_sync"):
            return []
        rows = state.db.get_pending_fund_orders_sync(status="pending")
        return [PendingFundOrderResponse(**row) for row in rows]

    @r.delete("/trade/{trade_id}")
    async def delete_trade(trade_id: int) -> dict:
        """删除交易记录。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        deleted = await state.db.delete_trade(trade_id)
        return {"deleted": deleted}

    return r
