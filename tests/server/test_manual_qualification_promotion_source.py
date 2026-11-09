"""Manual research promotion uses real lineage, never a synthetic daily winner."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_qualification import (
    manual_qualification_source_id,
)
from server.services.research import (
    strategy_promotion_qualification_source as source_module,
)
from server.services.research import strategy_promotion_support as support
from server.services.strategy_scan.universe.service import (
    PromotedStrategyUniverseScanService,
)


def binding():
    return {
        "source_kind": "manual_research",
        "manual_source_refs": {
            "session_id": "real-session",
            "draft_id": "real-draft",
            "backtest_run_id": "real-run",
            "critique_id": "real-critique",
            "canonical_backtest_result_id": 242,
        },
        "manual_source_fingerprint": "sha256:" + "a" * 64,
        "final_evaluation_id": "real-final",
        "final_evidence_fingerprint": "sha256:" + "b" * 64,
    }


def fail_daily(*args, **kwargs):
    raise AssertionError("manual research must not read a daily candidate or grant")


def source_fixture(monkeypatch, tmp_path):
    manual = binding()
    identity = manual_qualification_source_id(manual)
    ratio = {"op": "rolling_max_close_ratio", "window": 20}
    strategy = {
        "formula_ast": {"entry": {"op": "equal", "left": ratio, "right": ratio}}
    }
    verified = {
        "source_kind": "manual_research",
        "source_binding": manual,
        "candidate_id": identity,
        "run_id": identity,
        "draft_id": "real-draft",
        "formula_fingerprint": "formula",
        "strategy": strategy,
        "strategy_artifact_fingerprint": content_fingerprint(strategy),
        "evidence_fingerprint": content_fingerprint(manual),
        "dataset_snapshot_id": "dataset",
    }
    source = {
        "source_kind": "manual_research",
        "source_binding": manual,
        "candidate_id": identity,
        "run_id": identity,
        "draft_id": "real-draft",
        "critique_id": "real-critique",
        "comparison": {},
    }
    frozen = SimpleNamespace(
        verified=verified,
        source_candidate=source,
        source_selection=SimpleNamespace(fingerprint="selection-fingerprint"),
        source_critique={"artifact": {"analysis": "frozen critique"}},
    )
    run = {
        "qualification_run_id": "qualification",
        "source_binding": manual,
        "source_run_id": identity,
        "source_selection_id": "real-session",
        "source_selection_fingerprint": "selection-fingerprint",
        "source_backup_fingerprint": "not_applicable:manual_research",
        "baseline_result_id": 300,
    }
    candidate = {
        "qualification_run_id": "qualification",
        "source_candidate_id": identity,
        "source_draft_id": "real-draft",
        "candidate_result_id": 301,
        "comparison": {"source_binding": manual},
    }
    reopened = []
    store = SimpleNamespace(
        get_qualification_candidate=lambda _: candidate,
        get_qualification_run=lambda _: run,
        get_qualification_approval=lambda _: {"approval": "real"},
        get_qualification_backtest_source=lambda value: {"id": value},
        get_candidate=fail_daily,
    )
    monkeypatch.setattr(source_module, "ShadowResearchStore", lambda _: store)
    monkeypatch.setattr(source_module, "DailyStrategyArtifactStore", fail_daily)
    monkeypatch.setattr(
        "server.persistence.strategy_research.StrategyResearchAuditStore",
        lambda _: object(),
    )

    def freeze(**kwargs):
        assert kwargs["source_binding"] == manual
        reopened.append(deepcopy(manual))
        return frozen

    monkeypatch.setattr(
        "server.services.ai_shadow.ai_shadow_research_qualification_support.freeze_manual_qualification_source",
        freeze,
    )
    return manual, identity, frozen, run, candidate, reopened


def test_manual_source_reopens_canonical_five_refs_without_daily_rows(
    monkeypatch, tmp_path
):
    manual, _, frozen, run, candidate, reopened = source_fixture(monkeypatch, tmp_path)
    result = source_module.load_qualification_sources(
        tmp_path / "unused", "qualified", proposed_qualification_approval=None
    )
    assert result[:2] == (candidate, run)
    assert result[3] is frozen.source_candidate
    assert result[5:7] == ({"id": 300}, {"id": 301})
    assert result[7] == {
        "source_kind": "manual_research",
        "source_binding": manual,
        "strategy_artifact_fingerprint": frozen.verified[
            "strategy_artifact_fingerprint"
        ],
    }
    assert reopened == [manual]
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    "field",
    [
        "source_run_id",
        "source_selection_id",
        "source_selection_fingerprint",
        "source_backup_fingerprint",
        "comparison",
    ],
)
def test_manual_source_rejects_projection_or_lineage_drift(
    monkeypatch, tmp_path, field
):
    _, _, _, run, candidate, _ = source_fixture(monkeypatch, tmp_path)
    if field == "comparison":
        candidate[field] = {
            "source_binding": {**binding(), "final_evaluation_id": "other"}
        }
    else:
        run[field] = "other"
    with pytest.raises(ValueError, match="qualification_manual_source_binding_changed"):
        source_module.load_qualification_sources(
            tmp_path / "unused", "qualified", proposed_qualification_approval=None
        )


def test_manual_scan_reopens_source_and_final_without_daily_loader(
    monkeypatch, tmp_path
):
    manual, identity, frozen, _, _, reopened = source_fixture(monkeypatch, tmp_path)
    strategy_id = "ai_formula_shadow:" + identity
    final_calls = []
    evidence = {
        "sealed_test_id": "real-final",
        "evidence_fingerprint": manual["final_evidence_fingerprint"],
        "reservation": {
            "deployment_scope": {"scope": "complete"},
            "champion_formula_fingerprint": "sha256:"
            + content_fingerprint(frozen.verified["strategy"]["formula_ast"]),
        },
        "sealed_dataset_snapshot": {
            "immutable_dataset_id": "immutable-final",
            "date_range": {"start": "2026-01-01"},
        },
    }
    monkeypatch.setattr(
        "server.persistence.strategy_research.StrategyResearchAuditStore",
        lambda _: SimpleNamespace(
            get_sealed_test=lambda value: (
                {"evidence": evidence} if value == "real-final" else fail_daily()
            )
        ),
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result, **kwargs: final_calls.append((result, kwargs)),
    )
    monkeypatch.setattr(
        "server.contracts.recommendation_publication.publication_source_blocker",
        lambda *_: None,
    )
    promotion = {
        "decision_source": "human",
        "backtest_result_id": 301,
        "qualification_binding": {
            "source_binding": manual,
            "evidence_fingerprint": "qualified",
        },
        "daily_strategy_artifact_binding": {},
        "manual_strategy_artifact_binding": {
            "source_kind": "manual_research",
            "source_binding": manual,
            "strategy_artifact_fingerprint": frozen.verified[
                "strategy_artifact_fingerprint"
            ],
        },
    }
    service = object.__new__(PromotedStrategyUniverseScanService)
    service._db = SimpleNamespace(
        path=tmp_path / "unused",
        list_strategy_promotion_states_sync=lambda: [
            {"strategy_id": strategy_id, "stage": "paper_shadow"}
        ],
    )
    service._strategy_gate_resolver = lambda *_, **kwargs: (
        {"status": "pass", "promotion": promotion},
        [],
    )
    service._strategy_loader = fail_daily
    result, blockers = service._resolve_promoted_strategies("2026-11-03")
    assert blockers == []
    assert len(result) == 1 and result[0]["strategy_id"] == strategy_id
    assert result[0]["formula_dataset_anchor"]["dataset_id"] == "immutable-final"
    assert final_calls == [(301, {"expected_manual_source": manual})]
    assert reopened == [manual]

    promotion["manual_strategy_artifact_binding"]["strategy_artifact_fingerprint"] = (
        "tampered"
    )
    result, blockers = service._resolve_promoted_strategies("2026-11-03")
    assert not result and any(
        "manual_strategy_source_binding_changed" in item for item in blockers
    )
    assert len(final_calls) == 1


def test_manual_pipeline_passes_explicit_final_source_before_any_write(monkeypatch):
    from server.services.research import strategy_promotion_pipeline as pipeline

    readiness = {
        "strategy_id": "ai_formula_shadow:" + manual_qualification_source_id(binding()),
        "qualification_binding": {"source_binding": binding()},
        "backtest_result_id": 301,
    }
    monkeypatch.setattr(
        pipeline, "_require_ai_shadow_readiness_binding", lambda *_: None
    )
    calls = []

    def require(db, result, **kwargs):
        calls.append((result, kwargs))
        raise ValueError("final_incomplete")

    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        require,
    )
    db = SimpleNamespace(
        upsert_strategy_promotion_state_sync=fail_daily,
        record_strategy_promotion_event_sync=fail_daily,
    )
    with pytest.raises(ValueError, match="final_incomplete"):
        pipeline.StrategyPromotionPipeline(db=db).evaluate_readiness(readiness)
    assert calls == [(301, {"expected_manual_source": binding()})]


def test_manual_evidence_requires_specified_candidate_not_daily_winner(
    monkeypatch, tmp_path
):
    manual, identity, frozen, run, candidate, _ = source_fixture(monkeypatch, tmp_path)
    run.update(
        status="completed",
        selection={
            "status": "specified_candidate_qualified",
            "selected_qualification_candidate_id": "qualified",
            "winner_qualification_candidate_id": None,
        },
        account_evidence_reference="account",
        account_evidence_fingerprint="account-fp",
        valuation_snapshot_id="valuation",
        ledger_cutoff_id=4,
        ledger_fingerprint="ledger",
        reviewed_cost_model_reference="reviewed",
        reviewed_fee_schedule_fingerprint="fees",
        account_truth_source_fingerprint="truth",
        account_truth_scope_fingerprint="scope",
    )
    frozen.verified["strategy"]["formula_fingerprint"] = "formula"
    candidate.update(
        status="qualified",
        recommendation="paper_shadow_review",
        source_formula_fingerprint="formula",
        qualified_formula_fingerprint="qualified-formula",
        source_formula_semantic_fingerprint="semantic",
        qualified_formula_semantic_fingerprint="semantic",
    )
    baseline = {"metrics": {}}
    replayed = {
        "metrics": {
            "formula_fingerprint": "qualified-formula",
            "dataset_snapshot": {"snapshot_id": "dataset"},
            "fee_component_evidence": {
                "cost_model_reference": "reviewed",
                "fee_schedule_fingerprint": "fees",
            },
            "account_capital_constraint": {
                "account_state_record_fingerprint": "account-fp",
                "account_truth_source_fingerprint": "truth",
                "account_truth_scope_fingerprint": "scope",
            },
        }
    }
    gate = {
        "schema_version": support.MANUAL_FINAL_V2_ADVANCEMENT_GATE_SCHEMA,
        "source_binding": manual,
        "status": "pass",
        "evidence_fingerprint": "gate",
    }
    candidate["comparison"].update(
        research_capital_mode="account_bound",
        account_qualification_status="passed",
        baseline_source_fingerprint=content_fingerprint(baseline),
        candidate_source_fingerprint=content_fingerprint(replayed),
        promotion_gate=gate,
    )
    approval = {
        "qualification_candidate_id": "qualified",
        "qualification_run_id": "qualification",
        "target_stage": "paper_shadow",
        "qualification_candidate_fingerprint": "candidate-fp",
        "manual_confirmation_recorded": True,
    }
    artifact = {
        **frozen.verified,
        "critique_artifact": frozen.source_critique["artifact"],
    }
    monkeypatch.setattr(
        support,
        "load_qualification_sources",
        lambda *_, **kwargs: (
            candidate,
            run,
            approval,
            frozen.source_candidate,
            artifact,
            baseline,
            replayed,
            {"source_kind": "manual_research", "source_binding": manual},
        ),
    )
    monkeypatch.setattr(
        support, "qualification_candidate_fingerprint", lambda _: "candidate-fp"
    )
    monkeypatch.setattr(
        support, "qualification_formula_semantic_fingerprint", lambda _: "semantic"
    )
    account = SimpleNamespace(
        tool_name="account_state_projection.read",
        status="complete",
        authoritative=True,
        persisted_facts_only=True,
        record_fingerprint="account-fp",
        valuation_snapshot_id="valuation",
        ledger_cutoff_id=4,
        ledger_fingerprint="ledger",
    )
    monkeypatch.setattr(
        support,
        "CanonicalEvidenceRepository",
        lambda _: SimpleNamespace(get=lambda _: account),
    )
    valuation = {
        "status": "complete",
        "snapshot_id": "valuation",
        "ledger_cutoff_id": 4,
        "ledger_fingerprint": "ledger",
    }
    monkeypatch.setattr(support, "valuation_snapshot_from_row", lambda row: row)
    monkeypatch.setattr(support, "ledger_identity_from_rows", lambda _: valuation)
    monkeypatch.setattr(
        support, "strategy_advancement_backtest_view", lambda value: value
    )
    gate_calls = []

    def build(**kwargs):
        gate_calls.append(kwargs)
        return SimpleNamespace(to_json_dict=lambda: gate)

    monkeypatch.setattr(support, "build_manual_final_strategy_advancement_gate", build)
    monkeypatch.setattr(support, "build_strategy_advancement_gate", fail_daily)
    monkeypatch.setattr(
        support, "is_valid_passed_strategy_advancement_gate", lambda _: True
    )
    monkeypatch.setattr(support, "active_review_matches_fee_evidence", lambda *_: [])
    monkeypatch.setattr(
        support,
        "is_valid_passed_research_account_capital_evidence",
        lambda *_, **kwargs: True,
    )
    monkeypatch.setattr(
        support, "_dataset_replay_evidence_from_binding", lambda *_: {"status": "pass"}
    )
    db = SimpleNamespace(
        _path=tmp_path / "unused",
        get_valuation_snapshot_sync=lambda _: valuation,
        get_all_ledger_entries_sync=lambda: [],
    )
    evidence, blockers = support.resolve_ai_shadow_qualification_promotion_evidence(
        db, "qualified"
    )
    assert blockers == []
    assert evidence["source_candidate_id"] == identity
    assert evidence["qualification_binding"]["source_binding"] == manual
    assert evidence["daily_strategy_artifact_binding"] == {}
    assert evidence["manual_strategy_artifact_binding"]["source_binding"] == manual
    assert gate_calls[0]["critique_evidence"][
        "artifact_fingerprint"
    ] == content_fingerprint(frozen.source_critique["artifact"])
    run["selection"] = {
        "status": "winner_selected",
        "winner_qualification_candidate_id": "qualified",
    }
    _, blockers = support.resolve_ai_shadow_qualification_promotion_evidence(
        db, "qualified"
    )
    assert "ai_shadow_qualification_winner_not_completed" in blockers


@pytest.mark.parametrize("failure", [None, "source", "final"])
def test_human_manual_gate_reopens_final_and_keeps_cold_source_failures(
    monkeypatch, failure
):
    manual = binding()
    identity = manual_qualification_source_id(manual)
    strategy_id = "ai_formula_shadow:" + identity
    readiness = {
        "strategy_id": strategy_id,
        "backtest_result_id": 301,
        "qualification_candidate_id": "qualified",
        "qualification_binding": {"source_binding": manual},
        "daily_strategy_artifact_binding": {},
        "strategy_advancement_gate": {"evidence_fingerprint": "gate"},
    }
    state = {
        "stage": "paper_shadow",
        "gate_status": "paper_shadow_enabled",
        "live_like_enabled": False,
        "backtest_result_id": 301,
        "payload_json": {
            "readiness": readiness,
            "human_review": {
                "reviewer": "human:user",
                "review_note": "explicit manual publication",
                "confirmation_recorded": True,
                "strategy_advancement_gate_fingerprint": "gate",
            },
        },
    }
    db = SimpleNamespace(
        get_strategy_promotion_state_sync=lambda _: state,
        get_ai_shadow_strategy_promotion_binding_sync=fail_daily,
    )
    monkeypatch.setattr(support, "_ai_shadow_readiness_binding_blockers", lambda *_: [])
    evidence = {
        "qualification_binding": {"source_binding": manual},
        "manual_strategy_artifact_binding": {
            "source_kind": "manual_research",
            "source_binding": manual,
        },
    }
    monkeypatch.setattr(
        support,
        "_resolve_ai_shadow_qualification_promotion_evidence",
        lambda *_: (
            ({}, ["cold_source_changed"]) if failure == "source" else (evidence, [])
        ),
    )
    final_calls = []

    def require(db, result, **kwargs):
        final_calls.append((result, kwargs))
        if failure == "final":
            raise ValueError("final_changed")

    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        require,
    )
    result, blockers = support.resolve_human_ai_shadow_strategy_promotion_binding(
        db, strategy_id
    )
    assert final_calls == [(301, {"expected_manual_source": manual})]
    assert result["normalized_research"] is False
    assert result["status"] == ("blocked" if failure else "pass")
    if failure == "source":
        assert "cold_source_changed" in blockers
    elif failure == "final":
        assert "manual_strategy_final_evaluation_invalid:final_changed" in blockers
    else:
        assert (
            result["manual_strategy_artifact_binding"]
            == evidence["manual_strategy_artifact_binding"]
        )


def test_manual_profile_cannot_leak_into_legacy_or_another_final(monkeypatch):
    monkeypatch.setattr(
        support, "is_valid_passed_strategy_advancement_gate", lambda _: True
    )
    manual = binding()
    gate = {
        "schema_version": support.MANUAL_FINAL_V2_ADVANCEMENT_GATE_SCHEMA,
        "source_binding": manual,
    }
    assert support._qualification_advancement_gate_valid(gate, manual)
    assert not support._qualification_advancement_gate_valid(gate, None)
    assert not support._qualification_advancement_gate_valid(
        gate, {**manual, "final_evaluation_id": "other"}
    )
    assert not support._qualification_advancement_gate_valid(
        {"schema_version": "legacy"}, manual
    )
    assert support._qualification_advancement_gate_valid(
        {"schema_version": "legacy"}, None
    )
