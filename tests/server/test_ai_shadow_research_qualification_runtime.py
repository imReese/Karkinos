from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.composition.ai_application_services import (
    build_shadow_research_qualification_service,
)
from server.composition.ai_shadow_research_automation import (
    initialize_ai_shadow_research_qualification_persistence,
)
from server.contracts.ai_shadow_research_automation import ShadowResearchPolicy
from server.db import AppDatabase
from server.dependencies import AppState
from server.http.ai_shadow_research_qualification import create_router
from server.projections import portfolio_application
from server.services.ai_shadow_research_commands import AiShadowResearchCommandsMixin
from server.services.ai_shadow_research_qualification import (
    AiShadowResearchQualificationService,
)
from server.services.ai_shadow_research_qualification_support import (
    record_blocked_qualification_attempt,
)


class _StopLoop(Exception):
    pass


async def _stop_loop(_: float) -> None:
    raise _StopLoop


async def _activation_ready() -> None:
    return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_builder_is_provider_free_and_uses_local_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path / "market"))
    state = AppState()
    state.db = AppDatabase(tmp_path / "app.db")
    state.db.init_sync()
    initialize_ai_shadow_research_qualification_persistence(state)
    valuation = {"snapshot_id": "valuation-current-persisted"}
    valuation_reads: list[AppState] = []

    def read_current_valuation(current_state: AppState) -> dict[str, str]:
        valuation_reads.append(current_state)
        return valuation

    monkeypatch.setattr(
        portfolio_application,
        "current_valuation_snapshot",
        read_current_valuation,
    )

    service = build_shadow_research_qualification_service(state)
    result = await service.run_once()

    assert isinstance(service, AiShadowResearchQualificationService)
    assert service._db is state.db
    assert service._research_store._path == state.db.path
    assert service._store.path == state.db.path
    assert service._backtest_adapter._data_store._root == tmp_path / "market"
    assert service._account_identity_reader() is valuation
    assert valuation_reads == [state]
    assert result["provider_call_performed"] is False
    assert result["broker_order_created"] is False
    assert result["capital_authority_granted"] is False


@pytest.mark.unit
def test_qualification_composition_is_zero_write_after_explicit_startup_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path / "market"))
    state = AppState()
    state.db = AppDatabase(tmp_path / "app.db")
    state.db.init_sync()
    initialize_ai_shadow_research_qualification_persistence(state)
    database_before = state.db.path.stat().st_mtime_ns
    market_meta = tmp_path / "market" / "meta.db"
    market_before = market_meta.stat().st_mtime_ns

    def unexpected_init(*_args, **_kwargs):
        raise AssertionError("qualification composition must not initialize storage")

    monkeypatch.setattr(
        "server.composition.ai_shadow_research_automation.ShadowResearchStore.init",
        unexpected_init,
    )
    monkeypatch.setattr(
        "server.composition.ai_shadow_research_automation."
        "DailyStrategyArtifactStore.init",
        unexpected_init,
    )
    monkeypatch.setattr(
        "server.composition.ai_shadow_research_automation.StrategyResearchAuditStore.init",
        unexpected_init,
    )

    service = build_shadow_research_qualification_service(state)

    assert isinstance(service, AiShadowResearchQualificationService)
    assert state.db.path.stat().st_mtime_ns == database_before
    assert market_meta.stat().st_mtime_ns == market_before


