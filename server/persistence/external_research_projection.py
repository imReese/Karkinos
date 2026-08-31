"""Row projection for external backtest research requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.contracts.external_research import ExternalBacktestReportRecord


def external_backtest_report_record(
    row: Mapping[str, Any],
) -> ExternalBacktestReportRecord:
    return ExternalBacktestReportRecord(
        analysis_id=str(row["analysis_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        requested_by=str(row["requested_by"]),
        backtest_result_id=int(row["backtest_result_id"]),
        capture_id=str(row["capture_id"]),
        workflow_id=str(row["workflow_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        evidence_reference_id=str(row["evidence_reference_id"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        created_at=str(row["created_at"]),
    )


__all__ = ["external_backtest_report_record"]
