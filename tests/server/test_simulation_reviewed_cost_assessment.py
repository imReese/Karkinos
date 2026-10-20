"""Real reviewed costs/CAS and atomic qualification; short calculation interval.

These four prospective sessions test the derived applicability calculation and
its immutable qualification boundary. They deliberately do not claim to satisfy
the production minimum of 60 independent sessions or a full final evaluation.
"""

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.dataset_snapshot import build_backtest_dataset_snapshot
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership
from data.dataset.reader import read_daily_bar_dataset
from data.providers.tushare_corporate_actions import (
    collect_tushare_dividend_observation,
)
from data.storage.objects import ContentAddressedObjectStore
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.http.strategy_models import BacktestRequest
from server.services.ai_shadow.ai_shadow_research_commands import (
    simulation_validation_defaults,
)
from server.services.ai_shadow.ai_shadow_research_support import (
    shadow_research_backtest_source_fingerprint,
)
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
    normalize_a_share_members,
)
from server.services.research.dataset_inputs import load_dataset_backtest_inputs
from server.services.research_final_evaluation import (
    _simulation_reviewed_assessment,
    _verify_simulation_account_applicability,
    build_simulation_account_replay,
)
from server.services.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReviewRepository,
    build_reviewed_fee_schedule_preview,
    freeze_deployment_fee_schedule,
    resolve_reviewed_fee_schedule,
)
from tests.server.test_ai_shadow_research_qualification_persistence import (
    _atomic_candidate_args,
    _backtest_values,
    _run_args,
    _seed_source,
    _selection,
)
from tests.server.test_research_final_evaluation import (
    FREEZE,
    _seed_trial,
    harness,  # noqa: F401
)
from tests.server.test_reviewed_fee_schedule import _patch_ready_account_truth, _state
from tests.server.test_verified_interval_dataset import _verified_day

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def _snapshots(h, scope):
    root = h.db.path.parent / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    daily, memberships = [], []
    for number in range(1, 21):
        day = date(2026, 1, number)
        close = str(Decimal(20) + Decimal(max(0, number - 16)) / 10)
        row = read_daily_bar_dataset(objects, _verified_day(root, day, close=close))
        daily.append(row)
        at = row.snapshot.cutoff
        refs = ()
        if number >= 16:
            master = h.data.save_market_universe_snapshot(
                trade_date=day.isoformat(),
                provider_name="synthetic_fixture",
                members=normalize_a_share_members(["600000"]),
                capture_started_at=at - timedelta(seconds=1),
                capture_completed_at=at,
                source_metadata=[
                    {
                        "symbol": "600000",
                        "display_name": "合成普通股",
                        "list_date": "20200101",
                        "list_status": "L",
                    }
                ],
            )
            refs = (bind_stock_master_observation(objects, master),)
        memberships.append(
            DailyBarDatasetMembership(
                day,
                row.snapshot.instruments,
                at,
                refs,
                at + timedelta(minutes=1) if refs else None,
            )
        )
    snapshots = []
    for count in (16, 20):
        cutoff = daily[count - 1].snapshot.cutoff + timedelta(minutes=2)
        action = collect_tushare_dividend_observation(
            objects,
            instrument=daily[0].snapshot.instruments[0],
            client=SimpleNamespace(dividend=lambda **_: pd.DataFrame()),
            clock=lambda: cutoff,
        )
        snapshot = replace(
            daily[count - 1].snapshot,
            start_date=date(2026, 1, 1),
            cutoff=cutoff,
            partitions=tuple(
                replace(part, instruments=row.snapshot.instruments)
                for row in daily[:count]
                for part in row.snapshot.partitions
            ),
            session_memberships=tuple(memberships[:count]),
            universe_policy_id=scope["deployment_scope_fingerprint"],
            corporate_action_observation_ids=(action.object_id,),
        )
        ref = publish_daily_bar_dataset_manifest(objects, snapshot)
        DatasetCatalog(root).register(objects, ref)
        _, handlers, binding = load_dataset_backtest_inputs(
            root,
            BacktestRequest(
                dataset_id=ref.dataset_id,
                start_date="2026-01-01",
                end_date=f"2026-01-{count}",
            ),
        )
        snapshots.append(
            build_backtest_dataset_snapshot(
                start_date="2026-01-01",
                end_date=f"2026-01-{count}",
                configured_source=binding["source_names"][0],
                data_handlers=handlers,
                store=None,
                source_names=binding["source_names"],
                research_dataset_binding=binding,
            )
        )
    return snapshots


