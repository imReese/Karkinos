"""Production read source for explicit Karkinos AI context capture.

The source calls existing canonical projection builders and exact persisted
record readers. It never refreshes a provider and never invokes a model.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from .capture import (
    CAPTURE_TOOL_BY_TYPE,
    CapturedProjection,
    CaptureEvidenceType,
    CaptureSelectionError,
    CaptureSourceBatch,
    HumanContextCaptureRequest,
)
from .evidence import EvidenceIdentityMismatch


class PersistedKarkinosCaptureSource:
    """Select canonical projections and exact rows from one application state."""

    def __init__(self, state: Any) -> None:
        self._state = state

    async def load(
        self,
        request: HumanContextCaptureRequest,
    ) -> CaptureSourceBatch:
        from server.routes.portfolio import (
            _current_valuation_snapshot,
            build_account_state_response,
            build_portfolio_snapshot,
        )

        db = getattr(self._state, "db", None)
        if db is None:
            raise CaptureSelectionError("database is not initialized")

        portfolio = await build_portfolio_snapshot(self._state)
        identity = _portfolio_identity(portfolio)
        _require_persisted_valuation_snapshot(db, identity)
        portfolio_status = _portfolio_evidence_status(portfolio)
        projections: list[CapturedProjection] = []

        for evidence_type in request.evidence_types:
            tool_name = CAPTURE_TOOL_BY_TYPE[evidence_type]
            if evidence_type == CaptureEvidenceType.PORTFOLIO:
                projections.append(
                    CapturedProjection(
                        tool_name=tool_name,
                        status=portfolio_status,
                        as_of=str(portfolio.valuation_as_of),
                        source_schema_version="karkinos.portfolio_snapshot.v1",
                        payload=portfolio.model_dump(mode="json"),
                    )
                )
            elif evidence_type == CaptureEvidenceType.ACCOUNT_STATE:
                account_state = await build_account_state_response(
                    self._state,
                    snapshot=portfolio,
                )
                projections.append(
                    CapturedProjection(
                        tool_name=tool_name,
                        status=portfolio_status,
                        as_of=str(portfolio.valuation_as_of),
                        source_schema_version="karkinos.account_state.v1",
                        payload=account_state.model_dump(mode="json"),
                    )
                )
            elif evidence_type == CaptureEvidenceType.OPERATIONS:
                from server.routes.operations import build_today_operations_payload

                operations = await build_today_operations_payload(self._state)
                projections.append(
                    CapturedProjection(
                        tool_name=tool_name,
                        status=_operations_evidence_status(
                            operations,
                            portfolio_status=portfolio_status,
                        ),
                        as_of=str(
                            operations.get("generated_at") or portfolio.valuation_as_of
                        ),
                        source_schema_version=str(
                            operations.get("schema_version")
                            or "karkinos.operations_today.v1"
                        ),
                        payload=operations,
                    )
                )
            elif evidence_type == CaptureEvidenceType.RESEARCH_EVIDENCE:
                projections.append(
                    await _research_evidence_projection(
                        db,
                        tool_name=tool_name,
                        result_id=int(request.backtest_result_id or 0),
                    )
                )
            elif evidence_type == CaptureEvidenceType.ACCOUNT_TRUTH:
                projections.append(
                    _account_truth_projection(
                        self._state,
                        tool_name=tool_name,
                        fallback_as_of=str(portfolio.valuation_as_of),
                    )
                )
            elif evidence_type == CaptureEvidenceType.PAPER_SHADOW:
                projections.append(
                    _paper_shadow_projection(
                        db,
                        tool_name=tool_name,
                        run_id=str(request.paper_shadow_run_id or ""),
                    )
                )
            else:  # pragma: no cover - enum construction prevents this path
                raise CaptureSelectionError(
                    f"unsupported evidence type: {evidence_type}"
                )

        final_snapshot = _current_valuation_snapshot(self._state)
        final_identity = (
            str(final_snapshot.get("snapshot_id") or ""),
            int(final_snapshot.get("ledger_cutoff_id") or 0),
            str(final_snapshot.get("ledger_fingerprint") or ""),
        )
        if final_identity != identity:
            raise EvidenceIdentityMismatch(
                "valuation or ledger facts drifted during context capture"
            )
        _require_persisted_valuation_snapshot(db, final_identity)
        return CaptureSourceBatch(
            valuation_snapshot_id=identity[0],
            ledger_cutoff_id=identity[1],
            ledger_fingerprint=identity[2],
            projections=tuple(projections),
        )


def _portfolio_identity(portfolio: Any) -> tuple[str, int, str]:
    identity = (
        str(getattr(portfolio, "valuation_snapshot_id", None) or ""),
        int(getattr(portfolio, "ledger_cutoff_id", 0) or 0),
        str(getattr(portfolio, "ledger_fingerprint", None) or ""),
    )
    if not identity[0] or not identity[2]:
        raise EvidenceIdentityMismatch(
            "canonical portfolio is missing valuation or ledger identity"
        )
    return identity


def _require_persisted_valuation_snapshot(
    db: Any,
    identity: tuple[str, int, str],
) -> None:
    reader = getattr(db, "get_valuation_snapshot_sync", None)
    if not callable(reader):
        raise EvidenceIdentityMismatch(
            "database cannot resolve persisted valuation snapshots"
        )
    row = reader(identity[0])
    if not isinstance(row, dict):
        raise EvidenceIdentityMismatch(
            "valuation snapshot is not persisted and replayable"
        )
    persisted_identity = (
        str(row.get("snapshot_id") or ""),
        int(row.get("ledger_cutoff_id") or 0),
        str(row.get("ledger_fingerprint") or ""),
    )
    if persisted_identity != identity:
        raise EvidenceIdentityMismatch("persisted valuation identity drift")


def _portfolio_evidence_status(portfolio: Any) -> str:
    if getattr(portfolio, "position_review_items", None):
        return "unreconciled"
    status = str(getattr(portfolio, "valuation_status", "missing") or "missing")
    if status in {
        "complete",
        "degraded",
        "partial",
        "blocked",
        "missing",
        "stale",
        "estimated",
        "unreconciled",
    }:
        return status
    return "degraded"


def _operations_evidence_status(
    operations: dict[str, Any],
    *,
    portfolio_status: str,
) -> str:
    if portfolio_status != "complete":
        return portfolio_status
    conclusion = str(operations.get("conclusion_status") or "").lower()
    if conclusion == "blocked":
        return "blocked"
    if conclusion == "degraded":
        return "degraded"
    health = operations.get("health")
    if isinstance(health, dict):
        if int(health.get("blocked") or 0) > 0:
            return "blocked"
        if int(health.get("degraded") or 0) > 0:
            return "degraded"
    return "complete"


async def _research_evidence_projection(
    db: Any,
    *,
    tool_name: str,
    result_id: int,
) -> CapturedProjection:
    reader = getattr(db, "get_backtest_result", None)
    if not callable(reader):
        raise CaptureSelectionError("backtest result reader is unavailable")
    selected = reader(result_id)
    row = await selected if inspect.isawaitable(selected) else selected
    if not isinstance(row, dict):
        raise LookupError(f"backtest result not found: {result_id}")
    metrics, metrics_valid = _json_object(row.get("metrics_json"))
    config, config_valid = _json_object(row.get("config_json"))
    cost_summary, cost_summary_valid = _json_object(row.get("cost_summary_json"))
    bundle = metrics.get("research_evidence_bundle")
    bundle_payload = dict(bundle) if isinstance(bundle, dict) else {}
    after_cost = metrics.get("evidence_bundle")
    after_cost_payload = dict(after_cost) if isinstance(after_cost, dict) else {}
    bundle_gate = str(bundle_payload.get("gate_status") or "missing")
    status = {
        "pass": "complete",
        "degraded": "degraded",
        "blocked": "blocked",
    }.get(bundle_gate, "missing")
    complete = metrics_valid and bool(bundle_payload)
    if not complete:
        status = "missing"
    performance_summary = {
        key: row.get(key) if row.get(key) is not None else metrics.get(key)
        for key in (
            "initial_cash",
            "final_equity",
            "total_return",
            "sharpe",
            "sortino",
            "max_drawdown",
            "win_rate",
            "duration_days",
        )
    }
    required_performance_fields = (
        "initial_cash",
        "final_equity",
        "total_return",
        "max_drawdown",
        "duration_days",
    )
    analysis_blocking_reasons = []
    if not complete:
        analysis_blocking_reasons.append("research_evidence_bundle_missing")
    if bundle_gate != "pass":
        analysis_blocking_reasons.append(
            f"research_evidence_gate_not_pass:{bundle_gate}"
        )
    missing_performance = [
        key for key in required_performance_fields if performance_summary[key] is None
    ]
    if missing_performance:
        analysis_blocking_reasons.append(
            "persisted_performance_fields_missing:" + ",".join(missing_performance)
        )
    if not after_cost_payload:
        analysis_blocking_reasons.append("after_cost_evidence_missing")
    payload = {
        "schema_version": "karkinos.ai.research_evidence_capture.v2",
        "backtest_result_id": result_id,
        "backtest_created_at": row.get("created_at"),
        "performance_summary": performance_summary,
        "test_window": {
            "start_date": config.get("start_date") if config_valid else None,
            "end_date": config.get("end_date") if config_valid else None,
            "assets": config.get("assets") if config_valid else None,
            "benchmark_return": (
                config.get("benchmark_return") if config_valid else None
            ),
        },
        "after_cost_evidence": after_cost_payload,
        "cost_summary": cost_summary if cost_summary_valid else {},
        "research_evidence_bundle": bundle_payload,
        "bundle_status": "available" if complete else "missing",
        "blocking_reasons": [] if complete else ["research_evidence_bundle_missing"],
        "analysis_ready": not analysis_blocking_reasons,
        "analysis_blocking_reasons": analysis_blocking_reasons,
        "persisted_backtest_facts_only": True,
    }
    return CapturedProjection(
        tool_name=tool_name,
        status=status,
        as_of=str(row.get("created_at") or "1970-01-01T00:00:00+00:00"),
        source_schema_version="karkinos.ai.research_evidence_capture.v2",
        payload=payload,
    )


def _account_truth_projection(
    state: Any,
    *,
    tool_name: str,
    fallback_as_of: str,
) -> CapturedProjection:
    from server.account_truth_gate import build_latest_account_truth_score_payload
    from server.routes.account_truth import _missing_score_response

    payload = (
        build_latest_account_truth_score_payload(state) or _missing_score_response()
    )
    gate_status = str(payload.get("gate_status") or "blocked")
    freshness = str(payload.get("data_freshness_status") or "missing")
    if str(payload.get("status") or "missing") == "missing":
        status = "missing"
    elif freshness == "stale":
        status = "stale"
    elif gate_status != "pass":
        status = "unreconciled"
    else:
        status = "complete"
    return CapturedProjection(
        tool_name=tool_name,
        status=status,
        as_of=str(payload.get("created_at") or fallback_as_of),
        source_schema_version=str(
            payload.get("schema_version") or "karkinos.account_truth.score.v1"
        ),
        payload=dict(payload),
    )


def _paper_shadow_projection(
    db: Any,
    *,
    tool_name: str,
    run_id: str,
) -> CapturedProjection:
    reader = getattr(db, "get_paper_shadow_run_sync", None)
    if not callable(reader):
        raise CaptureSelectionError("paper/shadow run reader is unavailable")
    row = reader(run_id)
    if not isinstance(row, dict):
        raise LookupError(f"paper/shadow run not found: {run_id}")
    payload, payload_valid = _json_object(row.get("payload_json"))
    limitations, limitations_valid = _json_array(row.get("limitations_json"))
    required_identity_present = bool(
        str(row.get("run_id") or "").strip()
        and str(row.get("input_fingerprint") or "").strip()
    )
    complete = payload_valid and limitations_valid and required_identity_present
    persisted_run = {
        key: value
        for key, value in row.items()
        if key not in {"payload_json", "limitations_json"}
    }
    capture_payload = {
        "schema_version": "karkinos.ai.paper_shadow_evidence_capture.v1",
        "persisted_run": persisted_run,
        "run_payload": payload,
        "limitations": limitations,
        "payload_parse_status": "complete" if payload_valid else "invalid",
        "limitations_parse_status": ("complete" if limitations_valid else "invalid"),
    }
    return CapturedProjection(
        tool_name=tool_name,
        status="complete" if complete else "partial",
        as_of=str(
            row.get("updated_at")
            or row.get("created_at")
            or row.get("plan_date")
            or "1970-01-01T00:00:00+00:00"
        ),
        source_schema_version="karkinos.ai.paper_shadow_evidence_capture.v1",
        payload=capture_payload,
    )


def _json_object(value: Any) -> tuple[dict[str, Any], bool]:
    if isinstance(value, dict):
        return dict(value), True
    if not isinstance(value, str) or not value.strip():
        return {}, False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}, False
    return (dict(parsed), True) if isinstance(parsed, dict) else ({}, False)


def _json_array(value: Any) -> tuple[list[Any], bool]:
    if isinstance(value, list):
        return list(value), True
    if not isinstance(value, str) or not value.strip():
        return [], False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [], False
    return (list(parsed), True) if isinstance(parsed, list) else ([], False)
