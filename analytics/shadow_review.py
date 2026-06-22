"""Shadow review comparison evidence for strategy, paper, and account facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

SHADOW_REVIEW_SCHEMA_VERSION = "karkinos.shadow_review.v1"


@dataclass(frozen=True)
class StrategyCandidateEvidence:
    """Strategy candidate action captured before paper/shadow review."""

    candidate_id: str
    strategy_id: str
    symbol: str
    action: str
    quantity: Decimal
    reference_price: Decimal
    signal_id: str | None = None
    risk_decision_id: str | None = None


@dataclass(frozen=True)
class PaperOutcomeEvidence:
    """Paper order/fill outcome generated from a strategy candidate."""

    candidate_id: str
    order_id: str
    strategy_id: str
    symbol: str
    side: str
    status: str
    filled_quantity: Decimal
    average_fill_price: Decimal
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    fill_id: str | None = None


@dataclass(frozen=True)
class RealAccountMovementEvidence:
    """Read-only account movement evidence used for shadow review."""

    movement_id: str
    symbol: str
    quantity_delta: Decimal
    cash_delta: Decimal
    source: str
    source_ref: str | None = None
    linked_candidate_id: str | None = None
    linked_order_id: str | None = None
    linked_strategy_id: str | None = None


@dataclass(frozen=True)
class ShadowReviewItem:
    """One comparison row in a shadow review report."""

    item_key: str
    review_status: str
    symbol: str | None
    strategy_id: str | None
    attributed_to_strategy: bool
    attributed_strategy_id: str | None
    paper_quantity_delta: Decimal | None
    real_quantity_delta: Decimal | None
    quantity_difference: Decimal | None
    paper_cash_delta: Decimal | None
    real_cash_delta: Decimal | None
    cash_difference: Decimal | None
    severity: str
    suggested_action: str
    evidence_refs: dict[str, str]
    limitations: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "review_status": self.review_status,
            "symbol": self.symbol,
            "strategy_id": self.strategy_id,
            "attributed_to_strategy": self.attributed_to_strategy,
            "attributed_strategy_id": self.attributed_strategy_id,
            "paper_quantity_delta": _decimal_text(self.paper_quantity_delta),
            "real_quantity_delta": _decimal_text(self.real_quantity_delta),
            "quantity_difference": _decimal_text(self.quantity_difference),
            "paper_cash_delta": _decimal_text(self.paper_cash_delta),
            "real_cash_delta": _decimal_text(self.real_cash_delta),
            "cash_difference": _decimal_text(self.cash_difference),
            "severity": self.severity,
            "suggested_action": self.suggested_action,
            "evidence_refs": dict(self.evidence_refs),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class ShadowReviewReport:
    """Shadow review report that never mutates account facts."""

    items: tuple[ShadowReviewItem, ...]
    schema_version: str = SHADOW_REVIEW_SCHEMA_VERSION
    does_not_mutate_account_facts: bool = True

    @property
    def candidate_count(self) -> int:
        return sum(1 for item in self.items if item.item_key.startswith("candidate:"))

    @property
    def unsupported_real_movement_count(self) -> int:
        return sum(
            1
            for item in self.items
            if item.review_status == "unsupported_real_movement"
        )

    @property
    def supported_match_count(self) -> int:
        return sum(1 for item in self.items if item.attributed_to_strategy)

    @property
    def limitations(self) -> tuple[str, ...]:
        return (
            "Shadow review is audit evidence, not investment advice.",
            "Unsupported account movement is never attributed to a strategy "
            "without explicit candidate, paper-order, and strategy references.",
            "This report does not mutate account facts, ledger entries, or "
            "broker orders.",
        )

    def item_by_key(self, item_key: str) -> ShadowReviewItem:
        for item in self.items:
            if item.item_key == item_key:
                return item
        raise KeyError(item_key)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "does_not_mutate_account_facts": self.does_not_mutate_account_facts,
            "candidate_count": self.candidate_count,
            "supported_match_count": self.supported_match_count,
            "unsupported_real_movement_count": self.unsupported_real_movement_count,
            "items": [item.to_json_dict() for item in self.items],
            "limitations": list(self.limitations),
        }


def build_shadow_review_report(
    *,
    candidates: Iterable[StrategyCandidateEvidence],
    paper_outcomes: Iterable[PaperOutcomeEvidence],
    real_movements: Iterable[RealAccountMovementEvidence],
) -> ShadowReviewReport:
    """Compare strategy candidates, paper outcomes, and real account movement."""
    candidate_list = list(candidates)
    paper_list = list(paper_outcomes)
    movement_list = list(real_movements)

    paper_by_candidate = _paper_outcomes_by_candidate(paper_list)
    consumed_order_ids: set[str] = set()
    consumed_movement_ids: set[str] = set()
    items: list[ShadowReviewItem] = []

    for candidate in candidate_list:
        paper = paper_by_candidate.get(candidate.candidate_id)
        if paper is not None:
            consumed_order_ids.add(paper.order_id)
        movement = _find_supported_movement(
            candidate=candidate,
            paper=paper,
            real_movements=movement_list,
            consumed_movement_ids=consumed_movement_ids,
        )
        if movement is not None:
            consumed_movement_ids.add(movement.movement_id)
        items.append(
            _candidate_review_item(
                candidate=candidate,
                paper=paper,
                movement=movement,
            )
        )

    for paper in paper_list:
        if paper.order_id in consumed_order_ids:
            continue
        items.append(_orphan_paper_item(paper))

    for movement in movement_list:
        if movement.movement_id in consumed_movement_ids:
            continue
        items.append(_unsupported_real_movement_item(movement))

    return ShadowReviewReport(items=tuple(items))


def _paper_outcomes_by_candidate(
    paper_outcomes: Iterable[PaperOutcomeEvidence],
) -> dict[str, PaperOutcomeEvidence]:
    by_candidate: dict[str, PaperOutcomeEvidence] = {}
    for outcome in paper_outcomes:
        by_candidate.setdefault(outcome.candidate_id, outcome)
    return by_candidate


def _find_supported_movement(
    *,
    candidate: StrategyCandidateEvidence,
    paper: PaperOutcomeEvidence | None,
    real_movements: list[RealAccountMovementEvidence],
    consumed_movement_ids: set[str],
) -> RealAccountMovementEvidence | None:
    if paper is None:
        return None
    for movement in real_movements:
        if movement.movement_id in consumed_movement_ids:
            continue
        if movement.symbol != candidate.symbol:
            continue
        if movement.linked_candidate_id != candidate.candidate_id:
            continue
        if movement.linked_order_id != paper.order_id:
            continue
        if movement.linked_strategy_id != candidate.strategy_id:
            continue
        return movement
    return None


def _candidate_review_item(
    *,
    candidate: StrategyCandidateEvidence,
    paper: PaperOutcomeEvidence | None,
    movement: RealAccountMovementEvidence | None,
) -> ShadowReviewItem:
    evidence_refs = {
        "candidate_id": candidate.candidate_id,
        "strategy_id": candidate.strategy_id,
    }
    if candidate.signal_id:
        evidence_refs["signal_id"] = candidate.signal_id
    if candidate.risk_decision_id:
        evidence_refs["risk_decision_id"] = candidate.risk_decision_id
    if paper is not None:
        evidence_refs["paper_order_id"] = paper.order_id
        if paper.fill_id:
            evidence_refs["paper_fill_id"] = paper.fill_id
    if movement is not None:
        evidence_refs["real_movement_id"] = movement.movement_id

    if paper is None:
        return ShadowReviewItem(
            item_key=f"candidate:{candidate.candidate_id}",
            review_status="missing_paper_outcome",
            symbol=candidate.symbol,
            strategy_id=candidate.strategy_id,
            attributed_to_strategy=False,
            attributed_strategy_id=None,
            paper_quantity_delta=None,
            real_quantity_delta=None,
            quantity_difference=None,
            paper_cash_delta=None,
            real_cash_delta=None,
            cash_difference=None,
            severity="warning",
            suggested_action="run_or_link_paper_outcome",
            evidence_refs=evidence_refs,
            limitations=("paper_outcome_missing",),
        )

    paper_quantity_delta = _paper_quantity_delta(paper)
    paper_cash_delta = _paper_cash_delta(paper)
    if movement is None:
        return ShadowReviewItem(
            item_key=f"candidate:{candidate.candidate_id}",
            review_status="paper_only",
            symbol=candidate.symbol,
            strategy_id=candidate.strategy_id,
            attributed_to_strategy=False,
            attributed_strategy_id=None,
            paper_quantity_delta=paper_quantity_delta,
            real_quantity_delta=None,
            quantity_difference=None,
            paper_cash_delta=paper_cash_delta,
            real_cash_delta=None,
            cash_difference=None,
            severity="warning",
            suggested_action="link_or_review_real_account_movement",
            evidence_refs=evidence_refs,
            limitations=("real_account_movement_missing",),
        )

    quantity_difference = movement.quantity_delta - paper_quantity_delta
    cash_difference = movement.cash_delta - paper_cash_delta
    matches = quantity_difference == Decimal("0") and cash_difference == Decimal("0")
    return ShadowReviewItem(
        item_key=f"candidate:{candidate.candidate_id}",
        review_status="matched" if matches else "matched_with_difference",
        symbol=candidate.symbol,
        strategy_id=candidate.strategy_id,
        attributed_to_strategy=True,
        attributed_strategy_id=candidate.strategy_id,
        paper_quantity_delta=paper_quantity_delta,
        real_quantity_delta=movement.quantity_delta,
        quantity_difference=quantity_difference,
        paper_cash_delta=paper_cash_delta,
        real_cash_delta=movement.cash_delta,
        cash_difference=cash_difference,
        severity="pass" if matches else "warning",
        suggested_action="no_action_needed" if matches else "review_difference",
        evidence_refs=evidence_refs,
    )


def _orphan_paper_item(paper: PaperOutcomeEvidence) -> ShadowReviewItem:
    return ShadowReviewItem(
        item_key=f"paper:{paper.order_id}",
        review_status="orphan_paper_outcome",
        symbol=paper.symbol,
        strategy_id=paper.strategy_id,
        attributed_to_strategy=False,
        attributed_strategy_id=None,
        paper_quantity_delta=_paper_quantity_delta(paper),
        real_quantity_delta=None,
        quantity_difference=None,
        paper_cash_delta=_paper_cash_delta(paper),
        real_cash_delta=None,
        cash_difference=None,
        severity="warning",
        suggested_action="link_candidate_or_review_paper_outcome",
        evidence_refs={
            "candidate_id": paper.candidate_id,
            "paper_order_id": paper.order_id,
            "strategy_id": paper.strategy_id,
        },
        limitations=("strategy_candidate_missing",),
    )


def _unsupported_real_movement_item(
    movement: RealAccountMovementEvidence,
) -> ShadowReviewItem:
    evidence_refs = {
        "real_movement_id": movement.movement_id,
        "source": movement.source,
    }
    if movement.source_ref:
        evidence_refs["source_ref"] = movement.source_ref
    if movement.linked_candidate_id:
        evidence_refs["linked_candidate_id"] = movement.linked_candidate_id
    if movement.linked_order_id:
        evidence_refs["linked_order_id"] = movement.linked_order_id
    if movement.linked_strategy_id:
        evidence_refs["linked_strategy_id"] = movement.linked_strategy_id

    return ShadowReviewItem(
        item_key=f"real:{movement.movement_id}",
        review_status="unsupported_real_movement",
        symbol=movement.symbol,
        strategy_id=movement.linked_strategy_id,
        attributed_to_strategy=False,
        attributed_strategy_id=None,
        paper_quantity_delta=None,
        real_quantity_delta=movement.quantity_delta,
        quantity_difference=None,
        paper_cash_delta=None,
        real_cash_delta=movement.cash_delta,
        cash_difference=None,
        severity="warning",
        suggested_action="review_account_movement",
        evidence_refs=evidence_refs,
        limitations=("missing_explicit_strategy_link",),
    )


def _paper_quantity_delta(paper: PaperOutcomeEvidence) -> Decimal:
    return paper.filled_quantity if paper.side == "buy" else -paper.filled_quantity


def _paper_cash_delta(paper: PaperOutcomeEvidence) -> Decimal:
    notional = paper.average_fill_price * paper.filled_quantity
    if paper.side == "buy":
        return -(notional + paper.commission)
    return notional - paper.commission


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
