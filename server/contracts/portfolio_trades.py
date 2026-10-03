"""Typed commands and results for canonical manual portfolio trades."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ManualTradeWrite:
    """One canonical ledger trade and its compatibility projection."""

    command_id: str
    operator_id: str
    timestamp: str
    symbol: str
    display_name: str
    direction: str
    quantity: Decimal | int | float
    price: Decimal | int | float
    commission: Decimal | int | float
    gross_amount: Decimal | int | float
    net_cash_impact: Decimal | int | float
    fee_breakdown_json: str
    fee_rule_id: str
    fee_rule_version: str
    asset_class: str
    note: str
    cost_basis_method: str = "moving_average_buy_cost"


@dataclass(frozen=True, slots=True)
class PendingFundOrderWrite:
    """Restart-stable pending fund-subscription intent."""

    command_id: str
    operator_id: str
    submitted_at: str
    symbol: str
    display_name: str
    amount: float
    commission: float
    asset_class: str
    target_trade_date: str
    note: str


@dataclass(frozen=True, slots=True)
class PendingFundConfirmationWrite:
    """Human confirmation bound to one persisted NAV ingestion run."""

    command_id: str
    operator_id: str
    order_id: int
    evidence_fetch_run_id: str
    confirmation_note: str = ""


@dataclass(frozen=True, slots=True)
class ManualTradeCorrectionWrite:
    command_id: str
    operator_id: str
    trade_id: int


@dataclass(frozen=True, slots=True)
class ManualTradeWriteResult:
    trade: dict[str, object]
    ledger_entry_id: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ManualTradeCorrectionResult:
    trade_id: int
    correction_ledger_entry_id: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PendingFundOrderWriteResult:
    order: dict[str, object]
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PendingFundConfirmationResult:
    order: dict[str, object]
    trade: dict[str, object]
    ledger_entry_id: int
    replayed: bool = False


__all__ = [
    "ManualTradeWrite",
    "ManualTradeCorrectionWrite",
    "ManualTradeCorrectionResult",
    "ManualTradeWriteResult",
    "PendingFundConfirmationWrite",
    "PendingFundConfirmationResult",
    "PendingFundOrderWrite",
    "PendingFundOrderWriteResult",
]
