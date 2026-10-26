"""Operator history stays non-authoritative and cannot reset trial disclosures."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.ai_runtime.store import IdempotencyConflict
from server.ai_runtime.strategy_research_citations import (
    compact_hypothesis_citation_catalog,
    resolve_hypothesis_citations,
)
from server.ai_runtime.strategy_research_model_contract import bind_and_validate_drafts
from server.contracts.strategy_research import (
    CANONICAL_COST_MODEL_REFERENCE,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    STRATEGY_RESEARCH_MAX_INPUT_BYTES,
    HypothesisGenerationRequest,
    StrategyResearchRejected,
    StrategyResearchSelection,
)
from server.persistence.strategy_research import StrategyResearchAuditStore


def _request(**changes):
    selection = StrategyResearchSelection(
        saved_backtest_result_id=17,
        universe=("600000",),
        asset_classes=("stock",),
        dataset_snapshot_id="sha256:" + "1" * 64,
        start_date="2025-01-02",
        end_date="2025-01-08",
        frequency="1d",
        initial_cash=1_000_000,
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
    )
    return replace(
        HypothesisGenerationRequest(
            idempotency_key="history-fixture",
            requested_by="human:fixture",
            account_alias="synthetic-only",
            research_question="Investigate a measured research failure.",
            selection=selection,
            confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
        ),
        **changes,
    )


def _prior():
    return {
        "artifact_fingerprint": "sha256:" + "2" * 64,
        "source_code_sha": "3" * 64,
        "observed_at": "2025-01-09T01:00:00+00:00",
        "universe": ["600000"],
        "start_date": "2025-01-02",
        "end_date": "2025-01-08",
        "frequency": "1d",
        "cost_model_reference": CANONICAL_COST_MODEL_REFERENCE,
        "observed_trial_count": 2,
        "provenance": {
            "generator": "synthetic_public_research",
            "model_id": "fixture-requested-model-identity-only",
            "disposition": "measured_cost_stress_not_canonical_performance",
            "external_provider_api_called": False,
        },
    }


def _store(tmp_path):
    store = StrategyResearchAuditStore(tmp_path / "research.db")
    store.init()
    with sqlite3.connect(tmp_path / "research.db") as conn:
        conn.execute(
            "CREATE TABLE backtest_results(id INTEGER PRIMARY KEY,metrics_json TEXT)"
        )
        conn.execute(
            "INSERT INTO backtest_results VALUES(17,?)", ('{"untouched":true}',)
        )
    return store


def test_empty_history_keeps_legacy_request_identity_and_persisted_shape(tmp_path):
    request = _request()
    legacy = {
        "requested_by": request.requested_by,
        "account_alias": request.account_alias,
        "research_question": request.research_question,
        "selection": request.selection.to_dict(),
        "confirmation": request.confirmation,
        "iteration_context": None,
    }
    assert request.fingerprint == content_fingerprint(legacy)
    empty = replace(request, research_history={}, prior_diagnostic_exposures=())
    assert empty.fingerprint == request.fingerprint
    store = _store(tmp_path)
    row, reused = store.create_or_get_session(
        request, created_at="2025-01-09T02:00:00+00:00"
    )
    assert reused is False
    assert json.loads(row["request_json"]) == {
        key: value for key, value in legacy.items() if key != "confirmation"
    } | {"confirmation_recorded": True, "api_key_recorded": False}
    assert store.create_or_get_session(empty, created_at="2025-01-10T00:00:00+00:00")[1]


def test_normal_session_binds_history_and_original_prior_without_importing_scores(
    tmp_path,
):
    history = {
        "source_artifacts": [{"sha256": "4" * 64}],
        "feedback": {"failed_checks": ["turnover"], "critique_performed": False},
    }
    prior = _prior()
    request = _request(research_history=history, prior_diagnostic_exposures=(prior,))
    store = _store(tmp_path)
    row, reused = store.create_or_get_session(
        request, created_at="2025-01-09T02:00:00+00:00"
    )
    persisted = json.loads(row["request_json"])
    assert reused is False
    assert persisted["research_history"] == history
    assert persisted["prior_diagnostic_exposures"] == [prior]
    assert "source_provenance" not in persisted
    assert persisted["iteration_context"] is None
    assert store.research_trial_family(request.selection)["nominal_trial_count"] == 2
    assert store.verify_events(row["session_id"]) == (True, [])
    assert store.create_or_get_session(request, created_at="2025-01-10T00:00:00+00:00")[
        1
    ]
    store.create_or_get_session(
        replace(request, idempotency_key="same-original-prior"),
        created_at="2025-01-10T00:00:00+00:00",
    )
    assert store.research_trial_family(request.selection)["nominal_trial_count"] == 2
    for changed in (
        replace(request, research_history={**history, "new_failure": "drawdown"}),
        replace(
            request, prior_diagnostic_exposures=({**prior, "observed_trial_count": 3},)
        ),
    ):
        assert changed.fingerprint != request.fingerprint
        with pytest.raises(IdempotencyConflict):
            store.create_or_get_session(changed, created_at="2025-01-10T00:00:00+00:00")
    with sqlite3.connect(tmp_path / "research.db") as conn:
        assert conn.execute("SELECT metrics_json FROM backtest_results").fetchall() == [
            ('{"untouched":true}',)
        ]
        assert conn.execute(
            "SELECT count(*) FROM ai_strategy_formula_backtests"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "history",
    [
        [],
        {"bad": (1, 2)},
        {"bad": {1, 2}},
        {"bad": Decimal("0.1")},
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": {1: "non-string-key"}},
    ],
)
def test_history_rejects_non_json_and_nonfinite_values(history):
    with pytest.raises(StrategyResearchRejected, match="research_history_invalid"):
        _request(research_history=history)


@pytest.mark.parametrize(
    "key",
    ["api_key", "credentials", "account_id", "positions", "total_cost", "initial_cash"],
)
def test_history_rejects_nested_private_context_and_absolute_account_values(key):
    with pytest.raises(
        StrategyResearchRejected, match="research_history_private_field_forbidden"
    ):
        _request(research_history={"public": [{key: "fixture-secret-never-exported"}]})


def test_history_rejects_cycles_and_enforces_utf8_byte_cap():
    cyclic = {}
    cyclic["cycle"] = cyclic
    with pytest.raises(StrategyResearchRejected, match="research_history_invalid"):
        _request(research_history=cyclic)
    with pytest.raises(
        StrategyResearchRejected, match="strategy_research_input_too_large"
    ):
        _request(
            research_history={"text": "中" * (STRATEGY_RESEARCH_MAX_INPUT_BYTES // 3)}
        )


def test_normal_prior_uses_original_strict_contract_and_five_record_limit():
    prior = _prior()
    assert _request(prior_diagnostic_exposures=(prior,)).prior_diagnostic_exposures == (
        prior,
    )
    with pytest.raises(
        StrategyResearchRejected, match="prior_diagnostic_exposure_invalid"
    ):
        _request(prior_diagnostic_exposures=({**prior, "total_return": 1},))
    with pytest.raises(
        StrategyResearchRejected, match="prior_diagnostic_exposure_budget_exceeded"
    ):
        _request(prior_diagnostic_exposures=(prior,) * 6)


def test_history_has_a_real_hash_citation_without_an_iteration_or_relaxed_formula_checks():
    selection = _request().selection
    history = {"failed_checks": ["turnover"], "source_artifact_sha256": "5" * 64}
    sources = {
        "saved_backtest_evidence": {"performance_summary": {"total_return": -0.1}},
        "operator_frozen_selection": selection.to_external_dict(),
        "research_history": {
            "non_authoritative": True,
            "operator_supplied": True,
            "content_fingerprint": "sha256:" + content_fingerprint(history),
            "content": history,
        },
    }
    catalog = compact_hypothesis_citation_catalog(citation_sources=sources)
    assert list(catalog.values())[-1] == "research_history.content_fingerprint"
    close = {"op": "field", "name": "close"}
    mean = {"op": "rolling_mean", "input": close, "window": 3}
    payload = {
        "drafts": [
            {
                **{
                    name: "Synthetic public research context."
                    for name in (
                        "economic_hypothesis",
                        "entry_conditions",
                        "exit_conditions",
                        "position_sizing_hypothesis",
                        "sample_split_plan",
                        "risk_impact",
                    )
                },
                **{
                    name: ["Synthetic evidence limitation."]
                    for name in (
                        "required_evidence",
                        "anti_lookahead_assumptions",
                        "proposed_deterministic_tests",
                        "failure_conditions",
                        "limitations",
                    )
                },
                "selected_universe": list(selection.universe),
                "dataset_snapshot_id": selection.dataset_snapshot_id,
                "test_window": {
                    "start_date": selection.start_date,
                    "end_date": selection.end_date,
                },
                "frequency": selection.frequency,
                "formula_ast": {
                    "schema_version": FORMULA_AST_CONTRACT,
                    "entry": {"op": "cross", "left": close, "right": mean},
                    "exit": {"op": "lt", "left": close, "right": mean},
                    "position_size": {
                        "op": "max_weight",
                        "input": {"op": "equal_weight"},
                        "value": 0.99,
                    },
                },
                "parameter_values": {"window": 3},
                "parameter_ranges": {"window": [2, 3, 5]},
                "portfolio_constraints": {"long_only": True, "max_weight": 1.0},
                "cost_model_reference": selection.cost_model_reference,
                "citations": list(catalog),
            }
        ]
    }
    bound = resolve_hypothesis_citations(
        payload, citation_catalog=catalog, citation_sources=sources
    )

    def bind(artifact):
        return bind_and_validate_drafts(
            artifact,
            session_id="fixture-session",
            workflow_id="fixture-workflow",
            context_snapshot_id="fixture-context",
            context_fingerprint="sha256:" + "6" * 64,
            evidence_reference_id="fixture-evidence",
            selection=selection,
            research_question="Read a measured failure without fabricating a parent.",
            iteration_context=None,
            provider_id="fixture-provider",
            model_id="fixture-model",
        )[0]

    draft = bind(bound)
    assert draft["validation"]["status"] == "valid"
    assert draft["iteration_context"] == {}
    assert draft["citations"][-1] == "research_history.content_fingerprint"
    legacy_bound = {
        "drafts": [
            {
                **bound["drafts"][0],
                "citations": [
                    item
                    for item in draft["citations"]
                    if not item.startswith("research_history.")
                ],
            }
        ]
    }
    assert canonical_json(draft["formula_ast"]) == canonical_json(
        bind(legacy_bound)["formula_ast"]
    )
    bound["drafts"][0]["dataset_snapshot_id"] = "sha256:" + "7" * 64
    assert "provider_changed_dataset_snapshot" in bind(bound)["validation"]["errors"]
    bound["drafts"][0]["citations"] = ["unbound_history.false_claim"]
    assert "citation_outside_bound_input" in bind(bound)["validation"]["errors"]
