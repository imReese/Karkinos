"""Real deterministic final evidence is consumed by a bounded publication grant.

Synthetic prices are fixed before reservation; no market/account runtime is read.
Provider capture, SQLite/CAS, portfolio replays and the final verifier are real.
Only the external Account Truth readiness and valuation clock use test fixtures.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from types import SimpleNamespace

import pytest

from analytics.dataset_snapshot import (
    build_backtest_dataset_snapshot,
    load_immutable_dataset_inputs,
)
from analytics.strategy_advancement_gate import (
    strategy_advancement_backtest_view,
)
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
)
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
    build_dual_ma_research_strategy,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.strategy_research import StrategyResearchSelection
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.backtest_results import insert_backtest_result
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.account.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    ReviewedFeeScheduleReviewRepository,
    build_reviewed_fee_schedule_preview,
    resolve_reviewed_fee_schedule,
)
from server.services.account.valuation_snapshot import (
    build_current_valuation_snapshot,
    portfolio_equity_from_valuation,
)
from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.ai_shadow.ai_shadow_research_qualification_support import (
    formula_binding,
    qualification_backtest_values,
)
from server.services.research.research_final_evaluation import (
    reserve_final_research_evaluation,
)
from tests.server.test_recommendation_publication import _grant
from tests.server.test_reviewed_fee_schedule import _patch_ready_account_truth, _state

pytestmark = pytest.mark.product_smoke


def _report(data, ref):
    instruments, handlers, binding = load_immutable_dataset_inputs(
        data["root"], {"immutable_dataset_id": ref.dataset_id}
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date=min(
            h._df["timestamp"].min().date() for h in handlers.values()
        ).isoformat(),
        end_date=max(
            h._df["timestamp"].max().date() for h in handlers.values()
        ).isoformat(),
        configured_source=binding["source_names"][0],
        data_handlers=handlers,
        store=data["data_store"],
        source_names=binding["source_names"],
        research_dataset_binding=binding,
    )
    return snapshot


def _draft(selection, *, ordinal=1, formula=None):
    smooth = {
        "op": "rolling_mean",
        "input": {"op": "field", "name": "close"},
        "window": 3,
    }
    ast = formula or {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "lte",
            "left": smooth,
            "right": {"op": "constant", "value": 10.25},
        },
        "exit": {
            "op": "gte",
            "left": smooth,
            "right": {"op": "constant", "value": 10.75},
        },
        "position_size": {"op": "equal_weight"},
    }
    draft = {
        "draft_id": f"pipeline-draft-{ordinal}",
        "formula_ast": ast,
        "economic_hypothesis": "Deterministic predeclared synthetic mean reversion.",
        "risk_impact": "Shared capital and modeled fills can lose value.",
        "failure_conditions": ["Independent net advantage is insufficient."],
        "limitations": ["Synthetic fixture only; no investment claim."],
        "anti_lookahead_assumptions": ["Only completed session observations."],
        "parameter_values": {"signal_window": 3},
        "parameter_ranges": {"signal_window": [2, 3, 4]},
        "selected_universe": list(selection.universe),
        "dataset_snapshot_id": selection.dataset_snapshot_id,
        "test_window": {
            "start_date": selection.start_date,
            "end_date": selection.end_date,
        },
        "frequency": "1d",
        "cost_model_reference": selection.cost_model_reference,
        "validation": {"status": "valid", "errors": []},
    }
    if formula is not None:
        draft["parameter_values"], draft["parameter_ranges"] = {}, {}
    draft["formula_fingerprint"] = formula_binding(selection, draft).fingerprint
    return draft


def _save_result(db, result, request, at):
    values = qualification_backtest_values(request, result)
    with sqlite3.connect(db.path) as conn:
        return insert_backtest_result(conn, created_at=at, **values)


def _seed_source_rows(db, research, store, selection, result, request, at):
    from server.services.ai_shadow.ai_shadow_research_support import (
        shadow_research_backtest_source_fingerprint,
    )

    run, _ = store.claim_run(
        market_date=selection.end_date,
        input_fingerprint=content_fingerprint(
            {
                "fixture": "pipeline",
                "entry_board_policy": result["metrics_json"]["entry_board_policy"],
            }
        ),
        baseline_seed_result_id=selection.saved_backtest_result_id,
        research_capital_mode="normalized_notional",
        research_context_id="normalized-notional:fixture",
        valuation_snapshot_id=None,
        ledger_cutoff_id=0,
        now=at,
    )
    candidates, drafts = [], []
    for ordinal in range(1, 6):
        draft = _draft(selection, ordinal=ordinal)
        drafts.append(draft)
        sid, bid, cid = (
            f"pipeline-session-{ordinal}",
            f"pipeline-backtest-{ordinal}",
            f"pipeline-critique-{ordinal}",
        )
        result_id = _save_result(db, result, request, at)
        critique = {
            "summary": "Deterministic fixture critique; no external provider contacted."
        }
        with sqlite3.connect(db.path) as conn:
            conn.execute(
                "INSERT INTO ai_strategy_research_sessions(session_id,idempotency_key,request_fingerprint,request_json,selection_fingerprint,status,prompt_version,created_at,updated_at) VALUES(?,?,?,?,?,'completed','fixture',?,?)",
                (
                    sid,
                    sid,
                    sid,
                    json.dumps({"selection": selection.to_dict()}),
                    selection.fingerprint,
                    at,
                    at,
                ),
            )
            conn.execute(
                "INSERT INTO ai_strategy_hypothesis_drafts(draft_id,session_id,ordinal,contract_json,artifact_fingerprint,formula_fingerprint,validation_status,validation_errors_json,created_at) VALUES(?,?,1,?,?,?,'valid','[]',?)",
                (
                    draft["draft_id"],
                    sid,
                    json.dumps(draft),
                    content_fingerprint(draft),
                    draft["formula_fingerprint"],
                    at,
                ),
            )
            conn.execute(
                "INSERT INTO ai_strategy_formula_backtests(backtest_run_id,idempotency_key,request_fingerprint,session_id,draft_id,formula_fingerprint,dataset_snapshot_id,cost_model_reference,status,canonical_backtest_result_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'completed',?,?,?)",
                (
                    bid,
                    bid,
                    bid,
                    sid,
                    draft["draft_id"],
                    draft["formula_fingerprint"],
                    selection.dataset_snapshot_id,
                    selection.cost_model_reference,
                    result_id,
                    at,
                    at,
                ),
            )
            conn.execute(
                "INSERT INTO ai_strategy_backtest_critiques(critique_id,idempotency_key,request_fingerprint,session_id,draft_id,backtest_run_id,status,normalized_artifact_json,artifact_fingerprint,prompt_version,created_at,updated_at) VALUES(?,?,?,?,?,?,'completed',?,?,'fixture',?,?)",
                (
                    cid,
                    cid,
                    cid,
                    sid,
                    draft["draft_id"],
                    bid,
                    json.dumps(critique),
                    content_fingerprint(critique),
                    at,
                    at,
                ),
            )
        candidate = store.save_candidate(
            run_id=run["run_id"],
            session_id=sid,
            draft_id=draft["draft_id"],
            backtest_run_id=bid,
            critique_id=cid,
            baseline_result_id=selection.saved_backtest_result_id,
            candidate_result_id=result_id,
            status="evaluated_research_only",
            recommendation="formula_research_candidate",
            comparison={
                "research_capital_mode": "normalized_notional",
                "account_qualification_status": "not_evaluated",
                "baseline_source_fingerprint": shadow_research_backtest_source_fingerprint(
                    research.research_backtest_result(
                        selection.saved_backtest_result_id
                    )
                ),
                "candidate_source_fingerprint": shadow_research_backtest_source_fingerprint(
                    research.research_backtest_result(result_id)
                ),
                "baseline": strategy_advancement_backtest_view(
                    research.research_backtest_result(
                        selection.saved_backtest_result_id
                    )
                ),
                "candidate": strategy_advancement_backtest_view(
                    research.research_backtest_result(result_id)
                ),
                "deepseek_critique": critique,
                "normalized_research_operation_preview": result["metrics_json"][
                    "normalized_research_operation_preview"
                ],
                "iteration_lineage": {
                    "iteration_number": ordinal,
                    "total_iterations": 5,
                    "formula_fingerprint": draft["formula_fingerprint"],
                    "parent_candidate_id": candidates[-1]["candidate_id"]
                    if candidates
                    else None,
                    "parent_draft_id": drafts[-2]["draft_id"] if ordinal > 1 else None,
                    "parent_formula_fingerprint": draft["formula_fingerprint"]
                    if ordinal > 1
                    else None,
                    "iteration_context_fingerprint": content_fingerprint(
                        {"fixture_iteration": ordinal}
                    ),
                    "sequential_feedback_bound": True,
                },
            },
            now=at,
        )
        candidates.append(candidate)
    store.update_run(
        run["run_id"],
        status="completed",
        baseline_result_id=selection.saved_backtest_result_id,
        candidate_count=5,
        now=at,
    )
    artifacts = DailyStrategyArtifactStore(
        db.path, db.path.parent / "strategy-research-backups"
    )
    daily = artifacts.record_daily_artifacts(
        run=run,
        candidates=candidates,
        drafts=drafts,
        expected_candidate_count=5,
        run_status="completed",
        created_at=at,
    )
    return run, candidates, drafts, artifacts, daily


async def _run_real_forward_book(data, reservation, *, source_id, frozen_at, grant):
    import pandas as pd

    from data.dataset.manifest import publish_daily_bar_dataset_manifest
    from data.providers import tushare_corporate_actions as actions
    from server.contracts.http.strategy_models import BacktestCostAssumptions
    from server.contracts.research_observation_automation import (
        reserved_forward_identity,
    )
    from server.services.research.research_observations import (
        ResearchObservationService,
    )
    from server.services.research.research_paper_books import ResearchPaperBookService

    current = [frozen_at]
    db = data["db"]
    observations = ResearchObservationService(db, clock=lambda: current[0])
    key, identity = reserved_forward_identity(reservation["sealed_test_id"], grant)
    await observations.start(
        request_id=key + ":observation",
        source_backtest_result_id=source_id,
        horizon_sessions=1,
        max_symbol_weight=Decimal(grant["risk_limits"]["max_symbol_weight"]),
        max_gross_weight=Decimal(grant["risk_limits"]["max_gross_weight"]),
        forward_dataset_id=data["development_ref"].dataset_id,
        authorization_binding={
            "grant_id": grant["grant_id"],
            "generation": grant["generation"],
            "reservation_id": reservation["sealed_test_id"],
        },
        entry_board_policy=grant["entry_board_policy"],
    )
    paper = ResearchPaperBookService(db, clock=lambda: current[0])
    paper.start(
        identity,
        request_id=key + ":book",
        initial_cash=Decimal("20000"),
        cost_assumptions=BacktestCostAssumptions(),
        fee_schedule_binding=reservation["evidence"]["reservation"]["fee_schedule"],
        health_policy={
            "mode": "pause_on_breach",
            "minimum_settled_sessions": len(data["future_dates"]),
            "maximum_drawdown": grant["risk_limits"]["max_drawdown"],
            "minimum_net_excess_return": "0",
        },
    )
    observed = observations.repository.get(identity)
    observations.advance(
        identity,
        request_id=key + ":initial-target",
        expected_version=observed["version"],
        dataset_id=data["development_ref"].dataset_id,
    )
    snapshot = data["forward_snapshot"]
    for index, day in enumerate(data["future_dates"]):
        current[0] = datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=8, minutes=20)
        captures = tuple(
            actions.collect_tushare_dividend_observation(
                data["objects"],
                instrument=instrument,
                client=SimpleNamespace(
                    dividend=lambda **_: pd.DataFrame(
                        columns=actions.DIVIDEND_FIELDS.split(",")
                    )
                ),
                clock=lambda: current[0],
            ).object_id
            for instrument in data["instruments"]
        )
        prefix = publish_daily_bar_dataset_manifest(
            data["objects"],
            replace(
                snapshot,
                end_date=day,
                cutoff=current[0],
                partitions=tuple(
                    part for part in snapshot.partitions if part.partition_date <= day
                ),
                session_memberships=tuple(
                    member
                    for member in snapshot.session_memberships
                    if member.partition_date <= day
                ),
                corporate_action_observation_ids=captures,
            ),
        )
        book = paper.get(identity)
        settled = paper.settle(
            identity,
            request_id=f"fixture-settle-{day}",
            expected_version=book["version"],
            dataset_id=prefix.dataset_id,
        )
        assert settled["last_settled_session"] == day.isoformat(), settled
        if index < len(data["future_dates"]) - 1:
            observed = observations.repository.get(identity)
            advanced = observations.advance(
                identity,
                request_id=f"fixture-advance-{day}",
                expected_version=observed["version"],
                dataset_id=prefix.dataset_id,
            )
            assert advanced.get("publication_id"), (
                advanced.get("last_blocker") or advanced
            )
    return identity


@pytest.mark.asyncio
async def test_verified_final_qualification_policy_publication_and_revocation(
    tmp_path, monkeypatch
):
    from tests.server.deployment_pipeline_fixtures import build_real_scope_datasets

    data = build_real_scope_datasets(tmp_path)
    db = data["db"]
    state, imported = _state(tmp_path)
    _patch_ready_account_truth(monkeypatch, imported)
    fee_preview = build_reviewed_fee_schedule_preview(
        state,
        effective_start_date="2025-01-01",
        effective_end_date="2026-12-31",
        reviewed_asset_classes=["stock"],
    )
    assert fee_preview["status"] == "ready", fee_preview
    review = ReviewedFeeScheduleReviewRepository(db.path).record_review(
        preview=fee_preview,
        expected_preview_fingerprint=fee_preview["preview_fingerprint"],
        reviewer="synthetic_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    )
    fees = partial(resolve_reviewed_fee_schedule, state)
    research = StrategyResearchAuditStore(db.path)
    research.init()
    store = ShadowResearchStore(db.path)
    store.init()
    snapshot = _report(data, data["development_ref"])
    final_day = data["future_dates"][-1]
    frozen_at = datetime.combine(
        data["development_dates"][-1], datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=10)
    mature = datetime.combine(
        final_day, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=10)
    clock = lambda: mature
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp=frozen_at.isoformat(),
        amount=20000,
        asset_class="cash",
    )
    valuation_clock = [frozen_at]
    monkeypatch.setattr(
        "server.services.account.valuation_snapshot.build_current_valuation_snapshot",
        lambda db, **kwargs: build_current_valuation_snapshot(
            db, persist=kwargs.get("persist", False), now=valuation_clock[0]
        ),
    )
    grant = _grant(
        account_scope_fingerprint=review.account_truth_scope_fingerprint,
        deployment_scope_fingerprint=data["scope"]["deployment_scope_fingerprint"],
        max_initial_cash="20000",
        risk_limits={
            "max_drawdown": "0.2",
            "max_gross_weight": "1",
            "max_symbol_weight": "0.30",
            "max_positions": 4,
        },
    )
    grant["total_error_budget"] = "0.25"
    grant["statistical_policy"].update(
        minimum_observations=15,
        block_length=2,
        minimum_effective_blocks=5,
        bootstrap_samples=1000,
        significance_level="0.20",
        decision_checkpoint=final_day.isoformat(),
    )
    grant["statistical_policy_fingerprint"] = content_fingerprint(
        grant["statistical_policy"]
    )
    store.configure_publication_grant(
        policy=grant, expected_generation=None, now=frozen_at.isoformat()
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=tuple(i.symbol for i in data["instruments"]),
        asset_classes=tuple("stock" for _ in data["instruments"]),
        dataset_snapshot_id=snapshot["snapshot_id"],
        start_date=data["development_dates"][0].isoformat(),
        end_date=data["development_dates"][-1].isoformat(),
        sealed_end_date=final_day.isoformat(),
        frequency="1d",
        initial_cash=1000000,
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
        deployment_scope=data["scope"],
        portfolio_policy_id=data["scope"]["portfolio_policy_id"],
    )
    adapter = RestrictedFormulaBacktestAdapter(
        data_store=data["data_store"], research_root=data["root"]
    )
    baseline_formula = build_dual_ma_research_strategy(
        {"short_period": 5, "long_period": 20}, len(selection.universe)
    )._formula_ast
    baseline_result, baseline_request = adapter.run(
        selection=selection,
        draft=_draft(selection, formula=baseline_formula),
        expected_dataset_snapshot=snapshot,
        entry_board_policy=grant["entry_board_policy"],
    )
    baseline_request = baseline_request.model_copy(
        update={
            "strategy": "dual_ma",
            "params": {
                "short_period": 5,
                "long_period": 20,
                "entry_board_policy": grant["entry_board_policy"],
            },
        }
    )
    baseline_id = _save_result(
        db, baseline_result, baseline_request, frozen_at.isoformat()
    )
    selection = replace(selection, saved_backtest_result_id=baseline_id)
    candidate_result, candidate_request = adapter.run(
        selection=selection,
        draft=_draft(selection),
        expected_dataset_snapshot=snapshot,
        entry_board_policy=grant["entry_board_policy"],
    )
    run, candidates, drafts, artifacts, daily = _seed_source_rows(
        db,
        research,
        store,
        selection,
        candidate_result,
        candidate_request,
        frozen_at.isoformat(),
    )
    daily_selection = daily["selection"]
    winner_id = daily_selection["research_recommendation"][
        "research_winner_candidate_id"
    ]
    assert winner_id, daily_selection["research_recommendation"]
    champion = next(row for row in candidates if row["candidate_id"] == winner_id)
    reservation = await reserve_final_research_evaluation(
        db=db,
        research_store=research,
        run=run,
        selection=selection,
        candidates=candidates,
        daily_selection=daily_selection,
        now=frozen_at.isoformat(),
        reviewed_fee_schedule_resolver=fees,
        account_config=state.config,
    )
    await _run_real_forward_book(
        data,
        reservation,
        source_id=champion["candidate_result_id"],
        frozen_at=frozen_at,
        grant=grant,
    )
    from server.services.research.research_final_evaluation import (
        evaluate_reserved_champion,
    )

    source = SimpleNamespace(
        source_candidate=champion,
        source_selection=selection,
        source_draft=next(
            draft for draft in drafts if draft["draft_id"] == champion["draft_id"]
        ),
    )
    final = await evaluate_reserved_champion(
        research_store=research,
        source=source,
        adapter=adapter,
        now=mature,
        calendar_db=db,
    )
    assert final["deployment_assessment"]["status"] == "pass", final[
        "deployment_assessment"
    ]
    valuation_clock[0] = mature
    valuation = build_current_valuation_snapshot(db, persist=True, now=mature)
    from server.ai_runtime.evidence import (
        CanonicalEvidenceRecord,
        CanonicalEvidenceRepository,
    )
    from server.contracts.recommendation_publication import PUBLICATION_REVOKE
    from server.services.ai_shadow.ai_shadow_research_qualification import (
        AiShadowResearchQualificationService,
    )
    from server.services.decision.recommendation_publication import (
        RecommendationPublicationService,
    )
    from server.services.research.research_final_evaluation import (
        verify_deployment_validation,
    )
    from server.services.research.strategy_promotion_pipeline import (
        resolve_strategy_order_generation_gate,
    )

    account_identity = {
        "valuation_snapshot_id": valuation["snapshot_id"],
        "ledger_cutoff_id": valuation["ledger_cutoff_id"],
        "valuation_status": "complete",
        "total_equity": str(portfolio_equity_from_valuation(db, valuation)),
    }
    record = CanonicalEvidenceRecord.capture(
        tool_name="account_state_projection.read",
        valuation_snapshot_id=valuation["snapshot_id"],
        ledger_cutoff_id=valuation["ledger_cutoff_id"],
        ledger_fingerprint=valuation["ledger_fingerprint"],
        status="complete",
        as_of=mature.isoformat(),
        source_schema_version="fixture.account.v1",
        payload={"summary": dict(account_identity), "snapshot": dict(account_identity)},
        captured_at=mature.isoformat(),
    )
    canonical = CanonicalEvidenceRepository(db.path)
    canonical.init()
    canonical.persist(record)

    class Capture:
        async def capture(self, request, *, write_guard=None):
            if write_guard:
                write_guard()
            return SimpleNamespace(
                context=SimpleNamespace(
                    valuation_snapshot_id=record.valuation_snapshot_id,
                    ledger_cutoff_id=record.ledger_cutoff_id,
                    ledger_fingerprint=record.ledger_fingerprint,
                    persisted_facts_only=True,
                ),
                records=(record,),
            )

    def prepare_account_baseline(
        policy,
        *,
        initial_cash_override,
        reviewed_fee_schedule_resolution,
        entry_board_policy,
        **_,
    ):
        from analytics.research_account_capital_evidence import (
            build_research_account_capital_evidence,
        )
        from server.contracts.ai_shadow_research_automation import PreparedBaseline

        assert entry_board_policy == grant["entry_board_policy"]
        bound = replace(
            selection,
            initial_cash=initial_cash_override,
            cost_model_reference=reviewed_fee_schedule_resolution.cost_model_reference,
            sealed_end_date=None,
            valuation_snapshot_id=valuation["snapshot_id"],
            ledger_cutoff_id=valuation["ledger_cutoff_id"],
        )
        measured, request = adapter.run(
            selection=bound,
            draft=_draft(bound, formula=baseline_formula),
            expected_dataset_snapshot=snapshot,
            reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
            entry_board_policy=entry_board_policy,
            account_capital_evidence=build_research_account_capital_evidence(
                initial_cash=initial_cash_override,
                account_evidence=record.to_dict(),
                fee_schedule_evidence=reviewed_fee_schedule_resolution.fee_evidence,
                expected_valuation_snapshot_id=valuation["snapshot_id"],
                expected_ledger_cutoff_id=valuation["ledger_cutoff_id"],
            ),
        )
        return PreparedBaseline(
            seed_result_id=selection.saved_backtest_result_id,
            market_date=selection.end_date,
            snapshot=snapshot,
            cost_model_reference=bound.cost_model_reference,
            result=measured,
            request=request,
            fee_schedule_evidence=reviewed_fee_schedule_resolution.fee_evidence,
        )

    qualification = AiShadowResearchQualificationService(
        db=db,
        store=store,
        daily_artifact_store=artifacts,
        research_store=research,
        data_store=data["data_store"],
        capture_service=Capture(),
        account_identity_reader=lambda: valuation,
        reviewed_fee_schedule_resolver=fees,
        baseline_preparer=prepare_account_baseline,
        backtest_adapter=adapter,
        now=clock,
    )
    qualified = await qualification.run_once(source_run_id=run["run_id"])
    assert qualified["status"] == "completed", qualified
    winner = qualified["run"]["winner_qualification_candidate_id"]
    assert winner
    candidate = store.get_qualification_candidate(winner)
    verified = verify_deployment_validation(
        db,
        result_id=candidate["candidate_result_id"],
        expected_grant_id=grant["grant_id"],
    )
    assert verified["status"] == "pass", verified
    assert verified["entry_board_policy"] == grant["entry_board_policy"]
    automatic = qualified.get("publication_attempt") or {}
    assert automatic.get("strategy_promotion"), automatic
    automatic_strategy = automatic["strategy_promotion"]
    assert (
        db.get_strategy_promotion_state_sync(automatic_strategy["strategy_id"])
        == automatic_strategy
    )
    publication = RecommendationPublicationService(db, store, now=clock, state=state)
    published = publication.publish(winner)
    assert published["reused"] is True
    assert published["strategy_promotion"] == automatic_strategy
    strategy_id = published["strategy_promotion"]["strategy_id"]
    payload = json.loads(published["strategy_promotion"]["payload_json"])
    assert payload["decision_source"] == "policy"
    assert "human_review" not in payload
    assert store.get_qualification_approval(winner) is None
    gate, blockers = resolve_strategy_order_generation_gate(
        db, strategy_id, as_of_date=final_day.isoformat()
    )
    assert not blockers, blockers
    assert gate["status"] == "pass"
    assert gate["broker_submission_enabled"] is False
    scanner, portfolio_summary, decision_day = _prepare_real_scan_consumer(
        data, state, valuation
    )
    import data.dataset.reader as dataset_reader

    cold_reader = dataset_reader._read_daily_bar_dataset
    cold_reads = []

    def counted_read(objects, ref):
        cold_reads.append((objects.root.resolve(), ref.dataset_id))
        return cold_reader(objects, ref)

    monkeypatch.setattr(dataset_reader, "_read_daily_bar_dataset", counted_read)
    scan = scanner.run_once(
        decision_date=decision_day, portfolio_summary=portfolio_summary
    )
    assert scan["status"] == "completed", scan["blockers"]
    assert scan["raw_signal_count"] == scan["selected_signal_count"] == 4
    assert len(scan["action_tasks"]) == 4
    assert len(cold_reads) == len(set(cold_reads)) == 2
    task_ids = {row["id"] for row in db.get_action_tasks_sync(limit=100)}
    journal_count = len(db.list_signal_journal_sync(limit=100))
    same = scanner.run_once(
        decision_date=decision_day, portfolio_summary=portfolio_summary
    )
    assert same["status"] == "completed"
    assert len(cold_reads) == 4  # A new request reopens both immutable Datasets.
    assert {row["id"] for row in db.get_action_tasks_sync(limit=100)} == task_ids
    assert len(db.list_signal_journal_sync(limit=100)) == journal_count
    from tests.server.test_daily_decision_dataset_read_scope import _compose_reader

    with monkeypatch.context() as cycle_patch:
        read_plan = _compose_reader(
            scanner, state, portfolio_summary, decision_day, cycle_patch
        )
        for index in range(2):
            decision, _ = await read_plan()
            assert decision["summary"]["promoted_strategy_universe_scan"]["status"] == (
                "completed"
            )
            assert len(cold_reads) == 6 + 2 * index
            assert {
                row["id"] for row in db.get_action_tasks_sync(limit=100)
            } == task_ids
            assert len(db.list_signal_journal_sync(limit=100)) == journal_count
    from server.services.decision.daily_decision_preparation import (
        build_daily_candidate_preparation_check,
    )

    for index in range(2):
        preparation = build_daily_candidate_preparation_check(
            state, run_date=decision_day
        )
        assert preparation["passing_strategy_count"] == 1, preparation["blockers"]
        assert len(cold_reads) == 10 + 2 * index
    evaluate = scanner._evaluate_promoted_strategies

    def evaluate_then_revoke(**kwargs):
        measured = evaluate(**kwargs)
        assert len(measured[1]) == 4
        publication.update(
            {
                "enabled": False,
                "expected_generation": grant["generation"],
                "confirmation": PUBLICATION_REVOKE,
                "updated_by": "human:fixture-owner",
            }
        )
        return measured

    monkeypatch.setattr(scanner, "_evaluate_promoted_strategies", evaluate_then_revoke)
    # A stricter cash buffer gives this real re-evaluation a fresh scan identity.
    state.config.min_cash_buffer_ratio = 0.04
    refused = scanner.run_once(
        decision_date=decision_day, portfolio_summary=portfolio_summary
    )
    state.config.min_cash_buffer_ratio = 0.03
    assert refused["status"] == "blocked" and refused["action_tasks"] == []
    assert any(
        reason.startswith("promoted_strategy_scan_authority_changed_before_persist")
        for reason in refused["blockers"]
    )
    revoked, blockers = resolve_strategy_order_generation_gate(
        db, strategy_id, as_of_date=final_day.isoformat()
    )
    assert revoked["status"] == "blocked" and blockers
    assert db.get_strategy_promotion_state_sync(strategy_id)["stage"] == "paper_shadow"
    assert {row["id"] for row in db.get_action_tasks_sync(limit=100)} == task_ids
    assert len(db.list_signal_journal_sync(limit=100)) == journal_count
    assert scanner.current_input_blockers(
        scan=scan, portfolio_summary=portfolio_summary
    )
    preparation = build_daily_candidate_preparation_check(state, run_date=decision_day)
    assert preparation["passing_strategy_count"] == 0


def _prepare_real_scan_consumer(data, state, valuation):
    """Publish actual CAS observations as the scanner's canonical daily receipts."""
    import pandas as pd

    from data.dataset.reader import read_daily_bar_dataset
    from server.services.decision.decision_portfolio_projection import (
        portfolio_state_summary,
    )
    from server.services.portfolio.ledger import rebuild_portfolio_from_ledger
    from server.services.strategy_scan.promoted_strategy_universe_scan import (
        PromotedStrategyUniverseScanService,
    )

    result = read_daily_bar_dataset(data["objects"], data["forward_ref"])
    grouped = {}
    for bar in result.bars:
        grouped.setdefault(bar.session_date, []).append(
            {
                "symbol": bar.instrument.symbol,
                "timestamp": pd.Timestamp(bar.session_date),
                **{
                    name: float(getattr(bar, name))
                    for name in ("open", "high", "low", "close", "volume", "amount")
                },
            }
        )
    for day, rows in sorted(grouped.items()):
        receipt = data["data_store"].ingest_market_daily_batch(
            trade_date=day.isoformat(),
            provider_name="synthetic_fixture",
            bars=pd.DataFrame(rows),
        )
        assert receipt["row_count"] == len(data["instruments"])
    config = state.config
    config.initial_cash, config.assets = 0, []
    config.data_source = "synthetic_fixture"
    config.start_date = data["dates"][0].isoformat()
    config.min_cash_buffer_ratio = 0.03
    reconstructed = rebuild_portfolio_from_ledger(config, data["db"])
    summary = portfolio_state_summary(
        state,
        portfolio_context={
            "portfolio": reconstructed.portfolio,
            "instruments": reconstructed.instruments,
            "valuation_snapshot": valuation,
            "authority": "persisted_valuation_snapshot",
        },
    )
    assert Decimal(str(summary["total_equity"])) == portfolio_equity_from_valuation(
        data["db"], valuation
    )
    decision_day = data["future_dates"][-1] + timedelta(days=1)
    clock = datetime.combine(
        decision_day, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=1, minutes=36)
    scanner = PromotedStrategyUniverseScanService(
        db=data["db"],
        config=config,
        data_store=data["data_store"],
        policy=data["policy"],
        safety_gate_reader=lambda: {
            "default_execution_mode": "paper_shadow",
            "manual_confirmation_required": True,
            "broker_submission_enabled": False,
            "kill_switch_enabled": False,
        },
        clock=lambda: clock,
    )
    return scanner, summary, decision_day.isoformat()