@pytest.fixture
def reviewed_replay(harness, monkeypatch):
    h = harness
    # A real reconciled 4bp commission, one bp above the SIM default. All
    # prospective orders remain inside the reviewed 25,000 notional envelope.
    trades = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,600000.SH,synthetic stock,stock,CNY,2500,10.00,25000.00,10.00,0.00,-25010.25,74989.75,2500,10.01,synthetic buy,0.25,broker_remaining_cost
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,600000.SH,synthetic stock,stock,CNY,2500,10.00,25000.00,10.00,12.50,24977.25,99967.00,0,0,synthetic sell,0.25,broker_remaining_cost
"""
    state, imported = _state(h.db.path.parent, broker_trades=trades)
    state.config.broker_fee_schedule = replace(
        state.config.broker_fee_schedule, stock_a_commission_rate=Decimal("0.0004")
    )
    _patch_ready_account_truth(monkeypatch, imported)
    preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2026-01-01",
        effective_end_date="2026-12-31",
        reviewed_asset_classes=["stock"],
    )
    assert preview["status"] == "ready"
    repository = ReviewedFeeScheduleReviewRepository(h.db.path)
    review = repository.record_review(
        preview=preview,
        expected_preview_fingerprint=preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    h.snapshot, h.full_snapshot = _snapshots(h, scope)
    h.selection = replace(
        h.selection,
        dataset_snapshot_id=h.snapshot["snapshot_id"],
        deployment_scope=scope,
        portfolio_policy_id=scope["portfolio_policy_id"],
    )
    candidate, draft = _seed_trial(h, suffix="derived-cost", selection=h.selection)
    entry = {
        "op": "gt",
        "left": {"op": "field", "name": "close"},
        "right": {"op": "constant", "value": 0},
    }
    exit_ = {**entry, "op": "lt"}
    draft["formula_ast"].update(entry=entry, exit=exit_)
    baseline = deepcopy(draft["formula_ast"])
    baseline["entry"] = exit_
    with sqlite3.connect(h.db.path) as conn:
        conn.execute(
            "UPDATE ai_strategy_hypothesis_drafts SET contract_json=? WHERE draft_id=?",
            (json.dumps(draft), candidate["draft_id"]),
        )
    sim = simulation_validation_defaults(datetime.fromisoformat(FREEZE))
    # Explicit short calculation profile; production policy remains >=60.
    sim["statistical_policy"].update(
        minimum_observations=4,
        block_length=1,
        minimum_effective_blocks=4,
        bootstrap_samples=2000,
    )
    grant = {
        "grant_id": "synthetic-own-publication",
        "generation": "generation-1",
        "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
        "account_scope_fingerprint": review.account_truth_scope_fingerprint,
        "statistical_policy": sim["statistical_policy"],
        "statistical_policy_fingerprint": content_fingerprint(
            sim["statistical_policy"]
        ),
        "max_initial_cash": "80000",
        "risk_limits": sim["risk_limits"],
    }
    fee = freeze_deployment_fee_schedule(
        partial(resolve_reviewed_fee_schedule, state), h.selection, "2026-01-20", grant
    )
    binding = {
        "simulation_policy": sim,
        "deployment_scope": scope,
        "initial_cash": "80000",
        "research_identity": {"start_date": h.selection.start_date},
        "partition": {"sealed_start": "2026-01-17", "sealed_end": "2026-01-20"},
        "session_id": candidate["session_id"],
        "draft_id": candidate["draft_id"],
        "universe": ["600000"],
        "research_snapshot": h.snapshot,
        "entry_board_policy": sim["entry_board_policy"],
        "baseline_formula_ast": baseline,
        "challenger_family": [{"label": "challenger", "formula_ast": baseline}],
        "code_binding": {"fingerprint": "unit-calculation-owner"},
        "frozen_at": FREEZE,
        "effective_checkpoint": "2026-01-20",
    }
    monkeypatch.setattr(
        "server.services.market_universe_automation.verified_trading_dates",
        lambda _db, *, start_date, end_date, **_: [
            f"2026-01-{i:02}"
            for i in range(1, 32)
            if start_date <= f"2026-01-{i:02}" <= end_date
        ],
    )
    original = RestrictedFormulaBacktestAdapter(data_store=h.data).run_sealed(
        selection=h.selection,
        draft=draft,
        sealed_end_date="2026-01-20",
        expected_dataset_snapshot=h.snapshot,
        evaluation_dataset_snapshot=h.full_snapshot,
        expected_trading_dates=[f"2026-01-{i:02}" for i in range(1, 21)],
        initial_cash_override=Decimal(80000),
        entry_board_policy=sim["entry_board_policy"],
    )
    assert original.fills
    curve = [[ts.isoformat(), str(value)] for ts, value in original.equity_curve]
    evidence = {
        "sealed_test_id": "unit-cost-assessment-only",
        "evidence_fingerprint": "original-unit-final-identity",
        "reservation": binding,
        "sealed_dataset_snapshot": h.full_snapshot,
        "deployment_assessment": {
            "risk_limits": sim["risk_limits"],
            "membership_sessions": [f"2026-01-{i:02}" for i in range(17, 21)],
        },
        "session_curves": {
            "candidate": curve,
            "comparators": {"frozen_baseline": curve, "challenger": curve},
        },
        "economic_return_accounting": original.cash_dividend_accounting,
        "comparator_accounting": {
            "frozen_baseline": original.cash_dividend_accounting,
            "challenger": original.cash_dividend_accounting,
        },
        "portfolio_observations": original.portfolio_observations,
    }
    result = {
        "initial_cash": "80000",
        "metrics_json": {
            "formula_fingerprint": "sha256:" + content_fingerprint(draft),
            "fee_component_evidence": {"fee_schedule_binding": fee["fee_evidence"]},
            "cost_assumptions": {
                "commission_model_reference": fee["cost_model_reference"]
            },
        },
    }
    calls, real_run = [], RestrictedFormulaBacktestAdapter.run_sealed

    def counted(self, **kwargs):
        calls.append(kwargs)
        return real_run(self, **kwargs)

    monkeypatch.setattr(RestrictedFormulaBacktestAdapter, "run_sealed", counted)
    proof = build_simulation_account_replay(
        h.db, h.store, result, evidence, grant, data_store=h.data
    )
    result["metrics_json"]["simulation_account_replay"] = proof
    shadow, source = _seed_source(h.db.path.parent)
    binding["candidate_id"] = source["candidate_id"]
    # Source identity is part of the original unit reservation, before sealing
    # the derived artifact. No persisted qualification row is modified later.
    proof["reservation_fingerprint"] = content_fingerprint(binding)
    proof.pop("evidence_fingerprint")
    proof["evidence_fingerprint"] = content_fingerprint(proof)
    run, _ = shadow.create_or_get_qualification_run(
        **{
            **_run_args(),
            "initial_cash_text": "80000",
            "reviewed_cost_model_reference": fee["cost_model_reference"],
            "reviewed_fee_schedule_fingerprint": review.review_fingerprint,
        }
    )
    values = {
        **_backtest_values(),
        "initial_cash": 80000,
        "metrics_json": json.dumps(result["metrics_json"]),
    }
    qualified = shadow.save_qualification_candidate_with_backtest(
        **_atomic_candidate_args(run, source),
        backtest_values=values,
        candidate_evidence_builder=lambda row: (
            {
                "research_capital_mode": "account_bound",
                "candidate_source_fingerprint": shadow_research_backtest_source_fingerprint(
                    row
                ),
                "account_qualification_status": "passed",
            },
            "qualified",
            "paper_shadow_review",
        ),
    )
    result = h.store.research_backtest_result(qualified["candidate_result_id"])

    def finish(winner=qualified):
        return shadow.finish_qualification_run(
            run["qualification_run_id"],
            status="completed",
            selection=_selection(
                run=run, winner_id=winner["qualification_candidate_id"]
            ),
            blockers=[],
            failure_code=None,
            now="2026-09-01T08:03:00+00:00",
        )

    return SimpleNamespace(
        h=h,
        result=result,
        evidence=evidence,
        grant=grant,
        proof=proof,
        shadow=shadow,
        run=run,
        qualified=qualified,
        source=source,
        finish=finish,
        calls=calls,
        review=review,
        repository=repository,
        values=values,
    )


def test_changed_reviewed_fee_replays_once_then_requires_completed_atomic_winner(
    reviewed_replay,
):
    t = reviewed_replay
    assessed = t.proof["reviewed_replay"]["deployment_assessment"]
    assert assessed["status"] == "pass", assessed["blockers"]
    assert (
        t.proof["reviewed_replay"]["session_curves"]["candidate"]
        != t.evidence["session_curves"]["candidate"]
    )
    assert len(t.calls) == 3
    with pytest.raises(ValueError, match="qualification_binding_drift"):
        _verify_simulation_account_applicability(
            t.h.db, t.h.store, t.result, t.evidence, t.grant
        )
    t.finish()
    for _ in range(2):
        assert (
            _verify_simulation_account_applicability(
                t.h.db, t.h.store, t.result, t.evidence, t.grant
            )
            == assessed
        )
    assert len(t.calls) == 3


def test_self_rehashed_metrics_do_not_replace_atomic_qualification_comparison(
    reviewed_replay,
):
    t = reviewed_replay
    t.finish()
    metrics = json.loads(t.result["metrics_json"])
    proof = metrics["simulation_account_replay"]
    proof["reviewed_replay"]["session_curves"]["candidate"][-1][1] = "99999999"
    proof.pop("evidence_fingerprint")
    proof["evidence_fingerprint"] = content_fingerprint(proof)
    with sqlite3.connect(t.h.db.path) as conn:
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=?",
            (json.dumps(metrics), t.result["id"]),
        )
    changed = t.h.store.research_backtest_result(t.result["id"])
    with pytest.raises(ValueError, match="qualification_binding_drift"):
        _verify_simulation_account_applicability(
            t.h.db, t.h.store, changed, t.evidence, t.grant
        )
    with pytest.raises(ValueError, match="qualification_binding_missing"):
        _verify_simulation_account_applicability(
            t.h.db, t.h.store, {**t.result, "id": 999999}, t.evidence, t.grant
        )


@pytest.mark.parametrize(
    "change,code",
    [
        ("cash", "capital_mismatch"),
        ("expiry", "reviewed_cost_scope_mismatch"),
        ("revoke_fee", "frozen_fee_review_changed"),
    ],
)
def test_reviewed_cost_binding_changes_fail_closed(reviewed_replay, change, code):
    t = reviewed_replay
    t.finish()
    result, grant = deepcopy(t.result), deepcopy(t.grant)
    if change == "cash":
        result["initial_cash"] = "80001"
    elif change == "expiry":
        metrics = json.loads(result["metrics_json"])
        metrics["fee_component_evidence"]["fee_schedule_binding"][
            "effective_end_date"
        ] = "2026-01-19"
        result["metrics_json"] = json.dumps(metrics)
    else:
        t.repository.revoke_latest(
            expected_review_id=t.review.review_id,
            expected_review_fingerprint=t.review.review_fingerprint,
            reviewer="synthetic_owner",
            confirmation=REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
        )
    with pytest.raises(ValueError, match=code):
        _verify_simulation_account_applicability(
            t.h.db, t.h.store, result, t.evidence, grant
        )
    assert len(t.calls) == 3


def test_compatible_new_grant_reuses_completed_cost_artifact_without_authority_inheritance(
    reviewed_replay,
):
    from server.contracts.recommendation_publication import read_publication_grant
    from tests.server.test_recommendation_publication import _grant

    t = reviewed_replay
    t.finish()
    fresh = _grant(
        **{
            **t.grant,
            "grant_id": "f13ce1c1-8bee-4899-a1f7-f000ef96442e",
            "generation": "f13ce1c1-8bee-4899-a1f7-f000ef96442f",
            "cooldown_days": 2,
            "expires_at": "2099-12-31T00:00:00+00:00",
        }
    )
    fresh["statistical_policy"] = {
        **fresh["statistical_policy"],
        "decision_checkpoint": "2028-01-01",
    }
    fresh["statistical_policy_fingerprint"] = content_fingerprint(
        fresh["statistical_policy"]
    )
    previous = {
        **fresh,
        "generation": "f13ce1c1-8bee-4899-a1f7-f000ef964420",
        "expires_at": "2026-01-01T00:00:00+00:00",
    }
    t.shadow.configure_publication_grant(
        policy=previous, expected_generation=None, now="2026-01-01T00:00:00+00:00"
    )
    with pytest.raises(ValueError, match="publication_grant_expired"):
        read_publication_grant(t.h.db)
    t.shadow.configure_publication_grant(
        policy=fresh,
        expected_generation=previous["generation"],
        now="2026-10-16T00:00:00+00:00",
    )
    current = read_publication_grant(t.h.db)
    assessed = _verify_simulation_account_applicability(
        t.h.db, t.h.store, t.result, t.evidence, current
    )
    assert assessed["status"] == "pass"
    assert (
        assessed["statistical_policy_fingerprint"]
        == fresh["statistical_policy_fingerprint"]
    )
    assert len(t.calls) == 3
    # Revocation and expiry are checked by the real current authority reader,
    # before canonical deployment verification can consume the historical proof.
    for patch, code in [
        ({"enabled": False}, "publication_grant_disabled"),
        ({"expires_at": "2026-01-01T00:00:00+00:00"}, "publication_grant_expired"),
    ]:
        t.shadow.configure_publication_grant(
            policy={**fresh, **patch},
            expected_generation=fresh["generation"],
            now="2026-10-16T00:00:00+00:00",
        )
        with pytest.raises(ValueError, match=code):
            read_publication_grant(t.h.db)


def test_derived_assessment_rechecks_samples_and_actual_account_risk(reviewed_replay):
    t = reviewed_replay
    for change, expected in [
        ("samples", "deployment_independent_sample_insufficient"),
        ("risk", "deployment_risk_exceeds_grant"),
    ]:
        grant = deepcopy(t.grant)
        if change == "samples":
            grant["statistical_policy"]["minimum_observations"] = 60
        else:
            grant["risk_limits"]["max_symbol_weight"] = "0.01"
        assessment = _simulation_reviewed_assessment(
            t.h.db, t.evidence, grant, t.proof["reviewed_replay"]
        )
        assert assessment["status"] == "insufficient_evidence"
        assert expected in assessment["blockers"]
    assert len(t.calls) == 3


def test_independent_simulation_and_completed_qualification_never_supply_own_grant(
    reviewed_replay,
):
    from server.services.research_final_evaluation import verify_deployment_validation

    t = reviewed_replay
    t.finish()
    metrics = json.loads(t.result["metrics_json"])
    metrics["independent_evaluation"] = t.evidence
    with sqlite3.connect(t.h.db.path) as conn:
        conn.execute(
            "UPDATE backtest_results SET metrics_json=? WHERE id=?",
            (json.dumps(metrics), t.result["id"]),
        )
    assert t.h.db.get_automation_policy_sync("ai_recommendation_publication") is None
    with pytest.raises(ValueError, match="publication_grant_missing"):
        verify_deployment_validation(t.h.db, result_id=t.result["id"])


def test_frozen_simulation_cash_is_exact_and_requires_available_account_equity():
    from server.services.ai_shadow.ai_shadow_research_qualification_support import (
        qualification_initial_cash,
    )

    assert qualification_initial_cash(
        Decimal(1000000), frozen_simulation_cash=Decimal(123456)
    ) == Decimal(123456)
    with pytest.raises(ValueError, match="simulation_capital_unavailable"):
        qualification_initial_cash(
            Decimal(123455), frozen_simulation_cash=Decimal(123456)
        )
    assert qualification_initial_cash(Decimal(2000000)) == Decimal(1000000)


def test_public_summary_distinguishes_reviewed_cost_gate_and_original_simulation(
    reviewed_replay,
):
    from analytics.strategy_advancement_gate import strategy_advancement_backtest_view
    from server.contracts.ai_shadow_research_qualification import (
        public_qualification_candidate_projection,
    )

    t = reviewed_replay
    metrics = json.loads(t.result["metrics_json"])
    metrics["independent_evaluation"] = deepcopy(t.evidence)
    metrics["independent_evaluation"]["deployment_assessment"].update(
        status="pass", blockers=[]
    )
    for status, blockers in [
        ("pass", []),
        ("insufficient_evidence", ["deployment_net_excess_not_established"]),
    ]:
        metrics["simulation_account_replay"]["reviewed_replay"][
            "deployment_assessment"
        ].update(status=status, blockers=blockers)
        view = strategy_advancement_backtest_view({**t.result, "metrics_json": metrics})
        projected = public_qualification_candidate_projection(
            {**t.qualified, "comparison": {"candidate": view}}
        )
        assert projected["deployment_validation"]["status"] == status
        assert projected["deployment_validation"]["blockers"] == blockers
        assert (
            projected["deployment_validation"]["fee_cost_model_reference"]
            == t.proof["cost_model_reference"]
        )
        assert projected["original_simulation_validation"]["status"] == "pass"
        assert projected["original_simulation_validation"]["modeled_costs"] is True
        assert (
            projected["original_simulation_validation"]["fee_cost_model_reference"]
            != t.proof["cost_model_reference"]
        )
        assert projected["deployment_validation"]["initial_cash"] is None
        assert "80000" not in json.dumps(projected)
        assert "session_curves" not in json.dumps(projected)


def test_completed_nonwinner_qualification_cannot_supply_reviewed_curves(
    reviewed_replay,
):
    t = reviewed_replay
    source = t.shadow.save_candidate(
        **{
            key: t.source[key]
            for key in (
                "run_id",
                "session_id",
                "backtest_run_id",
                "critique_id",
                "baseline_result_id",
                "candidate_result_id",
                "status",
                "recommendation",
                "comparison",
            )
        },
        draft_id="second-source-draft",
        now="2026-08-31T08:01:00+00:00",
    )
    winner = t.shadow.save_qualification_candidate_with_backtest(
        **{**_atomic_candidate_args(t.run, source), "rank": 2},
        backtest_values=t.values,
        candidate_evidence_builder=lambda row: (
            {
                "research_capital_mode": "account_bound",
                "candidate_source_fingerprint": shadow_research_backtest_source_fingerprint(
                    row
                ),
                "account_qualification_status": "passed",
            },
            "qualified",
            "paper_shadow_review",
        ),
    )
    t.finish(winner)
    with pytest.raises(ValueError, match="qualification_binding_drift"):
        _verify_simulation_account_applicability(
            t.h.db, t.h.store, t.result, t.evidence, t.grant
        )
