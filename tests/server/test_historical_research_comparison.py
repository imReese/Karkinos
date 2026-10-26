from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from analytics.dataset_snapshot import backtest_dataset_snapshot_content_id
from server.persistence.backtest_results import (
    BacktestResultsRepository,
    backtest_row_fingerprint,
)
from server.projections.account_action_recommendation import (
    build_account_action_recommendation,
    resolve_account_strategy_context,
    resolve_historical_research_comparison,
)
from tests.server.test_account_action_recommendation import (
    frozen_strategy_context as frozen_strategy_context,
)
from tests.server.test_account_action_recommendation import (
    historical_comparison_rows as historical_comparison_rows,
)


@pytest.fixture
def research_pair(historical_comparison_rows, monkeypatch):
    fixture = historical_comparison_rows
    candidate_ast = fixture.rows[19]["metrics_json"]["formula_binding"]["formula_ast"]
    candidate_ast["entry"]["right"]["window"] = 40
    fixture.persist()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("historical facts must not require promotion or artifacts")

    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline."
        "resolve_strategy_order_generation_gate",
        forbidden,
    )
    monkeypatch.setattr(
        "server.services.ai_shadow.ai_shadow_research_daily_artifacts."
        "DailyStrategyArtifactStore.load_latest_verified_research_artifacts",
        forbidden,
    )
    monkeypatch.setattr(
        "server.persistence.research_observations.ResearchObservationsRepository.list",
        lambda _self, **_kwargs: [],
    )
    return fixture


@pytest.mark.unit
def test_history_is_readable_without_promotion_or_account_actions(research_pair):
    fixture = research_pair
    before = fixture.context.db.path.read_bytes()
    assert (
        resolve_account_strategy_context(fixture.context.db, {"verified": False}) == {}
    )
    recommendation = build_account_action_recommendation(
        decision_payload={},
        trading_plan={},
        promoted_scan={"verified": False},
        current_evidence_blockers=[],
        current_evidence_fingerprint="a" * 64,
    )
    pair = resolve_historical_research_comparison(fixture.context.db)
    assert pair is not None
    assert (pair["source_result_id"], pair["anchor_result_id"]) == (17, 19)
    assert (pair["baseline"]["result_id"], pair["candidate"]["result_id"]) == (18, 19)
    assert pair["point_in_time_verified"] is False
    assert pair["independent_final_evaluation"] is False
    assert pair["authority_effect"] == "none"
    assert pair["read_only"] is True and pair["authorizes_execution"] is False
    assert recommendation["actions"] == []
    assert recommendation["strategy_context"] == {}
    assert recommendation["authorizes_execution"] is False
    assert fixture.context.db.path.read_bytes() == before


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("result_id", [17, 18, 19])
async def test_withdrawn_source_or_either_pair_member_stays_raw_but_not_comparable(
    research_pair, result_id
):
    fixture = research_pair
    repo = BacktestResultsRepository(fixture.context.db.path)
    raw = await repo.get_result(result_id)
    assert raw is not None
    original = {
        key: value for key, value in raw.items() if key != "evidence_invalidation"
    }
    repo.append_invalidation_sync(
        result_id=result_id,
        expected_row_fingerprint=backtest_row_fingerprint(raw),
        actor="fixture-reviewer",
        reason="Saved evidence was not produced by the recorded calculation.",
        idempotency_key="withdraw-fixture-comparison-source",
    )
    before = fixture.context.db.path.read_bytes()
    assert resolve_historical_research_comparison(fixture.context.db) is None
    historical = await repo.get_result(result_id)
    assert historical is not None
    assert historical["evidence_invalidation"]["status"] == "invalidated"
    assert {
        key: value
        for key, value in historical.items()
        if key != "evidence_invalidation"
    } == original
    assert fixture.context.db.path.read_bytes() == before


