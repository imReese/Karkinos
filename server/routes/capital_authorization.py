"""Non-submitting capital-authorization preview and audit routes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.capital_authorization import (
    CAPITAL_AUTHORIZATION_SCHEMA_VERSION,
    CapitalAuthorizationContext,
    CapitalAuthorizationLimits,
    CapitalAuthorizationPolicy,
)
from server.services.capital_authorization_audit import (
    CapitalAuthorizationAuditService,
)
from server.services.operator_approval import (
    DEFAULT_CHALLENGE_TTL_SECONDS,
    OperatorApprovalRejected,
    OperatorApprovalService,
)


class CapitalAuthorizationLimitsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_authorized_capital: Decimal
    max_order_value: Decimal
    max_position_change_value: Decimal
    max_daily_turnover: Decimal
    max_daily_loss: Decimal
    max_drawdown_pct: Decimal
    max_order_rate_per_minute: int
    max_consecutive_errors: int

    def to_domain(self) -> CapitalAuthorizationLimits:
        return CapitalAuthorizationLimits(**self.model_dump())


class CapitalAuthorizationPolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_id: str = ""
    policy_version: str = ""
    mode: str = "disabled"
    enabled: bool = False
    authorized_by: str = ""
    connector_ids: list[str] = Field(default_factory=list)
    evidence_connector_ids: list[str] = Field(default_factory=list)
    execution_gateway_ids: list[str] = Field(default_factory=list)
    account_aliases: list[str] = Field(default_factory=list)
    strategy_ids: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    limits: CapitalAuthorizationLimitsPayload
    evidence_refs: list[str] = Field(default_factory=list)
    schema_version: str = CAPITAL_AUTHORIZATION_SCHEMA_VERSION

    def to_domain(self) -> CapitalAuthorizationPolicy:
        data = self.model_dump(
            exclude={
                "limits",
                "connector_ids",
                "evidence_connector_ids",
                "execution_gateway_ids",
                "account_aliases",
                "strategy_ids",
                "symbols",
                "evidence_refs",
            }
        )
        return CapitalAuthorizationPolicy(
            **data,
            connector_ids=tuple(self.connector_ids),
            evidence_connector_ids=tuple(self.evidence_connector_ids),
            execution_gateway_ids=tuple(self.execution_gateway_ids),
            account_aliases=tuple(self.account_aliases),
            strategy_ids=tuple(self.strategy_ids),
            symbols=tuple(self.symbols),
            limits=self.limits.to_domain(),
            evidence_refs=tuple(self.evidence_refs),
        )


class CapitalAuthorizationContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime
    connector_id: str
    account_alias: str
    strategy_id: str
    symbol: str
    order_value: Decimal
    position_change_value: Decimal
    current_authorized_exposure: Decimal
    daily_turnover_used: Decimal
    current_daily_loss: Decimal
    current_drawdown_pct: Decimal
    order_rate_per_minute: int
    consecutive_errors: int
    available_cash: Decimal
    account_capital_limit: Decimal
    strategy_capital_limit: Decimal
    symbol_capital_limit: Decimal
    liquidity_capital_limit: Decimal
    market_data_status: str
    account_truth_status: str
    risk_gate_status: str
    paper_shadow_status: str
    reconciliation_status: str
    connector_health_status: str
    connector_can_submit: bool
    kill_switch_enabled: bool
    order_fingerprint: str = ""
    manual_confirmation_fingerprint: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_connector_id: str
    execution_gateway_id: str
    evidence_connector_health_status: str
    evidence_connector_can_submit: bool = False
    execution_gateway_health_status: str
    execution_gateway_can_submit: bool = False
    connector_account_binding_status: str

    def to_domain(self) -> CapitalAuthorizationContext:
        data = self.model_dump(exclude={"evidence_refs"})
        return CapitalAuthorizationContext(
            **data,
            evidence_refs=tuple(self.evidence_refs),
        )


class CapitalAuthorizationEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: CapitalAuthorizationPolicyPayload
    context: CapitalAuthorizationContextPayload

    def to_domain(
        self,
    ) -> tuple[CapitalAuthorizationPolicy, CapitalAuthorizationContext]:
        return self.policy.to_domain(), self.context.to_domain()


class OperatorApprovalChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    key_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    action: Literal[
        "attest_per_order_dossier",
        "attest_controlled_session_envelope",
        "accept_broker_connector_soak_promotion",
    ]
    artifact_type: Literal[
        "per_order_dossier",
        "controlled_session_envelope",
        "broker_connector_soak_promotion_dossier",
    ]
    artifact_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    ttl_seconds: int = Field(
        default=DEFAULT_CHALLENGE_TTL_SECONDS,
        ge=30,
        le=300,
    )


class OperatorApprovalVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    signature_base64: str = Field(min_length=80, max_length=128)


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/capital-authority",
        tags=["automation", "capital-authority"],
    )

    @router.get("/status")
    async def get_capital_authority_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/preview")
    async def preview_capital_authorization(
        request: CapitalAuthorizationEvaluationRequest,
    ) -> dict[str, Any]:
        policy, context = request.to_domain()
        return _service().preview(policy=policy, context=context)

    @router.post("/evaluations")
    async def record_capital_authorization_evaluation(
        request: CapitalAuthorizationEvaluationRequest,
    ) -> dict[str, Any]:
        policy, context = request.to_domain()
        return _service().record_evaluation(policy=policy, context=context)

    @router.get("/evaluations")
    async def list_capital_authorization_evaluations(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return _service().list_evaluations(limit=limit)

    @router.get("/operator-approvals/status")
    async def get_operator_approval_status() -> dict[str, Any]:
        return _operator_approval_service().get_status()

    @router.post("/operator-approvals/challenges")
    async def create_operator_approval_challenge(
        request: OperatorApprovalChallengeRequest,
    ) -> dict[str, Any]:
        try:
            return _operator_approval_service().create_challenge(
                operator_id=request.operator_id,
                key_id=request.key_id,
                action=request.action,
                artifact_type=request.artifact_type,
                artifact_fingerprint=request.artifact_fingerprint,
                ttl_seconds=request.ttl_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/operator-approvals/challenges")
    async def list_operator_approval_challenges(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _operator_approval_service().list_challenges(limit=limit)

    @router.post("/operator-approvals/verifications")
    async def verify_operator_approval_signature(
        request: OperatorApprovalVerificationRequest,
    ) -> dict[str, Any]:
        try:
            return _operator_approval_service().verify_signature(
                challenge_id=request.challenge_id,
                signature_base64=request.signature_base64,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OperatorApprovalRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/operator-approvals")
    async def list_operator_approvals(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _operator_approval_service().list_approvals(limit=limit)

    return router


def _service() -> CapitalAuthorizationAuditService:
    from server.app import get_app_state

    state = get_app_state()
    return CapitalAuthorizationAuditService(db=state.db)


def _operator_approval_service() -> OperatorApprovalService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    trusted_identities = getattr(config, "trusted_operator_identities", []) or []
    return OperatorApprovalService(
        db=state.db,
        trusted_identities=trusted_identities,
    )
