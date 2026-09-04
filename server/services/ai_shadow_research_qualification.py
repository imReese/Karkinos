"""Provider-free account qualification for frozen normalized Formula research."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
    is_valid_passed_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
)
from server.ai_runtime.strategy_research_support import selection_from_session
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    ShadowResearchPolicy,
)
from server.contracts.ai_shadow_research_qualification import (
    ShadowResearchQualificationRejected,
    qualification_formula_semantic_fingerprint,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.daily_strategy_artifacts import DRAFT_BACKUP_FIELDS
from server.contracts.strategy_research import StrategyResearchSelection
from server.services.account_qualification_admission import (
    QualificationAdmission,
    QualificationAdmissionDeferred,
)
from server.services.account_qualification_capture import (
    capture_qualification_account_state,
)
from server.services.account_qualification_reuse import (
    require_current_qualification_valuation,
    require_normalized_source_selection,
    require_qualification_source_run_id,
    resolve_qualification_stock_fee_schedule,
    reusable_terminal_qualification_result,
    select_oldest_retryable_source_run_id,
)
from server.services.ai_shadow_research_qualification_support import (
    QUALIFICATION_COMPARISON_SCHEMA,
    QUALIFICATION_MARKET_OPEN_BLACKOUT_CODE,
    QUALIFICATION_NOTIONAL_POLICY_ID,
    FrozenQualificationSource,
    QualificationBaselinePreparer,
    blocked_result,
    call_maybe_async,
    classify_qualification_resume_candidates,
    deferred_result,
    failure_code,
    formula_binding,
    money_text,
    public_result,
    qualification_backtest_values,
    qualification_initial_cash,
    qualification_selection,
    record_blocked_qualification_attempt,
)
from server.services.ai_shadow_research_support import (
    shadow_research_backtest_source_fingerprint,
    shadow_research_market_close_as_of,
)
from server.services.market_calendar_dates import latest_verified_closed_trading_date


class AiShadowResearchQualificationService:
    """Replay a verified five-candidate batch without external authority."""

    def __init__(
        self,
        *,
        db: Any,
        store: Any,
        daily_artifact_store: Any,
        research_store: Any,
        data_store: Any,
        capture_service: Any | None,
        capture_service_factory: Callable[[], Any] | None = None,
        account_identity_reader: Callable[[], Any],
        reviewed_fee_schedule_resolver: Callable[..., Any],
        account_evidence_reader: Callable[[str], Any] | None = None,
        reviewed_fee_identity_reader: (
            Callable[[StrategyResearchSelection], Any] | None
        ) = None,
        dataset_snapshot_replay_reader: (
            Callable[[Mapping[str, Any]], Any] | None
        ) = None,
        now: Callable[[], datetime | str] | None = None,
        latest_closed_trading_date_reader: (
            Callable[[Any, datetime], str | None] | None
        ) = None,
        baseline_preparer: Callable[..., Any] | None = None,
        backtest_adapter: Any | None = None,
        advancement_gate_builder: Callable[..., Any] = (
            build_strategy_advancement_gate
        ),
    ) -> None:
        self._db = db
        self._store = store
        self._daily_artifact_store = daily_artifact_store
        self._research_store = research_store
        self._capture_service = capture_service
        self._capture_service_factory = capture_service_factory
        self._account_identity_reader = account_identity_reader
        self._reviewed_fee_schedule_resolver = reviewed_fee_schedule_resolver
        self._account_evidence_reader = account_evidence_reader
        self._reviewed_fee_identity_reader = reviewed_fee_identity_reader
        self._dataset_snapshot_replay_reader = dataset_snapshot_replay_reader
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._latest_closed_trading_date_reader = (
            latest_closed_trading_date_reader or latest_verified_closed_trading_date
        )
        self._baseline_preparer = baseline_preparer or (
            QualificationBaselinePreparer(
                db=db,
                data_store=data_store,
            )._prepare_baseline
        )
        self._backtest_adapter = backtest_adapter or (
            RestrictedFormulaBacktestAdapter(data_store=data_store)
        )
        self._advancement_gate_builder = advancement_gate_builder

    async def run_once(self, *, source_run_id: str | None = None) -> dict[str, Any]:
        """Qualify the oldest retryable or one explicitly selected source batch."""
        batch: dict[str, Any] | None = None
        qualification_run: dict[str, Any] | None = None
        try:
            admission = QualificationAdmission.admit(self._now)
            batch, frozen = await asyncio.to_thread(
                self._freeze_batch,
                source_run_id,
            )
            snapshot = await call_maybe_async(self._account_identity_reader)
            valuation = require_current_qualification_valuation(
                snapshot,
                batch=batch,
                db=self._db,
                clock=self._now,
                latest_closed_market_date_reader=(
                    self._latest_closed_trading_date_reader
                ),
            )
            terminal = await reusable_terminal_qualification_result(
                db=self._db,
                store=self._store,
                batch=batch,
                sources=frozen,
                valuation=valuation,
                account_evidence_reader=self._account_evidence_reader,
                reviewed_fee_identity_reader=self._reviewed_fee_identity_reader,
                dataset_snapshot_replay_reader=(self._dataset_snapshot_replay_reader),
                advancement_gate_builder=self._advancement_gate_builder,
            )
            if terminal is not None:
                return terminal
            admission.require_open()
            account = await self._capture_account_state(
                batch=batch,
                valuation=valuation,
                admission=admission,
            )
            admission.require_open()
            fee_resolution = await asyncio.to_thread(
                resolve_qualification_stock_fee_schedule,
                self._reviewed_fee_schedule_resolver,
                frozen[0].source_selection,
            )
            initial_cash = qualification_initial_cash(account["total_equity"])
            account_capital = build_research_account_capital_evidence(
                initial_cash=initial_cash,
                account_evidence=account["record"].to_dict(),
                fee_schedule_evidence=fee_resolution.fee_evidence,
                expected_valuation_snapshot_id=account["valuation_snapshot_id"],
                expected_ledger_cutoff_id=account["ledger_cutoff_id"],
            )
            if not is_valid_passed_research_account_capital_evidence(
                account_capital,
                expected_initial_cash=initial_cash,
                expected_valuation_snapshot_id=account["valuation_snapshot_id"],
                expected_ledger_cutoff_id=account["ledger_cutoff_id"],
            ):
                raise ShadowResearchQualificationRejected(
                    "qualification_account_capital_evidence_not_passing"
                )
            prepared, baseline_result_id = await self._prepare_account_baseline(
                source=frozen[0],
                initial_cash=initial_cash,
                fee_resolution=fee_resolution,
                admission=admission,
            )
            admission.require_open()
            run, reused = await asyncio.to_thread(
                self._create_or_get_run,
                batch,
                account,
                fee_resolution,
                initial_cash,
                baseline_result_id,
                admission,
            )
            qualification_run = run
            if reused and run.get("status") != "running":
                raise ShadowResearchQualificationRejected(
                    "qualification_terminal_evidence_revalidation_failed"
                )
            return await self._replay_and_finish(
                batch=batch,
                frozen=frozen,
                account=account,
                fee_resolution=fee_resolution,
                initial_cash=initial_cash,
                account_capital=account_capital,
                prepared=prepared,
                baseline_result_id=baseline_result_id,
                run=run,
                reused=reused,
                admission=admission,
            )
        except QualificationAdmissionDeferred:
            return deferred_result(QUALIFICATION_MARKET_OPEN_BLACKOUT_CODE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            blocker = failure_code(exc)
            result = blocked_result(blocker)
            if batch is None or qualification_run is not None:
                return result
            try:
                admission.require_open()
                attempt = await asyncio.to_thread(
                    record_blocked_qualification_attempt,
                    self._db,
                    batch=batch,
                    blocker=blocker,
                    recorded_at=admission.timestamp(),
                )
            except Exception:
                result["blockers"] = [
                    blocker,
                    "qualification_attempt_persistence_failed",
                ]
                return result
            return {**result, "qualification_attempt": attempt}

    def _freeze_batch(
        self,
        source_run_id: str | None,
    ) -> tuple[dict[str, Any], list[FrozenQualificationSource]]:
        selected_run_id = (
            require_qualification_source_run_id(source_run_id)
            if source_run_id is not None
            else select_oldest_retryable_source_run_id(
                self._daily_artifact_store,
                self._store,
            )
        )
        batch = dict(
            self._daily_artifact_store.load_verified_research_candidate_strategies(
                run_id=selected_run_id
            )
        )
        candidates = batch.get("candidate_strategies")
        if (
            batch.get("expected_candidate_count") != SHADOW_RESEARCH_MAX_CANDIDATES
            or not isinstance(candidates, list)
            or len(candidates) != SHADOW_RESEARCH_MAX_CANDIDATES
            or batch.get("provider_contact_performed") is not False
            or batch.get("changes_capital_authority") is not False
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_source_candidate_set_incomplete"
            )
        source_run = self._store.get_run(str(batch.get("run_id") or ""))
        if source_run.get("status") != "completed" or source_run.get(
            "market_date"
        ) != batch.get("market_date"):
            raise ShadowResearchQualificationRejected(
                "qualification_source_run_not_complete"
            )
        frozen = [self._freeze_source_candidate(batch, item) for item in candidates]
        first = frozen[0].source_selection.to_dict()
        if any(item.source_selection.to_dict() != first for item in frozen[1:]):
            raise ShadowResearchQualificationRejected(
                "qualification_source_selection_drift"
            )
        return batch, frozen

    def _freeze_source_candidate(
        self,
        batch: Mapping[str, Any],
        verified_value: Mapping[str, Any],
    ) -> FrozenQualificationSource:
        verified = dict(verified_value)
        source = self._store.get_candidate(str(verified.get("candidate_id") or ""))
        comparison = source.get("comparison")
        if (
            source.get("run_id") != batch.get("run_id")
            or source.get("draft_id") != verified.get("draft_id")
            or source.get("status") != "evaluated_research_only"
            or source.get("recommendation") != "formula_research_candidate"
            or not isinstance(comparison, Mapping)
            or content_fingerprint(comparison)
            != verified.get("source_comparison_fingerprint")
            or not source.get("session_id")
            or not source.get("backtest_run_id")
            or not source.get("critique_id")
            or int(source.get("candidate_result_id") or 0) <= 0
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_source_candidate_binding_invalid"
            )
        session = self._research_store.get_session(str(source["session_id"]))
        selection = selection_from_session(session)
        if (
            session.get("status") != "completed"
            or session.get("selection_fingerprint") != selection.fingerprint
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_source_session_binding_invalid"
            )
        require_normalized_source_selection(batch, source, selection)
        draft_row = self._research_store.get_draft(
            str(source["session_id"]), str(source["draft_id"])
        )
        draft = draft_row.get("contract")
        strategy = verified.get("strategy")
        if (
            not isinstance(draft, Mapping)
            or not isinstance(strategy, Mapping)
            or draft_row.get("artifact_fingerprint") != content_fingerprint(draft)
            or draft_row.get("formula_fingerprint") != draft.get("formula_fingerprint")
            or {key: draft[key] for key in DRAFT_BACKUP_FIELDS if key in draft}
            != dict(strategy)
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_source_draft_binding_invalid"
            )
        expected_source_binding = formula_binding(selection, draft)
        if expected_source_binding.fingerprint != verified.get("formula_fingerprint"):
            raise ShadowResearchQualificationRejected(
                "qualification_source_formula_binding_invalid"
            )
        source_backtest = self._research_store.get_backtest(
            str(source["backtest_run_id"])
        )
        if (
            source_backtest.get("status") != "completed"
            or source_backtest.get("session_id") != source.get("session_id")
            or source_backtest.get("draft_id") != source.get("draft_id")
            or source_backtest.get("formula_fingerprint")
            != source.get("comparison", {})
            .get("iteration_lineage", {})
            .get("formula_fingerprint")
            or int(source_backtest.get("canonical_backtest_result_id") or 0)
            != int(source["candidate_result_id"])
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_source_backtest_binding_invalid"
            )
        critique = self._research_store.get_critique(str(source["critique_id"]))
        artifact = critique.get("artifact")
        if (
            critique.get("status") != "completed"
            or critique.get("session_id") != source.get("session_id")
            or critique.get("draft_id") != source.get("draft_id")
            or critique.get("backtest_run_id") != source.get("backtest_run_id")
            or not isinstance(artifact, Mapping)
            or critique.get("artifact_fingerprint") != content_fingerprint(artifact)
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_source_critique_binding_invalid"
            )
        return FrozenQualificationSource(
            verified=verified,
            source_candidate=dict(source),
            source_selection=selection,
            source_draft=dict(draft),
            source_critique=dict(critique),
            source_backtest=dict(source_backtest),
            semantic_fingerprint=qualification_formula_semantic_fingerprint(strategy),
        )

    async def _capture_account_state(
        self,
        *,
        batch: Mapping[str, Any],
        valuation: Mapping[str, Any],
        admission: QualificationAdmission,
    ) -> dict[str, Any]:
        capture_service = self._capture_service
        if capture_service is None:
            if self._capture_service_factory is None:
                raise ShadowResearchQualificationRejected(
                    "qualification_capture_service_unavailable"
                )
            capture_service = self._capture_service_factory()
            self._capture_service = capture_service
        return await capture_qualification_account_state(
            capture_service,
            batch=batch,
            valuation=valuation,
            write_guard=admission.require_open,
        )

    async def _prepare_account_baseline(
        self,
        *,
        source: FrozenQualificationSource,
        initial_cash: Decimal,
        fee_resolution: Any,
        admission: QualificationAdmission,
    ) -> tuple[Any, int]:
        policy = ShadowResearchPolicy(
            enabled=False,
            baseline_backtest_result_id=source.source_selection.saved_backtest_result_id,
            research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
            require_complete_account_evidence=True,
        )
        admission.require_open()
        prepared = await asyncio.to_thread(
            self._baseline_preparer,
            policy,
            initial_cash_override=float(initial_cash),
            expected_market_date=source.source_selection.end_date,
            expected_dataset_snapshot_id=source.source_selection.dataset_snapshot_id,
            reviewed_fee_schedule_resolution=fee_resolution,
        )
        if (
            prepared.market_date != source.source_selection.end_date
            or prepared.snapshot.get("snapshot_id")
            != source.source_selection.dataset_snapshot_id
            or prepared.cost_model_reference != fee_resolution.cost_model_reference
            or Decimal(str(prepared.result.get("initial_cash"))) != initial_cash
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_baseline_binding_mismatch"
            )
        admission.require_open()
        baseline_result_id = await asyncio.to_thread(
            self._store.save_baseline,
            baseline_fingerprint=prepared.fingerprint,
            request=prepared.request,
            result=prepared.result,
            now=admission.timestamp(),
        )
        if int(baseline_result_id or 0) <= 0:
            raise ShadowResearchQualificationRejected(
                "qualification_baseline_persistence_failed"
            )
        return prepared, int(baseline_result_id)

    def _create_or_get_run(
        self,
        batch: Mapping[str, Any],
        account: Mapping[str, Any],
        fee_resolution: Any,
        initial_cash: Decimal,
        baseline_result_id: int,
        admission: QualificationAdmission,
    ) -> tuple[dict[str, Any], bool]:
        evidence = fee_resolution.fee_evidence
        admission.require_open()
        return self._store.create_or_get_qualification_run(
            source_run_id=str(batch["run_id"]),
            market_date=str(batch["market_date"]),
            source_selection_id=str(batch["selection_id"]),
            source_selection_fingerprint=str(batch["selection_fingerprint"]),
            source_backup_fingerprint=str(batch["backup_artifact_fingerprint"]),
            valuation_snapshot_id=str(account["valuation_snapshot_id"]),
            valuation_snapshot_fingerprint=str(
                account["valuation_snapshot_fingerprint"]
            ),
            ledger_cutoff_id=int(account["ledger_cutoff_id"]),
            ledger_fingerprint=str(account["ledger_fingerprint"]),
            account_evidence_reference=account["record"].reference_id,
            account_evidence_fingerprint=account["record"].record_fingerprint,
            account_truth_source_fingerprint=str(
                evidence["account_truth_source_fingerprint"]
            ),
            account_truth_scope_fingerprint=str(
                evidence["account_truth_scope_fingerprint"]
            ),
            reviewed_cost_model_reference=fee_resolution.cost_model_reference,
            reviewed_fee_schedule_fingerprint=str(evidence["fee_schedule_fingerprint"]),
            initial_cash_text=money_text(initial_cash),
            baseline_result_id=baseline_result_id,
            now=admission.timestamp(),
        )

    async def _replay_and_finish(
        self,
        *,
        batch: Mapping[str, Any],
        frozen: Sequence[FrozenQualificationSource],
        account: Mapping[str, Any],
        fee_resolution: Any,
        initial_cash: Decimal,
        account_capital: Mapping[str, Any],
        prepared: Any,
        baseline_result_id: int,
        run: Mapping[str, Any],
        reused: bool,
        admission: QualificationAdmission,
    ) -> dict[str, Any]:
        qualification_run_id = str(run["qualification_run_id"])
        persisted = await asyncio.to_thread(
            self._store.list_qualification_candidates,
            qualification_run_id,
        )
        existing, replay_failed = classify_qualification_resume_candidates(
            frozen, persisted, require_complete=False
        )
        for item in frozen:
            if item.source_candidate["candidate_id"] in existing:
                continue
            try:
                admission.require_open()
                candidate = await self._replay_candidate(
                    source=item,
                    account=account,
                    fee_resolution=fee_resolution,
                    initial_cash=initial_cash,
                    account_capital=account_capital,
                    prepared=prepared,
                    baseline_result_id=baseline_result_id,
                    qualification_run_id=qualification_run_id,
                    admission=admission,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                replay_failed = True
                admission.require_open()
                candidate = await asyncio.to_thread(
                    self._store.save_qualification_candidate,
                    qualification_run_id=qualification_run_id,
                    source_candidate_id=item.source_candidate["candidate_id"],
                    source_draft_id=item.source_candidate["draft_id"],
                    source_formula_fingerprint=item.source_draft["formula_fingerprint"],
                    qualified_formula_fingerprint=item.source_draft[
                        "formula_fingerprint"
                    ],
                    source_formula_semantic_fingerprint=item.semantic_fingerprint,
                    qualified_formula_semantic_fingerprint=item.semantic_fingerprint,
                    candidate_result_id=None,
                    comparison={
                        "schema_version": QUALIFICATION_COMPARISON_SCHEMA,
                        "research_capital_mode": "account_bound",
                        "account_qualification_status": "failed",
                        "failure_code": failure_code(exc),
                        "promotion_gate": {
                            "status": "blocked",
                            "blockers": [failure_code(exc)],
                        },
                        "provider_call_performed": False,
                        "broker_order_created": False,
                        "capital_authority_granted": False,
                    },
                    status="failed",
                    recommendation="reject",
                    rank=int(item.verified["iteration_number"]),
                    now=admission.timestamp(),
                )
            existing[item.source_candidate["candidate_id"]] = candidate
        persisted = await asyncio.to_thread(
            self._store.list_qualification_candidates,
            qualification_run_id,
        )
        candidates_by_source, final_invalid = classify_qualification_resume_candidates(
            frozen, persisted, require_complete=True
        )
        replay_failed = replay_failed or final_invalid
        candidates = [
            candidates_by_source[str(item.source_candidate["candidate_id"])]
            for item in frozen
            if str(item.source_candidate["candidate_id"]) in candidates_by_source
        ]
        terminal = qualification_selection(
            qualification_run_id=qualification_run_id,
            source_run_id=str(batch["run_id"]),
            market_date=str(batch["market_date"]),
            candidates=candidates,
            replay_failed=replay_failed,
        )
        admission.require_open()
        finished = await asyncio.to_thread(
            self._store.finish_qualification_run,
            qualification_run_id,
            status=terminal["run_status"],
            selection=terminal["selection"],
            blockers=terminal["blockers"],
            failure_code=terminal["failure_code"],
            now=admission.timestamp(),
        )
        return await asyncio.to_thread(public_result, self._store, finished, reused)

    async def _replay_candidate(
        self,
        *,
        source: FrozenQualificationSource,
        account: Mapping[str, Any],
        fee_resolution: Any,
        initial_cash: Decimal,
        account_capital: Mapping[str, Any],
        prepared: Any,
        baseline_result_id: int,
        qualification_run_id: str,
        admission: QualificationAdmission,
    ) -> dict[str, Any]:
        selection = StrategyResearchSelection(
            saved_backtest_result_id=baseline_result_id,
            universe=source.source_selection.universe,
            asset_classes=source.source_selection.asset_classes,
            dataset_snapshot_id=source.source_selection.dataset_snapshot_id,
            start_date=source.source_selection.start_date,
            end_date=source.source_selection.end_date,
            frequency=source.source_selection.frequency,
            initial_cash=float(initial_cash),
            cost_model_reference=fee_resolution.cost_model_reference,
            account_truth_freshness_as_of=shadow_research_market_close_as_of(
                source.source_selection.end_date, "15:30"
            ).isoformat(),
            valuation_snapshot_id=str(account["valuation_snapshot_id"]),
            ledger_cutoff_id=int(account["ledger_cutoff_id"]),
        )
        draft = dict(source.source_draft)
        draft["cost_model_reference"] = selection.cost_model_reference
        draft["formula_fingerprint"] = formula_binding(selection, draft).fingerprint
        qualified_semantic = qualification_formula_semantic_fingerprint(draft)
        if qualified_semantic != source.semantic_fingerprint:
            raise ShadowResearchQualificationRejected(
                "qualification_formula_semantics_changed"
            )
        admission.require_open()
        result, request = await asyncio.to_thread(
            self._backtest_adapter.run,
            selection=selection,
            draft=draft,
            expected_dataset_snapshot=prepared.snapshot,
            reviewed_fee_schedule_resolution=fee_resolution,
            account_capital_evidence=account_capital,
        )
        baseline_row = await self._db.get_backtest_result(baseline_result_id)
        if not isinstance(baseline_row, Mapping):
            raise ShadowResearchQualificationRejected(
                "qualification_backtest_persistence_missing"
            )
        baseline_view = strategy_advancement_backtest_view(baseline_row)

        def build_candidate_evidence(candidate_row: Mapping[str, Any]):
            candidate_view = strategy_advancement_backtest_view(candidate_row)
            gate = self._advancement_gate_builder(
                baseline=baseline_view,
                candidate=candidate_view,
                critique_evidence={
                    "status": "completed",
                    "critique_id": source.source_critique["critique_id"],
                    "artifact_fingerprint": source.source_critique[
                        "artifact_fingerprint"
                    ],
                },
            )
            gate_payload = gate.to_json_dict()
            status = "qualified" if gate.passed else "blocked"
            recommendation = (
                "paper_shadow_review" if gate.passed else "keep_researching"
            )
            comparison = {
                "schema_version": QUALIFICATION_COMPARISON_SCHEMA,
                "baseline_source_fingerprint": (
                    shadow_research_backtest_source_fingerprint(baseline_row)
                ),
                "candidate_source_fingerprint": (
                    shadow_research_backtest_source_fingerprint(candidate_row)
                ),
                "source_run_id": source.source_candidate["run_id"],
                "source_candidate_id": source.source_candidate["candidate_id"],
                "source_draft_id": source.source_candidate["draft_id"],
                "source_selection_fingerprint": source.source_selection.fingerprint,
                "qualified_selection_fingerprint": selection.fingerprint,
                "source_strategy_artifact_fingerprint": source.verified[
                    "strategy_artifact_fingerprint"
                ],
                "source_formula_semantic_fingerprint": source.semantic_fingerprint,
                "qualified_formula_semantic_fingerprint": qualified_semantic,
                "baseline": baseline_view,
                "candidate": candidate_view,
                "deltas": {
                    "total_return": candidate_view["total_return"]
                    - baseline_view["total_return"],
                    "sharpe": candidate_view["sharpe"] - baseline_view["sharpe"],
                    "max_drawdown": candidate_view["max_drawdown"]
                    - baseline_view["max_drawdown"],
                    "total_cost": candidate_view["total_cost"]
                    - baseline_view["total_cost"],
                },
                "deepseek_critique": dict(source.source_critique["artifact"]),
                "critique_reuse_scope": (
                    "formula_semantics_only_frozen_source_evidence"
                ),
                "research_capital_mode": "account_bound",
                "account_qualification_status": (
                    "passed" if gate.passed else "blocked"
                ),
                "account_capital_constraint": dict(account_capital),
                "initial_cash_policy": {
                    "policy_id": QUALIFICATION_NOTIONAL_POLICY_ID,
                    "normalized_notional_policy_id": (
                        NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID
                    ),
                    "rule": (
                        "minimum_of_normalized_notional_and_reconciled_total_equity"
                    ),
                    "research_initial_cash": money_text(initial_cash),
                },
                "iteration_lineage": dict(
                    source.source_candidate["comparison"]["iteration_lineage"]
                ),
                "recommendation": recommendation,
                "promotion_gate": gate_payload,
                "provider_call_performed": False,
                "automatic_strategy_replacement_enabled": False,
                "production_strategy_mutation_enabled": False,
                "broker_order_created": False,
                "broker_submission_enabled": False,
                "capital_authority_granted": False,
                "authority_effect": "research_only",
            }
            return comparison, status, recommendation

        admission.require_open()
        return await asyncio.to_thread(
            self._store.save_qualification_candidate_with_backtest,
            qualification_run_id=qualification_run_id,
            source_candidate_id=source.source_candidate["candidate_id"],
            source_draft_id=source.source_candidate["draft_id"],
            source_formula_fingerprint=source.source_draft["formula_fingerprint"],
            qualified_formula_fingerprint=draft["formula_fingerprint"],
            source_formula_semantic_fingerprint=source.semantic_fingerprint,
            qualified_formula_semantic_fingerprint=qualified_semantic,
            rank=int(source.verified["iteration_number"]),
            backtest_values=qualification_backtest_values(request, result),
            candidate_evidence_builder=build_candidate_evidence,
            now=admission.timestamp(),
        )