@pytest.mark.unit
@pytest.mark.trading_safety
def test_status_projects_only_current_source_qualification_attempt(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    batch = {
        "run_id": "source-run-current",
        "market_date": "2026-09-02",
        "selection_id": "selection-current",
        "selection_fingerprint": "a" * 64,
        "backup_artifact_fingerprint": "b" * 64,
    }
    attempt = record_blocked_qualification_attempt(
        db,
        batch=batch,
        blocker="qualification_valuation_or_ledger_not_complete",
        recorded_at="2026-09-02T17:00:00+08:00",
    )

    class Store:
        @staticmethod
        def list_runs(*, limit: int) -> list[dict[str, Any]]:
            return [
                {
                    "run_id": batch["run_id"],
                    "market_date": batch["market_date"],
                    "status": "completed",
                }
            ][:limit]

        @staticmethod
        def list_candidates(*, limit: int) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def list_public_qualification_runs(*, limit: int) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def usage_for_market_date(market_date: str | None) -> dict[str, Any]:
            return {"market_date": market_date, "provider_calls": 0}

    class Artifacts:
        @staticmethod
        def list_selections(*, limit: int) -> list[dict[str, Any]]:
            return [
                {
                    "run_id": batch["run_id"],
                    "market_date": batch["market_date"],
                    "selection_id": batch["selection_id"],
                    "selection_fingerprint": batch["selection_fingerprint"],
                    "integrity_status": "verified",
                    "status": "no_selection",
                }
            ][:limit]

        @staticmethod
        def list_backups(*, limit: int) -> list[dict[str, Any]]:
            return [
                {
                    "run_id": batch["run_id"],
                    "artifact_fingerprint": batch["backup_artifact_fingerprint"],
                    "verification_status": "verified",
                }
            ][:limit]

        @staticmethod
        def list_superseded_selections(*, limit: int) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def list_superseded_backups(*, limit: int) -> list[dict[str, Any]]:
            return []

    class StatusHarness(AiShadowResearchCommandsMixin):
        def __init__(self) -> None:
            self._db = db
            self._store = Store()
            self._daily_artifacts = Artifacts()

        def get_policy(self) -> ShadowResearchPolicy:
            return ShadowResearchPolicy()

        @staticmethod
        def _kill_switch() -> dict[str, Any]:
            return {"enabled": False, "reason": ""}

        @staticmethod
        def _provider_call_window_status() -> None:
            return None

    harness = StatusHarness()
    status = harness.status()

    assert status["latest_qualification_attempt"] == attempt
    assert status["research_outcome"]["account_qualification_status"] == "blocked"
    assert status["research_outcome"]["qualification_run_id"] is None
    public_json = str(status["latest_qualification_attempt"])
    assert "account_reference" not in public_json
    assert "backup_path" not in public_json

    original_selection_fingerprint = batch["selection_fingerprint"]
    original_backup_fingerprint = batch["backup_artifact_fingerprint"]
    batch["selection_fingerprint"] = "c" * 64
    assert harness.status()["latest_qualification_attempt"] is None
    batch["selection_fingerprint"] = original_selection_fingerprint
    batch["backup_artifact_fingerprint"] = "d" * 64
    assert harness.status()["latest_qualification_attempt"] is None
    batch["backup_artifact_fingerprint"] = original_backup_fingerprint
    batch["selection_id"] = "selection-replaced"
    assert harness.status()["latest_qualification_attempt"] is None


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    ("drift_field", "drift_value"),
    [
        ("selection_integrity", "invalid"),
        ("backup_integrity", "invalid"),
        ("selection_id", "selection-replaced"),
        ("selection_fingerprint", "c" * 64),
        ("backup_fingerprint", "d" * 64),
        ("run_selection_id", "selection-tampered"),
        ("run_selection_fingerprint", "e" * 64),
        ("run_backup_fingerprint", "f" * 64),
    ],
)
def test_status_requires_exact_verified_current_pair_for_qualification_run(
    drift_field: str,
    drift_value: str,
) -> None:
    selection = {
        "run_id": "source-run-current",
        "market_date": "2026-09-02",
        "selection_id": "selection-current",
        "selection_fingerprint": "a" * 64,
        "integrity_status": "verified",
        "status": "no_selection",
    }
    backup = {
        "run_id": selection["run_id"],
        "artifact_fingerprint": "b" * 64,
        "verification_status": "verified",
    }
    qualification = {
        "qualification_run_id": "qualification-current",
        "source_run_id": selection["run_id"],
        "market_date": selection["market_date"],
        "source_selection_id": selection["selection_id"],
        "source_selection_fingerprint": selection["selection_fingerprint"],
        "source_backup_fingerprint": backup["artifact_fingerprint"],
        "status": "completed",
        "winner_qualification_candidate_id": "qualified-current",
    }

    class Store:
        @staticmethod
        def list_runs(*, limit: int) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def list_candidates(*, limit: int) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def list_public_qualification_runs(*, limit: int) -> list[dict[str, Any]]:
            return [dict(qualification)][:limit]

        @staticmethod
        def list_public_qualification_candidates(
            qualification_run_id: str,
        ) -> list[dict[str, Any]]:
            assert qualification_run_id == qualification["qualification_run_id"]
            return []

        @staticmethod
        def usage_for_market_date(market_date: str | None) -> dict[str, Any]:
            return {"market_date": market_date, "provider_calls": 0}

    class Artifacts:
        @staticmethod
        def list_selections(*, limit: int) -> list[dict[str, Any]]:
            return [dict(selection)][:limit]

        @staticmethod
        def list_backups(*, limit: int) -> list[dict[str, Any]]:
            return [dict(backup)][:limit]

        @staticmethod
        def list_superseded_selections(*, limit: int) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def list_superseded_backups(*, limit: int) -> list[dict[str, Any]]:
            return []

    class StatusHarness(AiShadowResearchCommandsMixin):
        def __init__(self) -> None:
            self._db = object()
            self._store = Store()
            self._daily_artifacts = Artifacts()

        def get_policy(self) -> ShadowResearchPolicy:
            return ShadowResearchPolicy()

        @staticmethod
        def _kill_switch() -> dict[str, Any]:
            return {"enabled": False, "reason": ""}

        @staticmethod
        def _provider_call_window_status() -> None:
            return None

    harness = StatusHarness()
    current = harness.status()
    assert current["research_outcome"]["qualification_run_id"] == (
        "qualification-current"
    )
    assert current["research_outcome"]["account_qualification_status"] == "passed"

    if drift_field == "selection_integrity":
        selection["integrity_status"] = drift_value
    elif drift_field == "backup_integrity":
        backup["verification_status"] = drift_value
    elif drift_field == "selection_id":
        selection["selection_id"] = drift_value
    elif drift_field == "selection_fingerprint":
        selection["selection_fingerprint"] = drift_value
    elif drift_field == "backup_fingerprint":
        backup["artifact_fingerprint"] = drift_value
    elif drift_field == "run_selection_id":
        qualification["source_selection_id"] = drift_value
    elif drift_field == "run_selection_fingerprint":
        qualification["source_selection_fingerprint"] = drift_value
    else:
        qualification["source_backup_fingerprint"] = drift_value

    drifted = harness.status()
    assert drifted["research_outcome"]["qualification_run_id"] is None
    assert drifted["research_outcome"]["winner_qualification_candidate_id"] is None
    assert drifted["research_outcome"]["account_qualification_status"] != "passed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_background_loop_enqueues_without_constructing_provider_service(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from server.services import ai_shadow_research_automation as runtime

    events: list[str] = []

    class QualificationService:
        async def run_once(self) -> dict[str, Any]:
            events.append("qualification:run")
            return {"status": "blocked", "provider_call_performed": False}

    class JobScheduler:
        def enqueue_if_authorized(self) -> dict[str, Any]:
            events.append("scheduler:enqueue")
            return {"status": "enqueued", "provider_call_performed": False}

    def build_qualification() -> QualificationService:
        events.append("qualification:build")
        return QualificationService()

    def build_scheduler() -> JobScheduler:
        events.append("scheduler:build")
        return JobScheduler()

    async def stop_after_cycle(seconds: float) -> None:
        events.append(f"sleep:{seconds:g}")
        await _stop_loop(seconds)

    monkeypatch.setattr(runtime, "wait_for_release_activation", _activation_ready)
    monkeypatch.setattr(runtime.asyncio, "sleep", stop_after_cycle)

    with pytest.raises(_StopLoop):
        await runtime.run_ai_shadow_research_automation_loop(
            state=AppState(),
            qualification_service_builder=build_qualification,
            job_scheduler_builder=build_scheduler,
            interval_seconds=300,
        )

    assert events == [
        "scheduler:build",
        "scheduler:enqueue",
        "qualification:build",
        "qualification:run",
        "sleep:300",
    ]
    assert "Shadow research account qualification returned blocked" in caplog.text


