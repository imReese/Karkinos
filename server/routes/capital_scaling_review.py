"""Evidence-only capital scaling review routes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.account_truth_gate import build_latest_account_truth_score_payload
from server.services.capital_scaling_evidence_window import (
    CapitalScalingEvidenceWindowService,
)
from server.services.capital_scaling_review import (
    CapitalScalingEvidence,
    CapitalScalingReview,
    CapitalScalingTier,
    CapitalScalingTierLimits,
)
from server.services.capital_scaling_review_audit import (
    CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    CapitalScalingReviewAuditService,
    CapitalScalingReviewDecisionRejected,
)


class CapitalScalingTierLimitsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_authorized_capital: Decimal
    max_order_value: Decimal
    max_daily_turnover: Decimal
    max_daily_loss: Decimal
    max_drawdown_pct: Decimal

    def to_domain(self) -> CapitalScalingTierLimits:
        return CapitalScalingTierLimits(**self.model_dump())


class CapitalScalingTierPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier_id: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    limits: CapitalScalingTierLimitsPayload

    def to_domain(self) -> CapitalScalingTier:
        return CapitalScalingTier(
            tier_id=self.tier_id,
            policy_version=self.policy_version,
            limits=self.limits.to_domain(),
        )


class CapitalScalingEvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_window_start: datetime
    review_window_end: datetime
    reviewed_trading_days: int
    order_count: int
    filled_order_count: int
    rejected_order_count: int
    partial_fill_count: int
    critical_incident_count: int
    policy_violation_count: int
    unresolved_reconciliation_count: int
    p95_reconciliation_latency_minutes: Decimal
    average_slippage_bps: Decimal
    p95_slippage_bps: Decimal
    after_cost_return_pct: Decimal
    max_drawdown_pct: Decimal
    capacity_utilization_pct: Decimal
    liquidity_utilization_pct: Decimal
    paper_shadow_divergence_count: int
    broker_disconnect_count: int
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)

    def to_domain(self) -> CapitalScalingEvidence:
        data = self.model_dump(exclude={"evidence_refs"})
        return CapitalScalingEvidence(
            **data,
            evidence_refs=tuple(self.evidence_refs),
        )


class CapitalScalingReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_tier: CapitalScalingTierPayload
    proposed_tier: CapitalScalingTierPayload
    evidence: CapitalScalingEvidencePayload

    def to_domain(self) -> CapitalScalingReview:
        return CapitalScalingReview(
            current_tier=self.current_tier.to_domain(),
            proposed_tier=self.proposed_tier.to_domain(),
            evidence=self.evidence.to_domain(),
        )


class CapitalScalingHumanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    chosen_action: Literal[
        "request_new_authorization_for_scale_up",
        "hold",
        "scale_down",
        "disable",
    ]
    operator_label: str = Field(min_length=1, max_length=128)
    acknowledgement: Literal[
        "record_scaling_review_decision_without_authority_change"
    ] = CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT


class CapitalScalingEvidenceWindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_window_start: datetime
    review_window_end: datetime
    max_boundary_gap_hours: int = Field(default=72, ge=1, le=168)


class CapitalScalingAccountTruthSnapshotRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledgement: Literal["record_read_only_account_truth_snapshot"] = (
        "record_read_only_account_truth_snapshot"
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/capital-scaling",
        tags=["automation", "capital-scaling", "evidence-review"],
    )

    @router.get("/status")
    async def get_capital_scaling_review_status() -> dict[str, Any]:
        return _service().get_status()

    @router.get("/evidence/status")
    async def get_capital_scaling_evidence_status() -> dict[str, Any]:
        return _evidence_service().get_status()

    @router.get("/evidence/account-truth-snapshots/preview")
    async def preview_capital_scaling_account_truth_snapshot() -> dict[str, Any]:
        return _evidence_service().preview_account_truth_snapshot()

    @router.post("/evidence/account-truth-snapshots")
    async def record_capital_scaling_account_truth_snapshot(
        request: CapitalScalingAccountTruthSnapshotRecordRequest,
    ) -> dict[str, Any]:
        del request
        return _evidence_service().record_account_truth_snapshot()

    @router.get("/evidence/account-truth-snapshots")
    async def list_capital_scaling_account_truth_snapshots(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _evidence_service().list_account_truth_snapshots(limit=limit)

    @router.post("/evidence/windows/preview")
    async def preview_capital_scaling_evidence_window(
        request: CapitalScalingEvidenceWindowRequest,
    ) -> dict[str, Any]:
        try:
            return _evidence_service().preview_window(**request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/evidence/windows")
    async def record_capital_scaling_evidence_window(
        request: CapitalScalingEvidenceWindowRequest,
    ) -> dict[str, Any]:
        try:
            return _evidence_service().record_window(**request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/evidence/windows")
    async def list_capital_scaling_evidence_windows(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _evidence_service().list_windows(limit=limit)

    @router.post("/reviews/preview")
    async def preview_capital_scaling_review(
        request: CapitalScalingReviewRequest,
    ) -> dict[str, Any]:
        return _service().preview(review=request.to_domain())

    @router.post("/reviews/evaluations")
    async def record_capital_scaling_evaluation(
        request: CapitalScalingReviewRequest,
    ) -> dict[str, Any]:
        return _service().record_evaluation(review=request.to_domain())

    @router.get("/reviews/evaluations")
    async def list_capital_scaling_evaluations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_evaluations(limit=limit)

    @router.post("/reviews/decisions")
    async def record_capital_scaling_human_decision(
        request: CapitalScalingHumanDecisionRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record_review_decision(
                evaluation_fingerprint=request.evaluation_fingerprint,
                chosen_action=request.chosen_action,
                operator_label=request.operator_label,
                acknowledgement=request.acknowledgement,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CapitalScalingReviewDecisionRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/reviews/decisions")
    async def list_capital_scaling_human_decisions(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_review_decisions(limit=limit)

    return router


def _service() -> CapitalScalingReviewAuditService:
    from server.app import get_app_state

    return CapitalScalingReviewAuditService(db=get_app_state().db)


def _evidence_service() -> CapitalScalingEvidenceWindowService:
    from server.app import get_app_state

    state = get_app_state()
    return CapitalScalingEvidenceWindowService(
        db=state.db,
        account_truth_provider=lambda: build_latest_account_truth_score_payload(state),
    )
