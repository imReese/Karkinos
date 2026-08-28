"""Account strategy assignment routes — /api/account-strategy."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from server.models import (
    AccountStrategyAssignment,
    AccountStrategyAssignmentUpdate,
    AccountStrategyAttributionSummary,
    AccountStrategyContributionReport,
    AttributionReviewPrerequisite,
    HoldingStrategyAttributionReport,
)
from server.services.account_strategy_assignment import (
    ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY as _CONTROL_KEY,
)
from server.services.account_strategy_assignment import (
    ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION as _ASSIGNMENT_LIMITATION,
)
from server.services.account_strategy_assignment import (
    account_strategy_assignment_from_payload as _assignment_from_payload,
)
from server.services.account_strategy_assignment import (
    default_account_strategy_assignment as _default_assignment,
)
from server.services.account_strategy_evidence import fill_metadata as _fill_metadata
from server.services.account_strategy_evidence import (
    linked_strategy_evidence as _linked_strategy_evidence,
)
from server.services.account_strategy_evidence import (
    order_source_signal_id as _order_source_signal_id,
)
from server.services.account_strategy_evidence import same_symbol as _same_symbol
from server.services.account_strategy_evidence import (
    source_signal_id as _source_signal_id,
)
from server.services.account_strategy_projections import (
    build_attribution_summary as _canonical_attribution_summary,
)
from server.services.account_strategy_projections import (
    build_contribution_report as _canonical_contribution_report,
)

_ASSIGNMENT_REGISTRY_KEY = "instrument_strategy_assignments"
_HOLDING_ATTRIBUTION_LIMITATION = (
    "Holding-level strategy attribution is evidence-only until the linked fills "
    "are reviewed against the production ledger and valuation history."
)


def _assignment_update_payload(
    update: AccountStrategyAssignmentUpdate,
) -> dict[str, Any]:
    now = datetime.now().isoformat()
    strategy_id = update.strategy_id.strip() or "dual_ma"
    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_id,
        "status": update.status,
        "scope": update.scope,
        "asset_class": update.asset_class,
        "symbol": update.symbol,
        "effective_from": update.effective_from,
        "auto_trade_enabled": False,
        "attribution_status": "assignment_only",
        "attributed_pnl": None,
        "realized_pnl": None,
        "unrealized_pnl": None,
        "total_fees": None,
        "notes": update.notes,
        "updated_at": now,
        "limitations": [_ASSIGNMENT_LIMITATION],
    }


def _assignment_registry_from_payload(
    payload: object,
    *,
    fallback_config: Any,
) -> list[AccountStrategyAssignment]:
    raw_items: object
    if isinstance(payload, dict):
        raw_items = payload.get("assignments", [])
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        return []
    assignments: list[AccountStrategyAssignment] = []
    for item in raw_items:
        if isinstance(item, dict):
            assignments.append(
                _assignment_from_payload(item, fallback_config=fallback_config)
            )
    return sorted(assignments, key=_assignment_sort_key)


def _assignment_sort_key(assignment: AccountStrategyAssignment) -> tuple[str, str, str]:
    return (
        assignment.scope or "",
        assignment.asset_class or "",
        assignment.symbol or "",
    )


def _assignment_registry_key(
    assignment: AccountStrategyAssignment,
) -> tuple[str, str, str]:
    return (
        str(assignment.scope or "").strip().lower(),
        str(assignment.asset_class or "").strip().lower(),
        str(assignment.symbol or "").strip().lower(),
    )


def _validate_scoped_assignment(update: AccountStrategyAssignmentUpdate) -> None:
    scope = update.scope.strip().lower()
    if scope == "symbol" and not str(update.symbol or "").strip():
        raise HTTPException(status_code=400, detail="symbol is required")
    if scope == "asset_class" and not str(update.asset_class or "").strip():
        raise HTTPException(status_code=400, detail="asset_class is required")


def _upsert_assignment_registry(
    assignments: list[AccountStrategyAssignment],
    assignment: AccountStrategyAssignment,
) -> list[AccountStrategyAssignment]:
    target = _assignment_registry_key(assignment)
    merged = [
        existing
        for existing in assignments
        if _assignment_registry_key(existing) != target
    ]
    merged.append(assignment)
    return sorted(merged, key=_assignment_sort_key)


def _assignment_registry_payload(
    assignments: list[AccountStrategyAssignment],
) -> dict[str, Any]:
    return {"assignments": [assignment.model_dump() for assignment in assignments]}


def _scoped_assignment_for_symbol(
    assignments: list[AccountStrategyAssignment],
    *,
    symbol: str,
) -> AccountStrategyAssignment | None:
    for assignment in assignments:
        if assignment.scope == "symbol" and _same_symbol(assignment.symbol, symbol):
            return assignment
    return None


def _build_attribution_summary(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyAttributionSummary:
    return _canonical_attribution_summary(db, assignment)


def _build_attribution_review_prerequisites(
    *,
    signal_count: int,
    action_count: int,
    risk_decision_count: int,
    review_count: int,
    order_count: int,
    fill_count: int,
) -> list[AttributionReviewPrerequisite]:
    return [
        AttributionReviewPrerequisite(
            key="strategy_signal",
            passed=signal_count > 0,
            evidence_count=signal_count,
        ),
        AttributionReviewPrerequisite(
            key="candidate_action",
            passed=action_count > 0,
            evidence_count=action_count,
        ),
        AttributionReviewPrerequisite(
            key="risk_gate",
            passed=risk_decision_count > 0,
            evidence_count=risk_decision_count,
        ),
        AttributionReviewPrerequisite(
            key="manual_review",
            passed=review_count > 0,
            evidence_count=review_count,
        ),
        AttributionReviewPrerequisite(
            key="order_evidence",
            passed=order_count > 0,
            evidence_count=order_count,
        ),
        AttributionReviewPrerequisite(
            key="fill_evidence",
            passed=fill_count > 0,
            evidence_count=fill_count,
        ),
    ]


def _assignment_applies_to_symbol(
    assignment: AccountStrategyAssignment,
    *,
    symbol: str,
    signal_entries: list[dict[str, Any]],
    linked_fills: list[dict[str, Any]],
) -> bool:
    if assignment.scope == "symbol":
        return _same_symbol(assignment.symbol, symbol)
    if assignment.scope != "asset_class" or not assignment.asset_class:
        return True
    matching_asset_classes = {
        str((entry.get("signal") or {}).get("asset_class") or "")
        for entry in signal_entries
    }
    matching_asset_classes.update(
        str(fill.get("asset_class") or "") for fill in linked_fills
    )
    return assignment.asset_class in matching_asset_classes


def _build_holding_attribution_report(
    db: Any,
    assignment: AccountStrategyAssignment,
    *,
    symbol: str,
) -> HoldingStrategyAttributionReport:
    evidence = _linked_strategy_evidence(db, assignment)
    strategy_entries = [
        entry
        for entry in evidence["strategy_entries"]
        if _same_symbol((entry.get("signal") or {}).get("symbol"), symbol)
    ]
    signal_ids = {
        int(entry["signal"]["id"])
        for entry in strategy_entries
        if (entry.get("signal") or {}).get("id") is not None
    }
    risk_decisions = [
        entry.get("risk_decision")
        for entry in strategy_entries
        if entry.get("risk_decision") is not None
    ]
    risk_decision_ids = {
        str(risk["decision_id"])
        for risk in risk_decisions
        if risk and risk.get("decision_id")
    }
    intent_ids = {
        str(risk["intent_id"])
        for risk in risk_decisions
        if risk and risk.get("intent_id")
    }
    linked_orders = [
        order
        for order in evidence["linked_orders"]
        if _same_symbol(order.get("symbol"), symbol)
        or _order_source_signal_id(order) in signal_ids
        or order.get("risk_decision_id") in risk_decision_ids
        or order.get("intent_id") in intent_ids
    ]
    linked_order_ids = {str(order["order_id"]) for order in linked_orders}
    linked_fills = [
        fill
        for fill in evidence["linked_fills"]
        if _same_symbol(fill.get("symbol"), symbol)
        and (
            str(fill.get("order_id")) in linked_order_ids
            or _source_signal_id(
                _fill_metadata(fill).get("source_signal_id")
                or _fill_metadata(fill).get("signal_id")
            )
            in signal_ids
        )
    ]
    assignment_applies = _assignment_applies_to_symbol(
        assignment,
        symbol=symbol,
        signal_entries=strategy_entries,
        linked_fills=linked_fills,
    )

    if not assignment_applies:
        status = "assignment_not_applicable"
        limitations = [
            "The current strategy assignment does not apply to this holding."
        ]
    elif linked_fills:
        status = "holding_evidence_linked_review_required"
        limitations = [_HOLDING_ATTRIBUTION_LIMITATION]
    elif linked_orders:
        status = "holding_orders_linked_no_fills"
        limitations = [
            "Orders are linked for this holding, but no fills are available."
        ]
    elif strategy_entries:
        status = "holding_signal_chain_pending"
        limitations = [
            "Signals exist for this holding, but order/fill evidence is not linked yet."
        ]
    else:
        status = "not_started"
        limitations = [_ASSIGNMENT_LIMITATION]

    action_refs = sorted(
        {
            f"action:{entry['action_task']['id']}"
            for entry in strategy_entries
            if entry.get("action_task") and entry["action_task"].get("id") is not None
        }
    )
    risk_refs = sorted(
        {
            f"risk:{risk['decision_id']}"
            for risk in risk_decisions
            if risk and risk.get("decision_id")
        }
    )
    review_refs = sorted(
        {
            f"review:{entry['review']['signal_id']}"
            for entry in strategy_entries
            if entry.get("review") and entry["review"].get("signal_id") is not None
        }
    )
    evidence_refs = [
        *(f"signal:{signal_id}" for signal_id in sorted(signal_ids)),
        *action_refs,
        *risk_refs,
        *review_refs,
        *(f"order:{order['order_id']}" for order in linked_orders),
        *(f"fill:{fill['fill_id']}" for fill in linked_fills),
    ]
    signal_count = len(strategy_entries) if assignment_applies else 0
    action_count = (
        sum(1 for entry in strategy_entries if entry.get("action_task"))
        if assignment_applies
        else 0
    )
    risk_decision_count = len(risk_decisions) if assignment_applies else 0
    review_count = len(review_refs) if assignment_applies else 0
    order_count = len(linked_orders) if assignment_applies else 0
    fill_count = len(linked_fills) if assignment_applies else 0
    return HoldingStrategyAttributionReport(
        strategy_id=assignment.strategy_id,
        symbol=symbol,
        assignment_scope=assignment.scope,
        assignment_applies_to_symbol=assignment_applies,
        attribution_status=status,
        signal_count=signal_count,
        action_count=action_count,
        risk_decision_count=risk_decision_count,
        order_count=order_count,
        fill_count=fill_count,
        evidence_refs=evidence_refs if assignment_applies else [],
        review_prerequisites=_build_attribution_review_prerequisites(
            signal_count=signal_count,
            action_count=action_count,
            risk_decision_count=risk_decision_count,
            review_count=review_count,
            order_count=order_count,
            fill_count=fill_count,
        ),
        limitations=limitations,
    )


def _build_contribution_report(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyContributionReport:
    return _canonical_contribution_report(db, assignment)


def build_attribution_summary(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyAttributionSummary:
    """Compatibility port for non-HTTP composition callers."""

    return _build_attribution_summary(db, assignment)


def build_contribution_report(
    db: Any,
    assignment: AccountStrategyAssignment,
) -> AccountStrategyContributionReport:
    """Compatibility port for non-HTTP composition callers."""

    return _build_contribution_report(db, assignment)


def _account_strategy_contribution_for_state(
    state: Any,
) -> AccountStrategyContributionReport:
    db = getattr(state, "db", None)
    reader = getattr(db, "get_runtime_control_sync", None)
    payload = reader(_CONTROL_KEY) if callable(reader) else None
    assignment = (
        _assignment_from_payload(payload, fallback_config=state.config)
        if isinstance(payload, dict)
        else _default_assignment(state.config)
    )
    return _build_contribution_report(db, assignment)


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/account-strategy", tags=["account-strategy"])

    @r.get("", response_model=AccountStrategyAssignment)
    async def get_account_strategy() -> AccountStrategyAssignment:
        """Read the current research-only account strategy assignment."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_CONTROL_KEY) if callable(reader) else None
        if not isinstance(payload, dict):
            return _default_assignment(state.config)
        return _assignment_from_payload(payload, fallback_config=state.config)

    @r.get("/assignments", response_model=list[AccountStrategyAssignment])
    async def list_account_strategy_assignments() -> list[AccountStrategyAssignment]:
        """List symbol/asset-class strategy assignments for research context."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_ASSIGNMENT_REGISTRY_KEY) if callable(reader) else None
        return _assignment_registry_from_payload(
            payload,
            fallback_config=state.config,
        )

    @r.get("/attribution", response_model=AccountStrategyAttributionSummary)
    async def get_account_strategy_attribution() -> AccountStrategyAttributionSummary:
        """Summarize attribution evidence without mutating account facts."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_CONTROL_KEY) if callable(reader) else None
        assignment = (
            _assignment_from_payload(payload, fallback_config=state.config)
            if isinstance(payload, dict)
            else _default_assignment(state.config)
        )
        return _build_attribution_summary(db, assignment)

    @r.get("/contribution", response_model=AccountStrategyContributionReport)
    async def get_account_strategy_contribution() -> AccountStrategyContributionReport:
        """Estimate strategy contribution from linked fills without mutating facts."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return await asyncio.to_thread(
            _account_strategy_contribution_for_state,
            state,
        )

    @r.get(
        "/holdings/{symbol}/attribution",
        response_model=HoldingStrategyAttributionReport,
    )
    async def get_holding_strategy_attribution(
        symbol: str,
    ) -> HoldingStrategyAttributionReport:
        """Read symbol-filtered strategy attribution evidence without mutation."""
        from server.dependencies import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        payload = reader(_CONTROL_KEY) if callable(reader) else None
        assignment = (
            _assignment_from_payload(payload, fallback_config=state.config)
            if isinstance(payload, dict)
            else _default_assignment(state.config)
        )
        registry_payload = (
            reader(_ASSIGNMENT_REGISTRY_KEY) if callable(reader) else None
        )
        scoped_assignment = _scoped_assignment_for_symbol(
            _assignment_registry_from_payload(
                registry_payload,
                fallback_config=state.config,
            ),
            symbol=symbol,
        )
        if scoped_assignment is not None:
            assignment = scoped_assignment
        return _build_holding_attribution_report(db, assignment, symbol=symbol)

    @r.put("", response_model=AccountStrategyAssignment)
    async def update_account_strategy(
        update: AccountStrategyAssignmentUpdate,
    ) -> AccountStrategyAssignment:
        """Persist a research-only account strategy assignment."""
        from server.dependencies import get_app_state

        state = get_app_state()
        payload = _assignment_update_payload(update)
        db = getattr(state, "db", None)
        writer = getattr(db, "set_runtime_control_sync", None)
        if callable(writer):
            writer(_CONTROL_KEY, payload)
        return _assignment_from_payload(payload, fallback_config=state.config)

    @r.put("/assignments", response_model=AccountStrategyAssignment)
    async def upsert_account_strategy_assignment(
        update: AccountStrategyAssignmentUpdate,
    ) -> AccountStrategyAssignment:
        """Persist a scoped research-only strategy assignment."""
        from server.dependencies import get_app_state

        _validate_scoped_assignment(update)
        state = get_app_state()
        db = getattr(state, "db", None)
        reader = getattr(db, "get_runtime_control_sync", None)
        writer = getattr(db, "set_runtime_control_sync", None)
        payload = _assignment_update_payload(update)
        assignment = _assignment_from_payload(payload, fallback_config=state.config)
        existing_payload = (
            reader(_ASSIGNMENT_REGISTRY_KEY) if callable(reader) else None
        )
        assignments = _upsert_assignment_registry(
            _assignment_registry_from_payload(
                existing_payload,
                fallback_config=state.config,
            ),
            assignment,
        )
        if callable(writer):
            writer(_ASSIGNMENT_REGISTRY_KEY, _assignment_registry_payload(assignments))
        return assignment

    return r
