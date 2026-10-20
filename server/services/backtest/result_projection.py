"""Canonical backtest-result projections and payload mapping.

Canonical module in server.services.backtest.
"""

from __future__ import annotations

from server.projections.backtest_result import (
    backtest_evidence_from_payload,
    build_backtest_report_metrics_json,
    fill_to_response,
    json_object,
    strategy_metadata_snapshot,
)

__all__ = [
    "backtest_evidence_from_payload",
    "build_backtest_report_metrics_json",
    "fill_to_response",
    "json_object",
    "strategy_metadata_snapshot",
]
