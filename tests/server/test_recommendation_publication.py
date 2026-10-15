from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from server.contracts.ai_shadow_research_qualification import (
    public_qualification_approval_projection,
    public_qualification_candidate_projection,
)
from server.contracts.content_identity import content_fingerprint
from server.contracts.recommendation_publication import (
    PUBLICATION_AUTHORIZE,
    PUBLICATION_POLICY_SCHEMA,
    read_publication_grant,
)
from server.db import AppDatabase
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.services.recommendation_publication import (
    RecommendationPublicationService,
    publication_source_blocker,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]
NOW = "2026-10-15T10:00:00+00:00"


def _grant(**patch):
    from server.services.account_board_permissions import freeze_entry_board_policy

    statistical = {
        "method": "paired_moving_block_bootstrap.v1",
        "minimum_observations": 60,
        "block_length": 5,
        "minimum_effective_blocks": 10,
        "bootstrap_samples": 2000,
        "significance_level": "0.05",
        "minimum_net_excess": "0.001",
        "decision_checkpoint": "2027-02-15",
    }
    return {
        "schema_version": PUBLICATION_POLICY_SCHEMA,
        "enabled": True,
        "grant_id": str(uuid4()),
        "generation": str(uuid4()),
        "authorization": PUBLICATION_AUTHORIZE,
        "account_scope_fingerprint": "a" * 64,
        "allocation_scope": "stock_core",
        "deployment_scope_fingerprint": "b" * 64,
        "strategy_family": "formula",
        "max_initial_cash": "50000",
        "risk_limits": {
            "max_drawdown": "0.2",
            "max_gross_weight": "1",
            "max_symbol_weight": "0.25",
            "max_positions": 4,
        },
        "max_publications": 2,
        "max_final_tests": 2,
        "total_error_budget": "0.05",
        "statistical_policy": statistical,
        "statistical_policy_fingerprint": content_fingerprint(statistical),
        "entry_board_policy": freeze_entry_board_policy(None, NOW[:10]),
        "min_net_improvement": "0.001",
        "cooldown_days": 1,
        "incumbent_strategy_id": None,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "updated_by": "human:test-owner",
        **patch,
    }


