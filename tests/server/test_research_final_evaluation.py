from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.sealed_holdout import final_research_evaluation_blocker
from backtest.result import BacktestResult
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.handler import DataHandler
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research_privacy import NORMALIZED_RESEARCH_NOTIONAL
from server.ai_runtime.strategy_research_sealed import StrategyResearchSealedMixin
from server.contracts.strategy_research import (
    SEALED_TEST_CONFIRMATION,
    SealedTestRequest,
    StrategyResearchRejected,
    StrategyResearchSelection,
)
from server.db import AppDatabase
from server.persistence.backtest_results import insert_backtest_result
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.research_final_evaluation import (
    evaluate_reserved_champion,
    require_new_publication_final_evaluation,
    reserve_final_research_evaluation,
    verify_persisted_final_evaluation,
)
from tests.ai_runtime.test_strategy_formula_backtest import _formula

FREEZE = "2026-01-16T12:00:00+00:00"
MATURE = datetime.fromisoformat("2026-01-20T08:00:00+00:00")


def _curve(end=20, *, weak=False, baseline=False):
    equity = Decimal("100000")
    result = []
    for i in range(end):
        if i:
            change = (
                Decimal("0.002")
                if baseline
                else Decimal("0.009") + Decimal(i % 3) / 1000
            )
            if weak:
                change = Decimal("0.001") if i % 2 else Decimal("-0.001")
            equity *= 1 + change
        result.append((datetime(2026, 1, i + 1), equity))
    return result


def _persist_curve(curve):
    return [
        {"timestamp": stamp.isoformat(), "equity": float(value)}
        for stamp, value in curve
    ]


def _seed_trial(
    h, *, suffix="1", selection=None, capital=None, status="completed", exposed=False
):
    selection = selection or h.selection
    selected = selection.to_dict()
    if capital:
        # Legacy scored research may predate the fixed-notional contract.
        selected["initial_cash"] = capital
    draft = {
        "formula_ast": _formula(),
        "parameter_values": {"window": 3},
        "parameter_ranges": {"window": [2, 3, 4]},
    }
    metrics = {
        "formula_binding": {
            **{
                key: selection.to_dict()[key]
                for key in (
                    "universe",
                    "dataset_snapshot_id",
                    "start_date",
                    "end_date",
                    "frequency",
                )
            },
            "formula_ast": draft["formula_ast"],
        },
        "dataset_snapshot": h.snapshot,
        "parameter_robustness": {
            "tested_results": [
                {"params": {"window": 2}},
                {"params": {"window": 3}},
                {"params": {"window": 4}},
            ]
        },
    }
    with sqlite3.connect(h.db._path) as conn:
        result_id = insert_backtest_result(
            conn,
            created_at=FREEZE,
            config_json="{}",
            initial_cash=100000,
            final_equity=120000,
            total_return=0.2,
            sharpe=3,
            max_dd=0.01,
            equity_curve_json=json.dumps(_persist_curve(_curve(16, weak=h.weak))),
            metrics_json=json.dumps(metrics),
        )
        conn.execute(
            "INSERT INTO ai_strategy_research_sessions (session_id,idempotency_key,request_fingerprint,request_json,selection_fingerprint,status,prompt_version,created_at,updated_at,context_snapshot_id) VALUES (?,?,?,?,?,'completed','fixture',?,?,?)",
            (
                f"session-{suffix}",
                suffix,
                selection.fingerprint,
                json.dumps({"selection": selected}),
                selection.fingerprint,
                FREEZE,
                FREEZE,
                "exposed-context" if exposed else None,
            ),
        )
        conn.execute(
            "INSERT INTO ai_strategy_hypothesis_drafts (draft_id,session_id,ordinal,contract_json,artifact_fingerprint,validation_status,validation_errors_json,created_at) VALUES (?,?,1,?,?,'valid','[]',?)",
            (
                f"draft-{suffix}",
                f"session-{suffix}",
                json.dumps(draft),
                content_fingerprint(draft),
                FREEZE,
            ),
        )
        conn.execute(
            "INSERT INTO ai_strategy_formula_backtests (backtest_run_id,idempotency_key,request_fingerprint,session_id,draft_id,formula_fingerprint,dataset_snapshot_id,cost_model_reference,status,canonical_backtest_result_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"backtest-{suffix}",
                suffix,
                suffix,
                f"session-{suffix}",
                f"draft-{suffix}",
                "sha256:" + content_fingerprint(draft["formula_ast"]),
                selection.dataset_snapshot_id,
                selection.cost_model_reference,
                status,
                result_id,
                FREEZE,
                FREEZE,
            ),
        )
    return {
        "candidate_id": f"candidate-{suffix}",
        "run_id": "run-1",
        "session_id": f"session-{suffix}",
        "draft_id": f"draft-{suffix}",
        "backtest_run_id": f"backtest-{suffix}",
        "candidate_result_id": result_id,
    }, draft


