"""Stable request and evidence-binding contracts for AI strategy research."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from core.types import BarFrequency
from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.formula_dsl import (
    is_operator_approved_cost_model_reference,
)
from server.contracts.normalized_strategy_research import (
    CANONICAL_COST_MODEL_REFERENCE,
    NORMALIZED_RESEARCH_NOTIONAL,
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
)

STRATEGY_HYPOTHESIS_DRAFT_CONTRACT = "karkinos.ai.strategy_hypothesis_draft.v1"
STRATEGY_BACKTEST_CRITIQUE_CONTRACT = "karkinos.ai.strategy_backtest_critique.v1"
STRATEGY_RESEARCH_SELECTION_CONTRACT = "karkinos.ai.strategy_research_selection.v1"
STRATEGY_RESEARCH_API_CONTRACT = "karkinos.ai.strategy_research_api.v1"
STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT = (
    "karkinos.ai.strategy_iteration_context.v1"
)
STRATEGY_RESEARCH_PROMPT_VERSION = "karkinos.ai.strategy_research_prompt.v14"
SANITIZED_ACCOUNT_EVIDENCE_CONTRACT = "karkinos.ai.sanitized_account_risk_evidence.v1"

HYPOTHESIS_EXPORT_CONFIRMATION = (
    "send_selected_sanitized_strategy_research_evidence_to_configured_external_"
    "model_without_trade_authority"
)
BACKTEST_CONFIRMATION = (
    "run_selected_validated_formula_with_canonical_backtest_without_trade_authority"
)
CRITIQUE_EXPORT_CONFIRMATION = (
    "send_selected_formula_and_canonical_backtest_evidence_to_configured_external_"
    "model_without_trade_authority"
)
REVIEW_CONFIRMATION = "record_human_strategy_research_review_without_trade_authority"
SEALED_TEST_CONFIRMATION = (
    "run_frozen_champion_sealed_holdout_evaluation_without_trade_authority"
)
STRATEGY_RESEARCH_MAX_INPUT_BYTES = 196_608
STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS = 12_288
STRATEGY_RESEARCH_MAX_CITATION_PATHS = 512
STRATEGY_RESEARCH_MAX_CITATION_CATALOG_BYTES = 49_152
# One token cannot contain less than one input byte. The additional allowance
# covers the system prompt and request envelope outside the capped user payload.
STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION = (
    STRATEGY_RESEARCH_MAX_INPUT_BYTES + STRATEGY_RESEARCH_MAX_OUTPUT_TOKENS + 16_384
)
STRATEGY_RESEARCH_MAX_PROVIDER_CALLS = 10
STRATEGY_RESEARCH_MAX_CANDIDATES = 5


class StrategyResearchRejected(ValueError):
    """A fail-closed research boundary rejection before authority changes."""


@dataclass(frozen=True)
class StrategyResearchSelection:
    saved_backtest_result_id: int
    universe: tuple[str, ...]
    asset_classes: tuple[str, ...]
    dataset_snapshot_id: str
    start_date: str
    end_date: str
    frequency: str
    initial_cash: float
    sealed_end_date: str | None = None
    cost_model_reference: str = CANONICAL_COST_MODEL_REFERENCE
    account_truth_freshness_as_of: str | None = None
    valuation_snapshot_id: str | None = None
    ledger_cutoff_id: int | None = None
    schema_version: str = STRATEGY_RESEARCH_SELECTION_CONTRACT

    def __post_init__(self) -> None:
        if self.saved_backtest_result_id <= 0:
            raise StrategyResearchRejected("saved_backtest_result_id_invalid")
        if not self.universe or len(self.universe) != len(set(self.universe)):
            raise StrategyResearchRejected("selected_universe_invalid")
        if len(self.universe) != len(self.asset_classes):
            raise StrategyResearchRejected("selected_asset_classes_invalid")
        if self.frequency != BarFrequency.DAILY.value:
            raise StrategyResearchRejected("only_daily_research_is_supported")
        if not is_operator_approved_cost_model_reference(self.cost_model_reference):
            raise StrategyResearchRejected("cost_model_not_operator_approved")
        if not self.dataset_snapshot_id.startswith("sha256:"):
            raise StrategyResearchRejected("dataset_snapshot_identity_invalid")
        if self.start_date > self.end_date:
            raise StrategyResearchRejected("selected_window_invalid")
        if self.sealed_end_date is not None:
            try:
                date.fromisoformat(self.sealed_end_date)
            except ValueError as exc:
                raise StrategyResearchRejected("sealed_end_date_invalid") from exc
            if self.sealed_end_date <= self.end_date:
                raise StrategyResearchRejected("sealed_end_date_not_future")
        if self.initial_cash <= 0:
            raise StrategyResearchRejected("initial_cash_invalid")
        if self.account_truth_freshness_as_of is not None:
            try:
                account_truth_as_of = datetime.fromisoformat(
                    self.account_truth_freshness_as_of
                )
            except ValueError as exc:
                raise StrategyResearchRejected(
                    "account_truth_freshness_as_of_invalid"
                ) from exc
            if (
                account_truth_as_of.tzinfo is None
                or account_truth_as_of.utcoffset() is None
            ):
                raise StrategyResearchRejected("account_truth_freshness_as_of_invalid")
            if account_truth_as_of.date().isoformat() != self.end_date:
                raise StrategyResearchRejected(
                    "account_truth_freshness_as_of_date_mismatch"
                )
        if (self.valuation_snapshot_id is None) != (self.ledger_cutoff_id is None):
            raise StrategyResearchRejected("account_fact_binding_incomplete")
        if (
            not self.has_account_binding
            and self.cost_model_reference != CANONICAL_COST_MODEL_REFERENCE
        ):
            raise StrategyResearchRejected(
                "strategy_only_research_requires_canonical_cost_model"
            )
        if (
            not self.has_account_binding
            and self.initial_cash != NORMALIZED_RESEARCH_NOTIONAL
        ):
            raise StrategyResearchRejected(
                "strategy_only_research_requires_normalized_notional"
            )
        if self.has_account_binding:
            if self.cost_model_reference == CANONICAL_COST_MODEL_REFERENCE:
                raise StrategyResearchRejected(
                    "account_bound_research_requires_reviewed_cost_model"
                )
            if not str(self.valuation_snapshot_id or "").strip():
                raise StrategyResearchRejected("valuation_snapshot_identity_invalid")
            if int(self.ledger_cutoff_id or 0) < 0:
                raise StrategyResearchRejected("ledger_cutoff_identity_invalid")

    @property
    def has_account_binding(self) -> bool:
        return (
            self.valuation_snapshot_id is not None and self.ledger_cutoff_id is not None
        )

    @property
    def has_sealed_holdout(self) -> bool:
        return self.sealed_end_date is not None

    @property
    def sealed_start_date(self) -> str | None:
        """First date of the sealed holdout, immediately after the research end."""
        if self.sealed_end_date is None:
            return None
        research_end = date.fromisoformat(self.end_date)
        return (research_end + timedelta(days=1)).isoformat()

    @property
    def account_truth_freshness_datetime(self) -> datetime:
        value = self.account_truth_freshness_as_of
        if value is None:
            value = f"{self.end_date}T15:30:00+08:00"
        return datetime.fromisoformat(value)

    def to_dict(self) -> JsonObject:
        payload = {
            "schema_version": self.schema_version,
            "saved_backtest_result_id": self.saved_backtest_result_id,
            "universe": list(self.universe),
            "asset_classes": list(self.asset_classes),
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "frequency": self.frequency,
            "initial_cash": float(self.initial_cash),
            "cost_model_reference": self.cost_model_reference,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "ledger_cutoff_id": self.ledger_cutoff_id,
            "account_fact_binding": (
                "bound"
                if self.has_account_binding
                else "not_applicable_strategy_only_research"
            ),
        }
        if self.account_truth_freshness_as_of is not None:
            payload["account_truth_freshness_as_of"] = (
                self.account_truth_freshness_as_of
            )
        if self.sealed_end_date is not None:
            payload["sealed_end_date"] = self.sealed_end_date
        return payload

    def to_external_dict(self) -> JsonObject:
        """Expose research identifiers while keeping account bindings local."""
        payload = self.to_dict()
        payload.pop("valuation_snapshot_id", None)
        payload.pop("ledger_cutoff_id", None)
        payload.pop("sealed_end_date", None)
        payload.pop("initial_cash", None)
        if not self.has_account_binding:
            payload["notional_policy_id"] = NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID
        payload["account_fact_binding"] = (
            "present_but_identifiers_redacted"
            if self.has_account_binding
            else "not_applicable_strategy_only_research"
        )
        return payload

    @property
    def fingerprint(self) -> str:
        return "sha256:" + content_fingerprint(self.to_dict())


@dataclass(frozen=True)
class HypothesisGenerationRequest:
    idempotency_key: str
    requested_by: str
    account_alias: str
    research_question: str
    selection: StrategyResearchSelection
    confirmation: str
    iteration_context: JsonObject | None = None

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "requested_by",
            "account_alias",
            "research_question",
        ):
            if not str(getattr(self, name)).strip():
                raise StrategyResearchRejected(f"{name}_required")
        if self.confirmation != HYPOTHESIS_EXPORT_CONFIRMATION:
            raise PermissionError("hypothesis export requires exact human confirmation")
        validate_iteration_context(self.iteration_context)

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(
            {
                "requested_by": self.requested_by,
                "account_alias": self.account_alias,
                "research_question": self.research_question,
                "selection": self.selection.to_dict(),
                "confirmation": self.confirmation,
                "iteration_context": self.iteration_context,
            }
        )


@dataclass(frozen=True)
class FormulaBacktestRequest:
    idempotency_key: str
    requested_by: str
    session_id: str
    draft_id: str
    confirmation: str

    def __post_init__(self) -> None:
        for name in ("idempotency_key", "requested_by", "session_id", "draft_id"):
            if not str(getattr(self, name)).strip():
                raise StrategyResearchRejected(f"{name}_required")
        if self.confirmation != BACKTEST_CONFIRMATION:
            raise PermissionError("formula backtest requires exact human confirmation")


@dataclass(frozen=True)
class CritiqueRequest:
    idempotency_key: str
    requested_by: str
    session_id: str
    draft_id: str
    backtest_run_id: str
    confirmation: str

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "requested_by",
            "session_id",
            "draft_id",
            "backtest_run_id",
        ):
            if not str(getattr(self, name)).strip():
                raise StrategyResearchRejected(f"{name}_required")
        if self.confirmation != CRITIQUE_EXPORT_CONFIRMATION:
            raise PermissionError("critique export requires exact human confirmation")


@dataclass(frozen=True)
class SealedTestRequest:
    idempotency_key: str
    requested_by: str
    session_id: str
    draft_id: str
    backtest_run_id: str
    confirmation: str
    benchmark_return: Decimal | None = None

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "requested_by",
            "session_id",
            "draft_id",
            "backtest_run_id",
        ):
            if not str(getattr(self, name)).strip():
                raise StrategyResearchRejected(f"{name}_required")
        if self.confirmation != SEALED_TEST_CONFIRMATION:
            raise PermissionError("sealed test requires exact human confirmation")
        if self.benchmark_return is not None:
            try:
                normalized = Decimal(str(self.benchmark_return))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise StrategyResearchRejected("benchmark_return_invalid") from exc
            if not normalized.is_finite():
                raise StrategyResearchRejected("benchmark_return_invalid")


def validate_iteration_context(value: JsonObject | None) -> None:
    if value is None:
        return
    required = {
        "schema_version",
        "iteration_number",
        "total_iterations",
        "parent_iteration",
        "required_behavior",
        "context_fingerprint",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise StrategyResearchRejected("iteration_context_schema_invalid")
    if value.get("schema_version") != STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT:
        raise StrategyResearchRejected("iteration_context_version_invalid")
    iteration_number = value.get("iteration_number")
    total_iterations = value.get("total_iterations")
    if (
        not isinstance(iteration_number, int)
        or isinstance(iteration_number, bool)
        or not isinstance(total_iterations, int)
        or isinstance(total_iterations, bool)
        or not 1
        <= iteration_number
        <= total_iterations
        <= STRATEGY_RESEARCH_MAX_CANDIDATES
    ):
        raise StrategyResearchRejected("iteration_context_ordinal_invalid")
    behavior = value.get("required_behavior")
    if behavior != {
        "draft_count": 1,
        "must_change_formula_from_parent": iteration_number > 1,
        "must_use_parent_backtest_and_critique": iteration_number > 1,
        "authority_effect": "none",
    }:
        raise StrategyResearchRejected("iteration_context_behavior_invalid")
    parent = value.get("parent_iteration")
    if iteration_number == 1:
        if parent is not None:
            raise StrategyResearchRejected("initial_iteration_parent_forbidden")
    else:
        parent_required = {
            "iteration_number",
            "candidate_id",
            "session_id",
            "draft_id",
            "formula_fingerprint",
            "backtest_run_id",
            "critique_id",
            "strategy",
            "evaluation",
            "critique",
            "parent_artifact_fingerprint",
        }
        if not isinstance(parent, dict) or set(parent) != parent_required:
            raise StrategyResearchRejected("iteration_parent_schema_invalid")
        if parent.get("iteration_number") != iteration_number - 1:
            raise StrategyResearchRejected("iteration_parent_ordinal_invalid")
        for name in (
            "candidate_id",
            "session_id",
            "draft_id",
            "formula_fingerprint",
            "backtest_run_id",
            "critique_id",
        ):
            if not isinstance(parent.get(name), str) or not parent[name].strip():
                raise StrategyResearchRejected(f"iteration_parent_{name}_invalid")
        if not all(
            isinstance(parent.get(name), dict)
            for name in ("strategy", "evaluation", "critique")
        ):
            raise StrategyResearchRejected("iteration_parent_evidence_invalid")
        parent_fingerprint = parent.get("parent_artifact_fingerprint")
        parent_core = {
            key: item
            for key, item in parent.items()
            if key != "parent_artifact_fingerprint"
        }
        if parent_fingerprint != "sha256:" + content_fingerprint(parent_core):
            raise StrategyResearchRejected("iteration_parent_fingerprint_mismatch")
    reject_private_iteration_keys(value)
    context_fingerprint = value.get("context_fingerprint")
    context_core = {
        key: item for key, item in value.items() if key != "context_fingerprint"
    }
    if context_fingerprint != "sha256:" + content_fingerprint(context_core):
        raise StrategyResearchRejected("iteration_context_fingerprint_mismatch")


def reject_private_iteration_keys(value: Any) -> None:
    forbidden = {
        "account_id",
        "account_alias",
        "valuation_snapshot_id",
        "ledger_cutoff_id",
        "cash",
        "positions",
        "holdings",
        "broker_export",
        "credentials",
        "api_key",
    }
    if isinstance(value, Mapping):
        if forbidden.intersection(str(key) for key in value):
            raise StrategyResearchRejected("iteration_context_private_field_forbidden")
        for item in value.values():
            reject_private_iteration_keys(item)
    elif isinstance(value, list):
        for item in value:
            reject_private_iteration_keys(item)
