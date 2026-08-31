"""Canonical backtest risk preview projections."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from core.events import OrderIntentEvent
from core.types import AssetClass, OrderSide, Symbol
from server.contracts.http.backtest import (
    BacktestPaperShadowPreviewRequest,
    BacktestRiskPreviewRequest,
)
from server.services.backtest_views.strategy_inputs import (
    signal_preview_symbol_asset_class,
)


def run_backtest_risk_preview(
    request: BacktestRiskPreviewRequest,
    state: Any,
) -> dict[str, Any]:
    """Evaluate a signal candidate through pre-trade risk without side effects."""
    from risk.pre_trade import PreTradePolicy, preview_pre_trade_risk
    from server.services.live_context import LiveContextProvider
    from server.services.trading_controls import TradingControlState

    side = risk_preview_order_side(request.action)
    if side is None:
        raise HTTPException(
            status_code=422,
            detail={
                "action": request.action,
                "errors": [
                    {
                        "field": "action",
                        "code": "unsupported_risk_preview_action",
                        "message": "Risk preview currently supports buy or sell actions.",
                    }
                ],
            },
        )

    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler is not None else None
    controls = getattr(state, "trading_controls", None) or TradingControlState()
    context = LiveContextProvider(
        portfolio_getter=lambda: portfolio,
        controls=controls,
    ).snapshot()
    _, asset_class = signal_preview_symbol_asset_class(
        request.symbol,
        request.asset_class,
    )
    intent = OrderIntentEvent(
        timestamp=datetime.now(timezone.utc),
        intent_id="BACKTEST-RISK-PREVIEW",
        strategy_id=request.strategy,
        symbol=Symbol(request.symbol),
        side=side,
        target_weight=request.target_weight,
        quantity=request.quantity,
        reference_price=request.reference_price,
        asset_class=asset_class,
        reason="backtest_signal_preview_risk_check",
        metadata={
            "source": "backtest_signal_preview",
            "data_quality_issues": risk_preview_data_quality_issues(
                request.data_quality_status
            ),
        },
    )
    return preview_pre_trade_risk(
        intent=intent,
        context=context,
        policy=PreTradePolicy(execution_mode="manual"),
    )


def risk_preview_order_side(action: str) -> OrderSide | None:
    if action == "buy":
        return OrderSide.BUY
    if action == "sell":
        return OrderSide.SELL
    return None


def risk_preview_data_quality_issues(status: str) -> list[str]:
    normalized = status.lower()
    if normalized in {"pass", "ok", "complete", "confirmed", "live"}:
        return []
    return [f"preview data quality: {status}"]


def run_backtest_paper_shadow_preview(
    request: BacktestPaperShadowPreviewRequest,
    state: Any,
) -> dict[str, Any]:
    """Simulate a paper/shadow outcome without storing orders or fills."""
    from analytics.shadow_review import (
        PaperOutcomeEvidence,
        StrategyCandidateEvidence,
        build_shadow_review_report,
    )
    from core.types import OrderType
    from execution.paper_broker import (
        PaperBroker,
        PaperOrderContext,
        PaperOrderRequest,
    )

    side = risk_preview_order_side(request.action)
    if side is None:
        raise HTTPException(
            status_code=422,
            detail={
                "action": request.action,
                "errors": [
                    {
                        "field": "action",
                        "code": "unsupported_paper_shadow_preview_action",
                        "message": "Paper/shadow preview currently supports buy or sell actions.",
                    }
                ],
            },
        )

    if not request.risk_preview_passed:
        return {
            "schema_version": "karkinos.paper_shadow_preview.v1",
            "status": "blocked_by_risk",
            "execution_mode": "paper_shadow_preview",
            "manual_confirmation_required": True,
            "does_not_create_order": True,
            "does_not_create_fill": True,
            "does_not_mutate_ledger": True,
            "risk_reasons": request.risk_reasons,
            "order": None,
            "fill": None,
            "shadow_review": None,
            "limitations": [
                "Paper/shadow preview waits for a passing read-only risk preview.",
                "This preview does not mutate ledger entries or submit broker orders.",
            ],
        }

    _, asset_class = signal_preview_symbol_asset_class(
        request.symbol,
        request.asset_class,
    )
    order_id = (
        "paper-shadow-preview:"
        f"{request.strategy}:{request.symbol}:{request.action}:"
        f"{request.quantity}:{request.reference_price}"
    )
    context = PaperOrderContext(
        strategy_id=request.strategy,
        signal_id=request.signal_id,
        dataset_id=request.dataset_snapshot_id,
        cost_model_id="paper_shadow_preview_after_cost",
    )
    broker = PaperBroker(
        db=None,
        provider_name="paper-shadow-preview",
        commission_calc=paper_shadow_commission_calculator(asset_class),
    )
    result = broker.submit_order(
        PaperOrderRequest(
            timestamp=datetime.now(timezone.utc),
            order_id=order_id,
            symbol=Symbol(request.symbol),
            side=side,
            order_type=OrderType.MARKET,
            quantity=request.quantity,
            price=request.reference_price,
            asset_class=asset_class,
            context=context,
        ),
        fill_id=f"{order_id}:fill:1",
        fill_quantity=request.quantity,
        fill_price=request.reference_price,
    )
    order_payload = paper_shadow_payload(result.order.to_payload())
    fill_payload = (
        paper_shadow_payload(result.fill.to_payload())
        if result.fill is not None
        else None
    )
    paper_outcome = PaperOutcomeEvidence(
        candidate_id=request.signal_id or order_id,
        order_id=order_id,
        strategy_id=request.strategy,
        symbol=request.symbol,
        side=side.value,
        status=order_payload["status"],
        filled_quantity=request.quantity,
        average_fill_price=request.reference_price,
        commission=(
            result.fill.commission if result.fill is not None else Decimal("0")
        ),
        slippage=result.fill.slippage if result.fill is not None else Decimal("0"),
        fill_id=result.fill.fill_id if result.fill is not None else None,
    )
    shadow_review = build_shadow_review_report(
        candidates=[
            StrategyCandidateEvidence(
                candidate_id=request.signal_id or order_id,
                strategy_id=request.strategy,
                symbol=request.symbol,
                action=request.action,
                quantity=request.quantity,
                reference_price=request.reference_price,
                signal_id=request.signal_id,
            )
        ],
        paper_outcomes=[paper_outcome],
        real_movements=[],
    )
    return {
        "schema_version": "karkinos.paper_shadow_preview.v1",
        "status": "simulated",
        "execution_mode": "paper_shadow_preview",
        "manual_confirmation_required": True,
        "does_not_create_order": True,
        "does_not_create_fill": True,
        "does_not_mutate_ledger": True,
        "risk_reasons": request.risk_reasons,
        "order": order_payload,
        "fill": fill_payload,
        "shadow_review": shadow_review.to_json_dict(),
        "limitations": [
            "Paper/shadow preview is simulation evidence, not investment advice.",
            "This preview does not mutate ledger entries or submit broker orders.",
        ],
    }


def paper_shadow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "execution_mode": "paper_shadow_preview",
        "source": "backtest_paper_shadow_preview",
        "does_not_mutate_production_ledger": True,
    }


def paper_shadow_commission_calculator(asset_class: AssetClass):
    from execution.commission import (
        BondExchangeCommission,
        ETFCommission,
        GoldSpotCommission,
        StockACommission,
    )

    if asset_class == AssetClass.FUND:
        return ETFCommission()
    if asset_class == AssetClass.GOLD:
        return GoldSpotCommission()
    if asset_class == AssetClass.BOND:
        return BondExchangeCommission()
    return StockACommission()


__all__ = (
    "paper_shadow_commission_calculator",
    "paper_shadow_payload",
    "risk_preview_data_quality_issues",
    "risk_preview_order_side",
    "run_backtest_paper_shadow_preview",
    "run_backtest_risk_preview",
)
