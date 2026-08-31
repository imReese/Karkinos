"""Single ownership point for HTTP/WebSocket router composition and order."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import APIRouter, FastAPI

from server.routes import (
    acceptance_audit,
    account_strategy,
    account_truth,
    ai_external_analysis_reviews,
    ai_external_memory_informed_analyses,
    ai_external_promoted_analysis_memory,
    ai_external_promoted_analysis_memory_retrievals,
    ai_external_promoted_memory_analyses,
    ai_external_promoted_memory_analysis_reviews,
    ai_external_research,
    ai_external_reviewed_memory,
    ai_external_reviewed_memory_retrievals,
    ai_memory_informed_analyses,
    ai_provider_connectivity,
    ai_research,
    ai_research_task_analyses,
    ai_research_task_analysis_reviews,
    ai_research_tasks,
    ai_reviewed_memory_retrievals,
    ai_strategy_research,
    automation,
    backtest,
    broker_connector_soak,
    broker_gateway,
    capital_authorization,
    capital_scaling_review,
    controlled_broker_submission,
    controlled_broker_write_release,
    controlled_session_automatic_pause,
    controlled_session_budget_reservation,
    controlled_session_envelope,
    controlled_session_runtime_authority,
    controlled_session_runtime_rate_limiter,
    controlled_submission_ledger_correction,
    controlled_submission_ledger_posting,
    decision,
    execution_gateway_verification,
    execution_reconciliation,
    ledger,
    market,
    operations,
    per_order_confirmation,
    portfolio,
    service_health,
    session_start_account_truth,
    settings,
    signals,
    signed_broker_adapter_release_review,
    strategy_learning,
    strategy_promotion,
    trading,
)
from server.ws.handlers import router as websocket_router

RouterFactory = Callable[[], APIRouter]


def _aggregate(factories: Iterable[RouterFactory]) -> APIRouter:
    router = APIRouter()
    for factory in factories:
        router.include_router(factory())
    return router


def build_external_research_router() -> APIRouter:
    """Preserve the legacy external-report then strategy-research order."""

    return _aggregate(
        (
            ai_external_research.create_router,
            ai_strategy_research.create_router,
        )
    )


def build_memory_informed_analysis_router() -> APIRouter:
    """Compose the versioned reviewed-memory workflow in its original order."""

    return _aggregate(
        (
            ai_external_analysis_reviews.create_router,
            ai_external_promoted_analysis_memory_retrievals.create_router,
            ai_external_promoted_analysis_memory.create_router,
            ai_external_promoted_memory_analysis_reviews.create_router,
            ai_external_promoted_memory_analyses.create_router,
            ai_external_reviewed_memory_retrievals.create_router,
            ai_external_reviewed_memory.create_router,
            ai_external_memory_informed_analyses.create_router,
            ai_memory_informed_analyses.create_router,
        )
    )


def router_factories() -> tuple[RouterFactory, ...]:
    """Return factories in the stable public route-registration order."""

    return (
        service_health.create_router,
        market.create_router,
        acceptance_audit.create_router,
        account_strategy.create_router,
        account_truth.create_router,
        build_external_research_router,
        build_memory_informed_analysis_router,
        ai_provider_connectivity.create_router,
        ai_research.create_router,
        ai_reviewed_memory_retrievals.create_router,
        ai_research_task_analysis_reviews.create_router,
        ai_research_task_analyses.create_router,
        ai_research_tasks.create_router,
        automation.create_router,
        broker_gateway.create_router,
        broker_connector_soak.create_router,
        signed_broker_adapter_release_review.create_router,
        capital_authorization.create_router,
        capital_scaling_review.create_router,
        controlled_broker_submission.create_router,
        controlled_broker_write_release.create_router,
        controlled_submission_ledger_posting.create_router,
        controlled_submission_ledger_correction.create_router,
        controlled_session_envelope.create_router,
        controlled_session_budget_reservation.create_router,
        controlled_session_runtime_authority.create_router,
        controlled_session_runtime_rate_limiter.create_router,
        controlled_session_automatic_pause.create_router,
        execution_reconciliation.create_router,
        execution_gateway_verification.create_router,
        ledger.create_router,
        operations.create_router,
        per_order_confirmation.create_router,
        session_start_account_truth.create_router,
        portfolio.create_router,
        signals.create_router,
        decision.create_router,
        strategy_learning.create_router,
        strategy_promotion.create_router,
        backtest.create_router,
        settings.create_router,
        trading.create_router,
    )


def install_routers(app: FastAPI) -> None:
    for factory in router_factories():
        app.include_router(factory())
    app.include_router(websocket_router)
