"""Independent SIM opt-in, frozen final budgets, and account-authority separation."""

import asyncio
import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

import pytest

from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    ShadowResearchPolicy,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.research_observation_automation import (
    SIMULATION_VALIDATION_AUTHORIZE,
    read_research_validation_policy,
    validate_simulation_validation_policy,
)
from server.db import AppDatabase
from server.services.ai_shadow_research_commands import (
    AiShadowResearchCommandsMixin,
    simulation_validation_defaults,
)
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    market_deployment_scope,
)
from server.services.research_final_evaluation import reserve_final_research_evaluation
from tests.server.test_research_final_evaluation import (
    FREEZE,
    _seed_trial,
    harness,  # noqa: F401
)

NOW = datetime(2026, 1, 16, 12, tzinfo=timezone.utc)


class Commands(AiShadowResearchCommandsMixin):
    def __init__(self, db):
        self._db = db
        self._now = lambda: NOW

    def _save_research_policy(self, policy, **kwargs):
        from server.persistence.ai_shadow_research import ShadowResearchStore

        return ShadowResearchStore(self._db.path).configure_research_policy(
            policy=policy, now=NOW.isoformat(), **kwargs
        )


def minimal_simulation(**patch):
    return {"enabled": True, "authorization": SIMULATION_VALIDATION_AUTHORIZE, **patch}