@pytest.fixture
def harness(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = StrategyResearchAuditStore(db._path)
    store.init()
    data = DataStore(tmp_path)
    symbol = Symbol("600000")
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=20),
            "open": [10.0] * 20,
            "high": [11.0] * 20,
            "low": [9.0] * 20,
            "close": [10.0] * 20,
            "volume": [100000] * 20,
        }
    )
    data.save_bars(
        symbol,
        BarFrequency.DAILY,
        frame,
        provider_name="fixture",
        data_source="fixture",
        adjustment_mode="none",
        instrument_type=InstrumentType.STOCK,
    )

    def snapshot(end):
        return build_backtest_dataset_snapshot(
            start_date="2026-01-01",
            end_date=f"2026-01-{end}",
            configured_source="fixture",
            data_handlers={
                symbol: DataHandler(
                    frame.iloc[:end],
                    symbol,
                    BarFrequency.DAILY,
                    AssetClass.STOCK,
                    InstrumentType.STOCK,
                )
            },
            store=data,
            source_names=["fixture"],
        )

    h = SimpleNamespace(
        db=db,
        store=store,
        data=data,
        snapshot=snapshot(16),
        full_snapshot=snapshot(20),
        weak=False,
    )
    with sqlite3.connect(db._path) as conn:
        baseline_id = insert_backtest_result(
            conn,
            created_at=FREEZE,
            config_json=json.dumps(
                {"strategy": "dual_ma", "short_period": 2, "long_period": 4}
            ),
            initial_cash=100000,
            final_equity=100000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
            metrics_json=json.dumps({"dataset_snapshot": h.snapshot}),
        )
    h.selection = StrategyResearchSelection(
        saved_backtest_result_id=baseline_id,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id=h.snapshot["snapshot_id"],
        start_date="2026-01-01",
        end_date="2026-01-16",
        sealed_end_date="2026-01-20",
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
    )
    h.candidate, h.draft = _seed_trial(h)
    h.source = SimpleNamespace(
        source_candidate=h.candidate, source_selection=h.selection, source_draft=h.draft
    )
    h.adapter = SimpleNamespace(_data_store=data)
    h.calls = []

    def run_sealed(**kwargs):
        h.calls.append(kwargs)
        curve = _curve(
            baseline=kwargs["draft"]["formula_ast"] != h.draft["formula_ast"]
        )
        result = BacktestResult(
            equity_curve=curve,
            positions={},
            initial_cash=curve[0][1],
            final_equity=curve[-1][1],
        )
        result.dataset_snapshot = deepcopy(h.full_snapshot)
        return result

    h.adapter.run_sealed = run_sealed
    monkeypatch.setattr(
        "server.services.market_universe_automation.verified_trading_dates",
        lambda *a, **k: [f"2026-01-{i:02}" for i in range(1, 21)],
    )
    return h


