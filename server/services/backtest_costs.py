"""Resolve ordinary research requests into the existing execution cost models."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from backtest.costs import RESEARCH_SLIPPAGE_BPS, research_friction_assumptions
from backtest.engine import BacktestExecutionConfig
from core.types import GOLD_SPOT_COMMISSION_RATE, CommissionType, OrderSide
from domain.instrument import Instrument
from execution.commission import (
    BondExchangeCommission,
    CommissionCalculator,
    ETFCommission,
    MultiAssetCommission,
    StockACommission,
)
from execution.slippage import PercentSlippage
from server.contracts.http.strategy_models import BacktestCostAssumptions
from server.contracts.reviewed_fee_schedule import ReviewedFeeScheduleRejected
from server.services.reviewed_fee_schedule import resolve_frozen_deployment_fee_schedule


def quote_formula_purchase(
    calculator: CommissionCalculator | None,
    instrument: Instrument,
    symbol: str,
    price: Decimal,
    quantity: Decimal,
    *,
    slippage_bps: Decimal = RESEARCH_SLIPPAGE_BPS,
) -> Decimal | None:
    """Quote complete purchase costs only inside the reviewed size envelope."""
    calculator = calculator or MultiAssetCommission()
    slipped = price * (Decimal(1) + slippage_bps / Decimal(10000))
    try:
        if isinstance(calculator, MultiAssetCommission):
            fee = calculator.breakdown_for(
                instrument.commission_type,
                OrderSide.BUY,
                slipped,
                quantity,
                symbol=symbol,
            ).total_fee
        else:
            fee = calculator.calculate(OrderSide.BUY, slipped, quantity)
    except ReviewedFeeScheduleRejected as exc:
        if str(exc).startswith("reviewed_fee_schedule_notional_envelope_exceeded:"):
            return None
        raise
    return slipped * quantity + fee


def resolve_backtest_costs(
    assumptions: BacktestCostAssumptions | None,
) -> tuple[BacktestExecutionConfig, dict[str, Any]]:
    """Freeze effective defaults as well as overrides; taxes stay model-owned."""
    inputs = assumptions or BacktestCostAssumptions()
    models = {}
    for asset, factory in (("stock", StockACommission), ("etf", ETFCommission)):
        overrides = {
            field: Decimal(str(value))
            for field in ("commission_rate", "min_commission")
            if (value := getattr(inputs, f"{asset}_{field}")) is not None
        }
        models[asset] = (
            factory(**overrides, fee_rule_id=f"cn_{asset}_research_override_v1")
            if overrides
            else factory()
        )
    stock, etf = models["stock"], models["etf"]
    commission = MultiAssetCommission()
    commission.set_commission(CommissionType.STOCK_A, stock)
    commission.set_commission(CommissionType.FUND_ETF, etf)
    slippage_bps = Decimal(str(inputs.slippage_bps))
    participation = Decimal(str(inputs.max_volume_participation))
    bond = BondExchangeCommission()
    effective = {
        "schema_version": "karkinos.backtest_cost_assumptions.v1",
        "source": "research_simulation",
        **research_friction_assumptions(slippage_bps),
        "max_volume_participation": str(participation),
        "stock": {
            **_fee_parameters(stock),
            "sell_stamp_tax_rate": str(stock.stamp_tax_rate),
        },
        "etf": _fee_parameters(etf),
        "bond": {
            "commission_rate": str(bond.commission_rate),
            "min_commission": str(bond.min_commission),
            "other_fee_rate": str(bond.other_fee_rate),
            "fee_rule_id": bond.fee_rule_id,
        },
        "gold": {"commission_rate": str(GOLD_SPOT_COMMISSION_RATE)},
        "limitations": [
            "Research assumptions are not a reviewed broker fee schedule.",
            "Tax and transfer-fee rates use the built-in model, not historical dated schedules.",
            "Slippage and participation are research assumptions, not calibrated execution evidence.",
            "Daily-bar participation caps model partial fills but not intraday order-book liquidity.",
        ],
    }
    return (
        BacktestExecutionConfig(
            commission_calc=commission,
            slippage_model=PercentSlippage(slippage_bps / Decimal("10000")),
            max_volume_participation=participation,
        ),
        effective,
    )


def resolve_paper_book_costs(db, policy, universe):
    """Use the exact reviewed schedule when a deployment reservation bound one."""
    costs, effective = resolve_backtest_costs(
        BacktestCostAssumptions.model_validate(policy["cost_inputs"])
    )
    if binding := policy.get("fee_schedule_binding"):
        reviewed = resolve_frozen_deployment_fee_schedule(db, binding, tuple(universe))
        costs = replace(costs, commission_calc=reviewed.commission_calc)
        effective = {
            **{
                key: value
                for key, value in effective.items()
                if key not in {"stock", "etf", "bond", "gold", "limitations"}
            },
            "source": "reviewed_account_fee_schedule",
            "commission_model_reference": reviewed.cost_model_reference,
            "reviewed_fee_evidence": reviewed.fee_evidence,
            "limitations": [
                "Slippage and participation remain research assumptions, not calibrated execution evidence.",
                "Daily-bar participation caps model partial fills but not intraday order-book liquidity.",
            ],
        }
    return costs, effective


def _fee_parameters(model: StockACommission | ETFCommission) -> dict[str, str]:
    return {
        "commission_rate": str(model.commission_rate),
        "min_commission": str(model.min_commission),
        "transfer_fee_rate": str(model.transfer_fee_rate),
        "other_fee_rate": str(model.other_fee_rate),
        "fee_rule_id": model.fee_rule_id,
    }