@pytest.mark.unit
def test_forward_records_are_bound_to_each_actual_result(research_pair, monkeypatch):
    seen = []

    def observations(_self, *, limit, source_backtest_result_id):
        assert limit == 100
        seen.append(source_backtest_result_id)
        return (
            [{"lifecycle": "active", "publications": [{}], "outcomes": []}]
            if source_backtest_result_id == 18
            else []
        )

    monkeypatch.setattr(
        "server.persistence.research_observations.ResearchObservationsRepository.list",
        observations,
    )
    pair = resolve_historical_research_comparison(research_pair.context.db)
    assert pair is not None
    assert seen == [18, 19]
    assert pair["forward"]["baseline"]["source_backtest_result_id"] == 18
    assert pair["forward"]["baseline"]["status"] == "recorded"
    assert pair["forward"]["candidate"]["source_backtest_result_id"] == 19
    assert pair["forward"]["candidate"]["status"] == "not_started"
    assert all(
        item["qualification_assessed"] is False for item in pair["forward"].values()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "drift",
    [
        "missing_source",
        "source_ast",
        "missing_baseline",
        "seed_as_baseline",
        "source_family",
        "candidate_ast_missing",
        "dataset",
        "snapshot_identity",
        "snapshot_schema",
        "cost",
        "source_files",
        "authority",
    ],
)
def test_history_rejects_broken_exact_bindings(research_pair, drift):
    fixture = research_pair
    row = fixture.rows[19]
    metrics = row["metrics_json"]
    provenance = metrics["historical_comparison"]
    if drift == "missing_source":
        del fixture.rows[17]
    elif drift == "source_ast":
        fixture.rows[17]["metrics_json"]["formula_binding"]["formula_ast"] = {
            "entry": {"op": "constant", "value": 1}
        }
    elif drift == "missing_baseline":
        del fixture.rows[18]
    elif drift == "seed_as_baseline":
        provenance["actual_comparison_baseline_result_id"] = 17
    elif drift == "source_family":
        provenance["historical_formula_source_result_id"] = 99
    elif drift == "candidate_ast_missing":
        del metrics["formula_binding"]["formula_ast"]
    elif drift == "dataset":
        row["config_json"]["dataset_id"] = "sha256:" + "f" * 64
    elif drift == "snapshot_identity":
        metrics["dataset_snapshot"]["snapshot_id"] = "sha256:" + "f" * 64
    elif drift == "snapshot_schema":
        # Even mutually matching, rehashed unknown schemas cannot borrow v1 meaning.
        for result_id in (18, 19):
            value = fixture.rows[result_id]["metrics_json"]
            snapshot = value["dataset_snapshot"]
            snapshot["schema_version"] = "unknown.snapshot.v9"
            snapshot.pop("snapshot_id")
            snapshot["snapshot_id"] = backtest_dataset_snapshot_content_id(snapshot)
            value["formula_binding"]["dataset_snapshot_id"] = snapshot["snapshot_id"]
    elif drift == "cost":
        metrics["formula_binding"]["cost_model_reference"] = "different-cost-model"
    elif drift == "source_files":
        provenance["source_files"] = {"analytics/example.py": "f" * 64}
    elif drift == "authority":
        provenance["authority_effect"] = "account_preview"
    fixture.persist()
    assert resolve_historical_research_comparison(fixture.context.db) is None


