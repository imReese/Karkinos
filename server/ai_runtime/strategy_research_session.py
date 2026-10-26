"""Read-side integrity, account-capital, and fee bindings for strategy research."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
)
from server.ai_runtime.contracts import (
    JsonObject,
    content_fingerprint,
)
from server.ai_runtime.formula_dsl import CANONICAL_COST_MODEL_REFERENCE, FormulaBinding
from server.ai_runtime.strategy_research_backtest import (
    validated_fee_schedule_resolution,
)
from server.ai_runtime.strategy_research_codex import StrategyResearchSettings
from server.ai_runtime.strategy_research_support import (
    build_research_evaluation_bundle,
    build_research_run_projection,
    report_artifact,
    selection_from_session,
    strategy_research_json_object,
    strategy_research_request_json,
)
from server.ai_runtime.strategy_research_values import ACCOUNT_STATE_TOOL
from server.config_types import ResearchSimulationSourceConfig
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_API_CONTRACT,
    StrategyResearchRejected,
    StrategyResearchSelection,
    backtest_evidence_blocker,
)
from server.persistence.strategy_research_errors import (
    StrategyResearchDatabaseError,
    StrategyResearchOperationalError,
)

if TYPE_CHECKING:
    from server.ai_runtime.evidence import CanonicalEvidenceRepository
    from server.ai_runtime.store import AiAuditStore
    from server.persistence.strategy_research import StrategyResearchAuditStore


class StrategyResearchSessionMixin:
    _research_store: StrategyResearchAuditStore
    _ai_store: AiAuditStore
    _evidence_repository: CanonicalEvidenceRepository

    def _resolve_simulation_entry_board_policy(
        self,
        selection: StrategyResearchSelection,
        *,
        saved_backtest: Mapping[str, Any] | None = None,
    ) -> JsonObject | None:
        """Authorize a new SIM action against its frozen grant generation."""
        binding = selection.simulation_validation_binding
        if binding is None:
            return None
        from server.contracts.recommendation_publication import publication_number
        from server.contracts.research_observation_automation import (
            read_simulation_validation_policy,
        )
        from server.services.market.market_universe_truth import (
            MarketUniversePolicy,
            market_deployment_scope,
        )

        try:
            policy = read_simulation_validation_policy(self._db, now=self._now())
            scope = policy["deployment_scope"]
            canonical_scope = market_deployment_scope(
                MarketUniversePolicy.from_dict(scope["universe_policy"])
            )
            cash = publication_number(policy["initial_cash"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyResearchRejected("simulation_policy_not_current") from exc
        if any(binding[key] != policy[key] for key in ("grant_id", "generation")):
            raise StrategyResearchRejected("simulation_authorization_changed")
        if (
            publication_number(binding["initial_cash"]) != cash
            or publication_number(selection.initial_cash) != cash
            or selection.has_account_binding
            or scope != canonical_scope
            or selection.deployment_scope != scope
            or selection.portfolio_policy_id != scope["portfolio_policy_id"]
            or selection.cost_model_reference != policy["cost_model_reference"]
        ):
            raise StrategyResearchRejected("simulation_selection_policy_drift")
        entry_policy = policy["entry_board_policy"]
        if saved_backtest is not None:
            metrics = strategy_research_json_object(saved_backtest.get("metrics_json"))
            config = strategy_research_json_object(saved_backtest.get("config_json"))
            params = strategy_research_json_object(config.get("params"))
            try:
                cash_matches = (
                    publication_number(saved_backtest.get("initial_cash")) == cash
                    and publication_number(config.get("initial_cash")) == cash
                )
            except ValueError:
                cash_matches = False
            if (
                not cash_matches
                or metrics.get("source_selection") != selection.to_dict()
                or metrics.get("simulation_validation_binding") != binding
                or metrics.get("entry_board_policy") != entry_policy
                or params.get("entry_board_policy") != entry_policy
                or metrics.get("deployment_scope") != scope
                or params.get("deployment_scope") != scope
                or metrics.get("portfolio_policy_id") != selection.portfolio_policy_id
                or params.get("portfolio_policy_id") != selection.portfolio_policy_id
                or strategy_research_json_object(metrics.get("cost_assumptions")).get(
                    "commission_model_reference"
                )
                != selection.cost_model_reference
            ):
                raise StrategyResearchRejected(
                    "simulation_backtest_policy_binding_drift"
                )
        return deepcopy(entry_policy)

    def resolve_research_simulation_source(
        self, source: ResearchSimulationSourceConfig | None
    ) -> JsonObject:
        """Reopen one explicit research lineage without selecting or approving it.

        This checks saved facts and audit bindings only. It does not replay CAS
        bars, admit publication, run a critique, or create a human review.
        """
        result: JsonObject = {
            "status": "unavailable",
            "blockers": ["research_simulation_source_not_configured"],
            "read_only": True,
            "research_only": True,
            "requires_human_review": True,
            "executable": False,
            "authorizes_order_creation": False,
            "authorizes_account_publication": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }
        if source is None:
            return result
        from server.ai_runtime.karkinos_source import (
            saved_native_research_analysis_admission,
        )
        from server.ai_runtime.strategy_research_privacy import (
            build_normalized_research_pack,
            build_normalized_robustness_evidence,
        )

        try:
            session = self._research_store.get_session(source.session_id)
            if (
                session["status"] != "completed"
                or session["session_id"] != source.session_id
            ):
                raise StrategyResearchRejected("research_simulation_session_incomplete")
            self._validate_session_integrity(session)
            selection = selection_from_session(session)
            if selection.fingerprint != session["selection_fingerprint"]:
                raise StrategyResearchRejected("research_simulation_selection_drift")
            draft_row = self._research_store.get_draft(
                source.session_id, source.draft_id
            )
            draft = draft_row["contract"]
            if (
                draft_row["validation_status"] != "valid"
                or draft_row["session_id"] != source.session_id
                or draft_row["draft_id"] != source.draft_id
                or draft.get("session_id") != source.session_id
                or draft.get("draft_id") != source.draft_id
                or draft_row["artifact_fingerprint"] != content_fingerprint(draft)
                or any(
                    draft.get(key) != session[key]
                    for key in (
                        "workflow_id",
                        "context_snapshot_id",
                        "context_fingerprint",
                        "evidence_reference_id",
                    )
                )
            ):
                raise StrategyResearchRejected("research_simulation_draft_drift")
            backtest = self._research_store.get_backtest(source.backtest_run_id)
            if (
                backtest["status"] != "completed"
                or backtest["backtest_run_id"] != source.backtest_run_id
                or backtest["session_id"] != source.session_id
                or backtest["draft_id"] != source.draft_id
                or backtest["canonical_backtest_result_id"]
                != source.canonical_backtest_result_id
            ):
                raise StrategyResearchRejected("research_simulation_backtest_drift")
            saved = self._research_store.research_backtest_result(
                source.canonical_backtest_result_id
            )
            metrics = strategy_research_json_object(saved.get("metrics_json"))
            config = strategy_research_json_object(saved.get("config_json"))
            cost = strategy_research_json_object(saved.get("cost_summary_json"))
            binding = FormulaBinding(**metrics["formula_binding"])
            if (
                metrics["source_selection"] != selection.to_dict()
                or metrics["formula_binding"] != binding.to_dict()
                or draft.get("formula_fingerprint") != binding.fingerprint
                or draft_row["formula_fingerprint"] != binding.fingerprint
                or backtest["formula_fingerprint"] != binding.fingerprint
                or backtest["dataset_snapshot_id"] != selection.dataset_snapshot_id
                or backtest["cost_model_reference"] != selection.cost_model_reference
                or any(
                    draft.get(key) != value
                    for key, value in {
                        "selected_universe": list(selection.universe),
                        "dataset_snapshot_id": selection.dataset_snapshot_id,
                        "test_window": {
                            "start_date": selection.start_date,
                            "end_date": selection.end_date,
                        },
                        "frequency": selection.frequency,
                        "cost_model_reference": selection.cost_model_reference,
                        "formula_ast": binding.formula_ast,
                        "anti_lookahead_assumptions": list(
                            binding.anti_lookahead_assumptions
                        ),
                        "parameter_values": binding.parameter_values,
                        "parameter_ranges": binding.parameter_ranges,
                    }.items()
                )
            ):
                raise StrategyResearchRejected(
                    "research_simulation_formula_binding_drift"
                )
            evidence = metrics["research_evidence_bundle"]
            performance = {
                key: saved.get(key) if saved.get(key) is not None else metrics.get(key)
                for key in (
                    "initial_cash",
                    "final_equity",
                    "total_return",
                    "sharpe",
                    "sortino",
                    "max_drawdown",
                    "win_rate",
                    "duration_days",
                )
            }
            admission = saved_native_research_analysis_admission(
                result_id=source.canonical_backtest_result_id,
                row=saved,
                metrics=metrics,
                config=config,
                cost_summary=cost,
                bundle=evidence,
                performance=performance,
            )
            if (
                admission is None
                or content_fingerprint(evidence) != backtest["evidence_fingerprint"]
            ):
                raise StrategyResearchRejected(
                    "research_simulation_saved_facts_incomplete"
                )
            critique = self._research_store.get_critique(source.critique_id)
            artifact = critique.get("artifact")
            if (
                critique["status"] != "completed"
                or critique["critique_id"] != source.critique_id
                or critique["session_id"] != source.session_id
                or critique["draft_id"] != source.draft_id
                or critique["backtest_run_id"] != source.backtest_run_id
                or not isinstance(artifact, dict)
                or critique["artifact_fingerprint"] != content_fingerprint(artifact)
            ):
                raise StrategyResearchRejected("research_simulation_critique_drift")
            pack = build_normalized_research_pack(
                simulation_notional=selection.simulation_validation_binding is not None,
                performance=saved,
                after_cost_evidence=metrics["evidence_bundle"],
                cost_summary=cost,
                research_evidence_bundle=evidence,
                oos_validation=metrics["oos_validation"],
            )
            expected_echo = {
                "canonical_backtest_result_id": source.canonical_backtest_result_id,
                "formula_fingerprint": binding.fingerprint,
                "dataset_snapshot_id": selection.dataset_snapshot_id,
                "cost_model_reference": selection.cost_model_reference,
                "notional_policy_id": pack["notional_policy_id"],
                **pack["performance_summary"],
                **pack["cost_summary"],
                "oos_validation_fingerprint": content_fingerprint(
                    metrics["oos_validation"]
                ),
                "research_evidence_fingerprint": content_fingerprint(evidence),
                "robustness_evidence_fingerprint": content_fingerprint(
                    build_normalized_robustness_evidence(metrics)
                ),
            }
            critique_workflow = self._ai_store.get_workflow(critique["workflow_id"])
            if (
                artifact.get("canonical_binding_echo") != expected_echo
                or critique["workflow_id"] == session["workflow_id"]
                or critique_workflow.status != "completed"
                or critique_workflow.partial_result
                or critique_workflow.workflow_id != critique["workflow_id"]
                or critique_workflow.context_snapshot_id
                != session["context_snapshot_id"]
                or critique_workflow.context_fingerprint
                != session["context_fingerprint"]
                or artifact.get("evidence_reference_ids")
                != [session["evidence_reference_id"]]
                or not self._ai_store.verify_replay(critique["workflow_id"]).valid
                or report_artifact(self._ai_store, critique["workflow_id"]).content
                != artifact
                or any(
                    not self._research_store.verify_events(entity_id)[0]
                    for entity_id in (source.backtest_run_id, source.critique_id)
                )
            ):
                raise StrategyResearchRejected(
                    "research_simulation_critique_binding_drift"
                )
            core = {
                **result,
                "status": "ready",
                "blockers": [],
                "session_id": source.session_id,
                "draft_id": source.draft_id,
                "backtest_run_id": source.backtest_run_id,
                "critique_id": source.critique_id,
                "canonical_backtest_result_id": source.canonical_backtest_result_id,
                "selection": selection.to_dict(),
                "dataset_snapshot": metrics["dataset_snapshot"],
                "formula_fingerprint": binding.fingerprint,
                "formula_ast": binding.formula_ast,
                "draft": draft,
                "critique": artifact,
                "research_evidence_bundle": evidence,
                "dataset_simulation_admission": admission,
                "cost_assumptions": config.get("cost_assumptions"),
                "historical_validation_status": "not_assessed",
                "current_CAS_replayed": False,
            }
            return {
                **core,
                "source_fingerprint": "sha256:" + content_fingerprint(core),
            }
        except (
            KeyError,
            LookupError,
            OSError,
            TypeError,
            ValueError,
            StrategyResearchDatabaseError,
        ) as exc:
            result["status"] = "blocked"
            result["blockers"] = [
                str(exc)
                if isinstance(exc, StrategyResearchRejected)
                else "research_simulation_source_unreadable_or_invalid"
            ]
            return result

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
        stored_workflow = None
        workflow = None
        if session.get("workflow_id"):
            try:
                stored_workflow = self._ai_store.get_workflow(
                    str(session["workflow_id"])
                )
                workflow = {
                    "workflow_id": stored_workflow.workflow_id,
                    "status": stored_workflow.status.value,
                    "failure_code": stored_workflow.failure_code,
                }
            except (LookupError, StrategyResearchOperationalError):
                stored_workflow = None
                workflow = None
        request = strategy_research_request_json(session)
        research_run = build_research_run_projection(
            session=session,
            workflow=stored_workflow,
        )
        return {
            "schema_version": STRATEGY_RESEARCH_API_CONTRACT,
            "session_id": session["session_id"],
            "status": session["status"],
            "failure_code": session.get("failure_code"),
            "research_question": request.get("research_question"),
            "research_task_id": request.get("research_task_id"),
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
            "research_run": research_run.to_dict(),
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
        if blocker := backtest_evidence_blocker(row):
            raise StrategyResearchRejected(blocker)
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
            return self._build_account_capital_evidence(
                selection=selection,
                account_evidence=None,
                reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
            )
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

    def _require_settings(self) -> StrategyResearchSettings:
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
                evaluation_bundle = build_research_evaluation_bundle(
                    backtest_result_id=int(result_id),
                    persisted_row=row,
                    metrics=metrics,
                )
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
                    "evaluation_bundle": evaluation_bundle.to_dict(),
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