def _small_verified_snapshots(h):
    """Real CAS inputs for the cost-only replay unit interval."""
    import pandas as pd

    from analytics.dataset_snapshot import build_backtest_dataset_snapshot
    from data.dataset.catalog import DatasetCatalog
    from data.dataset.manifest import publish_daily_bar_dataset_manifest
    from data.dataset.reader import read_daily_bar_dataset
    from data.providers.tushare_corporate_actions import (
        collect_tushare_dividend_observation,
    )
    from data.storage.objects import ContentAddressedObjectStore
    from server.contracts.http.strategy_models import BacktestRequest
    from server.services.backtest_dataset_inputs import load_dataset_backtest_inputs
    from tests.server.test_verified_interval_dataset import _verified_day

    root = h.db.path.parent / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    daily = [
        read_daily_bar_dataset(
            objects,
            _verified_day(root, NOW.date().replace(day=i), close="10.00"),
        )
        for i in range(1, 21)
    ]
    snapshots = []
    for count in (16, 20):
        cutoff = daily[count - 1].snapshot.cutoff
        action = collect_tushare_dividend_observation(
            objects,
            instrument=daily[0].snapshot.instruments[0],
            client=SimpleNamespace(dividend=lambda **_: pd.DataFrame()),
            clock=lambda: cutoff,
        )
        snapshot = replace(
            daily[count - 1].snapshot,
            start_date=NOW.date().replace(day=1),
            partitions=tuple(
                part for d in daily[:count] for part in d.snapshot.partitions
            ),
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
        sources = binding["source_names"]
        snapshots.append(
            build_backtest_dataset_snapshot(
                start_date="2026-01-01",
                end_date=f"2026-01-{count}",
                configured_source=sources[0] if len(sources) == 1 else None,
                data_handlers=handlers,
                store=None,
                source_names=sources,
                research_dataset_binding=binding,
            )
        )
    return snapshots


def test_simulation_is_explicit_noncapital_and_old_research_updates_preserve_it(
    tmp_path,
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    commands = Commands(db)
    assert "simulation_validation" not in ShadowResearchPolicy().to_dict()
    with pytest.raises(ValueError, match="simulation_policy_authorization_missing"):
        commands.update_policy(
            {
                "enabled": True,
                "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
                "simulation_validation": {"enabled": True},
            }
        )
    saved = commands.update_policy(
        {
            "enabled": True,
            "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
            "simulation_validation": minimal_simulation(initial_cash="32000"),
        }
    )
    sim = saved["simulation_validation"]
    assert sim["initial_cash"] == "32000"
    assert sim["statistical_policy"]["minimum_observations"] == 60
    assert sim["max_final_tests"] == 1
    assert sim["statistical_policy"]["significance_level"] == "0.05"
    assert sim["entry_board_policy"]["allowed_boards"] == ["main"]
    assert db.get_automation_policy_sync("ai_recommendation_publication") is None
    unchanged = commands.update_policy(
        {
            "enabled": True,
            "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
            "research_question": "A changed research question is not renewed SIM authority",
            "simulation_validation": {
                **sim,
                "created_at": "ignored-delivery-time",
                "updated_at": "ignored-delivery-time",
            },
        }
    )["simulation_validation"]
    assert unchanged == sim
    same_numbers = commands.update_policy(
        {
            "enabled": True,
            "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
            "simulation_validation": {
                **sim,
                "initial_cash": "32000.00",
                "statistical_policy": {
                    **sim["statistical_policy"],
                    "significance_level": "0.0500",
                },
            },
        }
    )["simulation_validation"]
    assert same_numbers == sim
    assert (
        commands.update_policy(
            {
                "enabled": True,
                "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
                "simulation_validation": None,
            }
        )["simulation_validation"]
        == sim
    )
    revoked = commands.update_policy(
        {
            "enabled": True,
            "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
            "simulation_validation": {
                "enabled": False,
                "generation": sim["generation"],
            },
        }
    )["simulation_validation"]
    assert (
        revoked["grant_id"] == sim["grant_id"]
        and revoked["generation"] != sim["generation"]
    )
    with pytest.raises(ValueError, match="simulation_policy_disabled"):
        read_research_validation_policy(db, now=NOW)
    with pytest.raises(ValueError, match="simulation_policy_generation_conflict"):
        commands.update_policy(
            {
                "enabled": True,
                "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
                "simulation_validation": {**sim, "enabled": True},
            }
        )
    assert commands.get_policy().simulation_validation == revoked
    from server.services.ai_shadow_research_workflow import (
        AiShadowResearchWorkflowMixin,
    )

    def forbidden():
        raise AssertionError("revoked SIM cannot trigger LLM or formal work")

    service = SimpleNamespace(
        get_policy=commands.get_policy,
        _policy_preflight=lambda policy: None,
        _db=db,
        _now=lambda: NOW,
        status=lambda: {},
        _require_deepseek_provider=forbidden,
    )
    service._research_validation_grant = lambda policy: (
        AiShadowResearchWorkflowMixin._research_validation_grant(service, policy)
    )
    blocked = asyncio.run(AiShadowResearchWorkflowMixin._run_once_with_inputs(service))
    assert blocked == {
        "run_status": "awaiting_independent_validation",
        "failure_code": "simulation_policy_disabled",
        "provider_call_performed": False,
    }


@pytest.mark.parametrize(
    "profile,code",
    [
        ({"minimum_observations": 59}, "minimum_forward"),
        ({"bootstrap_samples": 100}, "bootstrap_tail"),
        ({"minimum_observations": 2001}, "observation_budget"),
    ],
)
def test_simulation_does_not_relax_final_requirements(profile, code):
    proposed = simulation_validation_defaults(NOW)
    proposed.update(
        minimal_simulation(), grant_id=str(uuid4()), generation=str(uuid4())
    )
    proposed["statistical_policy"].update(profile)
    proposed["statistical_policy_fingerprint"] = content_fingerprint(
        proposed["statistical_policy"]
    )
    with pytest.raises(ValueError, match=code):
        validate_simulation_validation_policy(proposed)


def test_full_scope_simulation_reserves_without_account_or_reviewed_fees(
    harness, monkeypatch
):
    h = harness
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    sim = {
        **simulation_validation_defaults(NOW),
        **minimal_simulation(),
        "grant_id": str(uuid4()),
        "generation": str(uuid4()),
        "deployment_scope": scope,
        "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
        "initial_cash": "123456",
    }
    h.db.upsert_automation_policy_sync(
        policy_id="ai_shadow_research",
        payload={"simulation_validation": sim},
        updated_by="human:test",
    )
    h.selection = replace(
        h.selection,
        deployment_scope=scope,
        portfolio_policy_id=scope["portfolio_policy_id"],
        initial_cash=123456,
        simulation_validation_binding={
            key: sim[key] for key in ("grant_id", "generation", "initial_cash")
        },
    )
    h.candidate, h.draft = _seed_trial(h, suffix="sim", selection=h.selection)
    with sqlite3.connect(h.db.path) as conn:
        for identity in (
            h.selection.saved_backtest_result_id,
            h.candidate["candidate_result_id"],
        ):
            row = conn.execute(
                "SELECT metrics_json FROM backtest_results WHERE id=?", (identity,)
            ).fetchone()
            metrics = json.loads(row[0])
            metrics["entry_board_policy"] = sim["entry_board_policy"]
            conn.execute(
                "UPDATE backtest_results SET metrics_json=? WHERE id=?",
                (json.dumps(metrics), identity),
            )
    monkeypatch.setattr(
        "server.services.market_universe_automation.verified_trading_dates",
        lambda _db, *, start_date, end_date: [
            day
            for i in range(1, 21)
            if start_date <= (day := f"2026-01-{i:02}") <= end_date
        ],
    )

    def forbidden(*_a, **_k):
        raise AssertionError("account fee/valuation must not authorize independent SIM")

    monkeypatch.setattr(
        "server.services.valuation_snapshot.build_current_valuation_snapshot", forbidden
    )
    reserved = asyncio.run(
        reserve_final_research_evaluation(
            db=h.db,
            research_store=h.store,
            run={"run_id": "sim-run"},
            selection=h.selection,
            candidates=[h.candidate],
            daily_selection={
                "selection_fingerprint": "sim-selection",
                "research_recommendation": {
                    "research_winner_candidate_id": h.candidate["candidate_id"]
                },
            },
            now=FREEZE,
            reviewed_fee_schedule_resolver=forbidden,
            account_config=None,
        )
    )
    binding = reserved["evidence"]["reservation"]
    assert reserved["status"] == "reserved"
    assert binding["simulation_policy"] == sim
    assert "publication_grant" not in binding and "fee_schedule" not in binding
    assert binding["initial_cash"] == "123456"
    assert binding["error_budget"]["attempt_count"] == 1
    from server.services.ai_shadow_research_automation import (
        AiShadowResearchAutomationService,
    )

    pending_reader = SimpleNamespace(_db=h.db)
    assert (
        AiShadowResearchAutomationService._open_deployment_reservation(
            pending_reader, sim
        )["sealed_test_id"]
        == reserved["sealed_test_id"]
    )
    saved = Commands(h.db).update_policy(
        {
            "enabled": True,
            "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
            "research_question": "Unrelated edit preserves the frozen prospective experiment",
            "simulation_validation": dict(sim),
        }
    )["simulation_validation"]
    assert saved["generation"] == sim["generation"]
    assert (
        AiShadowResearchAutomationService._open_deployment_reservation(
            pending_reader, saved
        )["sealed_test_id"]
        == reserved["sealed_test_id"]
    )
    assert h.db.get_automation_policy_sync("ai_recommendation_publication") is None
    assert h.db.list_strategy_promotion_states_sync() == []
    assert (
        h.store.reserve_research_champion(binding=binding, created_at=FREEZE)[
            "sealed_test_id"
        ]
        == reserved["sealed_test_id"]
    )
    next_trial = deepcopy(binding)
    next_trial["source_run_id"] = "another-sim-run"
    next_trial["partition"].update(sealed_start="2026-02-01", sealed_end="2026-02-10")
    next_trial["first_evaluation_session"] = "2026-02-02"
    next_trial["simulation_policy"]["generation"] = str(uuid4())
    with pytest.raises(ValueError, match="final_test_budget_exhausted"):
        h.store.reserve_research_champion(
            binding=next_trial, created_at="2026-01-25T12:00:00+00:00"
        )


def test_nondefault_sim_notional_reaches_baseline_request_and_saved_selection(
    harness,
):
    from server.ai_runtime.strategy_research_backtest import (
        RestrictedFormulaBacktestAdapter,
    )
    from server.ai_runtime.strategy_research_support import selection_from_session
    from server.services.ai_shadow_research_baseline import (
        _resolve_baseline_initial_cash,
    )
    from server.services.ai_shadow_research_workflow import (
        AiShadowResearchWorkflowMixin,
    )

    h = harness
    sim = {
        **simulation_validation_defaults(NOW),
        **minimal_simulation(initial_cash="123456"),
        "grant_id": str(uuid4()),
        "generation": str(uuid4()),
    }
    policy = ShadowResearchPolicy(simulation_validation=sim)
    calls = []

    def prepare(current, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            request=SimpleNamespace(
                initial_cash=_resolve_baseline_initial_cash(
                    current, {}, {}, kwargs["initial_cash_override"]
                )
            )
        )

    prepared = asyncio.run(
        AiShadowResearchWorkflowMixin._prepare_validation_baseline(
            SimpleNamespace(_prepare_baseline=prepare), policy, sim
        )
    )
    assert calls[0]["initial_cash_override"] == 123456
    assert prepared.request.initial_cash == 123456
    with pytest.raises(ValueError, match="override_invalid"):
        _resolve_baseline_initial_cash(policy, {}, {}, 123457)
    with pytest.raises(ValueError, match="requires_normalized_notional"):
        replace(h.selection, initial_cash=123456)
    selection = replace(
        h.selection,
        initial_cash=prepared.request.initial_cash,
        deployment_scope=sim["deployment_scope"],
        portfolio_policy_id=sim["deployment_scope"]["portfolio_policy_id"],
        simulation_validation_binding={
            key: sim[key] for key in ("grant_id", "generation", "initial_cash")
        },
    )
    candidate, draft = _seed_trial(h, suffix="notional", selection=selection)
    restored = selection_from_session(h.store.get_session(candidate["session_id"]))
    assert restored.to_dict() == selection.to_dict()
    assert restored.initial_cash == 123456 and not restored.has_account_binding
    external = restored.to_external_dict()
    assert "simulation_validation_binding" not in external
    assert external["notional_policy_id"] == (
        "karkinos.ai.explicit_noncapital_simulation_notional.v1"
    )
    actual = RestrictedFormulaBacktestAdapter(data_store=h.data).run_sealed(
        selection=restored,
        draft=draft,
        sealed_end_date="2026-01-20",
        expected_dataset_snapshot=h.snapshot,
    )
    assert actual.initial_cash == Decimal(123456)


def test_seed_declaration_has_stable_history_floor_across_new_market_dates(
    harness, monkeypatch
):
    from server.services.ai_shadow_research_baseline import (
        AiShadowResearchBaselineMixin,
    )
    from server.services.market_universe_truth import normalize_a_share_members
    from server.services.research.datasets import forward_seed_origin_id

    h = harness
    monkeypatch.setattr(
        "server.services.ai_shadow_research_baseline.verified_trading_dates",
        lambda _db, *, start_date, end_date: [
            day
            for i in range(1, 21)
            if start_date <= (day := f"2026-01-{i:02}") <= end_date
        ],
    )
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    with sqlite3.connect(h.db.path) as conn:
        conn.execute(
            "UPDATE backtest_results SET config_json=? WHERE id=?",
            (
                json.dumps(
                    {
                        "strategy": "dual_ma",
                        "start_date": "2026-01-01",
                        "assets": [{"symbol": "600000", "asset_class": "stock"}],
                    }
                ),
                h.selection.saved_backtest_result_id,
            ),
        )
    current = [NOW]
    service = SimpleNamespace(_db=h.db, _data_store=h.data, _now=lambda: current[0])
    sim = {**simulation_validation_defaults(NOW), "deployment_scope": scope}
    policy = ShadowResearchPolicy(
        baseline_backtest_result_id=h.selection.saved_backtest_result_id
    )
    sources = []
    for day in (16, 20):
        current[0] = NOW.replace(day=day)
        h.data.save_market_universe_snapshot(
            trade_date=f"2026-01-{day}",
            provider_name="fixture",
            members=normalize_a_share_members(["600000"]),
            source_metadata=[
                {
                    "symbol": "600000",
                    "display_name": "普通股票",
                    "list_date": "20000101",
                    "list_status": "L",
                }
            ],
            capture_started_at=current[0],
            capture_completed_at=current[0],
        )
        sources.append(
            AiShadowResearchBaselineMixin._validation_seed_source(service, policy, sim)
        )
    assert [source["minimum_bars"] for source in sources] == [2, 2]
    assert [source["end_date"] for source in sources] == ["2026-01-16", "2026-01-20"]
    ids = [
        forward_seed_origin_id(
            scope,
            source["minimum_bars"],
            "same-source-policy",
            start_date=source["start_date"],
        )
        for source in sources
    ]
    assert ids[0] == ids[1]
    assert ids[0] != forward_seed_origin_id(
        scope, 2, "same-source-policy", start_date="2026-01-02"
    )


@pytest.mark.parametrize("mixed_binding", [False, True])
def test_sim_notional_survives_immutable_daily_backup_without_account_authority(
    tmp_path, mixed_binding
):
    from server.contracts.strategy_research import StrategyResearchSelection
    from server.services.account_qualification_reuse import (
        require_normalized_source_selection,
    )
    from server.services.ai_shadow_research_daily_artifacts import (
        DailyStrategyArtifactStore,
    )
    from tests.server.test_ai_shadow_research_daily_artifacts import (
        _normalized_candidates,
        _normalized_drafts,
    )

    binding = {
        "grant_id": str(uuid4()),
        "generation": str(uuid4()),
        "initial_cash": "123456",
    }
    candidates, drafts = _normalized_candidates(), _normalized_drafts()
    for candidate, draft in zip(candidates, drafts, strict=True):
        candidate["comparison"]["simulation_validation_binding"] = dict(binding)
        candidate["comparison"]["candidate"]["initial_cash"] = 123456
        draft["selected_universe"] = ["600000"]
    if mixed_binding:
        candidates[-1]["comparison"]["simulation_validation_binding"][
            "initial_cash"
        ] = "123457"
        candidates[-1]["comparison"]["candidate"]["initial_cash"] = 123457
    artifacts = DailyStrategyArtifactStore(
        tmp_path / "app.db", tmp_path / "strategy-research-backups"
    )
    artifacts.record_daily_artifacts(
        run={
            "run_id": "run-normalized-research",
            "market_date": "2026-08-31",
            "input_fingerprint": "sha256:" + "e" * 64,
        },
        candidates=candidates,
        drafts=drafts,
        expected_candidate_count=5,
        run_status="completed",
        created_at="2026-08-31T10:16:00+00:00",
    )
    if mixed_binding:
        with pytest.raises(ValueError, match="source_selection_mismatch"):
            artifacts.load_latest_verified_research_candidate_strategies()
        return
    batch = artifacts.load_latest_verified_research_candidate_strategies()
    actual = batch["source_research_selection"]
    assert actual["initial_cash"] == 123456
    assert actual["simulation_validation_binding"] == binding
    assert actual["contains_private_account_identifiers"] is False
    scope = market_deployment_scope(
        MarketUniversePolicy(minimum_master_member_count=1, minimum_history_rows=2)
    )
    selection = StrategyResearchSelection(
        saved_backtest_result_id=1,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "d" * 64,
        start_date="2025-01-01",
        end_date="2026-08-31",
        frequency="1d",
        initial_cash=123456,
        simulation_validation_binding=binding,
        deployment_scope=scope,
        portfolio_policy_id=scope["portfolio_policy_id"],
    )
    require_normalized_source_selection(batch, {"baseline_result_id": 1}, selection)
    with pytest.raises(ValueError, match="source_selection_binding_invalid"):
        require_normalized_source_selection(
            batch,
            {"baseline_result_id": 1},
            replace(
                selection,
                initial_cash=123457,
                simulation_validation_binding={**binding, "initial_cash": "123457"},
            ),
        )
