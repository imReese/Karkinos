"""HTTP delivery for persisted AI shadow-research automation commands."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.ai_runtime.strategy_research import (
    STRATEGY_RESEARCH_MAX_CANDIDATES,
    STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
)
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
)


class ShadowResearchPolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    after_close_time: str = Field(default="15:30", min_length=5, max_length=5)
    max_provider_calls_per_market_date: int = Field(
        default=STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
        ge=1,
        le=STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
    )
    daily_token_budget: int | None = None
    token_budget_mode: Literal["unbounded_daily", "legacy_bounded_daily"] = (
        "unbounded_daily"
    )
    max_candidates_per_run: int = Field(
        default=STRATEGY_RESEARCH_MAX_CANDIDATES,
        ge=1,
        le=STRATEGY_RESEARCH_MAX_CANDIDATES,
    )
    baseline_backtest_result_id: int | None = Field(default=None, gt=0)
    research_capital_mode: Literal["normalized_notional", "account_bound"] = (
        SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
    )
    require_complete_account_evidence: bool = False
    research_question: str = Field(min_length=1, max_length=4_000)
    updated_by: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_sequential_iteration_budget(self) -> "ShadowResearchPolicyPayload":
        required_calls = self.max_candidates_per_run * 2
        if self.max_provider_calls_per_market_date < required_calls:
            raise ValueError(
                "max_provider_calls_per_market_date must cover one generation "
                "and one critique per sequential iteration"
            )
        if self.daily_token_budget is not None:
            if self.token_budget_mode != "legacy_bounded_daily":
                raise ValueError(
                    "daily_token_budget requires legacy_bounded_daily token mode"
                )
        elif self.token_budget_mode != "unbounded_daily":
            raise ValueError("token_budget_mode requires a daily_token_budget")
        if self.require_complete_account_evidence != (
            self.research_capital_mode == SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND
        ):
            raise ValueError(
                "research_capital_mode conflicts with account evidence requirement"
            )
        return self


class ShadowResearchPromotionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "approve_evidence_bound_candidate_for_paper_shadow_only_without_"
        "production_or_trade_authority"
    ]


class ShadowResearchRetryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "authorize_one_additional_complete_five_round_ten_call_strategy_"
        "research_retry_without_strategy_trade_or_capital_authority"
    ]


class ShadowResearchCorrectedPanelRearmPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "authorize_one_corrected_full_market_40_stock_panel_five_round_ten_call_"
        "research_without_strategy_trade_or_capital_authority"
    ]


class ShadowResearchCitationCallExtensionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "authorize_one_additional_deepseek_call_for_citation_contract_retry_"
        "without_strategy_trade_or_capital_authority"
    ]


class ShadowResearchCorrectedPanelCitationResumePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "authorize_one_additional_deepseek_call_for_corrected_panel_first_"
        "critique_citation_resume_without_strategy_trade_or_capital_authority"
    ]


class ShadowResearchOutputTruncationCallExtensionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "authorize_one_additional_deepseek_call_for_output_truncation_retry_"
        "without_strategy_trade_or_capital_authority"
    ]


class ShadowResearchTimeoutResumeCallExtensionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "authorize_one_additional_deepseek_call_for_partial_fifth_round_timeout_"
        "resume_without_strategy_trade_or_capital_authority"
    ]


def create_router(
    *,
    build_write_service: Callable[[Any], Any],
    build_job_scheduler: Callable[[Any], Any],
    build_read_service: Callable[[Any], Any],
    raise_http: Callable[[Exception], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/ai/strategy-research", tags=["ai-research"])

    @router.get("/shadow-automation")
    async def get_shadow_research_automation() -> dict[str, Any]:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        return build_read_service(state).status()

    @router.get("/shadow-automation/readiness")
    async def get_shadow_research_readiness() -> dict[str, Any]:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        return build_read_service(state).readiness_status()

    @router.get("/shadow-automation/worker-jobs")
    async def get_shadow_research_worker_jobs() -> dict[str, Any]:
        from server.composition.ai_shadow_research_automation import (
            read_ai_shadow_research_worker_status,
        )
        from server.dependencies import get_app_state

        return read_ai_shadow_research_worker_status(get_app_state())

    @router.put("/shadow-automation/policy")
    async def update_shadow_research_policy(
        payload: ShadowResearchPolicyPayload,
    ) -> dict[str, Any]:
        from server.dependencies import get_app_state

        try:
            return build_write_service(get_app_state()).update_policy(
                payload.model_dump(mode="json")
            )
        except Exception as exc:
            raise_http(exc)

    @router.post("/shadow-automation/run")
    async def run_shadow_research_now() -> dict[str, Any]:
        from server.dependencies import get_app_state

        try:
            result = await asyncio.to_thread(
                build_job_scheduler(get_app_state()).enqueue_if_authorized
            )
            return JSONResponse(status_code=202, content=result)
        except Exception as exc:
            raise_http(exc)

    def authorization(path: str, method: str, payload_type: type[BaseModel]) -> None:
        async def endpoint(run_id: str, payload: Any) -> JSONResponse:
            from server.dependencies import get_app_state

            try:
                service = build_write_service(get_app_state())
                operation = getattr(service, method)
                result = operation(
                    run_id,
                    approved_by=payload.approved_by,
                    notes=payload.notes,
                    confirmation=payload.confirmation,
                )
                if hasattr(result, "__await__"):
                    result = await result
                return JSONResponse(status_code=201, content=result)
            except Exception as exc:
                raise_http(exc)

        endpoint.__annotations__["payload"] = payload_type
        router.add_api_route(path, endpoint, methods=["POST"])

    authorization(
        "/shadow-automation/runs/{run_id}/retry-authorizations",
        "authorize_retry",
        ShadowResearchRetryPayload,
    )
    authorization(
        "/shadow-automation/runs/{run_id}/corrected-panel-rearm-authorizations",
        "authorize_corrected_panel_rearm",
        ShadowResearchCorrectedPanelRearmPayload,
    )
    authorization(
        "/shadow-automation/runs/{run_id}/citation-call-extensions",
        "authorize_citation_call_extension",
        ShadowResearchCitationCallExtensionPayload,
    )
    authorization(
        "/shadow-automation/runs/{run_id}/corrected-panel-citation-resume-extensions",
        "authorize_corrected_panel_citation_resume_extension",
        ShadowResearchCorrectedPanelCitationResumePayload,
    )
    authorization(
        "/shadow-automation/runs/{run_id}/output-truncation-call-extensions",
        "authorize_output_truncation_call_extension",
        ShadowResearchOutputTruncationCallExtensionPayload,
    )
    authorization(
        "/shadow-automation/runs/{run_id}/timeout-resume-call-extensions",
        "authorize_timeout_resume_call_extension",
        ShadowResearchTimeoutResumeCallExtensionPayload,
    )

    @router.post("/shadow-candidates/{candidate_id}/paper-shadow-approvals")
    async def approve_shadow_research_candidate(
        candidate_id: str,
        payload: ShadowResearchPromotionPayload,
    ) -> JSONResponse:
        from server.dependencies import get_app_state

        try:
            result = build_write_service(get_app_state()).approve_candidate(
                candidate_id,
                approved_by=payload.approved_by,
                notes=payload.notes,
                confirmation=payload.confirmation,
            )
            return JSONResponse(status_code=201, content=result)
        except Exception as exc:
            raise_http(exc)

    return router


__all__ = [
    "ShadowResearchCitationCallExtensionPayload",
    "ShadowResearchCorrectedPanelCitationResumePayload",
    "ShadowResearchCorrectedPanelRearmPayload",
    "ShadowResearchOutputTruncationCallExtensionPayload",
    "ShadowResearchPolicyPayload",
    "ShadowResearchPromotionPayload",
    "ShadowResearchRetryPayload",
    "ShadowResearchTimeoutResumeCallExtensionPayload",
    "create_router",
]
