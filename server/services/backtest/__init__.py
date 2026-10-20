"""Backtest domain package.

Canonical exports:
- costs: Execution cost resolution and formula quoting
- chronological: Historical chronological sweep engine
- result_projection: Result projection and payload mapping
"""

from __future__ import annotations

from server.services.backtest.chronological import run_chronological_sweep
from server.services.backtest.costs import (
    quote_formula_purchase,
    resolve_backtest_costs,
    resolve_paper_book_costs,
)
from server.services.backtest.result_projection import (
    backtest_evidence_from_payload,
    build_backtest_report_metrics_json,
    fill_to_response,
    strategy_metadata_snapshot,
)

__all__ = [
    "backtest_evidence_from_payload",
    "build_backtest_report_metrics_json",
    "fill_to_response",
    "quote_formula_purchase",
    "resolve_backtest_costs",
    "resolve_paper_book_costs",
    "run_chronological_sweep",
    "strategy_metadata_snapshot",
]
