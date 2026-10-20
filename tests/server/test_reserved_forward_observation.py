"""A standing grant resumes a real isolated book without inventing human approval."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetMembership
from data.dataset.reader import read_daily_bar_dataset
from data.store import DataStore
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from execution.commission import StockACommission
from server.ai_runtime.formula_dsl import FormulaBinding
from server.contracts.content_identity import content_fingerprint
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.automation_runs import AutomationRunRepository
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
    normalize_a_share_members,
)
from server.services.research_observation_automation import (
    configure_observation_automation,
    start_reserved_champion_observation,
)
from server.services.research_paper_books import ResearchPaperBookService
from tests.server.test_recommendation_publication import _grant
from tests.server.test_research_observation_inputs import DAYS, STOCK, formula_source
from tests.server.test_research_observations_journey import journey  # noqa: F401

pytestmark = pytest.mark.product_smoke


@pytest.mark.parametrize("exercise_forward", [False, "main", "star_excluded"])
@pytest.mark.parametrize("simulation", [False, True])
def test_reserved_start_waits_then_resumes_exact_cash_fees_and_keeps_owner_pause(
    journey, tmp_path, monkeypatch, exercise_forward, simulation
):
    _, observations, current, legacy, _ = journey
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    source = formula_source()
    raw_binding = source["metrics_json"]["formula_binding"]
    formula = {
        **raw_binding["formula_ast"],
        "entry": {
            "op": "gt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
    }
    formula_binding = FormulaBinding(
        **{
            **raw_binding,
            "formula_ast": formula,
            "universe": tuple(raw_binding["universe"]),
            "anti_lookahead_assumptions": tuple(
                raw_binding["anti_lookahead_assumptions"]
            ),
        }
    )
    source["metrics_json"].update(
        formula_binding=formula_binding.to_dict(),
        formula_fingerprint=formula_binding.fingerprint,
    )
    source["config_json"]["params"]["formula_fingerprint"] = formula_binding.fingerprint
    execution = source["metrics_json"]["signal_execution_evidence"]
    execution.update(allocation_slots=4, canonical_target_weight=0.25)
    execution["evidence_fingerprint"] = content_fingerprint(
        {k: v for k, v in execution.items() if k != "evidence_fingerprint"}
    )
    source["metrics_json"]["source_selection"] = {
        "universe": [STOCK.symbol],
        "dataset_snapshot_id": source["metrics_json"]["formula_binding"][
            "dataset_snapshot_id"
        ],
        "portfolio_policy_id": FORMULA_PORTFOLIO_POLICY_ID,
        "deployment_scope": scope,
    }
    source_id = asyncio.run(
        observations.db.save_backtest_result(
            config_json=json.dumps(source["config_json"]),
            metrics_json=json.dumps(source["metrics_json"]),
            initial_cash=100000,
            final_equity=100000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    original = read_daily_bar_dataset(observations.objects, legacy).snapshot
    master_store = DataStore(tmp_path / "market")
    memberships = []
    for day in DAYS[:5]:
        at = datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=7, minutes=10)
        master = master_store.save_market_universe_snapshot(
            trade_date=day.isoformat(),
            provider_name="fixture",
            members=normalize_a_share_members([STOCK.symbol]),
            capture_started_at=at - timedelta(seconds=1),
            capture_completed_at=at,
        )
        memberships.append(
            DailyBarDatasetMembership(
                day,
                (STOCK,),
                at,
                source_observation_ids=(
                    bind_stock_master_observation(observations.objects, master),
                ),
                decision_at=at,
            )
        )
    seed = publish_daily_bar_dataset_manifest(
        observations.objects,
        replace(
            original,
            partitions=tuple(
                replace(p, instruments=(STOCK,)) for p in original.partitions
            ),
            session_memberships=tuple(memberships),
            universe_policy_id=scope["deployment_scope_fingerprint"],
        ),
    )
    grant = _grant(deployment_scope_fingerprint=scope["deployment_scope_fingerprint"])
    grant["risk_limits"]["max_symbol_weight"] = "0.30"
    grant["statistical_policy"]["minimum_observations"] = 4
    grant["statistical_policy_fingerprint"] = content_fingerprint(
        grant["statistical_policy"]
    )
    grants = ShadowResearchStore(observations.db.path)
    grants.init()
    if simulation:
        from uuid import uuid4

        from server.contracts.research_observation_automation import (
            SIMULATION_VALIDATION_AUTHORIZE,
            validate_simulation_validation_policy,
        )
        from server.services.ai_shadow.ai_shadow_research_commands import (
            simulation_validation_defaults,
        )

        proposal = simulation_validation_defaults(current[0])
        grant = validate_simulation_validation_policy(
            {
                **proposal,
                "enabled": True,
                "authorization": SIMULATION_VALIDATION_AUTHORIZE,
                "grant_id": str(uuid4()),
                "generation": str(uuid4()),
                "deployment_scope": scope,
                "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
                "initial_cash": "32000",
            }
        )
        observations.db.upsert_automation_policy_sync(
            policy_id="ai_shadow_research",
            payload={"simulation_validation": grant},
            updated_by="human:test",
        )
        assert (
            observations.db.get_automation_policy_sync("ai_recommendation_publication")
            is None
        )
    else:
        grants.configure_publication_grant(
            policy=grant, expected_generation=None, now=current[0].isoformat()
        )
    fees = {
        "review_id": "reviewed-fixture",
        "cost_model_reference": "fixture.exact.fees",
    }
    binding = {
        "candidate_result_id": source_id,
        "simulation_policy" if simulation else "publication_grant": grant,
        "entry_board_policy": grant["entry_board_policy"],
        "deployment_scope": scope,
        "initial_cash": "32000",
        **({} if simulation else {"fee_schedule": fees}),
        "partition": {"sealed_start": DAYS[5].isoformat(), "sealed_end": "2026-09-24"},
    }
    monkeypatch.setattr(
        StrategyResearchAuditStore,
        "get_sealed_test",
        lambda *_: {"evidence": {"reservation": binding}},
    )
    queued = [
        {"status": "waiting", "job_ids": ["job-1"]},
        {"status": "ready", "dataset_id": seed.dataset_id},
    ]
    monkeypatch.setattr(
        "server.services.research.datasets.ensure_forward_seed_for_source",
        lambda *_a, **_kw: queued.pop(0),
    )
    monkeypatch.setattr(
        "server.services.backtest_costs.resolve_frozen_deployment_fee_schedule",
        lambda *_a: SimpleNamespace(
            commission_calc=StockACommission(),
            cost_model_reference=fees["cost_model_reference"],
            fee_evidence={"fixture": True},
        ),
    )
    args = dict(
        source_result_id=source_id,
        grant=grant,
        now=current[0],
        config=SimpleNamespace(),
        reservation_id="reserved-fixture",
    )
    pending = asyncio.run(
        start_reserved_champion_observation(
            observations.db, observations.objects, **args
        )
    )
    assert pending["status"] == "waiting"
    assert observations.repository.list() == []
    if not exercise_forward:
        from server.services.research_observations import ResearchObservationService

        original_publication = ResearchObservationService._publication
        failed = []

        def unavailable_once(self, *args, **kwargs):
            if not failed:
                failed.append(True)
                raise ValueError("observation_bound_evidence_unreadable")
            return original_publication(self, *args, **kwargs)

        monkeypatch.setattr(
            ResearchObservationService, "_publication", unavailable_once
        )
        retry = asyncio.run(
            start_reserved_champion_observation(
                observations.db, observations.objects, **args
            )
        )
        assert retry["status"] == "waiting", retry
        assert observations.repository.get(retry["observation_id"])["version"] == 1
    ready = asyncio.run(
        start_reserved_champion_observation(
            observations.db, observations.objects, **args
        )
    )
    assert ready["status"] == "ready", ready
    identity = ready["observation_id"]
    observed = observations.repository.get(identity)
    assert observed["policy"]["decision_actor"] == (
        "standing_simulation_policy" if simulation else "standing_publication_grant"
    )
    assert observed["publications"]
    assert max(
        Decimal(weight)
        for weight in observed["publications"][0]["payload"]["target_weights"].values()
    ) <= Decimal("0.25")
    assert (
        observed["policy"]["authorization_binding"]["reservation_id"]
        == "reserved-fixture"
    )
    paper = ResearchPaperBookService(observations.db, clock=lambda: current[0]).get(
        identity
    )
    assert paper["initial_cash"] == "32000"
    assert paper["state"]["cash"] == "32000"
    if simulation:
        assert "fee_schedule_binding" not in paper["policy"]
        assert paper["policy"]["cost_assumptions"]["source"] == "research_simulation"
    else:
        assert paper["policy"]["fee_schedule_binding"] == fees
        assert (
            paper["policy"]["cost_assumptions"]["commission_model_reference"]
            == "fixture.exact.fees"
        )
    assert (
        asyncio.run(
            start_reserved_champion_observation(
                observations.db, observations.objects, **args
            )
        )["book_id"]
        == paper["id"]
    )
    policies = AutomationRunRepository(observations.db.path)
    policy = policies.get_observation_automation_policy(identity)
    assert policy["dataset_preparation_enabled"] and policy["paper_settlement_enabled"]
    if exercise_forward:
        exercise_and_compare_forward(
            observations,
            current,
            seed,
            scope,
            master_store,
            binding,
            source,
            tmp_path,
            restricted_entry=exercise_forward == "star_excluded",
        )
    if simulation and not exercise_forward:
        observations.db.upsert_automation_policy_sync(
            policy_id="ai_shadow_research",
            payload={"simulation_validation": {**grant, "enabled": False}},
            updated_by="human:test",
        )
        before = observations.repository.get(identity)
        blocked = observations.advance(
            identity,
            request_id="revoked-sim-target",
            expected_version=before["version"],
            dataset_id=seed.dataset_id,
        )
        assert blocked["last_blocker"]["code"] == "simulation_policy_disabled"
        assert len(observations.repository.get(identity)["publications"]) == len(
            before["publications"]
        )
    configure_observation_automation(
        observations, identity, enabled=False, expected_generation=policy["generation"]
    )
    paused = asyncio.run(
        start_reserved_champion_observation(
            observations.db, observations.objects, **args
        )
    )
    assert paused["status"] == ("blocked" if simulation else "paused")
    assert len(observations.repository.list()) == 1
    assert policies.get_observation_automation_policy(identity)["enabled"] is False
    assert observations.db.list_strategy_promotion_states_sync() == []
    from server.services.research_paper_books import verify_reserved_forward_book

    observed = observations.repository.get(identity)
    observations.repository.pause(
        observation_id=identity,
        request_id="owner-pause",
        request_fingerprint="owner-pause",
        expected_version=observed["version"],
    )
    with pytest.raises(ValueError, match="deployment_forward_book_health_blocked"):
        verify_reserved_forward_book(
            observations.db,
            {
                "sealed_test_id": "reserved-fixture",
                "evidence": {"reservation": binding},
            },
            through_session=DAYS[5],
            now=current[0],
        )


def exercise_and_compare_forward(
    observations,
    current,
    seed,
    scope,
    master_store,
    binding,
    source,
    tmp_path,
    *,
    restricted_entry,
):
    import pandas as pd

    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from core.types import InstrumentKey, InstrumentType
    from data.providers import tushare_corporate_actions as ca_provider
    from server.ai_runtime.strategy_research_backtest import (
        RestrictedFormulaBacktestAdapter,
    )
    from server.contracts.http.strategy_models import BacktestRequest
    from server.contracts.normalized_strategy_research import (
        NORMALIZED_RESEARCH_NOTIONAL,
    )
    from server.contracts.strategy_research import StrategyResearchSelection
    from server.services.research.dataset_inputs import load_dataset_backtest_inputs
    from server.services.research_paper_books import verify_reserved_forward_book
    from tests.server.test_research_observation_inputs import calendar
    from tests.server.test_verified_interval_dataset import _verified_day

    identity = observations.repository.list()[0]["id"]
    reservation = {
        "sealed_test_id": "reserved-fixture",
        "evidence": {"reservation": binding},
    }
    with pytest.raises(ValueError, match="deployment_forward_settlement_incomplete"):
        verify_reserved_forward_book(
            observations.db,
            reservation,
            through_session=DAYS[5],
            now=datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc),
        )
    future = (*DAYS[5:], datetime(2026, 9, 24).date())
    trading = (
        *DAYS[:5],
        *future,
        datetime(2026, 9, 25).date(),
        datetime(2026, 9, 28).date(),
    )
    observations.db.upsert_market_calendar_snapshot_sync(calendar(trading_days=trading))
    second = InstrumentKey(
        "688001" if restricted_entry else "600001", InstrumentType.STOCK
    )
    previous = read_daily_bar_dataset(observations.objects, seed).snapshot
    held_quantities = []
    closes = ("10.48", "11.4", "12.4", "13.4")
    for index, day in enumerate(future):
        current[0] = datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=8, minutes=20)
        part_ref = _verified_day(
            tmp_path / "research",
            day,
            instruments=(STOCK, second),
            close=closes[index],
        )
        part = read_daily_bar_dataset(
            observations.objects, part_ref
        ).snapshot.partitions[0]
        at = current[0] - timedelta(minutes=1)
        master = master_store.save_market_universe_snapshot(
            trade_date=day.isoformat(),
            provider_name="fixture",
            members=normalize_a_share_members([STOCK.symbol, second.symbol]),
            capture_started_at=at - timedelta(seconds=1),
            capture_completed_at=at,
        )
        member = DailyBarDatasetMembership(
            day,
            (STOCK, second),
            at,
            source_observation_ids=(
                bind_stock_master_observation(observations.objects, master),
            ),
            decision_at=current[0],
        )
        actions = tuple(
            ca_provider.collect_tushare_dividend_observation(
                observations.objects,
                instrument=key,
                client=SimpleNamespace(
                    dividend=lambda **_: pd.DataFrame(
                        columns=ca_provider.DIVIDEND_FIELDS.split(",")
                    )
                ),
                clock=lambda: current[0],
            ).object_id
            for key in (STOCK, second)
        )
        full = publish_daily_bar_dataset_manifest(
            observations.objects,
            replace(
                previous,
                end_date=day,
                cutoff=current[0],
                instruments=(STOCK, second),
                partitions=(
                    *previous.partitions,
                    replace(part, instruments=(STOCK, second)),
                ),
                session_memberships=(*previous.session_memberships, member),
                corporate_action_observation_ids=actions,
            ),
        )
        book_service = ResearchPaperBookService(
            observations.db, clock=lambda: current[0]
        )
        book = book_service.get(identity)
        if index == 0 and binding.get("simulation_policy"):
            original_settle = book_service.repository.settle
            automation = observations.db.get_automation_policy_sync(
                "research-observation:" + identity
            )
            for generation in (None, automation["generation"]):

                def revoke_before_locked_write(**kwargs):
                    observations.db.upsert_automation_policy_sync(
                        policy_id="ai_shadow_research",
                        payload={
                            "simulation_validation": {
                                **binding["simulation_policy"],
                                "enabled": False,
                            }
                        },
                        updated_by="human:test",
                    )
                    return original_settle(**kwargs)

                with pytest.MonkeyPatch.context() as race:
                    race.setattr(
                        book_service.repository, "settle", revoke_before_locked_write
                    )
                    with pytest.raises(
                        ValueError, match="simulation_authorization_changed"
                    ):
                        book_service.settle(
                            identity,
                            request_id=f"revoked-settlement:{generation}",
                            expected_version=book["version"],
                            dataset_id=full.dataset_id,
                            automation_generation=generation,
                        )
                assert book_service.get(identity)["steps"] == []
                observations.db.upsert_automation_policy_sync(
                    policy_id="ai_shadow_research",
                    payload={"simulation_validation": binding["simulation_policy"]},
                    updated_by="human:test",
                )
        settled = book_service.settle(
            identity,
            request_id=f"settle:{day}",
            expected_version=book["version"],
            dataset_id=full.dataset_id,
        )
        assert settled["last_settled_session"] == day.isoformat()
        actual_book = book_service.get(identity)
        held_quantities.append(
            actual_book["state"]["positions"][STOCK.symbol]["quantity"]
        )
        if index < len(future) - 1:
            observed = observations.repository.get(identity)
            advanced = observations.advance(
                identity,
                request_id=f"advance:{day}",
                expected_version=observed["version"],
                dataset_id=full.dataset_id,
            )
            assert advanced["publication_id"], advanced
            publication = observations.repository.get(identity)["publications"][-1]
            # A hold remains observable, but is never another executable target.
            assert STOCK.symbol in publication["payload"]["desired_weights"]
            assert STOCK.symbol not in publication["payload"]["target_weights"]
        previous = read_daily_bar_dataset(observations.objects, full).snapshot
    assert len(set(held_quantities)) == 1
    if binding.get("simulation_policy"):
        # A real four-session SIM book advances, but is never a sixty-session final pass.
        with pytest.raises(ValueError, match="deployment_forward_health_not_ready"):
            verify_reserved_forward_book(
                observations.db, reservation, through_session=future[-1], now=current[0]
            )
        assert len(actual_book["steps"]) == 4
        assert actual_book["fills"]
        assert observations.db.list_strategy_promotion_states_sync() == []
        before = observations.repository.get(identity)
        original = observations._publication

        def revoke_after_calculation(*args, **kwargs):
            publication = original(*args, **kwargs)
            observations.db.upsert_automation_policy_sync(
                policy_id="ai_shadow_research",
                payload={
                    "simulation_validation": {
                        **binding["simulation_policy"],
                        "enabled": False,
                    }
                },
                updated_by="human:test",
            )
            return publication

        with pytest.MonkeyPatch.context() as race:
            race.setattr(observations, "_publication", revoke_after_calculation)
            with pytest.raises(ValueError, match="simulation_authorization_changed"):
                observations.advance(
                    identity,
                    request_id="revoke-between-calculate-and-persist",
                    expected_version=before["version"],
                    dataset_id=full.dataset_id,
                )
        assert len(observations.repository.get(identity)["publications"]) == len(
            before["publications"]
        )
        assert observations.db.list_strategy_promotion_states_sync() == []
        with pytest.raises(ValueError, match="simulation_policy_disabled"):
            book_service.settle(
                identity,
                request_id="new-settlement-after-revocation",
                expected_version=actual_book["version"],
                dataset_id=full.dataset_id,
            )
        assert book_service.get(identity)["steps"] == actual_book["steps"]
        assert (
            book_service.settle(
                identity,
                request_id=f"settle:{future[-1]}",
                expected_version=actual_book["version"] - 1,
                dataset_id=full.dataset_id,
            )
            == settled
        )
        return
    proof = verify_reserved_forward_book(
        observations.db, reservation, through_session=future[-1], now=current[0]
    )
    assert proof["settled_sessions"] == 4
    assert proof["health"]["status"] == "within_rule"
    from copy import deepcopy

    from server.persistence.research_paper_books import ResearchPaperBooksRepository

    # Exercise current-read risk guards without rewriting immutable history.
    current_book = book_service.get(identity)
    equity = Decimal(current_book["state"]["equity"])
    template = next(iter(current_book["state"]["positions"].values()))
    breaches = []
    for weights in (("0.9", "0.01"), ("0.26",) * 4, ("0.05",) * 5):
        breached = deepcopy(current_book)
        breached["state"]["positions"] = {
            str(600100 + index): {
                **template,
                "quantity": "100",
                "market_value": str(equity * Decimal(weight)),
            }
            for index, weight in enumerate(weights)
        }
        breaches.append(breached)
    drawdown = deepcopy(current_book)
    drawdown["performance"]["max_drawdown"] = "0.3"
    breaches.append(drawdown)
    for breached in breaches:
        with pytest.MonkeyPatch.context() as current_read:
            current_read.setattr(
                ResearchPaperBooksRepository, "get", lambda *_: breached
            )
            with pytest.raises(
                ValueError, match="deployment_forward_observed_risk_exceeds_grant"
            ):
                verify_reserved_forward_book(
                    observations.db,
                    reservation,
                    through_session=future[-1],
                    now=current[0],
                )
    assert (
        verify_reserved_forward_book(
            observations.db, reservation, through_session=future[-1], now=current[0]
        )
        == proof
    )
    book = book_service.get(identity)
    if restricted_entry:
        assert not any(f["symbol"] == second.symbol for f in book["fills"])
        assert any(
            row["symbol"] == second.symbol
            for row in observations.repository.get(identity)["publications"][-1][
                "payload"
            ]["forecasts"]
        )
    else:
        assert (
            next(f for f in book["fills"] if f["symbol"] == second.symbol)["session"]
            == future[2].isoformat()
        )
    request = BacktestRequest(
        dataset_id=full.dataset_id,
        start_date=DAYS[0].isoformat(),
        end_date=future[-1].isoformat(),
    )
    _, handlers, dataset_binding = load_dataset_backtest_inputs(
        tmp_path / "research", request
    )
    snapshot = build_backtest_dataset_snapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        configured_source="fixture",
        data_handlers=handlers,
        store=None,
        source_names=dataset_binding["source_names"],
        research_dataset_binding=dataset_binding,
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=binding["candidate_result_id"],
        universe=(STOCK.symbol,),
        asset_classes=("stock",),
        dataset_snapshot_id=source["metrics_json"]["dataset_snapshot"]["snapshot_id"],
        start_date=DAYS[0].isoformat(),
        end_date=DAYS[4].isoformat(),
        frequency="1d",
        initial_cash=NORMALIZED_RESEARCH_NOTIONAL,
        sealed_end_date=future[-1].isoformat(),
        deployment_scope=scope,
        portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID,
    )
    final = RestrictedFormulaBacktestAdapter(data_store=DataStore(tmp_path)).run_sealed(
        selection=selection,
        draft={"formula_ast": source["metrics_json"]["formula_binding"]["formula_ast"]},
        sealed_end_date=future[-1].isoformat(),
        evaluation_dataset_snapshot=snapshot,
        expected_trading_dates=[
            day.isoformat() for day in trading if day <= future[-1]
        ],
        initial_cash_override=Decimal(binding["initial_cash"]),
        commission_calc_override=StockACommission(),
        entry_board_policy=binding["entry_board_policy"],
    )
    actual = {stamp.date().isoformat(): value for stamp, value in final.equity_curve}
    for row in proof["session_equity"]:
        assert abs(
            Decimal(str(actual[row["session"]])) - Decimal(row["equity"])
        ) <= Decimal("0.01"), (row, actual)
