"""Versioned research evidence bundles for Strategy Lab experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

AnalyzerStatus = str


@dataclass(frozen=True)
class AnalyzerResult:
    """One composable analyzer result inside a research evidence bundle."""

    name: str
    status: AnalyzerStatus
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class ResearchEvidenceContext:
    """Normalized inputs available to research analyzers."""

    metrics_json: dict[str, Any]
    cost_summary_json: dict[str, Any]
    evidence_json: dict[str, Any]
    strategy_metadata: dict[str, Any]
    fills: list[dict[str, Any]]


class ResearchAnalyzer(Protocol):
    """Small analyzer contract inspired by pluggable research frameworks."""

    name: str

    def analyze(self, context: ResearchEvidenceContext) -> AnalyzerResult:
        """Return a deterministic analyzer result."""


class DataQualityAnalyzer:
    name = "data_quality"

    def analyze(self, context: ResearchEvidenceContext) -> AnalyzerResult:
        snapshot = _json_object(context.metrics_json.get("dataset_snapshot"))
        if not snapshot:
            return AnalyzerResult(
                name=self.name,
                status="degraded",
                summary="Dataset snapshot metadata is missing.",
                details={"snapshot_available": False},
                limitations=[
                    "Experiment reproducibility is weakened without dataset snapshot evidence."
                ],
            )

        quality = _json_object(snapshot.get("data_quality"))
        issues = _list_of_dicts(quality.get("issues"))
        row_count = int(snapshot.get("row_count") or 0)
        symbol_universe = _list_of_dicts(snapshot.get("symbol_universe"))
        blocked = row_count <= 0 or any(
            str(issue.get("code")) in {"no_rows", "provider_mismatch_blocked"}
            for issue in issues
        )
        status = "blocked" if blocked else "degraded" if issues else "pass"
        summary = (
            "Dataset quality blocks this experiment."
            if status == "blocked"
            else (
                "Dataset quality has warnings."
                if status == "degraded"
                else "Dataset quality checks passed."
            )
        )
        return AnalyzerResult(
            name=self.name,
            status=status,
            summary=summary,
            details={
                "snapshot_id": snapshot.get("snapshot_id"),
                "row_count": row_count,
                "symbol_count": len(symbol_universe),
                "issue_count": len(issues),
                "quality_status": quality.get("status") or "unknown",
            },
            warnings=[
                str(issue.get("message") or issue.get("code")) for issue in issues
            ],
            limitations=(
                []
                if status == "pass"
                else ["Data issues must be reviewed before promotion."]
            ),
        )


class AfterCostAnalyzer:
    name = "after_cost"

    def analyze(self, context: ResearchEvidenceContext) -> AnalyzerResult:
        evidence = context.evidence_json or _json_object(
            context.metrics_json.get("evidence_bundle")
        )
        if not evidence:
            return AnalyzerResult(
                name=self.name,
                status="degraded",
                summary="After-cost evidence is missing.",
                details={"after_cost_available": False},
                limitations=[
                    "Experiment cannot support promotion review without after-cost evidence."
                ],
            )

        total_cost = _float_value(evidence.get("total_cost"))
        fill_count = int(evidence.get("fill_count") or 0)
        return AnalyzerResult(
            name=self.name,
            status="pass",
            summary="After-cost evidence is attached.",
            details={
                "after_cost_available": True,
                "total_cost": total_cost,
                "fill_count": fill_count,
                "gross_turnover": _float_value(
                    evidence.get("gross_turnover")
                    or context.cost_summary_json.get("gross_turnover")
                ),
                "total_commission": _float_value(
                    context.cost_summary_json.get("total_commission")
                ),
                "total_slippage": _float_value(
                    context.cost_summary_json.get("total_slippage")
                ),
            },
            limitations=list(evidence.get("limitations") or []),
        )


class OosAnalyzer:
    name = "oos"

    def analyze(self, context: ResearchEvidenceContext) -> AnalyzerResult:
        oos = _json_object(context.metrics_json.get("oos_validation"))
        if not oos:
            return AnalyzerResult(
                name=self.name,
                status="pass",
                summary="No OOS split was requested for this run.",
                details={"oos_available": False, "required_for_current_run": False},
                limitations=[
                    "OOS evidence is not present; require it before promotion review."
                ],
            )

        validation_status = str(oos.get("validation_status") or "unknown")
        status = "degraded" if validation_status.endswith("failed") else "pass"
        return AnalyzerResult(
            name=self.name,
            status=status,
            summary="OOS validation evidence is attached.",
            details={
                "oos_available": True,
                "validation_mode": oos.get("validation_mode") or "single_split",
                "validation_status": validation_status,
                "split_timestamp": oos.get("split_timestamp"),
                "fold_count": oos.get("fold_count"),
                "aggregate": _json_object(oos.get("aggregate")),
            },
            limitations=list(oos.get("limitations") or []),
        )


def build_research_evidence_bundle(
    *,
    metrics_json: dict[str, Any],
    cost_summary_json: dict[str, Any],
    evidence_json: dict[str, Any],
    strategy_metadata: dict[str, Any],
    fills: list[dict[str, Any]] | None = None,
    analyzers: list[ResearchAnalyzer] | None = None,
) -> dict[str, Any]:
    """Build a stable v0.5 evidence bundle from existing backtest artifacts."""
    context = ResearchEvidenceContext(
        metrics_json=dict(metrics_json),
        cost_summary_json=dict(cost_summary_json),
        evidence_json=dict(evidence_json),
        strategy_metadata=dict(strategy_metadata),
        fills=_list_of_dicts(fills),
    )
    analyzer_results = [
        analyzer.analyze(context)
        for analyzer in (
            analyzers
            or [
                DataQualityAnalyzer(),
                AfterCostAnalyzer(),
                OosAnalyzer(),
            ]
        )
    ]
    statuses = [result.status for result in analyzer_results]
    gate_status = (
        "blocked"
        if "blocked" in statuses
        else "degraded" if "degraded" in statuses else "pass"
    )
    dataset_snapshot = _json_object(metrics_json.get("dataset_snapshot"))
    trade_statistics = _trade_statistics(context)
    limitations = _bundle_limitations(analyzer_results, context)
    bundle = {
        "schema_version": "karkinos.research_evidence.v1",
        "bundle_id": "",
        "gate_status": gate_status,
        "dataset_snapshot_id": dataset_snapshot.get("snapshot_id"),
        "strategy": {
            "strategy_id": strategy_metadata.get("strategy_id")
            or strategy_metadata.get("name"),
            "name": strategy_metadata.get("name"),
            "display_name": strategy_metadata.get("display_name"),
            "params": dict(strategy_metadata.get("params") or {}),
        },
        "analyzers": [result.to_json_dict() for result in analyzer_results],
        "evidence_references": {
            "dataset_snapshot_id": dataset_snapshot.get("snapshot_id"),
            "strategy_metadata_available": bool(strategy_metadata),
            "after_cost_evidence_available": bool(
                evidence_json or _json_object(metrics_json.get("evidence_bundle"))
            ),
            "oos_evidence_available": bool(
                _json_object(metrics_json.get("oos_validation"))
            ),
            "cost_summary_available": bool(cost_summary_json),
            "fill_count": trade_statistics["fill_count"],
            "trade_count": trade_statistics["trade_count"],
            "limitation_count": len(limitations),
        },
        "trade_statistics": trade_statistics,
        "china_market_assumptions": _china_market_assumptions(),
        "promotion_gate": {
            "status": gate_status,
            "manual_confirmation_required": True,
            "does_not_enable_execution": True,
            "next_review": _next_review(gate_status),
        },
        "limitations": limitations,
    }
    bundle["bundle_id"] = _bundle_id(bundle)
    return bundle


def _json_object(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _list_of_dicts(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _float_value(raw: Any) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _bundle_id(bundle: dict[str, Any]) -> str:
    stable = {**bundle, "bundle_id": ""}
    frozen = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(frozen.encode("utf-8")).hexdigest()


def _trade_statistics(context: ResearchEvidenceContext) -> dict[str, Any]:
    evidence = context.evidence_json or _json_object(
        context.metrics_json.get("evidence_bundle")
    )
    fill_count = len(context.fills) or int(evidence.get("fill_count") or 0)
    trade_count = int(context.cost_summary_json.get("total_trades") or 0)
    return {
        "fill_count": fill_count,
        "trade_count": trade_count,
        "gross_turnover": _float_value(
            context.cost_summary_json.get("gross_turnover")
            or evidence.get("gross_turnover")
        ),
        "total_commission": _float_value(
            context.cost_summary_json.get("total_commission")
        ),
        "total_slippage": _float_value(context.cost_summary_json.get("total_slippage")),
    }


def _bundle_limitations(
    results: list[AnalyzerResult],
    context: ResearchEvidenceContext,
) -> list[str]:
    limitations: list[str] = [
        "Research evidence is not investment advice or an execution approval."
    ]
    evidence = context.evidence_json or _json_object(
        context.metrics_json.get("evidence_bundle")
    )
    for key in (
        "cost_assumptions",
        "slippage_assumptions",
        "assumptions",
        "limitations",
    ):
        limitations.extend(str(item) for item in evidence.get(key) or [])
    for result in results:
        limitations.extend(result.limitations)
    return list(dict.fromkeys(limitations))


def _china_market_assumptions() -> dict[str, list[str]]:
    return {
        "modeled": [
            "Configured commission and slippage are included in after-cost evidence.",
            "Portfolio accounting and fills are replayed by the deterministic backtest engine.",
        ],
        "known_gaps": [
            "T+1, limit-up/limit-down, suspension or special-treatment status, full tax treatment, trading-calendar edge cases, and fund/NAV latency require explicit analyzer hardening before promotion.",
        ],
    }


def _next_review(gate_status: str) -> str:
    if gate_status == "blocked":
        return "Fix blocking evidence gaps before further review."
    if gate_status == "degraded":
        return "Review degraded evidence before shadow or paper consideration."
    return "Eligible for human research review only; execution remains gated."