@pytest.mark.unit
def test_manual_qualification_route_has_no_provider_or_force_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    class QualificationService:
        async def run_once(self, *, source_run_id: str | None = None) -> dict[str, Any]:
            calls.append(source_run_id)
            return {
                "status": "blocked",
                "provider_call_performed": False,
                "broker_order_created": False,
                "capital_authority_granted": False,
                "private_account_values_redacted": True,
            }

    state = AppState()
    state.db = object()  # type: ignore[assignment]
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    monkeypatch.setattr(
        "server.http.ai_shadow_research_qualification."
        "build_shadow_research_qualification_service",
        lambda current_state: QualificationService(),
    )
    app = FastAPI()
    app.include_router(create_router(), prefix="/api/ai/strategy-research")
    client = TestClient(app)

    response = client.post("/api/ai/strategy-research/shadow-qualification/run")

    assert response.status_code == 200
    assert response.json()["provider_call_performed"] is False
    assert calls == [None]
    operation = app.openapi()["paths"][
        "/api/ai/strategy-research/shadow-qualification/run"
    ]["post"]
    assert "requestBody" not in operation

    source_run_id = "ai-shadow-research:2026-08-31:0123456789abcdef"
    exact = client.post(
        "/api/ai/strategy-research/shadow-qualification/runs/" + source_run_id
    )
    assert exact.status_code == 200
    assert exact.json()["private_account_values_redacted"] is True
    assert calls == [None, source_run_id]
    exact_operation = app.openapi()["paths"][
        "/api/ai/strategy-research/shadow-qualification/runs/{source_run_id}"
    ]["post"]
    assert "requestBody" not in exact_operation
    assert exact_operation["parameters"] == [
        {
            "name": "source_run_id",
            "in": "path",
            "required": True,
            "schema": {
                "type": "string",
                "maxLength": 160,
                "minLength": 1,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]*$",
                "title": "Source Run Id",
            },
        }
    ]

    rejected = client.post(
        "/api/ai/strategy-research/shadow-qualification/runs/not-valid!"
    )
    assert rejected.status_code == 422
    assert calls == [None, source_run_id]


@pytest.mark.unit
def test_strategy_research_router_mounts_provider_free_qualification_run() -> None:
    from server.routes.ai_strategy_research import create_router as create_parent_router

    app = FastAPI()
    app.include_router(create_parent_router())

    assert (
        "/api/ai/strategy-research/shadow-qualification/run" in app.openapi()["paths"]
    )
    assert (
        "/api/ai/strategy-research/shadow-qualification/runs/{source_run_id}"
        in app.openapi()["paths"]
    )
