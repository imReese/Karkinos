"""Reserve and evaluate one frozen research champion on future observations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
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
from server.ai_runtime.formula_challengers import (
    build_challenger_comparison,
    frozen_research_challengers,
)
from server.ai_runtime.strategy_research_backtest import build_dual_ma_research_strategy
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.strategy_research import StrategyResearchRejected

FINAL_EVALUATION_SCHEMA = "karkinos.research_final_evaluation.v1"


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
        "data/store.py",
        "data/dataset/reader.py",
        "data/dataset/model.py",
        "data/dataset/manifest.py",
        "data/storage/objects.py",
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


async def reserve_final_research_evaluation(
    *,
    db: Any,
    research_store: Any,
    run: Mapping[str, Any],
    selection: Any,
    candidates: list[dict[str, Any]],
    daily_selection: Mapping[str, Any],
    now: str,
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
        != research_store.research_trial_family(source.source_selection)
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
    if not research_store.claim_reserved_sealed_test(
        row["sealed_test_id"], now=now.isoformat()
    ):
        raise StrategyResearchRejected("independent_final_evaluation_in_progress")
    binding = row["evidence"]["reservation"]
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
        common = {
            "expected_trading_dates": trading_dates,
            "selection": selection,
            "sealed_end_date": partition.sealed_end.isoformat(),
            "expected_dataset_snapshot": binding["research_snapshot"],
        }

        def require_fresh_book(measured):
            timing = measured.execution_timing or {}
            if (
                measured.initial_cash != Decimal(str(selection.initial_cash))
                or timing.get("evaluation_start") != partition.sealed_start.isoformat()
                or timing.get("warmup_basis") != "strategy_history_only_fresh_book"
                or timing.get("warmup_final_bar_targets") is not True
            ):
                raise StrategyResearchRejected("independent_final_fresh_book_mismatch")

        result = await asyncio.to_thread(
            adapter.run_sealed, draft=source.source_draft, **common
        )
        baseline = await asyncio.to_thread(
            adapter.run_sealed,
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
        challenger_results = []
        for challenger in binding["challenger_family"]:
            measured = await asyncio.to_thread(
                adapter.run_sealed, draft=challenger, **common
            )
            require_fresh_book(measured)
            if getattr(measured, "dataset_snapshot", None) != candidate_snapshot:
                raise StrategyResearchRejected(
                    "independent_final_challenger_dataset_drift"
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
        payload = {**core, "evidence_fingerprint": content_fingerprint(core)}
        research_store.finish_sealed_test(
            row["sealed_test_id"],
            status="completed",
            evidence=payload,
            evidence_fingerprint=payload["evidence_fingerprint"],
            failure_code=None,
            updated_at=now.isoformat(),
        )
        return payload
    except Exception as exc:
        # These errors are emitted by the input loader before any simulation.
        # A missing delivery can be retried without consuming a measured result.
        pending_inputs = result is None and (
            str(exc)
            in {
                "sealed_window_not_complete",
                "sealed_trading_calendar_coverage_incomplete",
            }
            or str(exc).startswith(
                (
                    "research_calendar_incomplete:",
                    "persisted_bars_missing:",
                    "persisted_window_empty:",
                )
            )
        )
        research_store.finish_sealed_test(
            row["sealed_test_id"],
            status="reserved" if pending_inputs else "failed",
            evidence={"reservation": binding},
            evidence_fingerprint=content_fingerprint({"reservation": binding}),
            failure_code=str(exc),
            updated_at=now.isoformat(),
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
    family = research_store.research_trial_family(selection)
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
    for snapshot in (binding["research_snapshot"], evidence["sealed_dataset_snapshot"]):
        replay = verify_backtest_dataset_snapshot_replay(
            snapshot, store_root=store_root
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
