"""Typed commands and results for canonical portfolio cash flows."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CashFlowWrite:
    command_id: str
    operator_id: str
    timestamp: str
    amount: float
    flow_type: str
    note: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.amount) or self.amount <= 0:
            raise ValueError("cash-flow amount must be finite and positive")


@dataclass(frozen=True, slots=True)
class CashFlowWriteResult:
    cash_flow: dict[str, object]
    ledger_entry_id: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CashFlowCorrectionWrite:
    command_id: str
    operator_id: str
    cash_flow_id: int


@dataclass(frozen=True, slots=True)
class CashFlowCorrectionResult:
    cash_flow_id: int
    correction_ledger_entry_id: int
    replayed: bool = False


__all__ = [
    "CashFlowCorrectionResult",
    "CashFlowCorrectionWrite",
    "CashFlowWrite",
    "CashFlowWriteResult",
]
