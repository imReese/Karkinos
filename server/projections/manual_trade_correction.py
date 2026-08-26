"""Replay-derived correction plan for one canonical manual trade."""

from __future__ import annotations

from typing import Any

from server.projections.ledger_exclusion_correction import (
    LedgerExclusionCorrectionPlanError,
    build_ledger_exclusion_correction_plan,
)

MANUAL_TRADE_CORRECTION_ENTRY_TYPE = "manual_trade_projection_correction"
MANUAL_TRADE_CORRECTION_SOURCE = "manual_trade_correction"
MANUAL_TRADE_CORRECTION_PLAN_SCHEMA_VERSION = "karkinos.manual_trade_correction_plan.v1"


class ManualTradeCorrectionPlanError(ValueError):
    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


def build_manual_trade_correction_plan(
    *,
    ledger_rows: list[dict[str, Any]],
    original_entry_id: int,
    trade_id: int,
) -> dict[str, Any]:
    """Derive a correction without accepting caller-owned financial values."""

    try:
        return build_ledger_exclusion_correction_plan(
            ledger_rows=ledger_rows,
            original_entry_ids=[original_entry_id],
            required_sources={"portfolio_trade"},
            schema_version=MANUAL_TRADE_CORRECTION_PLAN_SCHEMA_VERSION,
            correction_identity={"trade_id": str(trade_id)},
            blocker_prefix="manual_trade_correction",
        )
    except LedgerExclusionCorrectionPlanError as exc:
        raise ManualTradeCorrectionPlanError(str(exc)) from None


__all__ = [
    "MANUAL_TRADE_CORRECTION_ENTRY_TYPE",
    "MANUAL_TRADE_CORRECTION_PLAN_SCHEMA_VERSION",
    "MANUAL_TRADE_CORRECTION_SOURCE",
    "ManualTradeCorrectionPlanError",
    "build_manual_trade_correction_plan",
]
