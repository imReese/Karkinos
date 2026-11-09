"""Manual account consumers use real comparator identities and explicit approval.

The requirements fixture isolates already-verified final/fee adapters. It does
not synthesize 60 forward sessions or claim end-to-end financial qualification.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
import pytest_asyncio

from server.contracts.ai_shadow_research_qualification import (
    manual_qualification_source_id,
)
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.research import research_final_evaluation as owner
from tests.server.test_research_final_evaluation import harness  # noqa: F401
from tests.server.test_research_final_statistical_v2 import v2  # noqa: F401


def _source():
    return {
        "source_kind": "manual_research",
        "manual_source_refs": {
            "session_id": "fixture-session",
            "draft_id": "fixture-draft",
            "backtest_run_id": "fixture-backtest",
            "critique_id": "fixture-critique",
            "canonical_backtest_result_id": 242,
        },
        "manual_source_fingerprint": "sha256:" + "a" * 64,
        "final_evaluation_id": "fixture-final",
        "final_evidence_fingerprint": "b" * 64,
    }


def _evidence(binding=None):
    source = _source()
    return {
        "sealed_test_id": source["final_evaluation_id"],
        "evidence_fingerprint": source["final_evidence_fingerprint"],
        "reservation": {
            **(binding or {}),
            **{
                k: source[k]
                for k in (
                    "source_kind",
                    "manual_source_refs",
                    "manual_source_fingerprint",
                )
            },
        },
        "deployment_assessment": {"status": "pass"},
    }


@pytest_asyncio.fixture
async def requirements(v2, monkeypatch):
    t = v2
    evidence = _evidence(deepcopy(t.binding))
    original = deepcopy(evidence)
    validated = []
    monkeypatch.setattr(owner, "require_valid_final_evaluation", validated.append)
    monkeypatch.setattr(owner, "_require_manual_source_binding", lambda *_: None)
    monkeypatch.setattr(
        StrategyResearchAuditStore,
        "get_sealed_test",
        lambda _self, key: {"status": "completed", "evidence": original},
    )
    fees = {
        "review_id": "synthetic-reviewed-fee",
        "review_fingerprint": "c" * 64,
        "cost_model_reference": "synthetic-reviewed-cost",
        "fee_evidence": {"account_truth_scope_fingerprint": "synthetic-account"},
    }
    resolved = []
    monkeypatch.setattr(
        "server.services.account.reviewed_fee_schedule.resolve_frozen_deployment_fee_schedule",
        lambda _db, fee, universe: resolved.append((fee, universe)),
    )
    monkeypatch.setattr(
        "server.contracts.recommendation_publication.read_publication_grant",
        lambda *_a, **_k: pytest.fail("manual applicability must not read a grant"),
    )
    kwargs = {
        "account_scope_fingerprint": "synthetic-account",
        "initial_cash": t.binding["initial_cash"],
        "entry_board_policy": t.binding["entry_board_policy"],
        "fee_schedule_binding": fees,
    }
    return SimpleNamespace(
        t=t,
        evidence=evidence,
        original=original,
        kwargs=kwargs,
        validated=validated,
        resolved=resolved,
    )


@pytest.mark.asyncio
async def test_manual_reviewed_cost_identities_keep_fixed_science_without_grant(
    requirements,
):
    r = requirements
    actual = owner.manual_account_applicability_requirements(
        r.t.h.db, r.evidence, **r.kwargs
    )
    profile = actual["statistical_policy"]
    old = r.t.sim["statistical_policy"]
    assert actual["authority_effect"] == "none"
    assert not {"grant_id", "generation", "authorization", "expires_at"}.intersection(
        actual
    )
    assert actual["source_binding"] == _source()
    assert r.validated == [r.evidence] and len(r.resolved) == 1
    assert r.evidence == r.original
    assert {k: v for k, v in profile.items() if k != "comparator_bindings"} == {
        k: v for k, v in old.items() if k != "comparator_bindings"
    }
    assert len(profile["comparator_bindings"]) == 11
    assert all(
        profile["comparator_bindings"][k] != v
        for k, v in old["comparator_bindings"].items()
    )
    assert actual["risk_limits"] == r.t.sim["risk_limits"]
    derived = {**r.evidence["reservation"], "manual_account_requirements": actual}
    derived.pop("simulation_policy")
    assert owner._validation_policy(derived) == actual
    derived["publication_grant"] = {"grant_id": "invented"}
    with pytest.raises(ValueError, match="manual_account_requirements_invalid"):
        owner._validation_policy(derived)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["cash", "board", "fee_account", "failed_final", "persisted_drift"]
)
async def test_manual_requirements_reject_scope_or_final_drift(requirements, change):
    r = requirements
    if change == "cash":
        r.kwargs["initial_cash"] = "1"
    elif change == "board":
        r.kwargs["entry_board_policy"] = {"unapproved": True}
    elif change == "fee_account":
        r.kwargs["fee_schedule_binding"]["fee_evidence"][
            "account_truth_scope_fingerprint"
        ] = "other"
    elif change == "failed_final":
        r.evidence["deployment_assessment"]["status"] = "insufficient_evidence"
    else:
        r.evidence["reservation"]["manual_source_fingerprint"] = "sha256:" + "d" * 64
    with pytest.raises(ValueError):
        owner.manual_account_applicability_requirements(
            r.t.h.db, r.evidence, **r.kwargs
        )


def test_manual_account_read_requires_exact_source_and_canonical_human_approval(
    monkeypatch, tmp_path
):
    source = _source()
    evidence = _evidence()
    candidate = {
        "qualification_candidate_id": "qualified-manual",
        "comparison": {"source_binding": source},
    }
    run = {
        "source_binding": source,
        "account_truth_scope_fingerprint": "account",
        "initial_cash_text": "1000000",
    }
    expected = {
        "qualification_candidate_id": "qualified-manual",
        "approved_by": "human:fixture",
        "notes": "exact reviewed source",
        "confirmation": "fixture canonical confirmation",
        "created_at": "2026-01-01",
        "manual_confirmation_recorded": True,
    }
    state = {"approval": None}
    store = SimpleNamespace(
        qualification_for_backtest_result=lambda _id: {
            "candidate": candidate,
            "run": run,
        },
        get_qualification_approval=lambda _id: state["approval"],
        prepare_qualification_candidate_approval=lambda *_a, **_k: expected,
    )
    monkeypatch.setattr(
        "server.persistence.ai_shadow_research.ShadowResearchStore", lambda _: store
    )
    calls = []
    monkeypatch.setattr(
        owner,
        "manual_account_applicability_requirements",
        lambda *a, **k: calls.append(k) or {"authority_effect": "none"},
    )
    db = SimpleNamespace(path=tmp_path / "unused.db")
    result = {"id": 900, "metrics_json": {"entry_board_policy": {"main_only": True}}}
    with pytest.raises(ValueError, match="human_approval_required"):
        owner._manual_qualified_account_requirements(db, result, evidence, source, None)
    with pytest.raises(ValueError, match="human_approval_invalid"):
        owner._manual_qualified_account_requirements(
            db,
            result,
            evidence,
            source,
            {**expected, "manual_confirmation_recorded": False},
        )
    assert calls == []
    state["approval"] = deepcopy(expected)
    assert owner._manual_qualified_account_requirements(
        db, result, evidence, source, None
    ) == {"authority_effect": "none"}
    assert calls[0]["initial_cash"] == "1000000"
    run["source_binding"] = {**source, "final_evidence_fingerprint": "e" * 64}
    with pytest.raises(ValueError, match="source_binding_drift"):
        owner._manual_qualified_account_requirements(
            db, result, evidence, source, expected
        )


def test_manual_final_publication_route_has_no_daily_candidate_or_grant_fallback(
    monkeypatch, tmp_path
):
    evidence = _evidence({"deployment_scope": {"scope": "frozen"}})
    db = SimpleNamespace(_path=tmp_path / "unused.db")
    result = {"metrics_json": {"independent_evaluation": evidence}}
    monkeypatch.setattr(
        StrategyResearchAuditStore, "research_backtest_result", lambda *_: result
    )
    monkeypatch.setattr(
        "server.services.research.strategy_promotion_support.strategy_dataset_store_root",
        lambda _: tmp_path,
    )
    calls = []
    monkeypatch.setattr(
        owner,
        "verify_deployment_validation",
        lambda *a, **k: calls.append(k) or {"status": "pass"},
    )
    with pytest.raises(ValueError, match="manual_qualification_source_required"):
        owner.require_new_publication_final_evaluation(
            db, 900, expected_candidate_id=manual_qualification_source_id(_source())
        )
    assert calls == []
    owner.require_new_publication_final_evaluation(
        db,
        900,
        expected_manual_source=_source(),
        proposed_qualification_approval={"approval": "one specific source"},
    )
    assert calls == [
        {
            "result_id": 900,
            "expected_manual_source": _source(),
            "proposed_qualification_approval": {"approval": "one specific source"},
        }
    ]


@pytest.mark.parametrize(
    "forward_review", [None, {"review": "existing exact forward book"}]
)
@pytest.mark.parametrize("fail_final_call", [None, 1, 2])
def test_manual_command_uses_original_result_ref_without_daily_lookup(
    monkeypatch, forward_review, fail_final_call
):
    from server.contracts.ai_shadow_research_qualification import (
        SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
    )
    from server.services.ai_shadow.ai_shadow_research_commands import (
        AiShadowResearchCommandsMixin,
    )
    from tests.server.test_ai_shadow_research_qualification_promotion import (
        _evidence as promotion_evidence,
    )

    evidence = promotion_evidence()
    evidence.update(
        source_candidate_id=manual_qualification_source_id(_source()),
        qualification_binding={"source_binding": _source()},
        daily_strategy_artifact_binding={},
    )
    calls = []

    class Store:
        def get_candidate(self, _identity):
            pytest.fail("manual approval must not read a daily candidate")

        def prepare_qualification_candidate_approval(self, identity, **kwargs):
            return {
                "qualification_approval_id": "qualification-approval",
                "qualification_run_id": "qualification-run",
                "qualification_candidate_id": identity,
                "target_stage": "paper_shadow",
                "qualification_candidate_fingerprint": "sha256:candidate",
                "created_at": kwargs.pop("now"),
                **kwargs,
            }

        def approve_qualification_candidate_for_paper_shadow(self, identity, **kwargs):
            assert kwargs["current_evidence_validator"]() == (evidence, [])
            calls.append(kwargs)
            return {
                "qualification_approval": kwargs["approval"],
                "strategy_promotion": {
                    "strategy_id": kwargs["strategy_id"],
                    "stage": "paper_shadow",
                    "live_like_enabled": False,
                    "payload": kwargs["state_payload"],
                },
            }

        def get_public_qualification_run(self, _identity):
            return {}

        def get_public_qualification_candidate(self, _identity):
            return {}

    service = AiShadowResearchCommandsMixin()
    service._store = Store()
    service._db = SimpleNamespace(get_strategy_promotion_state_sync=lambda _: None)
    service._utc_now = lambda: "2026-09-01T10:00:00+00:00"
    monkeypatch.setattr(
        "server.services.ai_shadow.ai_shadow_research_commands.resolve_ai_shadow_qualification_promotion_evidence",
        lambda *_a, **_k: (evidence, []),
    )
    final_calls = []

    def verify_final(_db, result_id, **kwargs):
        final_calls.append((result_id, kwargs))
        if len(final_calls) == fail_final_call:
            raise ValueError("synthetic changed final/account evidence")

    monkeypatch.setattr(owner, "require_new_publication_final_evaluation", verify_final)
    forward_ids = []
    monkeypatch.setattr(
        "server.services.decision.forward_paper_review.verify_forward_paper_review",
        lambda _db, review, *, source_result_id: (
            forward_ids.append(source_result_id) or review
        ),
    )
    if fail_final_call is not None:
        with pytest.raises(
            ValueError, match="synthetic changed final/account evidence"
        ):
            service.approve_qualification_candidate(
                "qualified-candidate",
                approved_by="human:owner",
                notes="specific manual source",
                confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
                forward_review=forward_review,
            )
        assert calls == []
        assert len(final_calls) == fail_final_call
        return
    outcome = service.approve_qualification_candidate(
        "qualified-candidate",
        approved_by="human:owner",
        notes="specific manual source",
        confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
        forward_review=forward_review,
    )
    assert forward_ids == ([242, 242] if forward_review is not None else [])
    assert [call[0] for call in final_calls] == [22, 22]
    assert all(call[1]["expected_manual_source"] == _source() for call in final_calls)
    assert all(
        call[1]["proposed_qualification_approval"]["qualification_candidate_id"]
        == "qualified-candidate"
        for call in final_calls
    )
    assert calls[0]["readiness"]["backtest_result_id"] == 22
    assert calls[0]["readiness"]["qualification_binding"]["source_binding"] == _source()
    assert calls[0]["readiness"]["daily_strategy_artifact_binding"] == {}
    assert outcome["promotion_decision"]["capital_authority_effect"] == "none"


@pytest.mark.parametrize("crash", [False, True])
def test_manual_selected_candidate_atomic_approval_never_requires_five_batch_winner(
    tmp_path, monkeypatch, crash
):
    import sqlite3

    from server.contracts.ai_shadow_research_qualification import (
        SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
    )
    from tests.server.test_ai_shadow_research_qualification_persistence import (
        _atomic_promotion_args,
    )
    from tests.server.test_manual_research_qualification_persistence import (
        STAMP,
        manual_source,
        save_candidate,
    )

    store, binding, args = manual_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**args)
    candidate = save_candidate(store, run, binding)
    selected = {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_run_id": run["qualification_run_id"],
        "source_run_id": run["source_run_id"],
        "market_date": run["market_date"],
        "source_binding": binding,
        "status": "specified_candidate_qualified",
        "selected_qualification_candidate_id": candidate["qualification_candidate_id"],
        "winner_qualification_candidate_id": None,
        "provider_call_performed": False,
        "broker_order_created": False,
        "capital_authority_granted": False,
    }
    run = store.finish_qualification_run(
        run["qualification_run_id"],
        status="completed",
        selection=selected,
        blockers=[],
        failure_code=None,
        now=STAMP,
    )
    values = _atomic_promotion_args(store, run, candidate)
    values["readiness"]["qualification_binding"] = {"source_binding": binding}
    values["readiness"]["daily_strategy_artifact_binding"] = {}
    if crash:

        def fail(*_args, **_kwargs):
            raise RuntimeError("synthetic promotion event failure")

        monkeypatch.setattr(
            "server.persistence.ai_shadow_research_qualification_promotion._insert_qualification_promotion_event",
            fail,
        )
        with pytest.raises(RuntimeError, match="synthetic promotion event failure"):
            store.approve_qualification_candidate_for_paper_shadow(**values)
    else:
        saved = store.approve_qualification_candidate_for_paper_shadow(**values)
        assert saved["strategy_promotion"]["stage"] == "paper_shadow"
    with sqlite3.connect(store.path) as conn:
        for table in (
            "ai_shadow_research_qualification_approvals",
            "strategy_promotion_states",
            "strategy_promotion_events",
        ):
            assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == (
                0 if crash else 1
            )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_candidates"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_shadow_research_runs").fetchone()[0]
            == 0
        )
    assert (
        store.get_qualification_run(run["qualification_run_id"])["selection"][
            "winner_qualification_candidate_id"
        ]
        is None
    )


def test_reviewed_replay_cannot_use_requirements_from_another_manual_final():
    evidence = _evidence({"simulation_policy": {}})
    other = {**_source(), "final_evaluation_id": "different-final"}
    with pytest.raises(ValueError, match="manual_qualification_source_binding_drift"):
        owner._simulation_account_replay_inputs(
            None,
            None,
            {},
            evidence,
            {
                "schema_version": owner.MANUAL_ACCOUNT_REQUIREMENTS_SCHEMA,
                "source_binding": other,
            },
        )
