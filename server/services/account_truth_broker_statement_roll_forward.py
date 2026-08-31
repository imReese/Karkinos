"""Server-owned correction guardrails for Account Truth snapshot roll-forward."""

from __future__ import annotations

from typing import Any

from account_truth.broker_statement_roll_forward import (
    DailySnapshotRollForwardResult,
)
from account_truth.broker_statement_roll_forward import (
    roll_forward_daily_broker_statement_for_state as _roll_forward_for_state,
)
from server.account_truth_ledger_support import (
    legacy_fund_duplicate_roll_forward_guardrail,
)


def roll_forward_daily_broker_statement_for_state(
    *,
    state: Any,
    run_date: str,
) -> DailySnapshotRollForwardResult:
    """Run the pure writer with validated server-ledger correction evidence."""

    return _roll_forward_for_state(
        state=state,
        run_date=run_date,
        ledger_revision_guardrail_resolver=(
            legacy_fund_duplicate_roll_forward_guardrail
        ),
    )


__all__ = ["roll_forward_daily_broker_statement_for_state"]