async def _reserve(h, *, now=FREEZE):
    return await reserve_final_research_evaluation(
        db=h.db,
        research_store=h.store,
        run={"run_id": "run-1"},
        selection=h.selection,
        candidates=[h.candidate],
        daily_selection={
            "selection_fingerprint": "selection-1",
            "research_recommendation": {"research_winner_candidate_id": "candidate-1"},
        },
        now=now,
    )


async def _evaluate(h, *, now=MATURE):
    return await evaluate_reserved_champion(
        research_store=h.store,
        source=h.source,
        adapter=h.adapter,
        now=now,
        calendar_db=h.db,
    )


@pytest.mark.asyncio
async def test_freeze_evaluate_replay_and_new_publication_usable_path(harness):
    h = harness
    reserved = await _reserve(h)
    assert reserved["status"] == "reserved"
    assert (
        reserved["evidence"]["reservation"]["trial_family"]["nominal_trial_count"] == 3
    )
    assert not h.calls
    # A late replay reads the original freeze time; it does not re-freeze now.
    assert (await _reserve(h, now=MATURE.isoformat())) == reserved
    evidence = await _evaluate(h)
    assert final_research_evaluation_blocker(evidence) is None
    assert len(h.calls) == 2
    assert evidence["authority_effect"] == "none"
    assert await _evaluate(h) == evidence
    assert len(h.calls) == 2
    assert (
        verify_persisted_final_evaluation(
            research_store=h.store, evidence=evidence, store_root=h.data._root
        )
        == evidence
    )
    with sqlite3.connect(h.db._path) as conn:
        metrics = json.loads(
            conn.execute(
                "SELECT metrics_json FROM backtest_results WHERE id=?",
                (h.candidate["candidate_result_id"],),
            ).fetchone()[0]
        )
        metrics["independent_evaluation"] = evidence
        # Qualification uses a new row; source research evidence remains immutable.
        published_id = insert_backtest_result(
            conn,
            created_at=MATURE.isoformat(),
            config_json="{}",
            initial_cash=100000,
            final_equity=120000,
            total_return=0.2,
            sharpe=3,
            max_dd=0.01,
            equity_curve_json="[]",
            metrics_json=json.dumps(metrics),
        )
    require_new_publication_final_evaluation(
        h.db, published_id, expected_candidate_id="candidate-1"
    )
    with sqlite3.connect(h.db._path) as conn:
        metrics["formula_binding"]["universe"] = ["600001"]
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=?",
            (json.dumps(metrics), published_id),
        )
    with pytest.raises(
        StrategyResearchRejected, match="independent_final_research_identity_mismatch"
    ):
        require_new_publication_final_evaluation(
            h.db, published_id, expected_candidate_id="candidate-1"
        )


@pytest.mark.asyncio
async def test_final_missing_early_and_retrospective_freeze_fail_without_execution(
    harness,
):
    h = harness
    with pytest.raises(
        StrategyResearchRejected, match="independent_final_evaluation_missing"
    ):
        await _evaluate(h)
    with pytest.raises(
        StrategyResearchRejected, match="sealed_champion_not_frozen_before_holdout"
    ):
        await _reserve(h, now="2026-01-16T16:00:00+00:00")
    await _reserve(h)
    with pytest.raises(
        StrategyResearchRejected, match="independent_final_window_not_complete"
    ):
        await _evaluate(h, now=datetime.fromisoformat("2026-01-20T06:00:00+00:00"))
    assert h.calls == []


@pytest.mark.asyncio
async def test_actual_trial_family_deduplicates_replays_counts_variants_capital_and_failures(
    harness,
):
    h = harness
    _seed_trial(h, suffix="replay")
    _seed_trial(h, suffix="different-capital", capital=200000, status="failed")
    family = h.store.research_trial_family(h.selection)
    assert family["nominal_trial_count"] == 6
    assert len(family["sources"]) == 3
    assert family["trials_assumed_independent"] is False
    await _reserve(h)
    _seed_trial(h, suffix="late-variant", capital=300000)
    with pytest.raises(
        StrategyResearchRejected, match="independent_final_reservation_drift"
    ):
        await _evaluate(h)
    assert not h.calls