@pytest.fixture
def book(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(db.path)
    store.init()
    return db, store


def _state(db, identity):
    return db.upsert_strategy_promotion_state_sync(
        strategy_id=identity,
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=1,
        payload={"human_review": {"reviewer": "human:owner"}},
    )


def _decision(grant, *, incumbent=None, suffix="1"):
    return {
        "grant_id": grant["grant_id"],
        "generation": grant["generation"],
        "decision_id": "decision-" + suffix,
        "expected_incumbent_strategy_id": incumbent,
        "created_at": NOW,
    }


def _publish(store, grant, *, incumbent=None, expected=None, validate=None, suffix="1"):
    readiness = {"backtest_result_id": 2, "qualification_candidate_id": "qualified"}
    return store.publish_qualified_candidate_under_policy(
        strategy_id="ai_formula_shadow:new" + suffix,
        readiness=readiness,
        decision=_decision(
            grant,
            incumbent=incumbent["strategy_id"] if incumbent else None,
            suffix=suffix,
        ),
        expected_state=expected,
        incumbent=incumbent,
        current_evidence_validator=validate or (lambda: readiness),
        now=NOW,
    )


def test_grant_default_off_and_generation_cas_and_revocation(book):
    db, store = book
    with pytest.raises(ValueError, match="grant_missing"):
        read_publication_grant(db)
    grant = _grant()
    store.configure_publication_grant(policy=grant, expected_generation=None, now=NOW)
    assert read_publication_grant(db, now=NOW)["grant_id"] == grant["grant_id"]
    with pytest.raises(ValueError, match="generation_conflict"):
        store.configure_publication_grant(
            policy=grant, expected_generation=None, now=NOW
        )
    revoked = {
        **grant,
        "enabled": False,
        "generation": str(uuid4()),
        "authorization": "",
    }
    store.configure_publication_grant(
        policy=revoked, expected_generation=grant["generation"], now=NOW
    )
    with pytest.raises(ValueError, match="grant_disabled"):
        read_publication_grant(db, now=NOW)
    with pytest.raises(ValueError, match="changed_or_inactive"):
        _publish(store, grant)
    assert db.list_strategy_promotion_states_sync() == []


def test_old_grant_without_frozen_entry_mask_is_auditable_and_revocable_only(book):
    db, store = book
    old = _grant()
    old.pop("entry_board_policy")
    store.configure_publication_grant(policy=old, expected_generation=None, now=NOW)
    assert (
        read_publication_grant(db, require_active=False)["generation"]
        == old["generation"]
    )
    with pytest.raises(ValueError, match="entry_board_policy_missing"):
        read_publication_grant(db, now=NOW)
    service = RecommendationPublicationService(
        db, store, now=lambda: datetime.fromisoformat(NOW)
    )
    status = service.status(include_preview=False)
    assert status["status"] == "invalid"
    assert status["policy"]["generation"] == old["generation"]
    from server.contracts.recommendation_publication import PUBLICATION_REVOKE

    revoked = service.update(
        {
            "enabled": False,
            "expected_generation": old["generation"],
            "confirmation": PUBLICATION_REVOKE,
        }
    )
    assert revoked["status"] == "disabled"
    assert "entry_board_policy" not in revoked["policy"]


def test_policy_publish_replaces_only_named_incumbent_and_is_restart_idempotent(book):
    db, store = book
    incumbent = _state(db, "ai_formula_shadow:incumbent")
    _state(db, "unrelated-income-strategy")
    grant = _grant()
    store.configure_publication_grant(policy=grant, expected_generation=None, now=NOW)
    result = _publish(store, grant, incumbent=incumbent)
    payload = json.loads(result["strategy_promotion"]["payload_json"])
    assert payload["decision_source"] == "policy"
    assert "human_review" not in payload
    assert "human_approval_id" not in payload["readiness"]
    assert (
        db.get_strategy_promotion_state_sync(incumbent["strategy_id"])["stage"]
        == "retired"
    )
    assert (
        db.get_strategy_promotion_state_sync("unrelated-income-strategy")["stage"]
        == "paper_shadow"
    )
    restarted = ShadowResearchStore(db.path)
    replay = _publish(
        restarted, grant, incumbent=incumbent, expected=result["strategy_promotion"]
    )
    assert replay["reused"] is True


@pytest.mark.parametrize("failure", ["evidence", "incumbent"])
def test_policy_publication_rolls_back_without_reviving_or_retiring_other_sources(
    book, failure
):
    db, store = book
    incumbent = _state(db, "ai_formula_shadow:incumbent")
    unrelated = _state(db, "unrelated")
    grant = _grant()
    store.configure_publication_grant(policy=grant, expected_generation=None, now=NOW)
    if failure == "incumbent":
        db.upsert_strategy_promotion_state_sync(
            strategy_id=incumbent["strategy_id"],
            stage="paused",
            gate_status="paused",
            live_like_enabled=False,
            missing_requirements=[],
            backtest_result_id=1,
            payload={},
        )
    with pytest.raises(ValueError, match="evidence_changed|incumbent_state_conflict"):
        _publish(
            store,
            grant,
            incumbent=incumbent,
            validate=(lambda: {"backtest_result_id": 999})
            if failure == "evidence"
            else None,
        )
    assert db.get_strategy_promotion_state_sync("ai_formula_shadow:new1") is None
    assert (
        db.get_strategy_promotion_state_sync(unrelated["strategy_id"])["stage"]
        == "paper_shadow"
    )
    expected = "paused" if failure == "incumbent" else "paper_shadow"
    assert (
        db.get_strategy_promotion_state_sync(incumbent["strategy_id"])["stage"]
        == expected
    )


def test_publication_budget_is_not_reset_by_a_new_generation(book):
    db, store = book
    grant = _grant(max_publications=1)
    store.configure_publication_grant(policy=grant, expected_generation=None, now=NOW)
    _publish(store, grant)
    renewed = {**grant, "generation": str(uuid4())}
    store.configure_publication_grant(
        policy=renewed, expected_generation=grant["generation"], now=NOW
    )
    with pytest.raises(ValueError, match="count_budget_exhausted"):
        _publish(store, renewed, suffix="2")


def test_requalification_of_same_usable_final_does_not_spend_another_publication(
    book, monkeypatch
):
    db, store = book
    grant = _grant(max_publications=1)
    store.configure_publication_grant(policy=grant, expected_generation=None, now=NOW)
    saved = _publish(store, grant)["strategy_promotion"]
    payload = json.loads(saved["payload_json"])
    payload["publication_decision"].update(
        candidate_id="candidate",
        final_evaluation_id="same-final",
        deployment_validation_fingerprint="same-verified-final",
    )
    db.upsert_strategy_promotion_state_sync(
        strategy_id=saved["strategy_id"],
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=2,
        payload=payload,
    )
    readiness = {
        "strategy_id": saved["strategy_id"],
        "candidate_id": "candidate",
        "qualification_candidate_id": "new-current-qualification",
        "backtest_result_id": 2,
        "deployment_validation": {
            "final_evaluation_id": "same-final",
            "evidence_fingerprint": "same-verified-final",
        },
    }
    monkeypatch.setattr(
        RecommendationPublicationService, "readiness", lambda *args, **kwargs: readiness
    )
    import server.services.recommendation_publication as publications

    monkeypatch.setattr(
        publications,
        "resolve_policy_publication_binding",
        lambda *args: ({"status": "pass"}, []),
    )
    service = RecommendationPublicationService(db, store, now=lambda: NOW)
    assert service.publish("new-current-qualification")["reused"] is True
    assert len(db.list_strategy_promotion_events_sync(saved["strategy_id"])) == 1
    monkeypatch.setattr(
        publications,
        "resolve_policy_publication_binding",
        lambda *args: ({"status": "blocked"}, ["evidence_changed"]),
    )
    with pytest.raises(ValueError, match="publication_count_budget_exhausted"):
        service.publish("new-current-qualification")


def test_legacy_automation_cannot_be_presented_as_human_or_usable_publication():
    record = public_qualification_approval_projection(
        {"approved_by": "automation:optimal_strategy_gate"}
    )
    assert record["manual_confirmation_recorded"] is False
    assert record["decision_source"] == "legacy_ungranted"
    state = {
        "payload_json": json.dumps(
            {"human_review": {"reviewer": "automation:optimal_strategy_gate"}}
        )
    }
    assert (
        publication_source_blocker(object(), state)
        == "legacy_automated_publication_has_no_grant"
    )


def test_public_final_summary_preserves_unknown_and_redacts_account_capital():
    assert (
        public_qualification_candidate_projection({})["deployment_validation"] is None
    )
    projected = public_qualification_candidate_projection(
        {
            "source_candidate_id": "candidate",
            "comparison": {
                "candidate": {
                    "independent_evaluation": {
                        "reservation": {
                            "candidate_id": "candidate",
                            "effective_checkpoint": "2027-02-15",
                            "initial_cash": "47251.39",
                            "fee_schedule": {
                                "cost_model_reference": "reviewed:fixture"
                            },
                        },
                        "deployment_assessment": {
                            "status": "insufficient_evidence",
                            "blockers": ["deployment_independent_sample_insufficient"],
                        },
                    }
                },
            },
        }
    )
    assert projected["deployment_validation"] == {
        "status": "insufficient_evidence",
        "checkpoint": "2027-02-15",
        "initial_cash": None,
        "fee_cost_model_reference": "reviewed:fixture",
        "blockers": ["deployment_independent_sample_insufficient"],
    }
    assert "47251.39" not in json.dumps(projected)


def test_revoked_grant_excludes_only_policy_source_and_projects_validated_source(
    book, monkeypatch
):
    db, store = book
    grant = _grant()
    store.configure_publication_grant(policy=grant, expected_generation=None, now=NOW)
    _state(db, "ai_formula_shadow:human")
    _publish(store, grant)
    revoked = {
        **grant,
        "enabled": False,
        "generation": str(uuid4()),
        "authorization": "",
    }
    store.configure_publication_grant(
        policy=revoked,
        expected_generation=grant["generation"],
        now=NOW,
    )
    monkeypatch.setattr(
        "server.services.strategy_promotion_support.resolve_human_ai_shadow_strategy_promotion_binding",
        lambda db, strategy_id: ({"status": "pass", "decision_source": "human"}, []),
    )
    status = RecommendationPublicationService(db, store).status(include_preview=False)
    assert status["status"] == "disabled"
    assert status["usable_current_sources"] == [
        {"strategy_id": "ai_formula_shadow:human", "decision_source": "human"},
    ]
    assert status["excluded_sources"] == [
        {
            "strategy_id": "ai_formula_shadow:new1",
            "blocker": "publication_grant_inactive_or_invalid",
        },
    ]
    assert (
        publication_source_blocker(
            object(),
            {"payload_json": json.dumps({"human_review": {"reviewer": "Alice"}})},
        )
        is None
    )


def test_owner_preview_binds_current_scope_and_budget_before_enabling(
    book, monkeypatch
):
    from server.services.reviewed_fee_schedule_policy import (
        NOTIONAL_ENVELOPE_SCHEMA_VERSION,
        fingerprint_payload,
    )

    db, store = book

    def review_status(maximum="25000", *, start="2020-01-01", end="2099-12-31"):
        envelope = {
            "schema_version": NOTIONAL_ENVELOPE_SCHEMA_VERSION,
            "enforcement_mode": "maximum_matched_historical_gross_by_asset_class",
            "asset_classes": ["stock"],
            "limits": {
                "stock": {"maximum_gross_amount": maximum, "matched_trade_count": 2}
            },
        }
        envelope["evidence_fingerprint"] = fingerprint_payload(envelope)
        return {
            "status": "active",
            "review": {
                "account_truth_scope_fingerprint": "a" * 64,
                "effective_start_date": start,
                "effective_end_date": end,
                "preview": {
                    "component_reconciliation": {
                        "reconciled_notional_envelope": envelope
                    }
                },
            },
        }

    from server.services.valuation_snapshot import build_current_valuation_snapshot

    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp=NOW,
        amount=50000,
        asset_class="cash",
    )
    real_valuation = build_current_valuation_snapshot(
        db, now=datetime.fromisoformat(NOW)
    )
    monkeypatch.setattr(
        "server.services.valuation_snapshot.build_current_valuation_snapshot",
        lambda db, **kwargs: real_valuation,
    )
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_reviewed_fee_schedule_review_status",
        lambda state: review_status(),
    )
    service = RecommendationPublicationService(
        db, store, now=lambda: datetime.fromisoformat(NOW), state=object()
    )
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_reviewed_fee_schedule_review_status",
        lambda state: review_status(end="2026-12-31"),
    )
    uncovered = service.preview({})
    assert uncovered["proposed_binding"] is None
    assert uncovered["preview_blockers"] == [
        "publication_preview_reviewed_fee_checkpoint_not_covered"
    ]
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_reviewed_fee_schedule_review_status",
        lambda state: review_status(),
    )
    preview = service.preview({"max_final_tests": 10})
    proposed = preview["proposed_binding"]
    assert proposed["account_scope_fingerprint"] == "a" * 64
    assert proposed["entry_board_policy"]["allowed_boards"] == ["main"]
    assert (
        preview["binding_source"]["entry_board_policy"]
        == proposed["entry_board_policy"]
    )
    assert preview["binding_source"]["reviewed_fee_schedule"] == {
        "review_id": None,
        "effective_start_date": "2020-01-01",
        "effective_end_date": "2099-12-31",
    }
    assert proposed["deployment_scope_fingerprint"].startswith("sha256:")
    assert proposed["statistical_policy"]["significance_level"] == "0.005"
    assert proposed["statistical_policy"]["bootstrap_samples"] == 100000
    assert proposed["statistical_policy"]["checkpoint_interval_days"] == 120
    assert proposed["risk_limits"]["max_symbol_weight"] == "0.30"
    assert (
        preview["binding_source"]["portfolio_target_limits"]["max_symbol_weight"]
        == "0.25"
    )
    unsupported = service.preview(
        {"risk_limits": {**proposed["risk_limits"], "max_positions": 2}}
    )
    assert unsupported["proposed_binding"] is None
    assert unsupported["preview_blockers"] == [
        "publication_preview_risk_limits_below_fixed_portfolio_targets"
    ]
    assert proposed["statistical_policy_fingerprint"] == content_fingerprint(
        proposed["statistical_policy"]
    )
    infeasible = service.preview({"expires_at": "2027-01-01T00:00:00+00:00"})
    assert infeasible["proposed_binding"] is None
    assert infeasible["preview_blockers"] == [
        "publication_preview_checkpoint_not_before_expiry"
    ]
    under_resampled = service.preview({"max_final_tests": 100})
    assert under_resampled["proposed_binding"] is None
    assert under_resampled["preview_blockers"] == [
        "publication_preview_bootstrap_tail_insufficient"
    ]
    too_long = service.preview(
        {
            "statistical_policy": {
                **proposed["statistical_policy"],
                "minimum_observations": 2001,
            }
        }
    )
    assert too_long["proposed_binding"] is None
    assert too_long["preview_blockers"] == [
        "publication_statistical_observation_budget_exceeded"
    ]
    recurring = service.preview(
        {
            "statistical_policy": {
                **proposed["statistical_policy"],
                "decision_checkpoint": "2026-06-01",
            },
            "expires_at": "2026-12-01T00:00:00+00:00",
        }
    )
    assert recurring["proposed_binding"] is None
    assert recurring["preview_blockers"] == [
        "publication_preview_checkpoint_not_before_expiry"
    ]
    assert service.status()["status"] == "disabled"
    request = {
        **proposed,
        "expected_generation": None,
        "confirmation": PUBLICATION_AUTHORIZE,
    }
    with pytest.raises(ValueError, match="preview_binding_changed"):
        service.update({**request, "entry_board_policy": None})
    changed = {**request, "account_scope_fingerprint": "d" * 64}
    with pytest.raises(ValueError, match="preview_binding_changed"):
        service.update(changed)
    saved = service.update(request)
    assert saved["status"] == "active"
    assert Decimal(saved["policy"]["max_initial_cash"]) == Decimal("50000")
    assert saved["policy"]["statistical_policy"] == proposed["statistical_policy"]
    monkeypatch.setattr(
        "server.services.reviewed_fee_schedule.build_reviewed_fee_schedule_review_status",
        lambda state: review_status("10000"),
    )
    bounded = service.preview({})
    assert bounded["proposed_binding"]["max_initial_cash"] == "39800.99"
    exceeded = service.preview({"max_initial_cash": "50000"})
    assert exceeded["proposed_binding"] is None
    assert exceeded["preview_blockers"] == [
        "publication_preview_capital_exceeds_reviewed_fee_envelope"
    ]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"status": "insufficient_evidence"}, "deployment_validation_not_verified"),
        ({"deployment_scope_fingerprint": "c" * 64}, "scope_or_statistics_mismatch"),
        ({"initial_cash": "50001"}, "capital_mismatch"),
        ({"error_budget": {}}, "test_budget_invalid"),
    ],
)
def test_readiness_requires_verified_scope_capital_and_grant_bound_final_budget(
    monkeypatch, mutation, reason
):
    grant = _grant()
    validation = {
        "schema_version": "karkinos.deployment_validation.v1",
        "status": "pass",
        "deployment_scope_fingerprint": grant["deployment_scope_fingerprint"],
        "statistical_policy_fingerprint": grant["statistical_policy_fingerprint"],
        "entry_board_policy": grant["entry_board_policy"],
        "strategy_fingerprint": "strategy",
        "code_fingerprint": "code",
        "final_evaluation_id": "final",
        "final_evidence_fingerprint": "final-fp",
        "initial_cash": "50000",
        "risk_limits": grant["risk_limits"],
        "error_budget": {
            "grant_id": grant["grant_id"],
            "generation": grant["generation"],
            "attempt_count": 1,
            "error_budget_spent": "0.025",
        },
        **mutation,
    }
    validation["evidence_fingerprint"] = content_fingerprint(validation)
    import server.services.research_final_evaluation as final

    monkeypatch.setattr(
        final,
        "verify_deployment_validation",
        lambda *args, **kwargs: validation,
        raising=False,
    )
    evidence = {
        "status": "pass",
        "backtest_result_id": 2,
        "qualification_run_id": "run",
        "qualification_binding": {
            "account_truth_scope_fingerprint": grant["account_scope_fingerprint"]
        },
        "source_candidate_id": "source",
        "comparison_fingerprint": "comparison",
        "daily_strategy_artifact_binding": {},
        "strategy_advancement_gate": {},
        "fee_schedule_binding": {},
        "dataset_replay": {},
    }
    monkeypatch.setattr(
        "server.services.strategy_promotion_support.resolve_ai_shadow_qualification_promotion_evidence",
        lambda *args, **kwargs: (evidence, []),
    )
    service = RecommendationPublicationService(
        object(),
        SimpleNamespace(get_qualification_run=lambda _: {"initial_cash_text": "50000"}),
    )
    with pytest.raises(ValueError, match=reason):
        service.readiness("qualified", grant, fresh=False)


def test_portfolio_equity_replays_real_frozen_ledger_and_rejects_drift(book):
    from server.services.valuation_snapshot import (
        build_current_valuation_snapshot,
        portfolio_equity_from_valuation,
    )

    db, _ = book
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp=NOW,
        amount=50000,
        asset_class="cash",
    )
    valuation = build_current_valuation_snapshot(db, now=datetime.fromisoformat(NOW))
    assert "total_equity" not in valuation
    assert portfolio_equity_from_valuation(db, valuation) == Decimal("50000")
    db.insert_ledger_entry_sync(
        entry_type="cash_withdrawal",
        timestamp=NOW,
        amount=100,
        asset_class="cash",
    )
    with pytest.raises(ValueError, match="ledger_identity_changed"):
        portfolio_equity_from_valuation(db, valuation)
