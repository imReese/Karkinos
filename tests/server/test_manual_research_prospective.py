"""Manual SIM wiring: temporary SQLite, synthetic source bindings and clocks."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio

from analytics.sealed_holdout import build_sealed_partition
from server.config_types import ResearchSimulationSourceConfig
from server.contracts.content_identity import content_fingerprint
from server.persistence.strategy_research_sealed import final_reservation_id
from server.services.research import research_final_evaluation as owner
from tests.server.test_research_final_evaluation import harness  # noqa: F401
from tests.server.test_research_final_statistical_policy import final_policy  # noqa: F401


@pytest_asyncio.fixture
async def manual(final_policy, monkeypatch):
    t = final_policy
    h = t.h
    refs = ResearchSimulationSourceConfig(
        session_id=h.candidate["session_id"],
        draft_id=h.candidate["draft_id"],
        backtest_run_id=h.candidate["backtest_run_id"],
        critique_id="real-critique-ref",
        canonical_backtest_result_id=h.candidate["candidate_result_id"],
    )
    # The v2 helper first creates a non-SIM legacy reservation. This fixture
    # explicitly models a genuine prior SIM allocation instead of erasing it.
    prior = deepcopy(t.binding)
    prior["error_budget"] = {
        "grant_id": prior["simulation_policy"]["grant_id"],
        "generation": prior["simulation_policy"]["generation"],
        "attempt_count": 1,
        "allocated_alpha": "0.05",
        "error_budget_spent": "0.05",
    }
    envelope = {"reservation": prior}
    with sqlite3.connect(h.db.path) as conn:
        conn.execute(
            "UPDATE ai_strategy_sealed_tests SET request_fingerprint=?,evidence_json=?,evidence_fingerprint=? WHERE sealed_test_id=?",
            (
                content_fingerprint(prior),
                json.dumps(envelope),
                content_fingerprint(envelope),
                t.reserved["sealed_test_id"],
            ),
        )
    start, end = "2026-04-01", "2026-05-31"
    days = [
        (datetime(2026, 4, 1) + timedelta(days=i)).date().isoformat() for i in range(60)
    ]
    now = [datetime.fromisoformat("2026-03-31T12:00:00+00:00")]
    source_fingerprint = "sha256:" + "a" * 64

    def resolve(source):
        assert source == refs
        return {
            "status": "ready",
            "selection": h.selection.to_dict(),
            "source_fingerprint": source_fingerprint,
            "historical_validation_status": "not_assessed",
        }

    monkeypatch.setattr(
        "server.services.research.factory.build_strategy_research_read_service",
        lambda _db: SimpleNamespace(resolve_research_simulation_source=resolve),
    )
    sim = deepcopy(t.sim)
    sim.update(max_final_tests=3, total_error_budget="0.15")
    sim["statistical_policy"]["decision_checkpoint"] = end
    binding = deepcopy(t.binding)
    partition = build_sealed_partition(
        research_start=h.selection.start_date,
        research_end=h.selection.end_date,
        prospective_start=start,
        sealed_end=end,
    )
    binding.update(
        partition=partition.to_json_dict(),
        partition_fingerprint=partition.partition_fingerprint,
        first_evaluation_session=start,
        effective_checkpoint=days[-1],
        simulation_policy=sim,
    )
    sim["statistical_policy"]["comparator_bindings"] = (
        owner._statistical_comparator_bindings(
            binding, h.selection, h.store, policy=sim["statistical_policy"]
        )
    )
    sim["statistical_policy_fingerprint"] = content_fingerprint(
        sim["statistical_policy"]
    )
    monkeypatch.setattr(
        "server.contracts.research_observation_automation.read_simulation_validation_policy",
        lambda *_a, **_k: deepcopy(sim),
    )
    monkeypatch.setattr(
        "server.contracts.research_observation_automation.read_research_validation_policy",
        lambda *_a, **_k: deepcopy(sim),
    )
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.verified_trading_dates",
        lambda _db, *, start_date, end_date: [
            d for d in days if start_date <= d <= end_date
        ],
    )
    from server.services.research.research_observation_inputs import (
        load_research_observation_source,
    )

    monkeypatch.setattr(
        "server.services.research.research_observation_inputs.load_research_observation_source",
        lambda *a, **k: (
            {"minimum_bars": 20}
            if k.get("allow_unbound_dataset")
            else load_research_observation_source(*a, **k)
        ),
    )
    seed_calls = []

    def seed(*_a, **kwargs):
        seed_calls.append(kwargs["now"])
        return {"status": "ready", "dataset_id": "synthetic-seed"}

    monkeypatch.setattr(
        "server.services.research.datasets.ensure_forward_seed_for_source", seed
    )
    return SimpleNamespace(
        t=t, refs=refs, start=start, end=end, now=now, sim=sim, seed_calls=seed_calls
    )


async def reserve(m, **kwargs):
    return await owner.reserve_manual_research_evaluation(
        db=m.t.h.db,
        research_store=m.t.h.store,
        source=m.refs,
        prospective_start=m.start,
        prospective_end=m.end,
        config=None,
        clock=lambda: m.now[0],
        formula_comparators=m.t.references,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_real_refs_no_fabricated_winner_and_exact_retry_keeps_budget(manual):
    m = manual
    original = m.t.h.selection.to_dict()
    row = await reserve(m)
    binding = row["evidence"]["reservation"]
    assert binding["manual_source_refs"] == asdict(m.refs)
    assert row["sealed_test_id"] == final_reservation_id(binding)
    assert row["sealed_test_id"].startswith("ai-sealed-manual-")
    assert not {
        "candidate_id",
        "source_run_id",
        "selection_evidence_fingerprint",
        "research_candidate_qualified",
    }.intersection(binding)
    assert binding["partition"]["research_end"] == original["end_date"]
    assert binding["partition"]["prospective_start"] == m.start
    assert binding["first_evaluation_session"] == m.start
    assert binding["forward_seed_dataset_id"] == "synthetic-seed"
    assert binding["error_budget"]["attempt_count"] == 2
    assert binding["error_budget"]["error_budget_spent"] == "0.10"
    assert m.t.h.selection.to_dict() == original
    assert binding["trial_family"] == m.t.h.store.research_trial_family(m.t.h.selection)
    again = await reserve(m)
    assert again == row
    assert len(m.seed_calls) == 1
    assert again["evidence"]["reservation"]["error_budget"] == binding["error_budget"]


@pytest.mark.asyncio
async def test_new_forward_generation_preserves_original_source_and_spent_budget(
    manual,
):
    m = manual
    original = m.t.h.selection.to_dict()
    old_generation = original["simulation_validation_binding"]["generation"]
    m.sim["generation"] = "00000000-0000-0000-0000-000000000003"
    assert m.sim["generation"] != old_generation
    row = await reserve(m)
    binding = row["evidence"]["reservation"]
    assert binding["simulation_policy"]["generation"] == m.sim["generation"]
    assert binding["selection_fingerprint"] == m.t.h.selection.fingerprint
    assert binding["manual_source_refs"] == asdict(m.refs)
    assert binding["error_budget"]["attempt_count"] == 2
    assert binding["error_budget"]["error_budget_spent"] == "0.10"
    assert (
        binding["execution_cost_assumptions"]
        == m.t.binding["execution_cost_assumptions"]
    )
    assert m.t.h.selection.to_dict() == original


@pytest.mark.asyncio
async def test_missed_first_opening_cannot_backdate_or_extend_spent_allocation(manual):
    m = manual
    row = await reserve(m)
    m.now[0] = datetime.fromisoformat("2026-04-01T01:30:00+00:00")
    # Exact retrieval is still idempotent after opening; it never starts a book.
    assert await reserve(m) == row
    m.start = "2026-04-02"
    with pytest.raises(ValueError, match="reservation_conflict"):
        await reserve(m)
    assert m.t.h.store.get_sealed_test(row["sealed_test_id"]) == row


@pytest.mark.asyncio
async def test_seed_crossing_first_opening_never_allocates(manual, monkeypatch):
    m = manual

    def slow_seed(*_a, **_kw):
        m.now[0] = datetime.fromisoformat("2026-04-01T01:30:00+00:00")
        return {"status": "ready", "dataset_id": "synthetic-seed"}

    monkeypatch.setattr(
        "server.services.research.datasets.ensure_forward_seed_for_source", slow_seed
    )
    with pytest.raises(ValueError, match="first_opening_missed"):
        await reserve(m)
    assert m.t.h.store.manual_research_champion_reservation(asdict(m.refs)) is None


@pytest.mark.asyncio
async def test_seed_pending_and_wrong_policy_never_allocate(manual, monkeypatch):
    m = manual
    monkeypatch.setattr(
        "server.services.research.datasets.ensure_forward_seed_for_source",
        lambda *_a, **_k: {"status": "waiting", "job_ids": ["existing-job"]},
    )
    pending = await reserve(m)
    assert pending["status"] == "waiting" and pending["reservation_id"] is None
    assert m.t.h.store.manual_research_champion_reservation(asdict(m.refs)) is None
    m.end = "2026-06-01"
    with pytest.raises(ValueError, match="checkpoint_mismatch"):
        await reserve(m)


@pytest.mark.asyncio
async def test_verified_bars_without_rank_membership_do_not_spend_final_slot(
    manual, monkeypatch
):
    from tests.server.test_verified_interval_dataset import DAYS, _verified_day

    m = manual
    ref = _verified_day(m.t.h.db.path.parent / "research", DAYS[0])
    monkeypatch.setattr(
        "server.ai_runtime.formula_dsl.formula_requires_cross_section", lambda _: True
    )
    monkeypatch.setattr(
        "server.services.research.datasets.ensure_forward_seed_for_source",
        lambda *_a, **_k: {"status": "ready", "dataset_id": ref.dataset_id},
    )
    result = await reserve(m)
    assert result["status"] == "blocked"
    assert result["last_blocker"]["code"] == "dataset_cross_section_membership_invalid"
    assert result["reservation_id"] is None
    assert m.t.h.store.manual_research_champion_reservation(asdict(m.refs)) is None


@pytest.mark.asyncio
async def test_manual_final_require_reopens_source_and_never_uses_automation_candidate(
    manual, monkeypatch
):
    m = manual
    row = await reserve(m)
    source = owner.manual_final_research_source(
        research_store=m.t.h.store, source=m.refs, reservation_id=row["sealed_test_id"]
    )
    assert not hasattr(source, "source_candidate")
    mature = datetime.fromisoformat("2026-05-31T08:00:00+00:00")
    assert (
        owner.require_final_reservation(
            research_store=m.t.h.store, source=source, now=mature
        )
        == row
    )
    monkeypatch.setattr(
        "server.services.research.factory.build_strategy_research_read_service",
        lambda _db: SimpleNamespace(
            resolve_research_simulation_source=lambda _: {"status": "blocked"}
        ),
    )
    with pytest.raises(ValueError, match="source_not_ready"):
        owner.require_final_reservation(
            research_store=m.t.h.store, source=source, now=mature
        )


@pytest.mark.parametrize(
    "value", [{}, {"session_id": "x"}, {"canonical_backtest_result_id": True}]
)
def test_manual_id_rejects_incomplete_or_forged_references(value):
    with pytest.raises(ValueError, match="references_invalid"):
        final_reservation_id(
            {"source_kind": "manual_research", "manual_source_refs": value}
        )


def test_legacy_auto_id_is_byte_identical():
    assert (
        final_reservation_id({"source_run_id": "old-run"})
        == "ai-sealed-auto-" + content_fingerprint({"run_id": "old-run"})[:24]
    )


@pytest.mark.asyncio
async def test_allocation_rechecks_clock_inside_transaction_and_rolls_back(
    manual, monkeypatch
):
    from server.persistence import strategy_research_sealed as repository

    m = manual
    allocations = repository._related_final_allocations

    def budget_scan(conn, binding):
        result = allocations(conn, binding)
        m.now[0] = datetime.fromisoformat("2026-04-01T01:30:00+00:00")
        return result

    monkeypatch.setattr(repository, "_related_final_allocations", budget_scan)
    with pytest.raises(ValueError, match="not_frozen_before_holdout"):
        await reserve(m)
    assert m.t.h.store.manual_research_champion_reservation(asdict(m.refs)) is None
    assert (
        m.t.h.store.get_sealed_test(m.t.reserved["sealed_test_id"])["evidence"][
            "reservation"
        ]["error_budget"]["attempt_count"]
        == 1
    )


@pytest.mark.asyncio
async def test_manual_final_replays_every_comparator_with_gap_as_warmup_only(
    manual, monkeypatch
):
    from decimal import Decimal

    from analytics.sealed_holdout import final_research_evaluation_blocker
    from backtest.result import BacktestResult

    m = manual
    h = m.t.h
    row = await reserve(m)
    binding = row["evidence"]["reservation"]
    source = owner.manual_final_research_source(
        research_store=h.store, source=m.refs, reservation_id=row["sealed_test_id"]
    )
    days = [
        (datetime(2026, 4, 1) + timedelta(days=i)).date().isoformat() for i in range(60)
    ]
    cash = Decimal(binding["initial_cash"])
    asts = {
        content_fingerprint(h.draft["formula_ast"]): "candidate",
        **{
            content_fingerprint(v["formula_binding"]["formula_ast"]): k
            for k, v in binding["formula_comparators"].items()
        },
    }

    def curve(label):
        rate = (
            Decimal("0.002")
            if label == "candidate"
            else Decimal("0.003")
            if label == "MA"
            else Decimal("0.001")
        )
        return [
            (datetime.fromisoformat(day), cash * (1 + rate) ** (i + 1))
            for i, day in enumerate(days)
        ]

    calls = []

    def replay(**kwargs):
        calls.append(kwargs)
        label = asts.get(
            content_fingerprint(kwargs["draft"]["formula_ast"]), "frozen_baseline"
        )
        measured = curve(label)
        result = BacktestResult(
            equity_curve=measured,
            positions={},
            initial_cash=cash,
            final_equity=measured[-1][1],
            fills=[],
            execution_timing={
                "evaluation_start": kwargs.get("prospective_start"),
                "warmup_basis": "strategy_history_only_fresh_book",
                "warmup_final_bar_targets": True,
            },
        )
        result.dataset_snapshot = h.full_snapshot
        result.portfolio_observations = []
        return result

    h.adapter.run_sealed = replay
    all_days = ["2026-01-16", "2026-02-02", "2026-03-31", *days]
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.verified_trading_dates",
        lambda _db, *, start_date, end_date: [
            d for d in all_days if start_date <= d <= end_date
        ],
    )
    monkeypatch.setattr(owner, "_next_verified_session_opens", lambda *_a: {})
    monkeypatch.setattr(
        owner,
        "_reserved_execution_costs",
        lambda *_a: SimpleNamespace(commission_calc=object()),
    )
    monkeypatch.setattr(
        "server.services.research.datasets.resolve_deployment_evaluation_dataset",
        lambda *_a, **_k: {"status": "ready", "dataset_snapshot": h.full_snapshot},
    )
    monkeypatch.setattr(
        "server.services.research.research_paper_books.verify_reserved_forward_book",
        lambda *_a, **_k: {
            "session_equity": [
                {"session": ts.date().isoformat(), "equity": str(value)}
                for ts, value in curve("candidate")
            ]
        },
    )

    def assessment(**kwargs):
        assert kwargs["trading_dates"] == days
        payload = {
            "status": kwargs["uncertainty"]["status"],
            "uncertainty": kwargs["uncertainty"],
            "deployment_scope_fingerprint": binding["deployment_scope"][
                "deployment_scope_fingerprint"
            ],
            "risk_limits": m.sim["risk_limits"],
            "blockers": [],
            "return_basis": "synthetic-after-cost",
            "corporate_action_coverage": "synthetic",
            "membership_sessions": days,
        }
        return {**payload, "evidence_fingerprint": content_fingerprint(payload)}

    monkeypatch.setattr(owner, "_deployment_assessment", assessment)
    evidence = await owner.evaluate_reserved_champion(
        research_store=h.store,
        source=source,
        adapter=h.adapter,
        now=datetime.fromisoformat("2026-06-01T08:00:00+00:00"),
        calendar_db=h.db,
    )
    assert len(calls) == 12
    assert all(call["prospective_start"] == m.start for call in calls)
    assert all(call["selection"].end_date == "2026-01-16" for call in calls)
    assert all(call["initial_cash_override"] == cash for call in calls)
    assert final_research_evaluation_blocker(evidence) is None
    assert evidence["deployment_assessment"]["membership_sessions"] == days
    assert h.store.get_sealed_test(row["sealed_test_id"])["status"] == "completed"