@pytest.mark.asyncio
async def test_final_rejects_new_context_exposure_without_any_scored_backtest(harness):
    h = harness
    await _reserve(h)
    with sqlite3.connect(h.db._path) as conn:
        selection = replace(
            h.selection, end_date="2026-01-19", sealed_end_date=None
        ).to_dict()
        conn.execute(
            "UPDATE ai_strategy_research_sessions SET request_json=?,context_snapshot_id='exposed' WHERE session_id='session-1'",
            (json.dumps({"selection": selection}),),
        )
    with pytest.raises(
        StrategyResearchRejected, match="sealed_window_exposed_to_research"
    ):
        await _evaluate(h)


@pytest.mark.asyncio
async def test_failed_consumption_is_terminal_and_overlap_cannot_be_renamed(harness):
    h = harness
    row = await _reserve(h)
    binding = deepcopy(row["evidence"]["reservation"])
    binding["source_run_id"] = "different-run"
    binding["partition"]["research_start"] = "2025-12-31"
    binding["partition_fingerprint"] = "different-partition"
    with pytest.raises(
        StrategyResearchRejected, match="sealed_partition_overlap_already_reserved"
    ):
        h.store.reserve_research_champion(binding=binding, created_at=FREEZE)

    def failed(**kwargs):
        h.calls.append(kwargs)
        raise StrategyResearchRejected("sealed_data_incomplete")

    h.adapter.run_sealed = failed
    for _ in range(2):
        with pytest.raises(StrategyResearchRejected, match="sealed_data_incomplete"):
            await _evaluate(h)
    assert len(h.calls) == 1
    with pytest.raises(StrategyResearchRejected, match="sealed_test_already_terminal"):
        h.store.finish_sealed_test(
            row["sealed_test_id"],
            status="completed",
            evidence={},
            evidence_fingerprint="",
            failure_code=None,
            updated_at=MATURE.isoformat(),
        )


@pytest.mark.asyncio
async def test_trial_correction_and_final_benchmark_are_required(harness):
    h = harness
    await _reserve(h)
    evidence = await _evaluate(h)
    for mutate, blocker in [
        (
            lambda e: e["sealed_evaluation"].update(passed_benchmark=False),
            "independent_final_evaluation_invalid",
        ),
        (
            lambda e: e["reservation"]["trial_correction"].update(
                significant_at_0_95=False
            ),
            "independent_final_evaluation_invalid",
        ),
    ]:
        altered = deepcopy(evidence)
        mutate(altered)
        assert final_research_evaluation_blocker(altered) == blocker
    # Actual unremarkable daily returns fail the correction even if scalar Sharpe says 999.
    with sqlite3.connect(h.db._path) as conn:
        conn.execute(
            "UPDATE backtest_results SET equity_curve_json=?,sharpe=999 WHERE id=?",
            (
                json.dumps(_persist_curve(_curve(16, weak=True))),
                h.candidate["candidate_result_id"],
            ),
        )
    with pytest.raises(
        StrategyResearchRejected, match="independent_final_research_source_drift"
    ):
        await _evaluate(h)


@pytest.mark.asyncio
async def test_manual_sealed_endpoint_only_replays_completed_history(harness):
    h = harness
    service = StrategyResearchSealedMixin()
    service._research_store = h.store
    service._validate_session_integrity = lambda _: None
    service._now = lambda: MATURE.isoformat()
    request = SealedTestRequest(
        idempotency_key="manual",
        requested_by="human:owner",
        session_id="session-1",
        draft_id="draft-1",
        backtest_run_id="backtest-1",
        confirmation=SEALED_TEST_CONFIRMATION,
    )
    with pytest.raises(
        StrategyResearchRejected,
        match="sealed_test_requires_frozen_automation_champion",
    ):
        await service.sealed_test(request)
    assert h.store.list_sealed_tests("session-1") == []
    from analytics.sealed_holdout import build_sealed_partition

    partition = build_sealed_partition(
        research_start=h.selection.start_date,
        research_end=h.selection.end_date,
        sealed_end=h.selection.sealed_end_date,
    )
    row, _ = h.store.create_or_get_sealed_test(
        request,
        partition_fingerprint=partition.partition_fingerprint,
        champion_formula_fingerprint="sha256:"
        + content_fingerprint(h.draft["formula_ast"]),
        research_family_id="session-1",
        created_at=FREEZE,
    )
    h.store.finish_sealed_test(
        row["sealed_test_id"],
        status="completed",
        evidence={"legacy": True},
        evidence_fingerprint="old",
        failure_code=None,
        updated_at=FREEZE,
    )
    response = await service.sealed_test(request)
    assert response["reused"] is True
    assert response["evidence"] == {"legacy": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["trial", "benchmark"])
