"""Canonical backtest attribution projections."""

from __future__ import annotations

from typing import Any

from server.contracts.http.backtest import BacktestAttributionPreviewRequest


def preview_ref(
    prefix: str,
    value: str | None,
) -> str | None:
    return f"{prefix}:{value}" if value else None


def payload_value(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return str(value) if value else None


def build_attribution_review_linkage_candidate(
    *,
    request: BacktestAttributionPreviewRequest,
    order_id: str,
    fill_id: str,
) -> dict[str, Any]:
    signal_ref = preview_ref("signal_preview", request.signal_id)
    dataset_snapshot_ref = preview_ref(
        "dataset_snapshot",
        request.dataset_snapshot_id,
    )
    risk_preview_ref = preview_ref(
        "risk_preview",
        request.risk_reasons[0] if request.risk_reasons else None,
    )
    return {
        "candidate_id": (
            f"review-linkage:{request.strategy}:{request.symbol}:{request.signal_id}"
        ),
        "strategy_id": request.strategy,
        "symbol": request.symbol,
        "asset_class": request.asset_class,
        "signal_ref": signal_ref,
        "dataset_snapshot_ref": dataset_snapshot_ref,
        "risk_preview_ref": risk_preview_ref,
        "paper_shadow_order_ref": preview_ref("paper_shadow_order", order_id),
        "paper_shadow_fill_ref": preview_ref("paper_shadow_fill", fill_id),
        "recommended_review_action": "review_and_link_evidence_manually",
        "manual_confirmation_required": True,
        "does_not_create_order": True,
        "does_not_create_fill": True,
        "does_not_mutate_ledger": True,
        "can_link_to_strategy_pnl": False,
    }


def run_backtest_attribution_preview(
    request: BacktestAttributionPreviewRequest,
    state: Any,
) -> dict[str, Any]:
    """Summarize preview evidence before any production attribution claim."""
    order_id = payload_value(request.paper_shadow_order, "order_id")
    fill_id = payload_value(request.paper_shadow_fill, "fill_id")
    paper_shadow_simulated = request.paper_shadow_status == "simulated"
    evidence_counts = {
        "signal_preview": 1 if request.signal_id else 0,
        "risk_preview": 1 if request.risk_preview_passed else 0,
        "paper_shadow_order": 1 if paper_shadow_simulated and order_id else 0,
        "paper_shadow_fill": 1 if paper_shadow_simulated and fill_id else 0,
        "production_order": 0,
        "production_fill": 0,
    }
    evidence_refs = [
        ref
        for ref in (
            preview_ref("signal_preview", request.signal_id),
            preview_ref("dataset_snapshot", request.dataset_snapshot_id),
            preview_ref(
                "risk_preview",
                request.risk_reasons[0] if request.risk_reasons else None,
            ),
            preview_ref("paper_shadow_order", order_id),
            preview_ref("paper_shadow_fill", fill_id),
        )
        if ref is not None
    ]
    ready_for_review = (
        evidence_counts["signal_preview"] == 1
        and evidence_counts["risk_preview"] == 1
        and evidence_counts["paper_shadow_order"] == 1
        and evidence_counts["paper_shadow_fill"] == 1
    )
    required_next_actions = (
        ["link_signal_review_order_and_fill_before_strategy_pnl_attribution"]
        if ready_for_review
        else ["complete_signal_risk_and_paper_shadow_preview_before_review_linkage"]
    )
    review_linkage_candidate = (
        build_attribution_review_linkage_candidate(
            request=request,
            order_id=order_id or "",
            fill_id=fill_id or "",
        )
        if ready_for_review and order_id and fill_id
        else None
    )
    return {
        "schema_version": "karkinos.strategy_attribution_preview.v1",
        "status": (
            "ready_for_review_linkage" if ready_for_review else "evidence_incomplete"
        ),
        "strategy_id": request.strategy,
        "symbol": request.symbol,
        "asset_class": request.asset_class,
        "attribution_status": "preview_only_pnl_not_attributed",
        "can_attribute_pnl": False,
        "does_not_create_order": True,
        "does_not_create_fill": True,
        "does_not_mutate_ledger": True,
        "risk_reasons": request.risk_reasons,
        "evidence_counts": evidence_counts,
        "evidence_refs": evidence_refs,
        "required_next_actions": required_next_actions,
        "review_linkage_candidate": review_linkage_candidate,
        "limitations": [
            "Preview evidence is not production attribution evidence.",
            "Strategy P/L stays unavailable until signal, review, order, and fill facts are linked.",
        ],
    }


__all__ = (
    "build_attribution_review_linkage_candidate",
    "payload_value",
    "preview_ref",
    "run_backtest_attribution_preview",
)
