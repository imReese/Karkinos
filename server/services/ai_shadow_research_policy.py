"""Pure policy evidence for AI shadow research authorization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    PreparedBaseline,
    ShadowResearchRejected,
    require_corrected_panel_rearm_evidence,
)


def build_corrected_panel_rearm_evidence(
    prepared: PreparedBaseline,
) -> dict[str, Any]:
    metrics = prepared.result.get("metrics_json")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    truth = metrics.get("market_universe_truth")
    truth = truth if isinstance(truth, Mapping) else {}
    panel = truth.get("research_panel")
    panel = panel if isinstance(panel, Mapping) else {}
    core = {
        "schema_version": "karkinos.ai.corrected_panel_rearm_evidence.v1",
        "market_date": prepared.market_date,
        "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
        "prepared_baseline_fingerprint": prepared.fingerprint,
        "dataset_snapshot_id": str(prepared.snapshot.get("snapshot_id") or ""),
        "market_universe_truth_schema_version": str(truth.get("schema_version") or ""),
        "market_universe_truth_fingerprint": str(
            truth.get("evidence_fingerprint") or ""
        ),
        "market_universe_snapshot_id": str(
            truth.get("market_universe_snapshot_id") or ""
        ),
        "research_panel_schema_version": str(panel.get("schema_version") or ""),
        "research_panel_fingerprint": str(panel.get("panel_fingerprint") or ""),
        "research_panel_member_count": int(panel.get("member_count") or 0),
        "required_trading_date_count": int(
            truth.get("required_trading_date_count") or 0
        ),
        "receipt_bound_history": truth.get("receipt_bound_history") is True,
        "stock_only": truth.get("stock_only") is True,
        "provider_contacted_during_build": False,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "changes_capital_authority": False,
    }
    return require_corrected_panel_rearm_evidence(
        {**core, "evidence_fingerprint": content_fingerprint(core)}
    )


def optional_corrected_panel_rearm_evidence(
    prepared: PreparedBaseline,
) -> dict[str, Any] | None:
    try:
        return build_corrected_panel_rearm_evidence(prepared)
    except ShadowResearchRejected:
        return None