async def test_real_failed_final_evidence_cannot_pass_gate(harness, failure):
    h = harness
    if failure == "trial":
        with sqlite3.connect(h.db._path) as conn:
            conn.execute(
                "UPDATE backtest_results SET equity_curve_json=?,sharpe=999 WHERE id=?",
                (
                    json.dumps(_persist_curve(_curve(16, weak=True))),
                    h.candidate["candidate_result_id"],
                ),
            )
    else:
        original = h.adapter.run_sealed

        def equal_baseline(**kwargs):
            result = original(**kwargs)
            result.equity_curve = _curve(baseline=True)
            result.final_equity = result.equity_curve[-1][1]
            return result

        h.adapter.run_sealed = equal_baseline
    await _reserve(h)
    evidence = await _evaluate(h)
    blocker = (
        "multiple_testing_correction_not_significant"
        if failure == "trial"
        else "independent_final_excess_not_positive"
    )
    assert final_research_evaluation_blocker(evidence) == blocker
    assert h.store.get_sealed_test(evidence["sealed_test_id"])["status"] == "completed"
    with pytest.raises(StrategyResearchRejected, match=blocker):
        await _evaluate(h)
    assert len(h.calls) == 2


def test_direct_publication_cannot_bypass_final_guard(harness, monkeypatch):
    from server.services.strategy_promotion_pipeline import (
        STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
        StrategyPromotionPipeline,
    )

    monkeypatch.setattr(
        "server.services.strategy_promotion_pipeline._require_ai_shadow_readiness_binding",
        lambda *a: None,
    )
    with pytest.raises(
        StrategyResearchRejected, match="independent_final_evaluation_missing"
    ):
        StrategyPromotionPipeline(db=harness.db).request_promotion(
            "ai_formula_shadow:candidate-1",
            target_stage="paper_shadow",
            readiness={
                "strategy_id": "ai_formula_shadow:candidate-1",
                "backtest_result_id": harness.candidate["candidate_result_id"],
            },
            actor="human:owner",
            review_note="synthetic review",
            confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
        )
    assert (
        harness.db.get_strategy_promotion_state_sync("ai_formula_shadow:candidate-1")
        is None
    )


@pytest.mark.asyncio
async def test_passing_final_test_does_not_admit_raw_receipt_returns(harness):
    h = harness
    await _reserve(h)
    evidence = await _evaluate(h)
    assert final_research_evaluation_blocker(evidence) is None
    with sqlite3.connect(h.db._path) as conn:
        source = conn.execute(
            "SELECT metrics_json FROM backtest_results WHERE id=?",
            (h.candidate["candidate_result_id"],),
        ).fetchone()
        metrics = json.loads(source[0])
        metrics["independent_evaluation"] = evidence
        # Historical receipt snapshots lack the newer research_use annotation.
        metrics["dataset_snapshot"]["market_data_binding"] = {
            "receipts": [{"receipt_id": "historical-daily-observation"}]
        }
        published_id = insert_backtest_result(
            conn,
            created_at=MATURE.isoformat(),
            config_json="{}",
            initial_cash=100000,
            final_equity=120000,
            total_return=0.2,
            sharpe=3,
            max_dd=0.01,
            equity_curve_json="[]",
            metrics_json=json.dumps(metrics),
        )
    with pytest.raises(
        StrategyResearchRejected, match="candidate_dataset_exploratory_only"
    ):
        require_new_publication_final_evaluation(
            h.db, published_id, expected_candidate_id="candidate-1"
        )


