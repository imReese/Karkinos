"""Reserve and evaluate one frozen research champion on future observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from threading import Event, Thread
from typing import Any
from zoneinfo import ZoneInfo

from analytics.dataset_snapshot import (
    dataset_research_use,
    verify_backtest_dataset_snapshot_replay,
)
from analytics.multiple_testing import build_return_series_trial_correction
from analytics.sealed_holdout import (
    build_sealed_holdout_evaluation,
    build_sealed_partition,
    final_research_evaluation_blocker,
    sealed_return_from_result,
)
from backtest.costs import research_friction_assumptions
from core.types import InstrumentKey
from server.ai_runtime.formula_challengers import (
    build_challenger_comparison,
    frozen_research_challengers,
)
from server.ai_runtime.strategy_research_backtest import build_dual_ma_research_strategy
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.jobs import JobLease
from server.contracts.strategy_research import StrategyResearchRejected
from server.persistence.jobs import SQLiteJobStore

FINAL_EVALUATION_SCHEMA = "karkinos.research_final_evaluation.v1"


class _FinalEvaluationLeaseUnavailable(ValueError):
    """An interrupted operational owner is not a scientific final-test failure."""


def sealed_execution_code_binding() -> dict[str, Any]:
    """Freeze the implementation used for the future test, not historical proof."""
    import hashlib
    import platform
    from pathlib import Path

    import numpy as np
    import pandas as pd
    import pyarrow as pa

    root = Path(__file__).resolve().parents[2]
    paths = (
        "server/services/research_final_evaluation.py",
        "server/services/recommendation_publication.py",
        "server/services/strategy_promotion_support.py",
        "server/services/valuation_snapshot.py",
        "server/projections/valuation_snapshot.py",
        "server/valuation_snapshot_contract.py",
        "server/projections/service.py",
        "server/projections/portfolio_projection_values.py",
        "server/contracts/recommendation_publication.py",
        "server/services/reviewed_fee_schedule_commission.py",
        "server/services/reviewed_fee_schedule.py",
        "server/services/reviewed_fee_schedule_workflows.py",
        "server/services/reviewed_fee_schedule_repository.py",
        "server/services/reviewed_fee_schedule_policy.py",
        "server/services/backtest_costs.py",
        "server/services/market_universe_truth.py",
        "server/services/research/datasets.py",
        "server/services/research_corporate_action_jobs.py",
        "server/services/research_observation_data_preparation.py",
        "server/persistence/automation_runs.py",
        "server/contracts/research_observation_automation.py",
        "server/services/research_observation_automation.py",
        "server/services/research_observations.py",
        "server/services/research_observation_inputs.py",
        "server/services/research_paper_books.py",
        "backtest/paper_replay.py",
        "server/ai_runtime/strategy_research_backtest.py",
        "server/ai_runtime/formula_dsl.py",
        "server/ai_runtime/formula_challengers.py",
        "server/contracts/content_identity.py",
        "server/contracts/strategy_research.py",
        "server/services/market_calendar_evidence.py",
        "server/services/market_universe_automation.py",
        "analytics/dataset_snapshot.py",
        "analytics/sealed_holdout.py",
        "analytics/multiple_testing.py",
        "analytics/deployment_validation.py",
        "analytics/strategy_advancement_gate.py",
        "domain/research_targets.py",
        "server/ai_runtime/formula_portfolio.py",
        "server/services/account_board_permissions.py",
        "backtest/costs.py",
        "backtest/engine.py",
        "backtest/metrics.py",
        "backtest/result.py",
        "backtest/equity_curve.py",
        "core/event_bus.py",
        "core/events.py",
        "core/types.py",
        "core/clock.py",
        "domain/portfolio.py",
        "domain/position.py",
        "domain/portfolio_accounting.py",
        "domain/instrument.py",
        "domain/a_share_limits.py",
        "execution/commission.py",
        "execution/slippage.py",
        "execution/simulator.py",
        "risk/manager.py",
        "risk/rules.py",
        "strategy/base.py",
        "data/features.py",
        "data/handler.py",
        "data/manager.py",
        "data/research_market_data.py",
        "data/market_daily_store.py",
        "data/store.py",
        "data/dataset/reader.py",
        "data/dataset/model.py",
        "data/dataset/manifest.py",
        "data/market/revision.py",
        "data/market/reconciliation.py",
        "data/market/contracts.py",
        "data/market/capture.py",
        "data/market/normalize.py",
        "data/market/ingestion.py",
        "data/market/cross_source.py",
        "data/market/quality.py",
        "data/market/quality_evidence.py",
        "data/market/verification_evidence.py",
        "data/providers/baostock.py",
        "data/providers/tencent.py",
        "data/providers/tushare.py",
        "data/providers/akshare.py",
        "data/providers/eastmoney.py",
        "data/market/corporate_actions.py",
        "data/providers/tushare_corporate_actions.py",
        "data/storage/objects.py",
        "server/contracts/ai_shadow_research_automation.py",
        "server/services/ai_shadow/ai_shadow_research_commands.py",
        "server/services/ai_shadow/ai_shadow_research_workflow.py",
        "server/persistence/strategy_research_sealed.py",
        "server/persistence/jobs.py",
        "server/contracts/jobs.py",
        "server/persistence/research_observations.py",
        "server/services/ai_shadow/ai_shadow_research_qualification.py",
        "server/projections/daily_strategy_research_candidates.py",
        "server/projections/daily_strategy_artifacts.py",
        "server/projections/normalized_research_recommendation.py",
        "server/services/account_qualification_reuse.py",
        "server/services/ai_shadow/ai_shadow_research_candidate_workflow.py",
        "server/contracts/normalized_strategy_research.py",
        "server/ai_runtime/strategy_research_support.py",
        "server/ai_runtime/strategy_research_privacy.py",
        "server/services/ai_shadow/ai_shadow_research_baseline.py",
        "server/persistence/research_paper_books.py",
        "server/persistence/ai_shadow_research_qualification_promotion.py",
        "server/persistence/ai_shadow_research_qualification.py",
        "server/persistence/ai_shadow_research_qualification_candidate_uow.py",
        "server/contracts/ai_shadow_research_qualification.py",
        "server/services/ai_shadow/ai_shadow_research_support.py",
        "server/services/ai_shadow/ai_shadow_research_qualification_support.py",
    )
    payload = {
        "purpose": "frozen_future_evaluation_implementation",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": pa.__version__,
        "files": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in paths
        },
        "verifies_historical_research_code": False,
    }
    return {**payload, "fingerprint": content_fingerprint(payload)}


def _object(value: Any) -> dict[str, Any]:
    import json

    return json.loads(value) if isinstance(value, str) else dict(value or {})


def _validation_policy(binding):
    from server.contracts.research_observation_automation import (
        reserved_validation_policy,
    )

    return reserved_validation_policy(binding)


def _reserved_execution_costs(db, binding, universe):
    from types import SimpleNamespace

    if binding.get("simulation_policy"):
        from server.contracts.http.strategy_models import BacktestCostAssumptions
        from server.services.backtest_costs import resolve_backtest_costs

        costs, evidence = resolve_backtest_costs(
            BacktestCostAssumptions.model_validate(binding["simulation_cost_inputs"])
        )
        return SimpleNamespace(
            commission_calc=costs.commission_calc, fee_evidence=evidence
        )
    from server.services.account.reviewed_fee_schedule import (
        resolve_frozen_deployment_fee_schedule,
    )

    return resolve_frozen_deployment_fee_schedule(db, binding["fee_schedule"], universe)


async def reserve_final_research_evaluation(
    *,
    db: Any,
    research_store: Any,
    run: Mapping[str, Any],
    selection: Any,
    candidates: list[dict[str, Any]],
    daily_selection: Mapping[str, Any],
    now: str,
    reviewed_fee_schedule_resolver: Any = None,
    account_config: Any = None,
) -> dict[str, Any] | None:
    """Only a completed validation ranking may freeze a future-test champion."""
    if not selection.has_sealed_holdout:
        return None
    winner_id = daily_selection.get("research_recommendation", {}).get(
        "research_winner_candidate_id"
    )
    if not winner_id:
        return None
    champion = next(item for item in candidates if item["candidate_id"] == winner_id)
    partition = build_sealed_partition(
        research_start=selection.start_date,
        research_end=selection.end_date,
        sealed_end=selection.sealed_end_date,
    )
    baseline = await db.get_backtest_result(selection.saved_backtest_result_id)
    candidate = await db.get_backtest_result(champion["candidate_result_id"])
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        raise StrategyResearchRejected("sealed_research_result_missing")
    baseline_config = _object(baseline.get("config_json"))
    expected_costs = {
        **research_friction_assumptions(),
        "commission_model_reference": selection.cost_model_reference,
    }
    if any(
        _object(row.get("metrics_json")).get("cost_assumptions") != expected_costs
        for row in (baseline, candidate)
    ):
        raise StrategyResearchRejected("sealed_research_execution_cost_binding_missing")
    if baseline_config.get("strategy") != "dual_ma":
        raise StrategyResearchRejected("sealed_baseline_formula_unsupported")
    baseline_formula = build_dual_ma_research_strategy(
        baseline_config.get("params")
        or {
            "short_period": baseline_config.get("short_period", 5),
            "long_period": baseline_config.get("long_period", 20),
        },
        len(selection.universe),
    )._formula_ast
    draft = research_store.get_draft(champion["session_id"], champion["draft_id"])[
        "contract"
    ]
    family = research_store.research_trial_family(selection)
    import json

    curve = candidate.get("equity_curve_json", [])
    curve = json.loads(curve) if isinstance(curve, str) else curve
    correction = build_return_series_trial_correction(
        curve, family["trial_fingerprints"]
    )
    snapshot = _object(baseline.get("metrics_json")).get("dataset_snapshot")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("snapshot_id") != selection.dataset_snapshot_id
    ):
        raise StrategyResearchRejected("sealed_research_snapshot_missing")
    binding = {
        "schema_version": FINAL_EVALUATION_SCHEMA,
        "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
        "source_run_id": run["run_id"],
        "candidate_id": winner_id,
        "session_id": champion["session_id"],
        "draft_id": champion["draft_id"],
        "backtest_run_id": champion["backtest_run_id"],
        "candidate_result_id": champion["candidate_result_id"],
        "champion_formula_fingerprint": "sha256:"
        + content_fingerprint(draft["formula_ast"]),
        "baseline_formula_ast": baseline_formula,
        "challenger_family": frozen_research_challengers(selection.fingerprint),
        "execution_cost_assumptions": research_friction_assumptions(),
        "sealed_book_policy": "fresh_equal_notional_history_warmup_final_bar_target.v1",
        "code_binding": sealed_execution_code_binding(),
        "research_snapshot": snapshot,
        "selection_fingerprint": selection.fingerprint,
        "research_identity": {
            key: selection.to_dict()[key]
            for key in (
                "universe",
                "asset_classes",
                "dataset_snapshot_id",
                "start_date",
                "end_date",
                "frequency",
            )
        },
        "universe": list(selection.universe),
        "partition": partition.to_json_dict(),
        "partition_fingerprint": partition.partition_fingerprint,
        "trial_family": family,
        "trial_correction": correction,
        "selection_evidence_fingerprint": daily_selection["selection_fingerprint"],
        "cost_model_reference": selection.cost_model_reference,
        "frozen_at": now,
        "authority_effect": "none",
    }
    grant = None
    simulation = None
    if selection.deployment_scope:
        from server.contracts.research_observation_automation import (
            read_research_validation_policy,
        )

        try:
            validation_policy = read_research_validation_policy(db, now=now)
        except ValueError:
            if (db.get_automation_policy_sync("ai_shadow_research") or {}).get(
                "simulation_validation"
            ) is not None:
                raise
        else:
            if (
                validation_policy.get("schema_version")
                == "karkinos.research_simulation_policy.v1"
            ):
                simulation = validation_policy
            else:
                grant = validation_policy
    if simulation:
        from datetime import timedelta

        from server.contracts.http.strategy_models import BacktestCostAssumptions
        from server.services.market_universe_automation import verified_trading_dates

        if (
            selection.deployment_scope != simulation["deployment_scope"]
            or selection.simulation_validation_binding
            != {
                key: simulation[key]
                for key in ("grant_id", "generation", "initial_cash")
            }
            or Decimal(str(selection.initial_cash))
            != Decimal(simulation["initial_cash"])
        ):
            raise StrategyResearchRejected(
                "simulation_frozen_scope_or_notional_mismatch"
            )
        if any(
            _object(item.get("metrics_json")).get("entry_board_policy")
            != simulation["entry_board_policy"]
            for item in (baseline, candidate)
        ):
            raise StrategyResearchRejected("simulation_frozen_entry_policy_mismatch")
        opening_days = verified_trading_dates(
            db,
            start_date=partition.sealed_start.isoformat(),
            end_date=min(
                partition.sealed_start + timedelta(days=14), partition.sealed_end
            ).isoformat(),
        )
        if not opening_days:
            raise StrategyResearchRejected("deployment_future_opening_unverified")
        binding.update(
            simulation_policy=simulation,
            deployment_scope=selection.deployment_scope,
            initial_cash=simulation["initial_cash"],
            entry_board_policy=simulation["entry_board_policy"],
            effective_checkpoint=selection.sealed_end_date,
            first_evaluation_session=opening_days[0],
            simulation_cost_inputs=BacktestCostAssumptions().model_dump(mode="json"),
        )
    if selection.deployment_scope and grant:
        from zoneinfo import ZoneInfo

        from server.contracts.recommendation_publication import publication_time
        from server.services.account.account_board_permissions import (
            entry_board_policy_blocker,
            resolve_board_buy_permissions,
        )

        permission_blocker = entry_board_policy_blocker(
            grant["entry_board_policy"],
            resolve_board_buy_permissions(
                account_config,
                publication_time(now)
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .date()
                .isoformat(),
            ),
            decision_date=publication_time(now)
            .astimezone(ZoneInfo("Asia/Shanghai"))
            .date()
            .isoformat(),
        )
        if permission_blocker:
            raise StrategyResearchRejected(permission_blocker)
        if (
            selection.deployment_scope.get("deployment_scope_fingerprint")
            != grant["deployment_scope_fingerprint"]
        ):
            raise StrategyResearchRejected("deployment_grant_scope_mismatch")
        from server.services.account.valuation_snapshot import (
            build_current_valuation_snapshot,
            portfolio_equity_from_valuation,
        )

        valuation = build_current_valuation_snapshot(db, persist=False)
        if valuation.get("status") != "complete":
            raise StrategyResearchRejected("deployment_valuation_incomplete")
        cash = min(
            Decimal(str(selection.initial_cash)),
            portfolio_equity_from_valuation(db, valuation),
            Decimal(str(grant["max_initial_cash"])),
        )
        if cash <= 0:
            raise StrategyResearchRejected("deployment_initial_cash_invalid")
        from server.services.account.reviewed_fee_schedule import (
            freeze_deployment_fee_schedule,
        )

        frozen_fees = freeze_deployment_fee_schedule(
            reviewed_fee_schedule_resolver, selection, selection.sealed_end_date, grant
        )
        from datetime import timedelta

        from server.services.market_universe_automation import verified_trading_dates

        opening_days = verified_trading_dates(
            db,
            start_date=partition.sealed_start.isoformat(),
            end_date=min(
                partition.sealed_start + timedelta(days=14), partition.sealed_end
            ).isoformat(),
        )
        if not opening_days:
            raise StrategyResearchRejected("deployment_future_opening_unverified")
        binding["first_evaluation_session"] = opening_days[0]
        binding["fee_schedule"] = frozen_fees
        binding.update(
            publication_grant=grant,
            deployment_scope=selection.deployment_scope,
            initial_cash=str(cash),
            entry_board_policy=grant["entry_board_policy"],
            effective_checkpoint=selection.sealed_end_date,
        )
        from server.contracts.recommendation_publication import (
            publication_scope_incumbent,
        )

        incumbent = publication_scope_incumbent(db, grant)
        if incumbent:
            payload = _object(incumbent.get("payload_json") or incumbent.get("payload"))
            decision = _object(payload.get("publication_decision"))
            readiness = _object(
                payload.get("policy_readiness") or payload.get("readiness")
            )
            result_id = readiness.get("backtest_result_id") or decision.get(
                "backtest_result_id"
            )
            if not result_id:
                raise StrategyResearchRejected("deployment_incumbent_source_missing")
            old = research_store.research_backtest_result(int(result_id))
            ast = (
                _object(old.get("metrics_json"))
                .get("formula_binding", {})
                .get("formula_ast")
            )
            if not isinstance(ast, dict):
                raise StrategyResearchRejected("deployment_incumbent_formula_missing")
            binding["incumbent"] = {
                "strategy_id": incumbent["strategy_id"],
                "formula_ast": ast,
                "source_result_id": int(result_id),
                "source_fingerprint": content_fingerprint(old),
            }
    return research_store.reserve_research_champion(binding=binding, created_at=now)


def require_final_reservation(
    *,
    research_store: Any,
    source: Any,
    now: datetime,
) -> dict[str, Any]:
    try:
        row = research_store.research_champion_reservation(
            source.source_candidate["run_id"]
        )
    except LookupError as exc:
        raise StrategyResearchRejected("independent_final_evaluation_missing") from exc
    envelope = row.get("evidence") or {}
    binding = envelope.get("reservation", {})
    if (
        row.get("request_fingerprint") != content_fingerprint(binding)
        or binding.get("schema_version") != FINAL_EVALUATION_SCHEMA
        or binding.get("runtime_contract") != SHADOW_RESEARCH_RUNTIME_CONTRACT
        or binding.get("candidate_id") != source.source_candidate["candidate_id"]
        or binding.get("selection_fingerprint") != source.source_selection.fingerprint
        or binding.get("champion_formula_fingerprint")
        != "sha256:" + content_fingerprint(source.source_draft["formula_ast"])
        or binding.get("trial_family")
        != research_store.research_trial_family(
            source.source_selection,
            **(
                {
                    "trial_cutoff": binding["frozen_at"],
                    "exposure_cutoff": now.isoformat(),
                }
                if binding.get("deployment_scope")
                else {}
            ),
        )
    ):
        raise StrategyResearchRejected("independent_final_reservation_drift")
    if (
        binding.get("sealed_book_policy")
        != "fresh_equal_notional_history_warmup_final_bar_target.v1"
    ):
        raise StrategyResearchRejected("independent_final_fresh_book_binding_missing")
    if binding.get("code_binding") != sealed_execution_code_binding():
        raise StrategyResearchRejected("independent_final_execution_code_changed")
    if (
        "challenger_family" not in binding
        or binding.get("execution_cost_assumptions") != research_friction_assumptions()
    ):
        raise StrategyResearchRejected("independent_final_frozen_comparison_missing")
    if binding["challenger_family"] != frozen_research_challengers(
        source.source_selection.fingerprint
    ):
        raise StrategyResearchRejected("independent_final_challenger_family_drift")
    if now.tzinfo is None:
        raise StrategyResearchRejected("independent_final_clock_invalid")
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if local.date().isoformat() < binding["partition"]["sealed_end"] or (
        local.date().isoformat() == binding["partition"]["sealed_end"]
        and (local.hour, local.minute) < (15, 30)
    ):
        raise StrategyResearchRejected("independent_final_window_not_complete")
    if row["status"] == "failed":
        raise StrategyResearchRejected(
            row.get("failure_code") or "independent_final_evaluation_failed"
        )
    return row


async def evaluate_reserved_champion(
    *,
    research_store: Any,
    source: Any,
    adapter: Any,
    now: datetime,
    calendar_db: Any,
    lease_clock: Callable[[], datetime] | None = None,
    lease_seconds: int = 90,
) -> dict[str, Any]:
    row = require_final_reservation(
        research_store=research_store, source=source, now=now
    )
    if row["status"] == "completed":
        return verify_persisted_final_evaluation(
            research_store=research_store,
            evidence=row["evidence"],
            store_root=adapter._data_store._root,
        )
    clock = lease_clock or (lambda: datetime.now(timezone.utc))
    lease = research_store.claim_reserved_sealed_test(
        row["sealed_test_id"], now=clock().isoformat(), lease_seconds=lease_seconds
    )
    if lease is None:
        raise StrategyResearchRejected("independent_final_evaluation_in_progress")
    jobs = SQLiteJobStore(research_store._path)
    stopped = Event()
    lease_lost = Event()

    def require_current():
        if lease_lost.is_set():
            raise _FinalEvaluationLeaseUnavailable("job_lease_lost")
        try:
            jobs.heartbeat(lease, now=clock(), lease_seconds=lease_seconds)
        except Exception as exc:
            code = (
                "job_lease_lost"
                if str(exc) == "job_lease_lost"
                else "independent_final_evaluation_lease_unavailable"
            )
            raise _FinalEvaluationLeaseUnavailable(code) from exc

    def heartbeat():
        # Dataset reopening can also block the event loop. Keep the existing job
        # lease alive independently until every replay thread has stopped.
        interval = lease_seconds / 3
        while not stopped.wait(interval):
            try:
                require_current()
            except ValueError as exc:
                if str(exc) == "job_lease_lost":
                    lease_lost.set()
                    return
                interval = min(1, lease_seconds / 6)
            except Exception:
                # A temporary storage failure is not proof the owner has died.
                # Retry within the current lease; its SQL guard detects expiry.
                interval = min(1, lease_seconds / 6)
            else:
                interval = lease_seconds / 3

    keeper = Thread(target=heartbeat, name="research-final-lease", daemon=True)
    keeper.start()
    try:
        return await _evaluate_claimed_champion(
            research_store=research_store,
            source=source,
            adapter=adapter,
            now=now,
            calendar_db=calendar_db,
            row=row,
            lease=lease,
            lease_clock=clock,
            require_current=require_current,
        )
    finally:
        stopped.set()
        keeper.join()


async def _run_final_replay(adapter, *, require_current, **kwargs):
    """Cancellation cannot abandon a thread that is still measuring this test."""
    require_current()
    replay = asyncio.create_task(asyncio.to_thread(adapter.run_sealed, **kwargs))
    try:
        result = await asyncio.shield(replay)
        require_current()
        return result
    except asyncio.CancelledError:
        while not replay.done():
            try:
                await asyncio.shield(replay)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not replay.cancelled():
            replay.exception()
        raise


async def _evaluate_claimed_champion(
    *,
    research_store: Any,
    source: Any,
    adapter: Any,
    now: datetime,
    calendar_db: Any,
    row: dict[str, Any],
    lease: JobLease,
    lease_clock: Callable[[], datetime],
    require_current: Callable[[], None],
) -> dict[str, Any]:
    binding = row["evidence"]["reservation"]

    def finish(**kwargs):
        try:
            research_store.finish_sealed_test(
                row["sealed_test_id"],
                updated_at=now.isoformat(),
                evaluation_lease=lease,
                lease_clock=lease_clock,
                **kwargs,
            )
        except Exception as exc:
            code = (
                "job_lease_lost"
                if str(exc) == "job_lease_lost"
                else "independent_final_evaluation_lease_unavailable"
            )
            raise _FinalEvaluationLeaseUnavailable(code) from exc

    result = None
    try:
        selection = source.source_selection
        partition = build_sealed_partition(
            research_start=selection.start_date,
            research_end=selection.end_date,
            sealed_end=binding["partition"]["sealed_end"],
        )
        from server.services.market_universe_automation import verified_trading_dates

        trading_dates = verified_trading_dates(
            calendar_db,
            start_date=selection.start_date,
            end_date=partition.sealed_end.isoformat(),
        )
        if not any(day > selection.end_date for day in trading_dates):
            raise StrategyResearchRejected("independent_final_no_trading_observations")
        evaluation_snapshot = None
        forward_book = None
        if binding.get("deployment_scope"):
            _next_verified_session_opens(
                calendar_db, [d for d in trading_dates if d > selection.end_date]
            )
            from server.services.research.datasets import (
                resolve_deployment_evaluation_dataset,
            )
            from server.services.research_paper_books import (
                verify_reserved_forward_book,
            )

            forward_book = verify_reserved_forward_book(
                calendar_db, row, through_session=trading_dates[-1], now=now
            )
            resolved_dataset = resolve_deployment_evaluation_dataset(
                calendar_db,
                source_result_id=int(binding["candidate_result_id"]),
                scope=binding["deployment_scope"],
                start_date=partition.sealed_start.isoformat(),
                end_date=trading_dates[-1],
                cutoff=now,
                data_store=adapter._data_store,
            )
            if resolved_dataset.get("status") != "ready":
                raise StrategyResearchRejected("deployment_evaluation_dataset_pending")
            evaluation_snapshot = resolved_dataset["dataset_snapshot"]
            from server.services.research_paper_books import (
                verify_reserved_forward_book,
            )

            forward_book = verify_reserved_forward_book(
                calendar_db, row, through_session=trading_dates[-1], now=now
            )
            resolution = _reserved_execution_costs(
                calendar_db,
                binding,
                tuple(
                    item["symbol"] for item in evaluation_snapshot["symbol_universe"]
                ),
            )
        common = {
            "expected_trading_dates": trading_dates,
            "selection": selection,
            "sealed_end_date": partition.sealed_end.isoformat(),
            "expected_dataset_snapshot": binding["research_snapshot"],
            **(
                {
                    "evaluation_dataset_snapshot": evaluation_snapshot,
                    "initial_cash_override": Decimal(binding["initial_cash"]),
                    "commission_calc_override": resolution.commission_calc,
                    "entry_board_policy": binding["entry_board_policy"],
                }
                if evaluation_snapshot
                else {}
            ),
        }

        def require_fresh_book(measured):
            timing = measured.execution_timing or {}
            if (
                measured.initial_cash
                != Decimal(str(binding.get("initial_cash", selection.initial_cash)))
                or timing.get("evaluation_start") != partition.sealed_start.isoformat()
                or timing.get("warmup_basis") != "strategy_history_only_fresh_book"
                or timing.get("warmup_final_bar_targets") is not True
            ):
                raise StrategyResearchRejected("independent_final_fresh_book_mismatch")

        result = await _run_final_replay(
            adapter,
            require_current=require_current,
            draft=source.source_draft,
            **common,
        )
        baseline = await _run_final_replay(
            adapter,
            require_current=require_current,
            draft={"formula_ast": binding["baseline_formula_ast"]},
            **common,
        )
        require_fresh_book(result)
        require_fresh_book(baseline)
        candidate_snapshot = getattr(result, "dataset_snapshot", None)
        if not isinstance(candidate_snapshot, dict) or candidate_snapshot != getattr(
            baseline, "dataset_snapshot", None
        ):
            raise StrategyResearchRejected("independent_final_dataset_binding_invalid")

        def session_curve(measured):
            return [
                [stamp.isoformat(), str(equity)]
                for stamp, equity in measured.equity_curve
                if stamp.date() >= partition.sealed_start
            ]

        comparator_curves = {"frozen_baseline": session_curve(baseline)}
        comparator_accounting = {"frozen_baseline": baseline.cash_dividend_accounting}
        challenger_results = []
        for challenger in binding["challenger_family"]:
            measured = await _run_final_replay(
                adapter, require_current=require_current, draft=challenger, **common
            )
            require_fresh_book(measured)
            if getattr(measured, "dataset_snapshot", None) != candidate_snapshot:
                raise StrategyResearchRejected(
                    "independent_final_challenger_dataset_drift"
                )
            comparator_curves[challenger["label"]] = session_curve(measured)
            comparator_accounting[challenger["label"]] = (
                measured.cash_dividend_accounting
            )
            challenger_results.append(
                {
                    "label": challenger["label"],
                    "formula_fingerprint": "sha256:"
                    + content_fingerprint(challenger["formula_ast"]),
                    "sealed_return": float(
                        sealed_return_from_result(measured, partition)
                    ),
                }
            )
        incumbent_result = None
        if binding.get("incumbent"):
            incumbent_result = await _run_final_replay(
                adapter,
                require_current=require_current,
                draft={"formula_ast": binding["incumbent"]["formula_ast"]},
                **common,
            )
            require_fresh_book(incumbent_result)
            if (
                getattr(incumbent_result, "dataset_snapshot", None)
                != candidate_snapshot
            ):
                raise StrategyResearchRejected("deployment_incumbent_dataset_drift")
            comparator_curves["incumbent"] = session_curve(incumbent_result)
            comparator_accounting["incumbent"] = (
                incumbent_result.cash_dividend_accounting
            )
        champion_return = sealed_return_from_result(result, partition)
        baseline_return = sealed_return_from_result(baseline, partition)
        comparison = build_challenger_comparison(
            champion_return=float(champion_return),
            challenger_returns=[item["sealed_return"] for item in challenger_results],
        )
        benchmark_return = max(
            baseline_return,
            *(Decimal(str(item["sealed_return"])) for item in challenger_results),
        )
        evaluation = build_sealed_holdout_evaluation(
            strategy_id="ai_formula_research",
            benchmark_role="frozen_dual_ma_and_simple_random_challengers",
            research_family_id=binding["trial_family"]["research_family_id"],
            formula_fingerprint=binding["champion_formula_fingerprint"],
            partition=partition,
            result=result,
            benchmark_return=benchmark_return,
        ).to_json_dict()
        core = {
            "schema_version": FINAL_EVALUATION_SCHEMA,
            "reservation": binding,
            "sealed_test_id": row["sealed_test_id"],
            "sealed_dataset_snapshot": candidate_snapshot,
            "sealed_evaluation": evaluation,
            "challenger_results": challenger_results,
            "challenger_comparison": comparison,
            "baseline_sealed_return": float(baseline_return),
            "evaluated_at": now.isoformat(),
            "authority_effect": "none",
        }
        if binding.get("deployment_scope"):
            from analytics.deployment_validation import compare_session_curves

            policy = {
                **_validation_policy(binding)["statistical_policy"],
                "decision_checkpoint": trading_dates[-1],
            }
            uncertainty = compare_session_curves(
                candidate=session_curve(result),
                comparators=comparator_curves,
                initial_cash=result.initial_cash,
                policy=policy,
                seed=row["sealed_test_id"],
            )
            observed_curve = [
                [r["session"], Decimal(r["equity"])]
                for r in forward_book["session_equity"]
            ]
            measured_curve = [
                [ts[:10], Decimal(value)] for ts, value in session_curve(result)
            ]
            if len(observed_curve) != len(measured_curve) or any(
                day != real_day or abs(equity - real_equity) > Decimal("0.01")
                for (day, equity), (real_day, real_equity) in zip(
                    measured_curve, observed_curve, strict=True
                )
            ):
                raise StrategyResearchRejected("deployment_paper_replay_diverged")
            result.comparator_accounting = comparator_accounting
            result.incumbent_portfolio_observations = (
                incumbent_result.portfolio_observations if incumbent_result else []
            )
            assessment = _deployment_assessment(
                binding=binding,
                snapshot=candidate_snapshot,
                uncertainty=uncertainty,
                result=result,
                store_root=calendar_db.path.parent / "research",
                trading_dates=[d for d in trading_dates if d > selection.end_date],
                calendar_db=calendar_db,
            )
            core.update(
                session_curves={
                    "candidate": session_curve(result),
                    "comparators": comparator_curves,
                },
                deployment_assessment=assessment,
                economic_return_accounting=result.cash_dividend_accounting,
                portfolio_observations=result.portfolio_observations,
                incumbent_portfolio_observations=result.incumbent_portfolio_observations,
                comparator_accounting=comparator_accounting,
                forward_book=forward_book,
            )
        payload = {**core, "evidence_fingerprint": content_fingerprint(core)}
        finish(
            status="completed",
            evidence=payload,
            evidence_fingerprint=payload["evidence_fingerprint"],
            failure_code=None,
        )
        return payload
    except _FinalEvaluationLeaseUnavailable:
        # Losing the execution lease or its storage never refunds the frozen
        # test's budget and never fabricates a failed scientific measurement.
        raise
    except Exception as exc:
        # These errors are emitted by the input loader before any simulation.
        # A missing delivery can be retried without consuming a measured result.
        pending_inputs = result is None and (
            str(exc)
            in {
                "sealed_window_not_complete",
                "sealed_trading_calendar_coverage_incomplete",
                "deployment_evaluation_dataset_pending",
                "deployment_evaluation_window_pending",
                "deployment_next_trading_open_unverified",
            }
            or str(exc).startswith(
                (
                    "research_calendar_incomplete:",
                    "persisted_bars_missing:",
                    "persisted_window_empty:",
                    "deployment_forward_checkpoint_not_closed",
                    "deployment_forward_settlement_incomplete",
                )
            )
        )
        finish(
            status="reserved" if pending_inputs else "failed",
            evidence={"reservation": binding},
            evidence_fingerprint=content_fingerprint({"reservation": binding}),
            failure_code=str(exc),
        )
        raise


def require_valid_final_evaluation(value: Mapping[str, Any]) -> None:
    """Check final-test and nominal-trial evidence, without granting authority."""
    blocker = final_research_evaluation_blocker(value)
    if blocker is not None:
        raise StrategyResearchRejected(blocker)


def verify_persisted_final_evaluation(
    *,
    research_store: Any,
    evidence: Mapping[str, Any],
    store_root: Any,
) -> dict[str, Any]:
    """Reopen the exact final test and its input data before a new publication."""
    require_valid_final_evaluation(evidence)
    row = research_store.get_sealed_test(str(evidence.get("sealed_test_id") or ""))
    if row["status"] != "completed" or row.get("evidence") != dict(evidence):
        raise StrategyResearchRejected("independent_final_persisted_evidence_drift")
    import json

    from server.ai_runtime.strategy_research_support import selection_from_session

    binding = evidence["reservation"]
    session = research_store.get_session(binding["session_id"])
    selection = selection_from_session(session)
    family = research_store.research_trial_family(
        selection,
        **(
            {
                "trial_cutoff": binding["frozen_at"],
                "exposure_cutoff": evidence["evaluated_at"],
            }
            if binding.get("deployment_scope")
            else {}
        ),
    )
    original = research_store.research_backtest_result(binding["candidate_result_id"])
    curve = original["equity_curve_json"]
    curve = json.loads(curve) if isinstance(curve, str) else curve
    correction = build_return_series_trial_correction(
        curve, family["trial_fingerprints"]
    )
    draft = research_store.get_draft(binding["session_id"], binding["draft_id"])[
        "contract"
    ]
    if (
        binding.get("runtime_contract") != SHADOW_RESEARCH_RUNTIME_CONTRACT
        or binding["trial_family"] != family
        or binding["trial_correction"] != correction
        or binding["selection_fingerprint"] != selection.fingerprint
        or binding["champion_formula_fingerprint"]
        != "sha256:" + content_fingerprint(draft["formula_ast"])
        or row["request_fingerprint"] != content_fingerprint(binding)
    ):
        raise StrategyResearchRejected("independent_final_research_source_drift")
    if (
        binding.get("challenger_family")
        != frozen_research_challengers(selection.fingerprint)
        or binding.get("execution_cost_assumptions") != research_friction_assumptions()
        or binding.get("sealed_book_policy")
        != "fresh_equal_notional_history_warmup_final_bar_target.v1"
        or binding.get("code_binding") != sealed_execution_code_binding()
    ):
        raise StrategyResearchRejected("independent_final_frozen_comparison_drift")
    if binding.get("deployment_scope"):
        from datetime import timezone

        from server.db import AppDatabase
        from server.services.research_paper_books import verify_reserved_forward_book

        bound_db = AppDatabase(research_store._path)
        forward = verify_reserved_forward_book(
            bound_db,
            row,
            through_session=evidence["forward_book"]["through_session"],
            now=datetime.now(timezone.utc),
        )
        if forward != evidence["forward_book"]:
            raise StrategyResearchRejected("deployment_forward_book_evidence_drift")
    for snapshot in (binding["research_snapshot"], evidence["sealed_dataset_snapshot"]):
        from pathlib import Path

        replay = verify_backtest_dataset_snapshot_replay(
            snapshot,
            store_root=store_root,
            research_root=Path(research_store._path).parent / "research",
        )
        if replay.get("status") != "pass":
            raise StrategyResearchRejected("independent_final_dataset_replay_failed")
    return dict(evidence)


def require_new_publication_final_evaluation(
    db: Any, result_id: int, *, expected_candidate_id: str
) -> None:
    """New AI publications require final evidence; existing scopes stay unchanged."""
    from server.persistence.strategy_research import StrategyResearchAuditStore
    from server.services.strategy_promotion_support import strategy_dataset_store_root

    path = getattr(db, "_path", None)
    root = strategy_dataset_store_root(db)
    if path is None or root is None:
        raise StrategyResearchRejected("independent_final_store_missing")
    store = StrategyResearchAuditStore(path)
    result = store.research_backtest_result(result_id)
    metrics = _object(result.get("metrics_json"))
    snapshot = _object(metrics.get("dataset_snapshot"))
    research_use = dataset_research_use(snapshot)
    evidence = metrics.get("independent_evaluation")
    if isinstance(evidence, Mapping) and evidence.get("reservation", {}).get(
        "deployment_scope"
    ):
        if evidence.get("reservation", {}).get("candidate_id") != expected_candidate_id:
            raise StrategyResearchRejected("independent_final_candidate_mismatch")
        validation = verify_deployment_validation(db, result_id=result_id)
        if validation.get("status") != "pass":
            raise StrategyResearchRejected("deployment_validation_not_pass")
        return
    if research_use == "exploratory_backtest":
        raise StrategyResearchRejected("candidate_dataset_exploratory_only")
    if "research_use" in snapshot or "immutable_dataset_id" in snapshot:
        raise StrategyResearchRejected("candidate_dataset_research_use_not_admitted")
    evidence = metrics.get("independent_evaluation")
    if not isinstance(evidence, Mapping):
        raise StrategyResearchRejected("independent_final_evaluation_missing")
    if evidence.get("reservation", {}).get("candidate_id") != expected_candidate_id:
        raise StrategyResearchRejected("independent_final_candidate_mismatch")
    formula_binding = metrics.get("formula_binding", {})
    expected_identity = evidence.get("reservation", {}).get("research_identity", {})
    if not expected_identity or any(
        formula_binding.get(key) != expected_identity[key]
        for key in (
            "universe",
            "dataset_snapshot_id",
            "start_date",
            "end_date",
            "frequency",
        )
    ):
        raise StrategyResearchRejected("independent_final_research_identity_mismatch")
    if "sha256:" + content_fingerprint(
        metrics.get("formula_binding", {}).get("formula_ast", {})
    ) != evidence.get("reservation", {}).get("champion_formula_fingerprint"):
        raise StrategyResearchRejected("independent_final_formula_mismatch")
    verify_persisted_final_evaluation(
        research_store=store, evidence=evidence, store_root=root
    )


def _next_verified_session_opens(db, trading_dates):
    from datetime import date, time, timedelta

    from server.services.market_universe_automation import verified_trading_dates

    last = date.fromisoformat(trading_dates[-1])
    end = min(last + timedelta(days=31), date(last.year, 12, 31))
    dates = verified_trading_dates(
        db, start_date=trading_dates[0], end_date=end.isoformat()
    )
    if not any(day > trading_dates[-1] for day in dates):
        dates += verified_trading_dates(
            db,
            start_date=(end + timedelta(days=1)).isoformat(),
            end_date=(end + timedelta(days=31)).isoformat(),
        )
    openings = {}
    for day in trading_dates:
        following = next((other for other in dates if other > day), None)
        if following is None:
            raise StrategyResearchRejected("deployment_next_trading_open_unverified")
        openings[day] = datetime.combine(
            date.fromisoformat(following), time(9, 30), ZoneInfo("Asia/Shanghai")
        )
    return openings


def _replacement_transition_reserve(restored, binding, result, db):
    from backtest.costs import RESEARCH_SLIPPAGE_BPS
    from core.types import OrderSide
    from domain.instrument import make_research_stock
    from server.services.account.reviewed_fee_schedule import (
        resolve_frozen_deployment_fee_schedule,
    )

    books = (
        result.incumbent_portfolio_observations[-1],
        result.portfolio_observations[-1],
    )
    if books[0]["session"] != books[1]["session"]:
        raise StrategyResearchRejected("deployment_transition_interval_mismatch")
    prices = {}
    for bar in restored.bars:
        if bar.session_date.isoformat() <= books[0]["session"]:
            current = prices.get(bar.instrument.symbol)
            if current is None or bar.session_date > current.session_date:
                prices[bar.instrument.symbol] = bar
    symbols = tuple(
        sorted(set(books[0]["position_values"]) | set(books[1]["position_values"]))
    )
    calculator = resolve_frozen_deployment_fee_schedule(
        db, binding["fee_schedule"], symbols
    ).commission_calc
    total, rows = Decimal(0), []
    for side, book in zip((OrderSide.SELL, OrderSide.BUY), books, strict=True):
        for symbol, value in sorted(book["position_values"].items()):
            value = Decimal(value)
            if value <= 0:
                continue
            bar = prices[symbol]
            instrument = make_research_stock(symbol, symbol)
            quantity = value / bar.close
            slipped = bar.close * (
                Decimal(1)
                + (Decimal(1) if side == OrderSide.BUY else Decimal(-1))
                * RESEARCH_SLIPPAGE_BPS
                / Decimal(10000)
            )
            fee = calculator.breakdown_for(
                instrument.commission_type, side, slipped, quantity, symbol=symbol
            ).total_fee
            friction = abs(slipped - bar.close) * quantity + fee
            total += friction
            rows.append(
                {
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": str(quantity),
                    "reference_close": str(bar.close),
                    "modeled_fee": str(fee),
                    "modeled_friction": str(friction),
                }
            )
    capital = min(Decimal(book["equity"]) for book in books)
    if capital <= 0:
        raise StrategyResearchRejected("deployment_transition_capital_invalid")
    return {
        "basis": "reviewed_fees_and_slippage_full_terminal_books_exit_then_entry.v1",
        "session": books[0]["session"],
        "modeled_cost": str(total),
        "capital": str(capital),
        "cost_ratio": str(total / capital),
        "quotes": rows,
    }


def _deployment_assessment(
    *, binding, snapshot, uncertainty, result, store_root, trading_dates, calendar_db
):
    """Reopen dated raw inputs; backfilled warmup never supplies future proof."""
    from pathlib import Path

    from data.dataset.model import DatasetRef
    from data.dataset.reader import read_daily_bar_dataset
    from data.storage.objects import ContentAddressedObjectStore

    root = Path(store_root)
    objects = ContentAddressedObjectStore(root / "objects")
    ref = DatasetRef(objects.resolve_ref(snapshot["immutable_dataset_id"]))
    restored = read_daily_bar_dataset(objects, ref)
    dataset = restored.snapshot
    scope = binding["deployment_scope"]
    blockers = list(uncertainty["blockers"])
    if dataset.universe_policy_id != scope["deployment_scope_fingerprint"]:
        blockers.append("deployment_dataset_scope_mismatch")
    memberships = {
        row.partition_date.isoformat(): row for row in dataset.session_memberships
    }
    import json

    from server.services.market_universe_truth import (
        MarketUniversePolicy,
        market_master_buy_instruments,
    )

    coverage = []
    next_openings = _next_verified_session_opens(calendar_db, trading_dates)
    for day in trading_dates:
        membership = memberships.get(day)
        if (
            membership is None
            or not membership.source_observation_ids
            or membership.decision_at is None
        ):
            blockers.append("deployment_dated_membership_unverified")
            continue
        source_memberships: list[set[InstrumentKey]] = []
        source_count = 0
        for identity in membership.source_observation_ids:
            master = json.loads(objects.read_bytes(objects.resolve_ref(identity)))
            if master.get("schema_version") not in {
                "karkinos.market_universe_snapshot.v2",
                "karkinos.market_universe_snapshot.v3",
            }:
                blockers.append("deployment_dated_membership_unverified")
                source_memberships = []
                break
            source_memberships.append(
                set(
                    market_master_buy_instruments(
                        master, MarketUniversePolicy.from_dict(scope["universe_policy"])
                    )
                )
            )
            source_count = max(source_count, len(master["members"]))
        if not source_memberships:
            continue
        if any(members != source_memberships[0] for members in source_memberships):
            blockers.append("deployment_membership_sources_conflict")
        expected_members = source_memberships[0]
        if set(membership.instruments) != expected_members:
            blockers.append("deployment_full_scope_members_missing")
        coverage.append(
            {
                "session": day,
                "expected": source_count,
                "evaluated": len(membership.instruments),
                "excluded": source_count - len(expected_members),
                "unresolved": len(expected_members - set(membership.instruments)),
            }
        )
        # Even a faithfully captured later backfill is not a forward observation.
        last_admissible = next_openings[day]
        if (
            membership.decision_at >= last_admissible
            or membership.decision_at < datetime.fromisoformat(binding["frozen_at"])
        ):
            blockers.append("deployment_membership_observed_after_decision")
    if not dataset.verification_bound:
        blockers.append("deployment_cross_source_verification_missing")
    accounting = [
        result.cash_dividend_accounting,
        *result.comparator_accounting.values(),
    ]
    if restored.corporate_action_evidence is None or any(
        item is None for item in accounting
    ):
        blockers.append("deployment_economic_return_binding_missing")
    elif any(
        Decimal(str(item.get("gross_income", 0))) > 0
        or Decimal(str(item.get("share_quantity", 0))) > 0
        for item in accounting
    ):
        blockers.append("deployment_unmodeled_distribution_tax_exposure")
    from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence

    drawdown = build_backtest_drawdown_evidence(
        equity_curve=result.equity_curve, initial_cash=binding["initial_cash"]
    )
    books = result.portfolio_observations
    if (
        drawdown["status"] != "complete"
        or [row["session"] for row in books] != trading_dates
    ):
        blockers.append("deployment_book_observations_incomplete")
    gross, symbol, positions = Decimal(0), Decimal(0), 0
    for book in books:
        equity = Decimal(book["equity"])
        values = [Decimal(value) for value in book["position_values"].values()]
        if equity <= 0 or any(value < 0 for value in values):
            raise StrategyResearchRejected("deployment_book_values_invalid")
        gross = max(gross, sum(values, Decimal(0)) / equity)
        symbol = max(symbol, max(values, default=Decimal(0)) / equity)
        positions = max(positions, len(values))
    risk = {
        "max_drawdown": drawdown["max_drawdown_pct"],
        "max_gross_weight": str(gross),
        "max_symbol_weight": str(symbol),
        "max_positions": positions,
    }
    grant = _validation_policy(binding)
    if any(
        Decimal(str(risk[key])) > Decimal(str(limit))
        for key, limit in grant["risk_limits"].items()
    ):
        blockers.append("deployment_risk_exceeds_grant")
    declared_limits = {
        "max_positions": 4,
        "max_symbol_weight": "0.25",
        "max_gross_weight": "0.97",
    }
    if any(
        Decimal(str(value)) > Decimal(str(grant["risk_limits"][key]))
        for key, value in declared_limits.items()
    ):
        blockers.append("deployment_declared_policy_exceeds_grant")
    core = {
        "status": "pass" if not blockers else "insufficient_evidence",
        "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
        "entry_board_policy": binding.get("entry_board_policy"),
        "statistical_policy_fingerprint": grant["statistical_policy_fingerprint"],
        "effective_checkpoint": binding["effective_checkpoint"],
        "risk_limits": risk,
        "uncertainty": uncertainty,
        "return_basis": "after_execution_costs_reported_actions_no_unmodeled_entitlements.v1",
        "corporate_action_coverage": "provider_reported_only",
        "coverage": coverage,
        "dataset_id": ref.dataset_id,
        "membership_sessions": trading_dates,
        "blockers": list(dict.fromkeys(blockers)),
    }
    if binding.get("incumbent"):
        paired = next(
            row for row in uncertainty["comparisons"] if row["label"] == "incumbent"
        )
        reserve = _replacement_transition_reserve(
            restored, binding, result, calendar_db
        )
        transition = Decimal(reserve["cost_ratio"])
        lower = paired["net_excess_lower_bound"]
        core["replacement"] = {
            "incumbent_strategy_id": binding["incumbent"]["strategy_id"],
            "common_interval": True,
            "transition_cost": str(transition),
            "transition_reserve": reserve,
            "net_improvement_lower_bound": str(Decimal(str(lower)) - transition)
            if lower is not None
            else None,
        }
        if lower is None or Decimal(str(lower)) - transition < Decimal(
            str(grant["min_net_improvement"])
        ):
            core["status"] = "insufficient_evidence"
            core["blockers"].append("deployment_incumbent_improvement_not_established")
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def _simulation_account_replay_inputs(db, store, result, evidence, grant):
    """Bind a separately reviewed replay to the unchanged frozen SIM hypothesis.

    No research cost model is relabeled as broker-reviewed. The current review
    remains authoritative, and every frozen comparator is replayed with it.
    """

    from server.services.account.reviewed_fee_schedule import (
        resolve_frozen_deployment_fee_schedule,
    )

    binding = evidence["reservation"]
    sim = binding["simulation_policy"]
    if (
        binding["deployment_scope"]["deployment_scope_fingerprint"]
        != grant["deployment_scope_fingerprint"]
    ):
        raise StrategyResearchRejected("deployment_simulation_scope_mismatch")
    profiles = [
        {k: v for k, v in p.items() if k != "decision_checkpoint"}
        for p in (sim["statistical_policy"], grant["statistical_policy"])
    ]
    if profiles[0] != profiles[1]:
        raise StrategyResearchRejected(
            "deployment_simulation_statistical_requirements_mismatch"
        )
    if Decimal(str(result["initial_cash"])) != Decimal(
        binding["initial_cash"]
    ) or Decimal(binding["initial_cash"]) > Decimal(grant["max_initial_cash"]):
        raise StrategyResearchRejected("deployment_simulation_capital_mismatch")
    if grant.get("incumbent_strategy_id") != binding.get("incumbent", {}).get(
        "strategy_id"
    ):
        raise StrategyResearchRejected("deployment_simulation_incumbent_not_validated")
    assessment = evidence["deployment_assessment"]
    if any(
        Decimal(str(assessment["risk_limits"][k])) > Decimal(str(v))
        for k, v in grant["risk_limits"].items()
    ):
        raise StrategyResearchRejected("deployment_simulation_risk_mismatch")
    metrics = _object(result.get("metrics_json"))
    fee = metrics.get("fee_component_evidence", {}).get("fee_schedule_binding") or {}
    cost_ref = metrics.get("cost_assumptions", {}).get("commission_model_reference")
    if (
        fee.get("account_truth_scope_fingerprint") != grant["account_scope_fingerprint"]
        or fee.get("effective_start_date", "9999")
        > binding["research_identity"]["start_date"]
        or fee.get("effective_end_date", "") < binding["partition"]["sealed_end"]
    ):
        raise StrategyResearchRejected(
            "deployment_simulation_reviewed_cost_scope_mismatch"
        )
    resolution = resolve_frozen_deployment_fee_schedule(
        db,
        {
            "review_id": fee.get("fee_schedule_review_id"),
            "review_fingerprint": fee.get("fee_schedule_review_fingerprint"),
            "cost_model_reference": cost_ref,
            "fee_evidence": fee,
        },
        tuple(binding["universe"]),
    )
    proof = {
        "schema_version": "karkinos.simulation_account_cost_replay.v2",
        "final_evaluation_id": evidence["sealed_test_id"],
        "final_evidence_fingerprint": evidence["evidence_fingerprint"],
        "reservation_fingerprint": content_fingerprint(binding),
        "qualified_formula_fingerprint": metrics.get("formula_fingerprint"),
        "review_id": resolution.review.review_id,
        "review_fingerprint": resolution.review.review_fingerprint,
        "cost_model_reference": cost_ref,
        "fee_evidence_fingerprint": content_fingerprint(fee),
        "initial_cash": binding["initial_cash"],
        "code_fingerprint": binding["code_binding"]["fingerprint"],
        "curves_fingerprint": content_fingerprint(evidence["session_curves"]),
        "portfolio_fingerprint": content_fingerprint(
            evidence["portfolio_observations"]
        ),
        "account_scope_fingerprint": grant["account_scope_fingerprint"],
        "statistical_requirements": profiles[1],
    }
    return resolution, proof


def _simulation_reviewed_assessment(db, evidence, grant, replay):
    """Calculate account applicability without rewriting the original SIM final."""
    from types import SimpleNamespace

    from analytics.deployment_validation import compare_session_curves

    binding = evidence["reservation"]
    curves = replay["session_curves"]
    if set(curves["comparators"]) != set(evidence["session_curves"]["comparators"]) or [
        row[0] for row in curves["candidate"]
    ] != [row[0] for row in evidence["session_curves"]["candidate"]]:
        raise StrategyResearchRejected("deployment_simulation_replay_interval_drift")
    uncertainty = compare_session_curves(
        candidate=curves["candidate"],
        comparators=curves["comparators"],
        initial_cash=binding["initial_cash"],
        policy={
            **grant["statistical_policy"],
            "decision_checkpoint": curves["candidate"][-1][0][:10],
        },
        seed=evidence["sealed_test_id"],
    )
    # This local calculation uses current reviewed account requirements. It is
    # explicitly derived evidence; the immutable SIM reservation remains intact.
    account_binding = {**binding, "publication_grant": grant}
    account_binding.pop("simulation_policy", None)
    account_binding["fee_schedule"] = replay["fee_schedule"]
    return _deployment_assessment(
        binding=account_binding,
        snapshot=evidence["sealed_dataset_snapshot"],
        uncertainty=uncertainty,
        result=SimpleNamespace(
            equity_curve=[
                (datetime.fromisoformat(ts), Decimal(value))
                for ts, value in curves["candidate"]
            ],
            portfolio_observations=replay["portfolio_observations"],
            incumbent_portfolio_observations=replay.get(
                "incumbent_portfolio_observations", []
            ),
            comparator_accounting=replay["comparator_accounting"],
            cash_dividend_accounting=replay["economic_return_accounting"],
        ),
        store_root=db.path.parent / "research",
        trading_dates=evidence["deployment_assessment"]["membership_sessions"],
        calendar_db=db,
    )


def build_simulation_account_replay(db, store, result, evidence, grant, *, data_store):
    """One expensive, fixed account-cost replay during fresh qualification."""
    from data.dataset.reader import daily_bar_dataset_read_scope

    with daily_bar_dataset_read_scope(join_existing=True):
        return _build_simulation_account_replay(
            db, store, result, evidence, grant, data_store=data_store
        )


def _build_simulation_account_replay(db, store, result, evidence, grant, *, data_store):
    from pathlib import Path

    from server.ai_runtime.strategy_research_backtest import (
        RestrictedFormulaBacktestAdapter,
    )
    from server.ai_runtime.strategy_research_support import selection_from_session
    from server.services.market_universe_automation import verified_trading_dates

    resolution, proof = _simulation_account_replay_inputs(
        db, store, result, evidence, grant
    )
    binding = evidence["reservation"]
    selection = selection_from_session(store.get_session(binding["session_id"]))
    adapter = RestrictedFormulaBacktestAdapter(
        data_store=data_store,
        research_root=Path(db.path).parent / "research",
    )
    dates = verified_trading_dates(
        db, start_date=selection.start_date, end_date=binding["partition"]["sealed_end"]
    )
    drafts = {
        "candidate": store.get_draft(binding["session_id"], binding["draft_id"])[
            "contract"
        ],
        "frozen_baseline": {"formula_ast": binding["baseline_formula_ast"]},
        **{r["label"]: r for r in binding["challenger_family"]},
    }
    if binding.get("incumbent"):
        drafts["incumbent"] = {"formula_ast": binding["incumbent"]["formula_ast"]}
    curves, accounting, books = {}, {}, {}
    for label, draft in drafts.items():
        replay = adapter.run_sealed(
            selection=selection,
            draft=draft,
            sealed_end_date=binding["partition"]["sealed_end"],
            expected_dataset_snapshot=binding["research_snapshot"],
            expected_trading_dates=dates,
            evaluation_dataset_snapshot=evidence["sealed_dataset_snapshot"],
            initial_cash_override=Decimal(binding["initial_cash"]),
            commission_calc_override=resolution.commission_calc,
            entry_board_policy=binding["entry_board_policy"],
        )
        curves[label] = [
            [ts.isoformat(), str(value)]
            for ts, value in replay.equity_curve
            if ts.date().isoformat() >= binding["partition"]["sealed_start"]
        ]
        accounting[label] = replay.cash_dividend_accounting
        books[label] = replay.portfolio_observations
    metrics = _object(result.get("metrics_json"))
    fee = metrics["fee_component_evidence"]["fee_schedule_binding"]
    derived = {
        "session_curves": {
            "candidate": curves.pop("candidate"),
            "comparators": curves,
        },
        "economic_return_accounting": accounting.pop("candidate"),
        "comparator_accounting": accounting,
        "portfolio_observations": books["candidate"],
        "incumbent_portfolio_observations": books.get("incumbent", []),
        "fee_schedule": {
            "review_id": fee["fee_schedule_review_id"],
            "review_fingerprint": fee["fee_schedule_review_fingerprint"],
            "cost_model_reference": proof["cost_model_reference"],
            "fee_evidence": fee,
        },
    }
    derived["deployment_assessment"] = _simulation_reviewed_assessment(
        db, evidence, grant, derived
    )
    payload = {**proof, "reviewed_replay": derived}
    return {**payload, "evidence_fingerprint": content_fingerprint(payload)}


def _verify_simulation_account_applicability(db, store, result, evidence, grant):
    """Reopen immutable replay provenance; daily consumers do not rerun a kernel."""
    from server.persistence.ai_shadow_research import ShadowResearchStore
    from server.services.ai_shadow.ai_shadow_research_support import (
        shadow_research_backtest_source_fingerprint,
    )

    _, expected = _simulation_account_replay_inputs(db, store, result, evidence, grant)
    actual = _object(result.get("metrics_json")).get("simulation_account_replay")
    if not isinstance(actual, Mapping):
        raise StrategyResearchRejected(
            "deployment_simulation_account_replay_missing_or_stale"
        )
    payload = dict(actual)
    fingerprint = payload.pop("evidence_fingerprint", None)
    if fingerprint != content_fingerprint(payload) or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise StrategyResearchRejected(
            "deployment_simulation_account_replay_missing_or_stale"
        )
    try:
        authority = ShadowResearchStore(db.path).qualification_for_backtest_result(
            int(result["id"])
        )
    except (LookupError, KeyError, TypeError, ValueError) as exc:
        raise StrategyResearchRejected(
            "deployment_simulation_qualification_binding_missing"
        ) from exc
    candidate, run = authority["candidate"], authority["run"]
    selection = run.get("selection") or {}
    comparison = candidate["comparison"]
    if (
        run["status"] != "completed"
        or selection.get("status") != "winner_selected"
        or selection.get("winner_qualification_candidate_id")
        != candidate["qualification_candidate_id"]
        or candidate["status"] != "qualified"
        or candidate["recommendation"] != "paper_shadow_review"
        or candidate["candidate_result_id"] != result["id"]
        or candidate["source_candidate_id"] != evidence["reservation"]["candidate_id"]
        or comparison.get("candidate_source_fingerprint")
        != shadow_research_backtest_source_fingerprint(result)
        or comparison.get("account_qualification_status") != "passed"
        or run["reviewed_cost_model_reference"] != expected["cost_model_reference"]
        or run["reviewed_fee_schedule_fingerprint"] != expected["review_fingerprint"]
        or Decimal(run["initial_cash_text"]) != Decimal(expected["initial_cash"])
    ):
        raise StrategyResearchRejected(
            "deployment_simulation_qualification_binding_drift"
        )
    replay = payload.get("reviewed_replay")
    if not isinstance(replay, Mapping):
        raise StrategyResearchRejected("deployment_simulation_reviewed_replay_missing")
    original_assessment = _object(replay.get("deployment_assessment"))
    core = dict(original_assessment)
    fingerprint = core.pop("evidence_fingerprint", None)
    if (
        fingerprint != content_fingerprint(core)
        or original_assessment.get("status") != "pass"
    ):
        raise StrategyResearchRejected(
            "deployment_simulation_reviewed_assessment_drift"
        )
    # Admission/expiry/generation belong to CURRENT publication authority, not
    # this completed scientific artifact. Reassess its trusted observations
    # against current limits instead of rewriting or reviving an old grant.
    return _simulation_reviewed_assessment(db, evidence, grant, replay)


def verify_deployment_validation(
    db: Any, *, result_id: int, expected_grant_id: str | None = None
) -> dict[str, Any]:
    """Canonical authority consumer: reopen final, code, dataset and trial source."""
    from analytics.deployment_validation import compare_session_curves
    from server.contracts.recommendation_publication import read_publication_grant
    from server.persistence.strategy_research import StrategyResearchAuditStore
    from server.services.strategy_promotion_support import strategy_dataset_store_root

    store = StrategyResearchAuditStore(db._path)
    result = store.research_backtest_result(result_id)
    metrics = _object(result.get("metrics_json"))
    evidence = metrics.get("independent_evaluation")
    if not isinstance(evidence, Mapping):
        raise StrategyResearchRejected("independent_final_evaluation_missing")
    binding = evidence.get("reservation", {})
    if not binding.get("deployment_scope"):
        raise StrategyResearchRejected("deployment_scope_not_validated")
    grant = read_publication_grant(db)
    simulation = binding.get("simulation_policy")
    if (
        binding.get("entry_board_policy") != grant["entry_board_policy"]
        or metrics.get("entry_board_policy") != grant["entry_board_policy"]
        or _object(result.get("config_json"))
        .get("params", {})
        .get("entry_board_policy")
        != grant["entry_board_policy"]
        or (expected_grant_id and grant["grant_id"] != expected_grant_id)
        or (
            not simulation
            and (
                binding.get("publication_grant", {}).get("grant_id")
                != grant["grant_id"]
                or binding["publication_grant"]["generation"] != grant["generation"]
                or binding["publication_grant"]["statistical_policy_fingerprint"]
                != grant["statistical_policy_fingerprint"]
            )
        )
    ):
        raise StrategyResearchRejected("deployment_grant_changed")
    # This reopens immutable rows and the original research selection/code/data.
    verify_persisted_final_evaluation(
        research_store=store,
        evidence=evidence,
        store_root=strategy_dataset_store_root(db),
    )
    row = store.get_sealed_test(evidence["sealed_test_id"])
    if row["evidence_fingerprint"] != evidence.get("evidence_fingerprint"):
        raise StrategyResearchRejected("deployment_final_fingerprint_drift")
    reviewed_assessment = None
    if simulation:
        reviewed_assessment = _verify_simulation_account_applicability(
            db, store, result, evidence, grant
        )
    elif (
        metrics.get("cost_assumptions", {}).get("commission_model_reference")
        != binding["fee_schedule"]["cost_model_reference"]
    ):
        raise StrategyResearchRejected("deployment_qualified_fee_schedule_drift")
    from server.services.account.reviewed_fee_schedule import (
        resolve_frozen_deployment_fee_schedule,
    )

    if not simulation:
        resolve_frozen_deployment_fee_schedule(
            db, binding["fee_schedule"], tuple(binding["universe"])
        )
    formula = metrics.get("formula_binding", {}).get("formula_ast")
    if (
        "sha256:" + content_fingerprint(formula or {})
        != binding["champion_formula_fingerprint"]
    ):
        raise StrategyResearchRejected("deployment_qualified_formula_drift")
    assessment = _object(evidence.get("deployment_assessment"))
    core = dict(assessment)
    fingerprint = core.pop("evidence_fingerprint", None)
    if fingerprint != content_fingerprint(core):
        raise StrategyResearchRejected("deployment_assessment_drift")
    curves = evidence["session_curves"]
    policy = {
        **grant["statistical_policy"],
        "decision_checkpoint": curves["candidate"][-1][0][:10],
    }
    uncertainty = compare_session_curves(
        candidate=curves["candidate"],
        comparators=curves["comparators"],
        initial_cash=binding["initial_cash"],
        policy=policy,
        seed=evidence["sealed_test_id"],
    )
    if assessment.get("uncertainty") != uncertainty:
        raise StrategyResearchRejected("deployment_uncertainty_drift")
    # Dataset replay above verifies the bytes; repeat scope and prospective-time
    # checks through the same calculation without rerunning an adaptive trial.
    from types import SimpleNamespace

    checked = _deployment_assessment(
        binding=binding,
        snapshot=evidence["sealed_dataset_snapshot"],
        uncertainty=uncertainty,
        result=SimpleNamespace(
            equity_curve=[
                (datetime.fromisoformat(ts), Decimal(value))
                for ts, value in curves["candidate"]
            ],
            portfolio_observations=evidence["portfolio_observations"],
            incumbent_portfolio_observations=evidence.get(
                "incumbent_portfolio_observations", []
            ),
            comparator_accounting=evidence["comparator_accounting"],
            cash_dividend_accounting=evidence.get("economic_return_accounting"),
        ),
        store_root=db.path.parent / "research",
        trading_dates=assessment["membership_sessions"],
        calendar_db=db,
    )
    if checked != assessment:
        raise StrategyResearchRejected("deployment_scope_evidence_drift")
    if reviewed_assessment is not None:
        assessment = reviewed_assessment
    payload = {
        "schema_version": "karkinos.deployment_validation.v1",
        "status": assessment["status"],
        "deployment_scope_fingerprint": binding["deployment_scope"][
            "deployment_scope_fingerprint"
        ],
        "strategy_fingerprint": binding["champion_formula_fingerprint"],
        "code_fingerprint": binding["code_binding"]["fingerprint"],
        "initial_cash": binding["initial_cash"],
        "risk_limits": assessment["risk_limits"],
        "entry_board_policy": binding["entry_board_policy"],
        "final_evaluation_id": evidence["sealed_test_id"],
        "final_evidence_fingerprint": evidence["evidence_fingerprint"],
        "statistical_policy_fingerprint": grant["statistical_policy_fingerprint"],
        "error_budget": binding["error_budget"],
        **(
            {
                "validation_provenance": "independent_simulation",
                "publication_grant_id": grant["grant_id"],
                "publication_grant_generation": grant["generation"],
                "account_applicability_evidence_fingerprint": metrics[
                    "simulation_account_replay"
                ]["evidence_fingerprint"],
                "qualified_result_id": result_id,
            }
            if simulation
            else {}
        ),
        "blockers": assessment["blockers"],
        "return_basis": assessment["return_basis"],
        "corporate_action_coverage": assessment["corporate_action_coverage"],
        **(
            {"replacement": assessment["replacement"]}
            if "replacement" in assessment
            else {}
        ),
    }
    return {**payload, "evidence_fingerprint": content_fingerprint(payload)}
