"""Server-owned correction guardrails for Account Truth snapshot roll-forward."""

from __future__ import annotations

from pathlib import Path
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
from server.runtime_paths import resolve_broker_statement_path


def roll_forward_daily_broker_statement_for_state(
    *,
    state: Any,
    run_date: str,
    path: str | Path | None = None,
) -> DailySnapshotRollForwardResult:
    """Run the pure writer with validated server-ledger correction evidence."""

    resolved_path = path
    if resolved_path is None:
        collector = getattr(state, "broker_statement_collector", None)
        collector_path = getattr(collector, "_path", None)
        if collector_path:
            resolved_path = collector_path
        else:
            config = getattr(
                getattr(state, "config", None),
                "broker_statement_collector",
                None,
            )
            raw_path = getattr(config, "path", "")
            if raw_path:
                resolved_path = resolve_broker_statement_path(raw_path)

    return _roll_forward_for_state(
        state=state,
        run_date=run_date,
        ledger_revision_guardrail_resolver=(
            legacy_fund_duplicate_roll_forward_guardrail
        ),
        path=resolved_path,
    )


__all__ = ["roll_forward_daily_broker_statement_for_state"]
