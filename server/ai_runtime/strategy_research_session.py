"""Read-side integrity, account-capital, and fee bindings for strategy research."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
)
from server.ai_runtime.contracts import JsonObject
from server.ai_runtime.formula_dsl import CANONICAL_COST_MODEL_REFERENCE
from server.ai_runtime.provider_connectivity_contracts import (
    ProviderConnectivitySettings,
)
from server.ai_runtime.strategy_research_backtest import (
    validated_fee_schedule_resolution,
)
from server.ai_runtime.strategy_research_support import (
    selection_from_session,
    strategy_research_json_object,
    strategy_research_request_json,
)
from server.ai_runtime.strategy_research_values import ACCOUNT_STATE_TOOL
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_API_CONTRACT,
    StrategyResearchRejected,
    StrategyResearchSelection,
)
from server.persistence.strategy_research_errors import (
    StrategyResearchDatabaseError,
    StrategyResearchOperationalError,
)


class StrategyResearchSessionMixin:
    def get_session(self, session_id: str, *, reused: bool = False) -> JsonObject:
        session = self._research_store.get_session_if_initialized(session_id)
        if session is None:
            raise LookupError(f"strategy research session not found: {session_id}")
        binding_validity = "not_established"
        binding_errors: list[str] = []
        if session.get("workflow_id") and session.get("context_snapshot_id"):
            try:
                self._validate_session_integrity(session)
                binding_validity = "valid"
            except StrategyResearchRejected as exc:
                binding_validity = "invalidated_by_drift"
                binding_errors.append(str(exc))
        workflow = None
        if session.get("workflow_id"):
            try:
                stored = self._ai_store.get_workflow(str(session["workflow_id"]))
                workflow = {
                    "workflow_id": stored.workflow_id,
                    "status": stored.status.value,
                    "failure_code": stored.failure_code,
                }
            except (LookupError, StrategyResearchOperationalError):
                workflow = None
        request = strategy_research_request_json(session)
        return {
            "schema_version": STRATEGY_RESEARCH_API_CONTRACT,
            "session_id": session["session_id"],
            "status": session["status"],
            "failure_code": session.get("failure_code"),
            "research_question": request.get("research_question"),
            "iteration_context": request.get("iteration_context"),
            "selection": request.get("selection"),
            "selection_fingerprint": session["selection_fingerprint"],
            "context_snapshot_id": session.get("context_snapshot_id"),
            "context_fingerprint": session.get("context_fingerprint"),
            "evidence_reference_id": session.get("evidence_reference_id"),
            "provider_id": session.get("provider_id"),
            "model_id": session.get("model_id"),
            "prompt_version": session.get("prompt_version"),
            "binding_validity": binding_validity,
            "binding_errors": binding_errors,
            "workflow": workflow,
            "drafts": [
                item["contract"]
                for item in self._research_store.list_drafts(session_id)
            ],
            "reviews": self._research_store.list_reviews(session_id),
            "reused": reused,
            "non_authoritative": True,
            "non_executable": True,
            "requires_human_review": True,
            "decision_input_created": False,
            "trade_plan_created": False,
            "authority_effect": "none",
        }

    async def _validate_saved_selection(
        self, selection: StrategyResearchSelection
    ) -> JsonObject:
        row = await self._db.get_backtest_result(selection.saved_backtest_result_id)
        if not isinstance(row, dict):
            raise LookupError(
                f"backtest result not found: {selection.saved_backtest_result_id}"
            )
        config = strategy_research_json_object(row.get("config_json"))
        metrics = strategy_research_json_object(row.get("metrics_json"))
        snapshot = metrics.get("dataset_snapshot")
        if not isinstance(snapshot, dict):
            raise StrategyResearchRejected("saved_dataset_snapshot_missing")
        if snapshot.get("snapshot_id") != selection.dataset_snapshot_id:
            raise StrategyResearchRejected("selected_dataset_snapshot_mismatch")
        if (
            config.get("start_date") != selection.start_date
            or config.get("end_date") != selection.end_date
        ):
            raise StrategyResearchRejected("selected_window_mismatch")
        configured_assets = config.get("assets")
        if not isinstance(configured_assets, list):
            raise StrategyResearchRejected("saved_universe_missing")
        saved_symbols = tuple(
            str(item.get("symbol"))
            for item in configured_assets
            if isinstance(item, dict)
        )
        saved_asset_classes = tuple(
            str(item.get("asset_class") or "stock")
            for item in configured_assets
            if isinstance(item, dict)
        )
        if (
            saved_symbols != selection.universe
            or saved_asset_classes != selection.asset_classes
        ):
            raise StrategyResearchRejected("selected_universe_mismatch")
        if float(config.get("initial_cash") or 0) != selection.initial_cash:
            raise StrategyResearchRejected("selected_initial_cash_mismatch")
        return dict(snapshot)

    def _account_capital_evidence_for_session(
        self,
        *,
        session: Mapping[str, Any],
        selection: StrategyResearchSelection,
        reviewed_fee_schedule_resolution: Any | None,
    ) -> dict[str, Any]:
        if not selection.has_account_binding:
            raise StrategyResearchRejected("research_account_binding_required")
        context = self._ai_store.get_context(str(session["context_snapshot_id"]))
        account_records = []
        for reference_id in context.evidence_reference_ids:
            record = self._evidence_repository.get(str(reference_id))
            if record is not None and record.tool_name == ACCOUNT_STATE_TOOL:
                account_records.append(record)
        if len(account_records) != 1:
            raise StrategyResearchRejected("account_evidence_binding_drift")
        evidence = self._build_account_capital_evidence(
            selection=selection,
            account_evidence=account_records[0],
            reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
        )
        if evidence.get("status") != "pass":
            raise StrategyResearchRejected(
                str(
                    next(
                        iter(evidence.get("issues") or []),
                        "research_account_capital_evidence_not_passing",
                    )
                )
            )
        return evidence

    @staticmethod
    def _build_account_capital_evidence(
        *,
        selection: StrategyResearchSelection,
        account_evidence: Any,
        reviewed_fee_schedule_resolution: Any | None,
    ) -> dict[str, Any]:
        _, fee_schedule_evidence = validated_fee_schedule_resolution(
            selection,
            reviewed_fee_schedule_resolution,
        )
        account_payload = (
            account_evidence.to_dict()
            if hasattr(account_evidence, "to_dict")
            else dict(account_evidence or {})
        )
        return build_research_account_capital_evidence(
            initial_cash=selection.initial_cash,
            account_evidence=account_payload,
            fee_schedule_evidence=fee_schedule_evidence,
            expected_valuation_snapshot_id=selection.valuation_snapshot_id,
            expected_ledger_cutoff_id=selection.ledger_cutoff_id,
        )

    def _resolve_reviewed_fee_schedule(
        self,
        selection: StrategyResearchSelection,
    ) -> Any | None:
        if selection.cost_model_reference == CANONICAL_COST_MODEL_REFERENCE:
            return None
        if self._reviewed_fee_schedule_resolver is None:
            raise StrategyResearchRejected("reviewed_fee_schedule_resolver_missing")
        return self._reviewed_fee_schedule_resolver(
            start_date=selection.start_date,
            end_date=selection.end_date,
            universe=selection.universe,
            asset_classes=selection.asset_classes,
            expected_cost_model_reference=selection.cost_model_reference,
            account_truth_as_of=selection.account_truth_freshness_datetime,
        )

    def _require_settings(self) -> ProviderConnectivitySettings:
        if self._settings is None:
            raise StrategyResearchRejected("external_provider_not_configured")
        return self._settings

    def _validate_session_integrity(self, session: Mapping[str, Any]) -> None:
        workflow_id = session.get("workflow_id")
        context_snapshot_id = session.get("context_snapshot_id")
        if not workflow_id or not context_snapshot_id:
            raise StrategyResearchRejected("research_binding_missing")
        context = self._ai_store.get_context(str(context_snapshot_id))
        if context.fingerprint != session.get("context_fingerprint"):
            raise StrategyResearchRejected("research_context_drift")
        evidence_reference_id = session.get("evidence_reference_id")
        if (
            not evidence_reference_id
            or evidence_reference_id not in context.evidence_reference_ids
        ):
            raise StrategyResearchRejected("research_evidence_binding_drift")
        try:
            evidence = self._evidence_repository.get(str(evidence_reference_id))
        except (ValueError, StrategyResearchDatabaseError) as exc:
            raise StrategyResearchRejected("research_evidence_drift") from exc
        expected_reference = next(
            item
            for item in context.evidence_references
            if item.reference_id == evidence_reference_id
        )
        if (
            evidence is None
            or evidence.record_fingerprint != expected_reference.fingerprint
            or evidence.status != "complete"
        ):
            raise StrategyResearchRejected("research_evidence_drift")
        selection = selection_from_session(session)
        if selection.has_account_binding:
            if (
                context.valuation_snapshot_id != selection.valuation_snapshot_id
                or context.ledger_cutoff_id != selection.ledger_cutoff_id
            ):
                raise StrategyResearchRejected("account_evidence_binding_drift")
            account_references = []
            for reference in context.evidence_references:
                try:
                    record = self._evidence_repository.get(reference.reference_id)
                except (ValueError, StrategyResearchDatabaseError) as exc:
                    raise StrategyResearchRejected("account_evidence_drift") from exc
                if record is not None and record.tool_name == ACCOUNT_STATE_TOOL:
                    account_references.append((reference, record))
            if len(account_references) != 1:
                raise StrategyResearchRejected("account_evidence_binding_drift")
            account_reference, account_record = account_references[0]
            if (
                account_record.record_fingerprint != account_reference.fingerprint
                or account_record.status != "complete"
            ):
                raise StrategyResearchRejected("account_evidence_drift")
        replay = self._ai_store.verify_replay(str(workflow_id))
        if not replay.valid:
            raise StrategyResearchRejected("research_audit_drift")
        strategy_replay_valid, _ = self._research_store.verify_events(
            str(session["session_id"])
        )
        if not strategy_replay_valid:
            raise StrategyResearchRejected("strategy_research_audit_drift")

    async def _backtest_response(
        self, backtest: dict[str, Any], *, reused: bool
    ) -> JsonObject:
        canonical = None
        result_id = backtest.get("canonical_backtest_result_id")
        if result_id:
            row = await self._db.get_backtest_result(int(result_id))
            if isinstance(row, dict):
                metrics = strategy_research_json_object(row.get("metrics_json"))
                canonical = {
                    "result_id": int(result_id),
                    "initial_cash": row.get("initial_cash"),
                    "final_equity": row.get("final_equity"),
                    "total_return": row.get("total_return"),
                    "sharpe": row.get("sharpe"),
                    "max_drawdown": row.get("max_drawdown"),
                    "duration_days": row.get("duration_days"),
                    "cost_summary": strategy_research_json_object(
                        row.get("cost_summary_json")
                    ),
                    "oos_validation": metrics.get("oos_validation"),
                    "research_evidence_bundle": metrics.get("research_evidence_bundle"),
                    "dataset_snapshot": metrics.get("dataset_snapshot"),
                    "formula_binding": metrics.get("formula_binding"),
                    "signal_execution_evidence": metrics.get(
                        "signal_execution_evidence"
                    ),
                    "lot_feasibility_evidence": metrics.get("lot_feasibility_evidence"),
                }
        return {
            "schema_version": STRATEGY_RESEARCH_API_CONTRACT,
            "backtest_run_id": backtest["backtest_run_id"],
            "status": backtest["status"],
            "failure_code": backtest.get("failure_code"),
            "session_id": backtest["session_id"],
            "draft_id": backtest["draft_id"],
            "formula_fingerprint": backtest["formula_fingerprint"],
            "dataset_snapshot_id": backtest["dataset_snapshot_id"],
            "cost_model_reference": backtest["cost_model_reference"],
            "canonical_backtest": canonical,
            "reused": reused,
            "research_only": True,
            "non_authoritative": True,
            "non_executable": True,
            "requires_human_review": True,
            "authority_effect": "none",
        }