@pytest.mark.asyncio
async def test_late_market_delivery_waits_then_evaluates_same_champion(harness):
    h = harness
    row = await _reserve(h)
    actual = h.adapter.run_sealed

    def incomplete(**kwargs):
        raise StrategyResearchRejected("sealed_trading_calendar_coverage_incomplete")

    h.adapter.run_sealed = incomplete
    with pytest.raises(
        StrategyResearchRejected, match="sealed_trading_calendar_coverage_incomplete"
    ):
        await _evaluate(h)
    assert h.store.get_sealed_test(row["sealed_test_id"])["status"] == "reserved"
    assert not h.calls
    h.adapter.run_sealed = actual
    assert final_research_evaluation_blocker(await _evaluate(h)) is None
    assert len(h.calls) == 2


@pytest.mark.asyncio
async def test_automatic_completed_batch_freezes_selected_champion_before_cutoff(
    harness, monkeypatch
):
    from server.services.ai_shadow_research_automation import (
        AiShadowResearchAutomationService,
        ShadowResearchStore,
    )
    from tests.server.test_ai_shadow_research_automation import (
        _policy_payload,
        _prepared_baseline,
        _state,
    )
    from tests.server.test_normalized_research_recommendation import _candidate

    h = harness
    auto_store = ShadowResearchStore(h.db._path)
    auto_store.init()
    prepared = _prepared_baseline()
    result = deepcopy(prepared.result)
    result["metrics_json"]["dataset_snapshot"] = h.snapshot
    prepared = replace(
        prepared,
        seed_result_id=h.selection.saved_backtest_result_id,
        market_date=h.selection.end_date,
        snapshot=h.snapshot,
        result=result,
        request=prepared.request.model_copy(
            update={
                "start_date": h.selection.start_date,
                "end_date": h.selection.end_date,
                "assets": [{"symbol": "600000", "asset_class": "stock"}],
            }
        ),
    )
    service = AiShadowResearchAutomationService(
        state=_state(h.db),
        store=auto_store,
        data_store=h.data,
        research_service_builder=lambda external: SimpleNamespace(
            _research_store=h.store
        ),
        now=lambda: datetime.fromisoformat(FREEZE),
    )
    service.update_policy(
        {
            **_policy_payload(enabled=True),
            "research_end_date": h.selection.end_date,
            "sealed_end_date": h.selection.sealed_end_date,
        }
    )
    monkeypatch.setattr(service, "_prepare_baseline", lambda policy: prepared)
    generated = []
    saved = []

    async def generate(**kwargs):
        selection = kwargs["selection"]
        ordinal = len(generated) + 1
        candidate, draft = _seed_trial(h, suffix=f"auto-{ordinal}", selection=selection)
        draft.update(
            draft_id=candidate["draft_id"],
            formula_fingerprint="sha256:" + content_fingerprint(draft["formula_ast"]),
        )
        generated.append(candidate)
        return {"session_id": candidate["session_id"]}, draft

    async def evaluated(**kwargs):
        ordinal = len(saved) + 1
        trial = generated[-1]
        candidate = _candidate(ordinal, total_return=0.01 * ordinal)
        comparison = candidate["comparison"]
        previous = saved[-1] if saved else None
        comparison["iteration_lineage"].update(
            total_iterations=5,
            formula_fingerprint=kwargs["draft"]["formula_fingerprint"],
            parent_candidate_id=previous["candidate_id"] if previous else None,
            parent_draft_id=previous["draft_id"] if previous else None,
            parent_formula_fingerprint=previous["comparison"]["iteration_lineage"][
                "formula_fingerprint"
            ]
            if previous
            else None,
            iteration_context_fingerprint=kwargs["iteration_context"][
                "context_fingerprint"
            ],
        )
        persisted = auto_store.save_candidate(
            run_id=kwargs["run"]["run_id"],
            session_id=trial["session_id"],
            draft_id=trial["draft_id"],
            backtest_run_id=trial["backtest_run_id"],
            critique_id=f"critique-{ordinal}",
            baseline_result_id=kwargs["baseline_result_id"],
            candidate_result_id=trial["candidate_result_id"],
            status=candidate["status"],
            recommendation=candidate["recommendation"],
            comparison=comparison,
            now=FREEZE,
        )
        saved.append(persisted)
        return persisted

    monkeypatch.setattr(service, "_generate_iteration_hypothesis", generate)
    monkeypatch.setattr(service, "_run_candidate", evaluated)
    response = await service.run_once()
    assert response["run_status"] == "completed", response
    reservation = h.store.research_champion_reservation(response["run_id"])
    binding = reservation["evidence"]["reservation"]
    assert binding["candidate_id"] == saved[-1]["candidate_id"]
    assert binding["research_identity"]["end_date"] == h.selection.end_date
    assert binding["partition"]["sealed_end"] == h.selection.sealed_end_date
    assert (
        binding["trial_family"]["nominal_trial_count"] == 3
    )  # Same AST/inputs replayed.
    daily = service._daily_artifacts.list_selections()[0]
    assert (
        daily["research_recommendation"]["research_winner_candidate_id"]
        == binding["candidate_id"]
    )
    assert (await service.run_once())["reused"] is True
    assert len(generated) == 5
    service._now = lambda: MATURE
    assert (await service.run_once())["run_status"] == "research_window_frozen"
    assert len(generated) == 5


