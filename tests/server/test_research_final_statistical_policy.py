"""Frozen v2 callers, using synthetic curves and temporary canonical rows only."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
import pytest_asyncio

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from analytics.sealed_holdout import final_research_evaluation_blocker
from backtest.result import BacktestResult
from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.handler import DataHandler
from server.contracts.content_identity import content_fingerprint
from server.contracts.http.strategy_models import BacktestCostAssumptions
from server.contracts.recommendation_publication import (
    FINAL_CALENDAR_AT_EVALUATION,
    FINAL_STATISTICAL_POLICY_SCHEMA,
    LEGACY_CALENDAR_AT_EVALUATION,
    LEGACY_FINAL_STATISTICAL_POLICY_SCHEMA,
    is_final_calendar_timing,
    is_final_statistical_policy,
)
from server.services.ai_shadow.ai_shadow_research_commands import (
    simulation_validation_defaults,
)
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
)
from server.services.research import research_final_evaluation as owner
from tests.server.test_research_final_evaluation import (
    FREEZE,
    _reserve,
    _seed_exact_formula_comparator,
    _use_formula_baseline,
    harness,  # noqa: F401
)


def test_legacy_statistical_policy_identifier_remains_readable():
    assert is_final_statistical_policy(
        {"schema_version": FINAL_STATISTICAL_POLICY_SCHEMA}
    )
    assert is_final_statistical_policy(
        {"schema_version": LEGACY_FINAL_STATISTICAL_POLICY_SCHEMA}
    )
    assert not is_final_statistical_policy({})
    assert not is_final_statistical_policy({"schema_version": "unknown"})


def test_legacy_calendar_verification_timing_remains_readable():
    assert is_final_calendar_timing(FINAL_CALENDAR_AT_EVALUATION)
    assert is_final_calendar_timing(next(iter(LEGACY_CALENDAR_AT_EVALUATION)))
    assert not is_final_calendar_timing(None)
    assert not is_final_calendar_timing("unknown")


@pytest_asyncio.fixture
async def final_policy(harness):
    h = harness
    symbol = Symbol("600000")
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-10-01", "2026-01-16"),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 100000,
        }
    )
    h.snapshot = build_backtest_dataset_snapshot(
        start_date="2025-10-01",
        end_date="2026-01-16",
        configured_source="fixture",
        data_handlers={
            symbol: DataHandler(
                frame,
                symbol,
                BarFrequency.DAILY,
                AssetClass.STOCK,
                InstrumentType.STOCK,
            )
        },
        store=h.data,
        source_names=["fixture"],
    )
    sim = simulation_validation_defaults(datetime.fromisoformat(FREEZE))
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    sim.update(
        grant_id="00000000-0000-0000-0000-000000000001",
        generation="00000000-0000-0000-0000-000000000002",
        initial_cash=str(h.selection.initial_cash),
        deployment_scope=scope,
    )
    h.entry_board_policy = sim["entry_board_policy"]
    h.selection = replace(
        h.selection,
        start_date="2025-10-01",
        dataset_snapshot_id=h.snapshot["snapshot_id"],
        sealed_end_date="2026-03-18",
        deployment_scope=scope,
        portfolio_policy_id=scope["portfolio_policy_id"],
        simulation_validation_binding={
            key: sim[key] for key in ("grant_id", "generation", "initial_cash")
        },
    )
    _use_formula_baseline(h)
    references = {
        "MA": _seed_exact_formula_comparator(h, 7),
        "Gen7": _seed_exact_formula_comparator(h, 9),
    }
    with sqlite3.connect(h.db.path) as conn:
        row = conn.execute(
            "SELECT metrics_json FROM backtest_results WHERE id=?",
            (h.candidate["candidate_result_id"],),
        ).fetchone()
        metrics = json.loads(row[0])
        metrics["entry_board_policy"] = h.entry_board_policy
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=?",
            (json.dumps(metrics), h.candidate["candidate_result_id"]),
        )
    reserved = await _reserve(h, formula_comparators=references)
    binding = deepcopy(reserved["evidence"]["reservation"])
    days = [
        (datetime(2026, 1, 17) + timedelta(days=i)).date().isoformat()
        for i in range(60)
    ]
    binding.update(
        simulation_policy=sim,
        deployment_scope=scope,
        initial_cash=sim["initial_cash"],
        entry_board_policy=h.entry_board_policy,
        simulation_cost_inputs=BacktestCostAssumptions().model_dump(mode="json"),
        first_evaluation_session=days[0],
        effective_checkpoint=days[-1],
    )
    profile = {
        "schema_version": FINAL_STATISTICAL_POLICY_SCHEMA,
        "method": "paired_moving_block_bootstrap.v1",
        "research_policy_fingerprint": "sha256:" + "a" * 64,
        "minimum_observations": 60,
        "block_length": 5,
        "minimum_effective_blocks": 12,
        "bootstrap_samples": 100000,
        "significance_level": "0.05",
        "minimum_net_excess": "0",
        "decision_checkpoint": "2026-03-18",
        "minimum_candidate_net_return": "0",
        "minimum_annualized_relative_wealth": "0.03",
        "maximum_drawdown": "0.15",
        "primary_comparator": "Gen7",
    }
    profile["comparator_bindings"] = owner._statistical_comparator_bindings(
        binding, h.selection, h.store, policy=profile
    )
    sim.update(
        statistical_policy=profile,
        statistical_policy_fingerprint=content_fingerprint(profile),
    )

    def curve(rate):
        cash = Decimal(binding["initial_cash"])
        return [
            [day + "T00:00:00", str(cash * (1 + Decimal(rate)) ** (index + 1))]
            for index, day in enumerate(days)
        ]

    curves = {
        "candidate": curve("0.002"),
        "comparators": {
            label: curve("0.003" if label == "MA" else "0.001")
            for label in profile["comparator_bindings"]
        },
    }
    return SimpleNamespace(
        h=h,
        binding=binding,
        sim=sim,
        days=days,
        references=references,
        curves=curves,
        reserved=reserved,
    )


def _compare(t, binding=None, curves=None):
    return owner._compare_final_curves(
        binding or t.binding,
        curves or t.curves,
        seed=t.reserved["sealed_test_id"],
        research_store=t.h.store,
        selection=t.h.selection,
    )


@pytest.mark.asyncio
async def test_v2_reserve_verifies_prebound_mapping_and_calendar_without_filling_policy(
    final_policy, monkeypatch
):
    t = final_policy
    before = deepcopy(t.sim)
    monkeypatch.setattr(
        "server.contracts.research_observation_automation.read_research_validation_policy",
        lambda *_a, **_k: t.sim,
    )
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.verified_trading_dates",
        lambda _db, *, start_date, end_date: [
            d for d in t.days if start_date <= d <= end_date
        ],
    )
    monkeypatch.setattr(t.h.store, "reserve_research_champion", lambda **kw: kw)
    result = await _reserve(t.h, formula_comparators=t.references)
    assert result["binding"]["effective_checkpoint"] == "2026-03-17"
    assert result["binding"]["simulation_policy"] == before
    assert t.sim == before
    t.sim["statistical_policy"]["comparator_bindings"].pop("MA")
    t.sim["statistical_policy_fingerprint"] = content_fingerprint(
        t.sim["statistical_policy"]
    )
    with pytest.raises(ValueError, match="comparator_identity_binding_mismatch"):
        await _reserve(t.h, formula_comparators=t.references)


@pytest.mark.asyncio
async def test_v2_all_eleven_identities_keep_primary_only_gate_and_full_alpha(
    final_policy,
):
    result = _compare(final_policy)
    assert result["status"] == "pass"
    assert result["policy"] == final_policy.sim["statistical_policy"]
    assert result["effective_checkpoint"] == "2026-03-17"
    assert result["policy"]["decision_checkpoint"] == "2026-03-18"
    assert len(result["comparisons"]) == 11
    assert all(
        item["one_sided_alpha"] == pytest.approx(0.05 / 11)
        for item in result["comparisons"]
    )
    assert (
        next(item for item in result["comparisons"] if item["label"] == "MA")[
            "net_excess_lower_bound"
        ]
        < 0
    )
    relabeled = deepcopy(final_policy.binding)
    relabeled["formula_comparators"]["alias"] = relabeled["formula_comparators"].pop(
        "Gen7"
    )
    actual = owner._statistical_comparator_bindings(
        relabeled,
        final_policy.h.selection,
        final_policy.h.store,
        policy={"primary_comparator": "MA"},
    )
    original = final_policy.sim["statistical_policy"]["comparator_bindings"]
    assert (
        actual["alias"]["identity_fingerprint"]
        == original["Gen7"]["identity_fingerprint"]
    )
    assert (
        actual["MA"]["identity_fingerprint"] == original["MA"]["identity_fingerprint"]
    )
    with pytest.raises(ValueError, match="comparator_identity_binding_mismatch"):
        _compare(final_policy, relabeled)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "fee",
        "cash",
        "code",
        "scope",
        "clock",
        "formula",
        "role",
        "missing_curve",
        "truncated",
        "source",
    ],
)
async def test_v2_callers_reject_tampering(final_policy, change):
    binding, curves = deepcopy(final_policy.binding), deepcopy(final_policy.curves)
    if change == "fee":
        binding["simulation_cost_inputs"]["slippage_bps"] = 99
    elif change == "cash":
        binding["initial_cash"] = "999999"
    elif change == "code":
        binding["code_binding"]["fingerprint"] = "wrong"
    elif change == "scope":
        binding["entry_board_policy"] = {"scope": "changed"}
    elif change == "clock":
        binding["effective_checkpoint"] = "2026-03-16"
    elif change == "formula":
        binding["formula_comparators"]["Gen7"]["formula_binding"]["parameter_values"][
            "window"
        ] = 10
    elif change == "role":
        profile = binding["simulation_policy"]["statistical_policy"]
        profile["primary_comparator"] = "MA"
        binding["simulation_policy"]["statistical_policy_fingerprint"] = (
            content_fingerprint(profile)
        )
    elif change == "missing_curve":
        curves["comparators"].pop("MA")
    elif change == "truncated":
        curves["candidate"].pop()
        for curve in curves["comparators"].values():
            curve.pop()
    elif change == "source":
        with sqlite3.connect(final_policy.h.db.path) as conn:
            conn.execute(
                "UPDATE backtest_results SET created_at=? WHERE id=?",
                ("changed", final_policy.references["Gen7"]["source_result_id"]),
            )
    if change == "truncated":
        result = _compare(final_policy, binding, curves)
        assert result["status"] == "insufficient_evidence"
        assert "deployment_independent_sample_insufficient" in result["blockers"]
    else:
        with pytest.raises((ValueError, KeyError)):
            _compare(final_policy, binding, curves)


@pytest.mark.asyncio
async def test_v2_reviewed_fee_context_is_distinct_and_cannot_relabel_original_sim(
    final_policy, monkeypatch
):
    t = final_policy
    original = deepcopy(t.binding)
    grant = deepcopy(t.sim)
    reviewed = {
        **t.binding,
        "publication_grant": grant,
        "fee_schedule": {
            "review_id": "frozen-review",
            "review_fingerprint": "sha256:" + "b" * 64,
            "cost_model_reference": "reviewed-fees",
            "fee_evidence": {"source": "synthetic-reviewed-fees"},
        },
    }
    reviewed.pop("simulation_policy")
    with pytest.raises(ValueError, match="comparator_identity_binding_mismatch"):
        owner._verified_statistical_inputs(reviewed, t.h.selection, t.h.store)
    profile = grant["statistical_policy"]
    profile["comparator_bindings"] = owner._statistical_comparator_bindings(
        reviewed, t.h.selection, t.h.store, policy=profile
    )
    grant["statistical_policy_fingerprint"] = content_fingerprint(profile)
    assert all(
        profile["comparator_bindings"][label]["identity_fingerprint"]
        != t.sim["statistical_policy"]["comparator_bindings"][label][
            "identity_fingerprint"
        ]
        for label in profile["comparator_bindings"]
    )
    monkeypatch.setattr(
        owner, "_deployment_assessment", lambda **kwargs: kwargs["uncertainty"]
    )
    replay = {
        "session_curves": t.curves,
        "fee_schedule": reviewed["fee_schedule"],
        "portfolio_observations": [],
        "comparator_accounting": {},
        "economic_return_accounting": {},
    }
    evidence = {
        "reservation": t.binding,
        "sealed_test_id": t.reserved["sealed_test_id"],
        "session_curves": t.curves,
        "sealed_dataset_snapshot": t.h.full_snapshot,
        "deployment_assessment": {"membership_sessions": t.days},
    }
    actual = owner._simulation_reviewed_assessment(t.h.db, evidence, grant, replay)
    assert actual["status"] == "pass"
    assert actual["policy_fingerprint"] == grant["statistical_policy_fingerprint"]
    assert t.binding == original
    assert _compare(t)["policy_fingerprint"] == t.sim["statistical_policy_fingerprint"]


@pytest.mark.asyncio
async def test_v2_incumbent_uses_full_canonical_source_and_remains_in_alpha(
    final_policy,
):
    t = final_policy
    reference = _seed_exact_formula_comparator(t.h, 11)
    saved = t.h.store.research_backtest_result(reference["source_result_id"])
    binding = deepcopy(t.binding)
    binding["incumbent"] = {
        "strategy_id": "existing-incumbent",
        "source_result_id": saved["id"],
        "source_fingerprint": content_fingerprint(saved),
        "formula_ast": json.loads(saved["metrics_json"])["formula_binding"][
            "formula_ast"
        ],
    }
    profile = binding["simulation_policy"]["statistical_policy"]
    profile["comparator_bindings"] = owner._statistical_comparator_bindings(
        binding, t.h.selection, t.h.store, policy=profile
    )
    binding["simulation_policy"]["statistical_policy_fingerprint"] = (
        content_fingerprint(profile)
    )
    curves = deepcopy(t.curves)
    curves["comparators"]["incumbent"] = curves["comparators"]["Gen7"]
    result = _compare(t, binding, curves)
    assert len(result["comparisons"]) == 12
    assert all(
        item["one_sided_alpha"] == pytest.approx(0.05 / 12)
        for item in result["comparisons"]
    )
    binding["incumbent"]["source_fingerprint"] = "forged"
    with pytest.raises(ValueError, match="incumbent_source_drift"):
        _compare(t, binding, curves)


@pytest.mark.asyncio
async def test_v1_caller_retains_exact_prior_calculator_bytes_without_new_fields(
    final_policy,
):
    from analytics.deployment_validation import compare_session_curves

    binding = deepcopy(final_policy.binding)
    profile = {
        key: binding["simulation_policy"]["statistical_policy"][key]
        for key in (
            "method",
            "minimum_observations",
            "block_length",
            "minimum_effective_blocks",
            "bootstrap_samples",
            "significance_level",
            "minimum_net_excess",
            "decision_checkpoint",
        )
    }
    binding["simulation_policy"]["statistical_policy"] = profile
    before = deepcopy(binding)
    expected = compare_session_curves(
        candidate=final_policy.curves["candidate"],
        comparators=final_policy.curves["comparators"],
        initial_cash=binding["initial_cash"],
        policy={
            **profile,
            "decision_checkpoint": final_policy.curves["candidate"][-1][0][:10],
        },
        seed=final_policy.reserved["sealed_test_id"],
    )
    actual = _compare(final_policy, binding)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert binding == before
    assert not {
        "comparator_bindings",
        "effective_checkpoint",
        "policy_fingerprint",
    }.intersection(actual)


@pytest.mark.asyncio
async def test_v2_final_replay_and_persisted_gate_do_not_reintroduce_max(
    final_policy, monkeypatch
):
    t = final_policy
    cash = Decimal(t.binding["initial_cash"])
    asts = {
        content_fingerprint(t.h.draft["formula_ast"]): "candidate",
        **{
            content_fingerprint(item["formula_binding"]["formula_ast"]): label
            for label, item in t.binding["formula_comparators"].items()
        },
    }
    calls = []

    def replay(**kwargs):
        calls.append(kwargs)
        label = asts.get(
            content_fingerprint(kwargs["draft"]["formula_ast"]), "frozen_baseline"
        )
        curve = (
            t.curves["candidate"]
            if label == "candidate"
            else t.curves["comparators"][label]
        )
        result = BacktestResult(
            equity_curve=[
                (datetime.fromisoformat(day), Decimal(value)) for day, value in curve
            ],
            positions={},
            initial_cash=cash,
            final_equity=Decimal(curve[-1][1]),
            fills=[],
            execution_timing={
                "evaluation_start": "2026-01-17",
                "warmup_basis": "strategy_history_only_fresh_book",
                "warmup_final_bar_targets": True,
            },
        )
        result.dataset_snapshot = t.h.full_snapshot
        result.portfolio_observations = []
        return result

    t.h.adapter.run_sealed = replay
    all_days = [f"2026-01-{i:02}" for i in range(1, 17)] + t.days
    monkeypatch.setattr(
        "server.services.market.market_universe_automation.verified_trading_dates",
        lambda *_a, **_k: all_days,
    )
    monkeypatch.setattr(owner, "_next_verified_session_opens", lambda *_a: {})
    monkeypatch.setattr(
        owner,
        "_reserved_execution_costs",
        lambda *_a: SimpleNamespace(commission_calc=object()),
    )
    monkeypatch.setattr(
        "server.services.research.datasets.resolve_deployment_evaluation_dataset",
        lambda *_a, **_k: {"status": "ready", "dataset_snapshot": t.h.full_snapshot},
    )
    monkeypatch.setattr(
        "server.services.research.research_paper_books.verify_reserved_forward_book",
        lambda *_a, **_k: {
            "session_equity": [
                {"session": day[:10], "equity": value}
                for day, value in t.curves["candidate"]
            ]
        },
    )

    def assessment(**kwargs):
        result = {
            "status": kwargs["uncertainty"]["status"],
            "uncertainty": kwargs["uncertainty"],
            "deployment_scope_fingerprint": t.binding["deployment_scope"][
                "deployment_scope_fingerprint"
            ],
            "risk_limits": t.sim["risk_limits"],
            "blockers": [],
            "return_basis": "synthetic-after-cost",
            "corporate_action_coverage": "synthetic",
            "membership_sessions": t.days,
        }
        return {**result, "evidence_fingerprint": content_fingerprint(result)}

    monkeypatch.setattr(owner, "_deployment_assessment", assessment)
    finished = []
    monkeypatch.setattr(
        t.h.store, "finish_sealed_test", lambda *a, **kw: finished.append(kw)
    )
    t.binding["error_budget"] = {"synthetic_preconsumed_attempt": 1}
    evidence = await owner._evaluate_claimed_champion(
        research_store=t.h.store,
        source=t.h.source,
        adapter=t.h.adapter,
        now=datetime(2026, 3, 19, tzinfo=timezone.utc),
        calendar_db=t.h.db,
        row={
            "sealed_test_id": t.reserved["sealed_test_id"],
            "evidence": {"reservation": t.binding},
        },
        lease=None,
        lease_clock=lambda: datetime.now(timezone.utc),
        require_current=lambda: None,
    )
    assert len(calls) == 12
    assert finished[-1]["status"] == "completed"
    assert (
        evidence["sealed_evaluation"]["benchmark_role"]
        == "frozen_primary_comparator:Gen7"
    )
    assert final_research_evaluation_blocker(evidence) is None
    assert (
        next(
            row
            for row in evidence["formula_comparator_results"]
            if row["label"] == "MA"
        )["sealed_return"]
        > evidence["sealed_evaluation"]["sealed_return"]
    )
    forged = deepcopy(evidence)
    forged["deployment_assessment"]["uncertainty"]["comparisons"].pop()
    forged["evidence_fingerprint"] = content_fingerprint(
        {k: v for k, v in forged.items() if k != "evidence_fingerprint"}
    )
    assert final_research_evaluation_blocker(forged) == "deployment_uncertainty_drift"
    for kind in ("baseline", "simple", "formula"):
        contradicted = deepcopy(evidence)
        if kind == "baseline":
            contradicted["baseline_sealed_return"] = 0.0
        elif kind == "simple":
            contradicted["challenger_results"][0]["sealed_return"] = 0.0
        else:
            next(
                item
                for item in contradicted["formula_comparator_results"]
                if item["label"] == "MA"
            )["sealed_return"] = 0.0
        contradicted["evidence_fingerprint"] = content_fingerprint(
            {k: v for k, v in contradicted.items() if k != "evidence_fingerprint"}
        )
        assert (
            final_research_evaluation_blocker(contradicted)
            == "independent_final_comparator_return_drift"
        )

    # The public read consumer first verifies immutable lineage/account proof;
    # stub those independent owners here and test its actual policy selection.
    grant = deepcopy(t.sim)
    for label, value in grant["statistical_policy"]["comparator_bindings"].items():
        value["identity_fingerprint"] = "sha256:" + content_fingerprint(
            {"reviewed_fee_source": label}
        )
    grant["statistical_policy_fingerprint"] = content_fingerprint(
        grant["statistical_policy"]
    )
    result = {
        "id": 999,
        "config_json": {
            "params": {"entry_board_policy": t.binding["entry_board_policy"]}
        },
        "metrics_json": {
            "independent_evaluation": evidence,
            "entry_board_policy": t.binding["entry_board_policy"],
            "formula_binding": {"formula_ast": t.h.draft["formula_ast"]},
            "simulation_account_replay": {
                "evidence_fingerprint": "verified-reviewed-proof"
            },
        },
    }
    original_reader = t.h.store.research_backtest_result
    monkeypatch.setattr(
        t.h.store,
        "research_backtest_result",
        lambda identity: result if identity == 999 else original_reader(identity),
    )
    monkeypatch.setattr(
        "server.persistence.strategy_research.StrategyResearchAuditStore",
        lambda *_a: t.h.store,
    )
    monkeypatch.setattr(
        "server.contracts.recommendation_publication.read_publication_grant",
        lambda _db: grant,
    )
    monkeypatch.setattr(
        owner, "verify_persisted_final_evaluation", lambda **_kw: evidence
    )
    monkeypatch.setattr(
        t.h.store,
        "get_sealed_test",
        lambda *_a: {"evidence_fingerprint": evidence["evidence_fingerprint"]},
    )
    monkeypatch.setattr(
        owner,
        "_verify_simulation_account_applicability",
        lambda *_a: evidence["deployment_assessment"],
    )
    verified = owner.verify_deployment_validation(t.h.db, result_id=999)
    assert verified["status"] == "pass"
    assert (
        verified["statistical_policy_fingerprint"]
        == grant["statistical_policy_fingerprint"]
    )
    assert (
        evidence["deployment_assessment"]["uncertainty"]["policy_fingerprint"]
        == t.sim["statistical_policy_fingerprint"]
    )
    assert len(calls) == 12  # verification never starts another replay
