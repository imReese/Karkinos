"""Shared manual trade fee contract for ledger-producing routes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.types import OrderSide
from execution.commission import (
    BondExchangeCommission,
    ETFCommission,
    FeeBreakdown,
    StockACommission,
)

MANUAL_CONFIGURED_FEE_RULE_ID = "manual_configured_commission"
MANUAL_CONFIGURED_FEE_RULE_VERSION = "account_commission_rate"
MANUAL_FEE_INPUT_RULE_ID = "manual_fee_input"
MANUAL_FEE_INPUT_RULE_VERSION = "manual_fee_input"


@dataclass(frozen=True)
class ManualTradeFeeResult:
    """Structured fee result ready for ledger storage."""

    commission: float
    total_fee: float
    fee_breakdown_json: dict[str, str]
    fee_rule_id: str
    fee_rule_version: str
    note: str


def resolve_manual_trade_fee_breakdown(
    config,
    *,
    asset_class: str,
    direction: str,
    quantity: float | None,
    price: float | None,
    symbol: str | None = None,
) -> ManualTradeFeeResult | None:
    """Resolve configured stock/ETF manual-trade fee assumptions."""
    if config is None or quantity is None or price is None:
        return None

    normalized_asset_class = asset_class.strip().lower().replace("-", "_")
    normalized_direction = direction.strip().lower()
    if normalized_asset_class not in {"stock", "etf", "bond", "convertible_bond"}:
        return None
    if normalized_direction not in {"buy", "sell"}:
        return None

    rate = _decimal_config_value(config, "account_commission_rate", "0.0001")
    min_commission = _decimal_config_value(config, "account_min_commission", "5")
    schedule = getattr(config, "broker_fee_schedule", None)
    transfer_fee_rate = Decimal(str(getattr(schedule, "transfer_fee_rate", "0.00001")))
    exchange_transfer_fee_rates = _exchange_transfer_fee_rates(schedule)
    other_fee_rate = Decimal(str(getattr(schedule, "other_fee_rate", "0")))
    limitations = tuple(
        getattr(
            schedule,
            "limitations",
            (
                "transfer_fee_exchange_not_split",
                "broker_regulatory_fees_assumed_absorbed",
            ),
        )
    )

    side = OrderSide.BUY if normalized_direction == "buy" else OrderSide.SELL
    if normalized_asset_class == "etf":
        calculator = ETFCommission(
            commission_rate=rate,
            min_commission=min_commission,
            transfer_fee_rate=transfer_fee_rate,
            other_fee_rate=other_fee_rate,
            fee_rule_id=MANUAL_CONFIGURED_FEE_RULE_ID,
            limitations=limitations,
        )
    elif normalized_asset_class in {"bond", "convertible_bond"}:
        calculator = BondExchangeCommission(
            commission_rate=rate,
            min_commission=min_commission,
            other_fee_rate=other_fee_rate,
            fee_rule_id=MANUAL_CONFIGURED_FEE_RULE_ID,
            limitations=("bond_fee_rules_need_broker_confirmation",),
        )
    else:
        stock_exchange = _infer_stock_exchange(symbol)
        stock_limitations = limitations
        if stock_exchange and exchange_transfer_fee_rates:
            stock_limitations = tuple(
                item
                for item in limitations
                if item != "transfer_fee_exchange_not_split"
            )
        calculator = StockACommission(
            commission_rate=rate,
            min_commission=min_commission,
            stamp_tax_rate=Decimal(str(getattr(schedule, "stamp_tax_rate", "0.0005"))),
            transfer_fee_rate=transfer_fee_rate,
            exchange=stock_exchange,
            exchange_transfer_fee_rates=exchange_transfer_fee_rates,
            other_fee_rate=other_fee_rate,
            fee_rule_id=MANUAL_CONFIGURED_FEE_RULE_ID,
            limitations=stock_limitations,
        )

    breakdown = calculator.breakdown(
        side,
        Decimal(str(price)),
        Decimal(str(quantity)),
    )
    return ManualTradeFeeResult(
        commission=float(breakdown.commission),
        total_fee=float(breakdown.total_fee),
        fee_breakdown_json=fee_breakdown_payload(breakdown),
        fee_rule_id=breakdown.fee_rule_id,
        fee_rule_version=_fee_rule_version(schedule),
        note=_account_commission_note(rate, min_commission),
    )


def manual_fee_input_payload(fee: float) -> dict[str, str]:
    """Return the structured payload for an explicit user-supplied fee."""
    return {
        "commission": str(fee),
        "stamp_tax": "0",
        "transfer_fee": "0",
        "other_fees": "0",
        "total_fee": str(fee),
    }


def fee_breakdown_payload(breakdown: FeeBreakdown) -> dict[str, str]:
    """Return the canonical JSON payload for a configured fee breakdown."""
    return {
        "commission": _fee_component_text(breakdown.commission, "0.01"),
        "stamp_tax": _fee_component_text(breakdown.stamp_tax),
        "transfer_fee": _fee_component_text(breakdown.transfer_fee),
        "other_fees": _fee_component_text(breakdown.other_fees),
        "total_fee": _fee_component_text(breakdown.total_fee),
    }


def _decimal_config_value(config, name: str, fallback: str) -> Decimal:
    value = getattr(config, name, fallback)
    return Decimal(str(value))


def _fee_rule_version(schedule) -> str:
    schedule_id = str(getattr(schedule, "schedule_id", "") or "").strip()
    return schedule_id or MANUAL_CONFIGURED_FEE_RULE_VERSION


def _exchange_transfer_fee_rates(schedule) -> dict[str, Decimal]:
    raw_rates = getattr(schedule, "exchange_transfer_fee_rates", None)
    if not isinstance(raw_rates, dict):
        return {}
    parsed: dict[str, Decimal] = {}
    for raw_exchange, raw_value in raw_rates.items():
        exchange = _normalize_exchange(raw_exchange)
        if exchange:
            parsed[exchange] = Decimal(str(raw_value))
    return parsed


def _infer_stock_exchange(symbol: str | None) -> str | None:
    if not symbol:
        return None
    normalized = symbol.strip().lower()
    if not normalized:
        return None
    if normalized.endswith((".sh", ".sse")) or normalized.startswith(("sh", "sse")):
        return "shanghai"
    if normalized.endswith((".sz", ".szse")) or normalized.startswith(("sz", "szse")):
        return "shenzhen"

    core = normalized.split(".", maxsplit=1)[0]
    if core.startswith("6"):
        return "shanghai"
    if core.startswith(("0", "2", "3")):
        return "shenzhen"
    return None


def _normalize_exchange(value: object) -> str | None:
    key = str(value).strip().lower()
    if key in {"sh", "sse", "shanghai", "上海", "沪"}:
        return "shanghai"
    if key in {"sz", "szse", "shenzhen", "深圳", "深"}:
        return "shenzhen"
    return None


def _format_decimal_short(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def _account_commission_note(rate: Decimal, min_commission: Decimal) -> str:
    rate_per_ten_thousand = rate * Decimal("10000")
    return (
        "账户佣金配置：佣金率万"
        f"{_format_decimal_short(rate_per_ten_thousand)}，"
        f"最低{_format_decimal_short(min_commission)}元"
    )


def _fee_component_text(value: Decimal, quantization: str = "0.000001") -> str:
    return format(value.quantize(Decimal(quantization)), "f")