@pytest.mark.parametrize(
    "dates",
    [
        {"research_end_date": "2026-01-16"},
        {"sealed_end_date": "2026-01-20"},
        {"research_end_date": "2026-01-16", "sealed_end_date": "2026-01-15"},
        {"research_end_date": "2026-01-xx", "sealed_end_date": "2026-01-20"},
    ],
)
def test_final_policy_dates_are_paired_iso_dates(dates):
    from server.contracts.ai_shadow_research_automation import (
        ShadowResearchPolicy,
        ShadowResearchRejected,
    )

    with pytest.raises(ShadowResearchRejected):
        ShadowResearchPolicy(**dates)


def test_exploration_policy_needs_no_final_dates():
    from server.contracts.ai_shadow_research_automation import ShadowResearchPolicy

    policy = ShadowResearchPolicy()
    assert policy.research_end_date is None
    assert policy.sealed_end_date is None
    configured = replace(
        policy, research_end_date="2026-01-16", sealed_end_date="2026-01-20"
    )
    assert ShadowResearchPolicy.from_mapping(configured.to_dict()) == configured


def test_exploration_and_unready_final_batches_cannot_starve_ready_backlog():
    from server.services.account_qualification_reuse import (
        select_oldest_retryable_source_run_id,
    )

    daily = SimpleNamespace(
        list_verified_research_artifact_pairs=lambda: [
            {"run_id": key}
            for key in ("exploration", "failed-final", "future", "ready")
        ],
        load_verified_research_candidate_strategies=lambda **_: {},
    )
    qualifications = SimpleNamespace(list_qualification_runs=lambda **_: [])

    def reservations(run_id):
        if run_id == "exploration":
            raise LookupError("no reservation")
        return {
            "status": "failed" if run_id == "failed-final" else "reserved",
            "evidence": {
                "reservation": {
                    "partition": {
                        "sealed_end": "2026-01-21"
                        if run_id == "future"
                        else "2026-01-20"
                    }
                }
            },
        }

    assert (
        select_oldest_retryable_source_run_id(
            daily,
            qualifications,
            final_reservation_reader=reservations,
            final_evaluation_as_of=MATURE,
        )
        == "ready"
    )