@pytest.mark.unit
def test_invalid_latest_anchor_falls_back_within_twenty(research_pair):
    fixture = research_pair
    for result_id in range(20, 40):
        row = deepcopy(fixture.rows[19])
        row["id"] = result_id
        row["metrics_json"]["formula_binding"]["cost_model_reference"] = "wrong-cost"
        fixture.rows[result_id] = row
    fixture.persist()
    repository = BacktestResultsRepository(fixture.context.db.path)
    anchors = repository.read_recent_historical_comparison_anchors(limit=999)
    assert len(anchors) == 20
    assert [row["id"] for row in anchors] == list(range(39, 19, -1))
    assert set(anchors[0]) == {"id", "formula_ast_json", "evidence_invalidation"}
    assert anchors[0]["evidence_invalidation"] is None
    assert resolve_historical_research_comparison(fixture.context.db) is None
    del fixture.rows[39]
    fixture.persist()
    pair = resolve_historical_research_comparison(fixture.context.db)
    assert pair is not None and pair["anchor_result_id"] == 19


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    ["historical_formula_source_result_id", "actual_comparison_baseline_result_id"],
)
@pytest.mark.parametrize("identity", [None, 0, -1, True, "17"])
def test_discovery_requires_explicit_integer_source_ids(research_pair, field, identity):
    fixture = research_pair
    fixture.rows[19]["metrics_json"]["historical_comparison"][field] = identity
    fixture.persist()
    assert (
        BacktestResultsRepository(
            fixture.context.db.path
        ).read_recent_historical_comparison_anchors()
        == []
    )
    assert resolve_historical_research_comparison(fixture.context.db) is None


@pytest.mark.unit
def test_newer_matching_formula_without_explicit_provenance_is_not_an_anchor(
    research_pair,
):
    fixture = research_pair
    row = deepcopy(fixture.rows[19])
    row["id"] = 20
    row["metrics_json"].pop("historical_comparison")
    row["total_return"] = 999
    fixture.rows[20] = row
    fixture.persist()
    pair = resolve_historical_research_comparison(fixture.context.db)
    assert pair is not None and pair["anchor_result_id"] == 19


@pytest.mark.unit
def test_missing_or_unreadable_database_does_not_create_state(tmp_path):
    assert resolve_historical_research_comparison(None) is None
    path = tmp_path / "absent.db"
    assert resolve_historical_research_comparison(SimpleNamespace(path=path)) is None
    assert not path.exists()


@pytest.mark.unit
def test_malformed_latest_metrics_do_not_hide_explicit_valid_history(research_pair):
    import sqlite3

    fixture = research_pair
    with sqlite3.connect(fixture.context.db.path) as connection:
        connection.execute(
            "INSERT INTO backtest_results (id, config_json, metrics_json) VALUES (?,?,?)",
            (20, "{}", "{invalid-json"),
        )
    pair = resolve_historical_research_comparison(fixture.context.db)
    assert pair is not None and pair["anchor_result_id"] == 19


@pytest.mark.unit
def test_existing_get_adds_only_a_nullable_history_sibling(monkeypatch):
    from server.routes import decision

    recommendation = {"status": "blocked", "actions": [], "strategy_context": {}}
    pair = {"status": "recorded_pair", "anchor_result_id": 19}
    monkeypatch.setattr(
        "server.services.research.daily_research_operation_preview."
        "resolve_latest_verified_research_operation_preview",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "server.services.decision.plan.build_daily_trading_plan",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(decision, "_trading_plan_positions", lambda *_a, **_k: [])
    monkeypatch.setattr(
        decision, "_current_account_action_evidence", lambda *_a, **_k: ([], "")
    )
    monkeypatch.setattr(
        "server.projections.account_action_recommendation.resolve_latest_verified_promoted_strategy_scan",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "server.projections.account_action_recommendation.resolve_account_strategy_context",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        "server.projections.account_action_recommendation.build_account_action_recommendation",
        lambda **_kwargs: recommendation,
    )
    monkeypatch.setattr(
        "server.services.research.instruments.build_research_operation_instruments",
        lambda *_a, **_k: {},
    )
    for value in (None, pair):
        monkeypatch.setattr(
            "server.projections.account_action_recommendation.resolve_historical_research_comparison",
            lambda *_a, **_k: value,
        )
        result = decision._build_daily_trading_plan_for_state(SimpleNamespace(), {}, {})
        assert result["historical_research_comparison"] is value
        assert result["account_action_recommendation"] is recommendation
        assert (
            json.loads(json.dumps(result))["account_action_recommendation"]
            == recommendation
        )
