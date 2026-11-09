"""Actual terminal cost paths enter history without inventing another candidate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import (
    BACKTEST_CONFIRMATION,
    FormulaBacktestRequest,
    StrategyResearchRejected,
)
from server.persistence.backtest_results import backtest_row_fingerprint
from tests.ai_runtime.test_strategy_research_backtest_cancellation import (
    research_case as research_case,
)
from tests.ai_runtime.test_strategy_research_history import _prior, _request, _store

CREATED = "2025-01-09T02:00:00+00:00"
COMPLETED = "2025-01-09T03:00:00+00:00"
OBSERVED = "2025-01-09T03:00:01+00:00"
RECORDED = "2025-01-09T04:00:00+00:00"
EVENT = "formula_backtest.actual_cost_exposure"


def _case(tmp_path, count=2, status="completed"):
    store = _store(tmp_path)
    request = _request(prior_diagnostic_exposures=(_prior(),))
    session, _ = store.create_or_get_session(request, created_at=CREATED)
    ast = {"schema_version": "fixture", "entry": {"op": "constant", "value": 1}}
    draft = {
        "draft_id": "fixture-cost-draft",
        "formula_ast": ast,
        "parameter_values": {},
        "parameter_ranges": {},
        "formula_fingerprint": content_fingerprint(ast),
        "validation": {"status": "valid", "errors": []},
    }
    store.save_drafts(session["session_id"], [draft], created_at=CREATED)
    run, _ = store.create_or_get_backtest(
        FormulaBacktestRequest(
            idempotency_key="actual-cost-fixture",
            requested_by="human:fixture",
            session_id=session["session_id"],
            draft_id=draft["draft_id"],
            confirmation=BACKTEST_CONFIRMATION,
        ),
        formula_fingerprint=draft["formula_fingerprint"],
        dataset_snapshot_id=request.selection.dataset_snapshot_id,
        cost_model_reference=request.selection.cost_model_reference,
        created_at=CREATED,
    )
    costs = [
        {
            "slippage_bps": str(bps),
            "total_return": -0.02,
            "max_drawdown": 0.04,
            "fill_count": 2,
            "unfiltered_nested_source": {"failed_gate": "net"},
        }
        for bps in (10, 25)[:count]
    ]
    metrics = {
        "source_selection": request.selection.to_dict(),
        "formula_fingerprint": draft["formula_fingerprint"],
        "formula_binding": {
            key: draft[key]
            for key in ("formula_ast", "parameter_values", "parameter_ranges")
        },
        "dataset_snapshot": {"snapshot_id": request.selection.dataset_snapshot_id},
        "cost_sensitivity": costs,
    }
    row = {"id": 18, "metrics_json": json.dumps(metrics)}
    with store._connect(immediate=True) as conn:
        conn.execute(
            "INSERT INTO backtest_results VALUES(?,?)", (18, row["metrics_json"])
        )
    store.finish_backtest(
        run["backtest_run_id"],
        status=status,
        result_id=18,
        evidence_fingerprint="fixture-evidence",
        failure_code=None,
        updated_at=COMPLETED,
    )
    saved_json = json.dumps({**row, "evidence_invalidation": None}, indent=2) + "\n"
    file_sha = "sha256:" + hashlib.sha256(saved_json.encode()).hexdigest()
    exposure = None
    if costs:
        exposure = {
            **_prior(),
            "artifact_fingerprint": "sha256:"
            + content_fingerprint(
                {
                    "source_result_id": 18,
                    "source_saved_row_sha256": file_sha,
                    "only_actual_cost_sensitivity": costs,
                }
            ),
            "observed_at": OBSERVED,
            "observed_trial_count": count,
        }
    kwargs = dict(
        result_id=18,
        source_row_fingerprint=backtest_row_fingerprint(row),
        saved_result_json=saved_json,
        exposure=exposure,
        created_at=RECORDED,
    )
    return SimpleNamespace(
        store=store,
        request=request,
        session=session,
        run_id=run["backtest_run_id"],
        row=row,
        metrics=metrics,
        costs=costs,
        kwargs=kwargs,
    )


def _events(case):
    with case.store._connect_readonly() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ai_strategy_research_events WHERE entity_id=? AND event_type=?",
                (case.run_id, EVENT),
            )
        ]


def _originals(case):
    with case.store._connect_readonly() as conn:
        return {
            table: [tuple(row) for row in conn.execute("SELECT * FROM " + table)]
            for table in (
                "ai_strategy_research_sessions",
                "ai_strategy_hypothesis_drafts",
                "ai_strategy_formula_backtests",
                "backtest_results",
            )
        }


@pytest.mark.parametrize("count", [0, 1, 2])
def test_actual_paths_append_once_without_changing_original_rows(tmp_path, count):
    case = _case(tmp_path, count)
    before = case.store.research_trial_family(case.request.selection)
    originals = _originals(case)
    fact, reused = case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    assert not reused and fact["actual_cost_count"] == count
    assert fact["cost_sensitivity_fingerprint"] == "sha256:" + content_fingerprint(
        case.costs
    )
    assert fact["exposure"] == case.kwargs["exposure"]
    assert "saved_result_json" not in fact and "cost_sensitivity" not in fact
    after = case.store.research_trial_family(case.request.selection)
    assert after["nominal_trial_count"] == before["nominal_trial_count"] + count
    assert all(source in after["sources"] for source in before["sources"])
    assert case.store.record_actual_cost_exposure(
        case.run_id, **{**case.kwargs, "created_at": "2025-01-10T04:00:00+00:00"}
    ) == (fact, True)
    assert case.store.research_trial_family(case.request.selection) == after
    assert len(_events(case)) == 1
    assert case.store.verify_events(case.run_id) == (True, [])
    assert _originals(case) == originals


@pytest.mark.parametrize("prior_first", [True, False])
def test_event_and_later_admission_share_existing_ordinal_identity(
    tmp_path, prior_first
):
    case = _case(tmp_path)
    before = case.store.research_trial_family(case.request.selection)
    prior_request = replace(
        case.request,
        idempotency_key="actual-cost-prior",
        prior_diagnostic_exposures=(case.kwargs["exposure"],),
    )
    if prior_first:
        case.store.create_or_get_session(prior_request, created_at=RECORDED)
        prior_sources = case.store.research_trial_family(case.request.selection)[
            "sources"
        ]
    case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    if not prior_first:
        case.store.create_or_get_session(prior_request, created_at=RECORDED)
        prior_sources = before["sources"]
    after = case.store.research_trial_family(case.request.selection)
    assert after["nominal_trial_count"] == before["nominal_trial_count"] + 2
    assert all(source in after["sources"] for source in prior_sources)
    expected = {
        content_fingerprint(
            {
                "diagnostic_artifact_fingerprint": case.kwargs["exposure"][
                    "artifact_fingerprint"
                ],
                "conservative_exposure_ordinal": i,
            }
        )
        for i in range(2)
    }
    assert (
        set(after["trial_fingerprints"]) - set(before["trial_fingerprints"]) == expected
    )


@pytest.mark.parametrize("status", ["running", "pending"])
def test_nonterminal_original_run_cannot_register_cost_paths(tmp_path, status):
    case = _case(tmp_path, status=status)
    with pytest.raises(StrategyResearchRejected, match="terminal_backtest_required"):
        case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    assert _events(case) == []


def test_failed_run_without_linked_saved_result_cannot_register(tmp_path):
    case = _case(tmp_path, status="failed")
    case.store.finish_backtest(
        case.run_id,
        status="failed",
        result_id=None,
        evidence_fingerprint=None,
        failure_code="formula_backtest_cancelled",
        updated_at=COMPLETED,
    )
    with pytest.raises(StrategyResearchRejected, match="saved_result_required"):
        case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    assert _events(case) == []


@pytest.mark.parametrize(
    "change",
    [
        "result",
        "row_hash",
        "row_bytes",
        "count",
        "artifact",
        "scope",
        "early_observed",
        "before_observed",
        "reordered_costs",
    ],
)
def test_forged_identity_source_count_and_order_never_append(tmp_path, change):
    case = _case(tmp_path)
    kwargs = {**case.kwargs, "exposure": dict(case.kwargs["exposure"])}
    if change == "result":
        kwargs["result_id"] = 17
    elif change == "row_hash":
        kwargs["source_row_fingerprint"] = "sha256:" + "0" * 64
    elif change == "row_bytes":
        kwargs["saved_result_json"] = json.dumps({**case.row, "id": 19})
    elif change == "count":
        kwargs["exposure"]["observed_trial_count"] = 1
    elif change == "artifact":
        kwargs["exposure"]["artifact_fingerprint"] = "sha256:" + "0" * 64
    elif change == "scope":
        kwargs["exposure"]["universe"] = ["600001"]
    elif change == "early_observed":
        kwargs["exposure"]["observed_at"] = CREATED
    elif change == "before_observed":
        kwargs["created_at"] = COMPLETED
    else:
        kwargs["exposure"]["artifact_fingerprint"] = "sha256:" + content_fingerprint(
            {
                "source_result_id": 18,
                "source_saved_row_sha256": "sha256:"
                + hashlib.sha256(kwargs["saved_result_json"].encode()).hexdigest(),
                "only_actual_cost_sensitivity": list(reversed(case.costs)),
            }
        )
    before = _originals(case)
    with pytest.raises(StrategyResearchRejected):
        case.store.record_actual_cost_exposure(case.run_id, **kwargs)
    assert _events(case) == [] and _originals(case) == before


def test_different_source_bytes_for_same_run_conflict_without_new_trials(tmp_path):
    case = _case(tmp_path)
    case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    changed = dict(case.kwargs)
    changed["saved_result_json"] = canonical_json(
        {**case.row, "evidence_invalidation": None}
    )
    changed["exposure"] = {
        **changed["exposure"],
        "artifact_fingerprint": "sha256:"
        + content_fingerprint(
            {
                "source_result_id": 18,
                "source_saved_row_sha256": "sha256:"
                + hashlib.sha256(changed["saved_result_json"].encode()).hexdigest(),
                "only_actual_cost_sensitivity": case.costs,
            }
        ),
    }
    before = case.store.research_trial_family(case.request.selection)
    with pytest.raises(IdempotencyConflict):
        case.store.record_actual_cost_exposure(case.run_id, **changed)
    assert case.store.research_trial_family(case.request.selection) == before
    assert len(_events(case)) == 1


def test_later_withdrawal_retains_counts_but_source_drift_blocks_read(tmp_path):
    case = _case(tmp_path)
    case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    before = case.store.research_trial_family(case.request.selection)
    with case.store._connect(immediate=True) as conn:
        conn.execute(
            "CREATE TABLE backtest_result_invalidations(result_id INTEGER PRIMARY KEY, reason TEXT)"
        )
        conn.execute(
            "INSERT INTO backtest_result_invalidations VALUES(18,'historical financial evidence withdrawn')"
        )
    assert case.store.research_trial_family(case.request.selection) == before
    changed = {**case.metrics, "cost_sensitivity": case.costs[:1]}
    with case.store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=18",
            (json.dumps(changed),),
        )
    with pytest.raises(StrategyResearchRejected, match="source_row_mismatch"):
        case.store.research_trial_family(case.request.selection)
    assert len(_events(case)) == 1


def test_forged_event_payload_never_enters_family(tmp_path):
    case = _case(tmp_path)
    fact, _ = case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    case.store.append_event(
        case.run_id, EVENT, {**fact, "actual_cost_count": 9}, created_at=RECORDED
    )
    with pytest.raises(StrategyResearchRejected, match="actual_cost_event_invalid"):
        case.store.research_trial_family(case.request.selection)


def test_concurrent_same_record_is_one_append(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    case = _case(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                case.store.record_actual_cost_exposure, case.run_id, **case.kwargs
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(reused for _, reused in results) == [False, True]
    assert results[0][0] == results[1][0]
    assert len(_events(case)) == 1
    assert case.store.verify_events(case.run_id) == (True, [])


def test_unrelated_family_is_not_blocked_by_old_source_drift(tmp_path):
    case = _case(tmp_path)
    case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    unrelated = replace(case.request.selection, universe=("600001",))
    before = case.store.research_trial_family(unrelated)
    with case.store._connect(immediate=True) as conn:
        conn.execute("UPDATE backtest_results SET metrics_json='{}' WHERE id=18")
    assert case.store.research_trial_family(unrelated) == before
    with pytest.raises(StrategyResearchRejected, match="source_row_mismatch"):
        case.store.research_trial_family(case.request.selection)


def test_historical_cutoff_survives_later_cost_registration(tmp_path):
    case = _case(tmp_path)
    before = case.store.research_trial_family(
        case.request.selection, trial_cutoff=COMPLETED
    )
    case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    assert (
        case.store.research_trial_family(case.request.selection, trial_cutoff=COMPLETED)
        == before
    )
    assert (
        case.store.research_trial_family(case.request.selection)["nominal_trial_count"]
        == before["nominal_trial_count"] + 2
    )


def test_zero_cost_fact_cannot_be_backdated_before_terminal(tmp_path):
    case = _case(tmp_path, count=0)
    with pytest.raises(StrategyResearchRejected, match="recorded_before_terminal"):
        case.store.record_actual_cost_exposure(
            case.run_id, **{**case.kwargs, "created_at": CREATED}
        )
    assert _events(case) == []


def test_corrupt_original_event_chain_cannot_receive_cost_fact(tmp_path):
    case = _case(tmp_path)
    with case.store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE ai_strategy_research_events SET event_hash='corrupt-fixture' WHERE entity_id=?",
            (case.run_id,),
        )
    with pytest.raises(StrategyResearchRejected, match="event_chain_invalid"):
        case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    assert _events(case) == []


@pytest.mark.parametrize("missing", ["result", "run", "session"])
def test_verified_event_scope_limits_missing_source_failure(tmp_path, missing):
    case = _case(tmp_path)
    case.store.record_actual_cost_exposure(case.run_id, **case.kwargs)
    unrelated = replace(case.request.selection, universe=("600001",))
    before = case.store.research_trial_family(unrelated)
    with case.store._connect(immediate=True) as conn:
        if missing == "result":
            conn.execute("DELETE FROM backtest_results WHERE id=18")
        elif missing == "run":
            conn.execute(
                "DELETE FROM ai_strategy_formula_backtests WHERE backtest_run_id=?",
                (case.run_id,),
            )
        else:
            conn.execute(
                "DELETE FROM ai_strategy_research_sessions WHERE session_id=?",
                (case.session["session_id"],),
            )
    assert case.store.research_trial_family(unrelated) == before
    with pytest.raises(StrategyResearchRejected, match="actual_cost_"):
        case.store.research_trial_family(case.request.selection)
    assert len(_events(case)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["terminal_write", "internal_cancellation"])
async def test_real_post_save_failure_retains_actual_cost_trials_and_dedups(
    research_case, monkeypatch, failure
):
    from server.ai_runtime import strategy_research_backtest_workflow

    case = research_case
    store = case.service._research_store
    if failure == "terminal_write":
        original_finish = store.finish_backtest

        def finish(*args, **kwargs):
            if kwargs["status"] == "completed":
                raise OSError("synthetic post-save terminal failure")
            return original_finish(*args, **kwargs)

        monkeypatch.setattr(store, "finish_backtest", finish)
        with pytest.raises(OSError, match="synthetic post-save terminal failure"):
            await case.service.run_formula_backtest(case.request)
    else:

        def cancel_after_saved_result(_value):
            raise asyncio.CancelledError

        monkeypatch.setattr(
            strategy_research_backtest_workflow,
            "content_fingerprint",
            cancel_after_saved_result,
        )
        with pytest.raises(asyncio.CancelledError):
            await case.service.run_formula_backtest(case.request)
    run_id = (
        "ai-formula-backtest-"
        + content_fingerprint({"idempotency_key": case.request.idempotency_key})[:24]
    )
    run = store.get_backtest(run_id)
    assert run["status"] == "failed" and run["canonical_backtest_result_id"] == 18
    if failure == "internal_cancellation":
        assert run["failure_code"] == "formula_backtest_cancelled"
    row = await case.db.get_backtest_result(18)
    costs = json.loads(row["metrics_json"])["cost_sensitivity"]
    assert (
        len(costs) == 2
    )  # Actual engine output persisted before the injected failure.
    serialized = json.dumps(row, ensure_ascii=False, indent=2) + "\n"
    source_sha = "sha256:" + hashlib.sha256(serialized.encode()).hexdigest()
    exposure = {
        **_prior(),
        **{
            key: case.selection.to_dict()[key]
            for key in (
                "universe",
                "start_date",
                "end_date",
                "frequency",
                "cost_model_reference",
            )
        },
        "artifact_fingerprint": "sha256:"
        + content_fingerprint(
            {
                "source_result_id": 18,
                "source_saved_row_sha256": source_sha,
                "only_actual_cost_sensitivity": costs,
            }
        ),
        "observed_at": run["updated_at"],
        "observed_trial_count": len(costs),
    }
    before = store.research_trial_family(case.selection)
    recorded = (
        datetime.fromisoformat(run["updated_at"]) + timedelta(seconds=1)
    ).isoformat()
    kwargs = dict(
        result_id=18,
        source_row_fingerprint=backtest_row_fingerprint(row),
        saved_result_json=serialized,
        exposure=exposure,
        created_at=recorded,
    )
    fact, reused = store.record_actual_cost_exposure(run_id, **kwargs)
    assert not reused and fact["terminal_at"] == run["updated_at"]
    assert "completed_at" not in fact and fact["actual_cost_count"] == 2
    after = store.research_trial_family(case.selection)
    assert after["nominal_trial_count"] == before["nominal_trial_count"] + 2
    assert all(source in after["sources"] for source in before["sources"])
    new_source = next(
        source
        for source in after["sources"]
        if source.get("source_kind") == "actual_cost_exposure"
    )
    assert new_source["canonical_performance_admitted"] is False
    assert store.record_actual_cost_exposure(run_id, **kwargs) == (fact, True)
    store.create_or_get_session(
        _request(
            idempotency_key="later-disclosure-of-postsave-failure",
            selection=case.selection,
            prior_diagnostic_exposures=(exposure,),
        ),
        created_at=recorded,
    )
    assert (
        store.research_trial_family(case.selection)["nominal_trial_count"]
        == after["nominal_trial_count"]
    )
    assert (
        store.get_backtest(run_id) == run
    )  # Failure and original source are not rewritten.
    assert await case.db.get_backtest_result(18) == row
    assert store.verify_events(run_id) == (True, [])


@pytest.mark.parametrize(
    "source_case",
    ["present_conflict", "diagnostic_binding_conflict", "diagnostic_hash_invalid"],
)
def test_legacy_source_selection_fallback_never_masks_conflicts(tmp_path, source_case):
    case = _case(tmp_path)
    metrics = json.loads(case.row["metrics_json"])
    diagnostic = {
        "schema_version": "karkinos.ai.native_formula_diagnostic.v1",
        **{
            key: metrics.get(key)
            for key in (
                "formula_binding",
                "formula_fingerprint",
                "dataset_snapshot",
                "cost_assumptions",
            )
        },
        "source_selection": case.request.selection.to_dict(),
    }
    if source_case == "diagnostic_binding_conflict":
        diagnostic["formula_fingerprint"] = "sha256:" + "0" * 64
    diagnostic["evidence_fingerprint"] = content_fingerprint(diagnostic)
    if source_case == "diagnostic_hash_invalid":
        diagnostic["evidence_fingerprint"] = "0" * 64
    metrics["native_diagnostic"] = diagnostic
    if source_case == "present_conflict":
        metrics["source_selection"] = {
            **metrics["source_selection"],
            "universe": ["600001"],
        }
    else:
        del metrics["source_selection"]
    row = {**case.row, "metrics_json": json.dumps(metrics)}
    with case.store._connect(immediate=True) as conn:
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=18",
            (row["metrics_json"],),
        )
    kwargs = {
        **case.kwargs,
        "source_row_fingerprint": backtest_row_fingerprint(row),
        "saved_result_json": json.dumps(row),
    }
    with pytest.raises(
        StrategyResearchRejected, match="actual_cost_source_binding_mismatch"
    ):
        case.store.record_actual_cost_exposure(case.run_id, **kwargs)
    assert _events(case) == []
