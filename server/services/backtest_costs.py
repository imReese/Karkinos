"""Resolve ordinary research requests into the existing execution cost models."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from backtest.engine import BacktestExecutionConfig
from core.types import GOLD_SPOT_COMMISSION_RATE, CommissionType
from execution.commission import (
    BondExchangeCommission,
    ETFCommission,
    MultiAssetCommission,
    StockACommission,
)
from execution.slippage import PercentSlippage
from server.contracts.http.strategy_models import BacktestCostAssumptions


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
    bond = BondExchangeCommission()
    effective = {
        "schema_version": "karkinos.backtest_cost_assumptions.v1",
        "source": "research_simulation",
        "slippage_model": "percent_of_reference_price",
        "slippage_bps": str(slippage_bps),
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
            "Fixed proportional slippage does not model market impact or partial fills.",
        ],
    }
    return (
        BacktestExecutionConfig(
            commission_calc=commission,
            slippage_model=PercentSlippage(slippage_bps / Decimal("10000")),
        ),
        effective,
    )


def _fee_parameters(model: StockACommission | ETFCommission) -> dict[str, str]:
    return {
        "commission_rate": str(model.commission_rate),
        "min_commission": str(model.min_commission),
        "transfer_fee_rate": str(model.transfer_fee_rate),
        "other_fee_rate": str(model.other_fee_rate),
        "fee_rule_id": model.fee_rule_id,
    }
