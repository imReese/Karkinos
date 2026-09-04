from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.contracts.ai_shadow_research_automation import ShadowResearchRejected
from server.http.ai_shadow_research_qualification import create_router
from server.services.ai_shadow_research_commands import AiShadowResearchCommandsMixin
from server.services.strategy_promotion_support import (
    AI_SHADOW_QUALIFICATION_READINESS_SCHEMA,
    ai_shadow_qualification_readiness_binding_blockers,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def _evidence() -> dict:
    gate = {"status": "pass", "evidence_fingerprint": "sha256:gate"}
    return {
        "status": "pass",
        "source_candidate_id": "source-candidate",
        "qualification_candidate_id": "qualified-candidate",
        "qualification_run_id": "qualification-run",
        "qualification_approval_id": "qualification-approval",
        "backtest_result_id": 22,
        "comparison_fingerprint": "sha256:comparison",
        "strategy_advancement_gate": gate,
        "daily_strategy_artifact_binding": {"source": "verified-normalized"},
        "qualification_binding": {"qualification": "verified"},
        "fee_schedule_binding": {"fee": "verified"},
        "dataset_replay": {"status": "pass"},
        "blockers": [],
    }


def _readiness(evidence: dict) -> dict:
    return {
        "schema_version": AI_SHADOW_QUALIFICATION_READINESS_SCHEMA,
        "strategy_id": "ai_formula_shadow:source-candidate",
        "candidate_id": "source-candidate",
        "qualification_candidate_id": "qualified-candidate",
        "qualification_run_id": "qualification-run",
        "qualification_binding": evidence["qualification_binding"],
        "daily_strategy_artifact_binding": evidence["daily_strategy_artifact_binding"],
        "backtest_result_id": 22,
        "comparison_fingerprint": "sha256:comparison",
        "human_approval_id": "qualification-approval",
        "strategy_advancement_gate": evidence["strategy_advancement_gate"],
        "promotion_status": "promotable_for_paper_review",
        "is_promotable": True,
        "missing_requirements": [],
        "live_like_enabled": False,
        "broker_submission_enabled": False,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
    }


def test_qualification_readiness_requires_exact_reopened_binding(
    monkeypatch,
) -> None:
    evidence = _evidence()
    monkeypatch.setattr(
        "server.services.strategy_promotion_support."
        "_resolve_ai_shadow_qualification_promotion_evidence",
        lambda db, qualification_candidate_id: (evidence, []),
    )
    monkeypatch.setattr(
        "server.services.strategy_promotion_support."
        "is_valid_passed_strategy_advancement_gate",
        lambda gate: True,
    )
    readiness = _readiness(evidence)

    assert ai_shadow_qualification_readiness_binding_blockers(object(), readiness) == []

    readiness["qualification_binding"] = {"qualification": "drifted"}
    readiness["does_not_create_order"] = False
    blockers = ai_shadow_qualification_readiness_binding_blockers(object(), readiness)
    assert "ai_shadow_qualification_binding_mismatch" in blockers
    assert "ai_shadow_qualification_authority_boundary_invalid" in blockers


def test_normalized_candidate_cannot_use_legacy_approval_path() -> None:
    class Store:
        def get_candidate(self, candidate_id):
            return {
                "candidate_id": candidate_id,
                "run_id": "normalized-run",
                "comparison": {
                    "research_capital_mode": "normalized_notional",
                    "account_qualification_status": "not_evaluated",
                },
            }

    class DailyArtifacts:
        def require_verified_winner(self, **kwargs):
            raise AssertionError("legacy daily winner lookup must not run")

    service = AiShadowResearchCommandsMixin()
    service._store = Store()
    service._daily_artifacts = DailyArtifacts()

    with pytest.raises(
        ShadowResearchRejected,
        match="candidate_account_qualification_required",
    ):
        service.approve_candidate(
            "normalized-candidate",
            approved_by="human:owner",
            notes="reviewed",
            confirmation="unused",
        )


def test_qualification_command_promotes_source_id_to_paper_shadow_only(
    monkeypatch,
) -> None:
    evidence = _evidence()
    calls: dict[str, object] = {}

    class Store:
        def prepare_qualification_candidate_approval(self, candidate_id, **kwargs):
            calls["preflight_approval"] = {"candidate_id": candidate_id, **kwargs}
            return {
                "qualification_approval_id": "qualification-approval",
                "qualification_candidate_id": candidate_id,
                "target_stage": "paper_shadow",
            }

        def approve_qualification_candidate_for_paper_shadow(
            self, candidate_id, **kwargs
        ):
            calls["atomic_promotion"] = {"candidate_id": candidate_id, **kwargs}
            return {
                "qualification_approval": kwargs["approval"],
                "strategy_promotion": {
                    "strategy_id": kwargs["strategy_id"],
                    "stage": "paper_shadow",
                    "live_like_enabled": False,
                    "payload": kwargs["state_payload"],
                },
            }

        def get_public_qualification_run(self, run_id):
            return {
                "qualification_run_id": run_id,
                "private_account_values_redacted": True,
            }

        def get_public_qualification_candidate(self, candidate_id):
            return {
                "qualification_candidate_id": candidate_id,
                "private_account_values_redacted": True,
            }

    class Database:
        def get_strategy_promotion_state_sync(self, strategy_id):
            return None

    service = AiShadowResearchCommandsMixin()
    service._store = Store()
    service._db = Database()
    service._utc_now = lambda: "2026-09-01T10:00:00+00:00"
    monkeypatch.setattr(
        "server.services.ai_shadow_research_commands."
        "resolve_ai_shadow_qualification_promotion_evidence",
        lambda db, candidate_id, **kwargs: (evidence, []),
    )

    result = service.approve_qualification_candidate(
        "qualified-candidate",
        approved_by="human:owner",
        notes="reviewed exact qualified evidence",
        confirmation="exact-confirmation",
    )

    readiness = calls["atomic_promotion"]["readiness"]
    assert readiness["strategy_id"] == "ai_formula_shadow:source-candidate"
    assert readiness["qualification_candidate_id"] == "qualified-candidate"
    assert readiness["backtest_result_id"] == 22
    assert readiness["live_like_enabled"] is False
    assert readiness["broker_submission_enabled"] is False
    assert readiness["does_not_create_order"] is True
    assert readiness["does_not_authorize_execution"] is True
    assert result["strategy_promotion_state_recorded"] is True
    assert result["production_strategy_registry_mutated"] is False
    assert result["broker_order_created"] is False
    assert result["capital_authority_granted"] is False


def test_qualification_promotion_preflight_failure_performs_zero_writes(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class Store:
        @staticmethod
        def prepare_qualification_candidate_approval(candidate_id, **kwargs):
            calls.append("read_only_preflight")
            return {
                "qualification_approval_id": "qualification-approval",
                "qualification_candidate_id": candidate_id,
                "target_stage": "paper_shadow",
            }

        @staticmethod
        def approve_qualification_candidate_for_paper_shadow(*args, **kwargs):
            calls.append("write_uow")
            raise AssertionError("blocked preflight must not enter the write UoW")

    service = AiShadowResearchCommandsMixin()
    service._store = Store()
    service._db = object()
    service._utc_now = lambda: "2026-09-01T10:00:00+00:00"
    monkeypatch.setattr(
        "server.services.ai_shadow_research_commands."
        "resolve_ai_shadow_qualification_promotion_evidence",
        lambda db, candidate_id, **kwargs: (
            {"status": "blocked"},
            ["qualification_evidence_drift"],
        ),
    )

    with pytest.raises(
        ShadowResearchRejected,
        match="qualification_promotion_evidence_invalid",
    ):
        service.approve_qualification_candidate(
            "qualified-candidate",
            approved_by="human:owner",
            notes="reviewed exact qualified evidence",
            confirmation="exact-confirmation",
        )

    assert calls == ["read_only_preflight"]


def test_qualification_http_route_requires_exact_confirmation(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class Service:
        def approve_qualification_candidate(self, candidate_id, **kwargs):
            calls["request"] = {"candidate_id": candidate_id, **kwargs}
            return {
                "qualification_candidate_id": candidate_id,
                "strategy_id": "ai_formula_shadow:source-candidate",
                "paper_shadow_stage_recorded": True,
                "broker_order_created": False,
            }

    monkeypatch.setattr(
        "server.http.ai_shadow_research_qualification."
        "build_shadow_research_write_service",
        lambda state: Service(),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: object())
    app = FastAPI()
    app.include_router(create_router(), prefix="/api/ai/strategy-research")
    client = TestClient(app)
    path = (
        "/api/ai/strategy-research/shadow-qualification-candidates/"
        "qualified-candidate/paper-shadow-approvals"
    )

    rejected = client.post(
        path,
        json={
            "approved_by": "human:owner",
            "notes": "reviewed",
            "confirmation": "approve",
        },
    )
    accepted = client.post(
        path,
        json={
            "approved_by": "human:owner",
            "notes": "reviewed",
            "confirmation": (
                "approve_exact_account_qualified_candidate_for_paper_shadow_only_"
                "without_order_trade_or_capital_authority"
            ),
        },
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 201
    assert calls["request"] == {
        "candidate_id": "qualified-candidate",
        "approved_by": "human:owner",
        "notes": "reviewed",
        "confirmation": (
            "approve_exact_account_qualified_candidate_for_paper_shadow_only_"
            "without_order_trade_or_capital_authority"
        ),
    }
