from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app import create_app
from server.release_activation import (
    RELEASE_ACTIVATION_GUARD_DETAIL,
    RELEASE_ACTIVATION_JOURNALS,
    ReleaseActivationGuardMiddleware,
    is_release_activation_guarded,
    is_scheduler_release_activation_guarded,
    wait_for_release_activation,
)


def _release_journal(*, phase: str) -> str:
    return (
        json.dumps(
            {
                "schema_version": "karkinos.release_transaction.v2",
                "operation": "deploy",
                "old_current": "a" * 40,
                "old_previous": "b" * 40,
                "target": "c" * 40,
                "snapshot_id": "d" * 32,
                "phase": phase,
            },
            sort_keys=True,
        )
        + "\n"
    )


def _legacy_journal(tmp_path, *, phase: str) -> str:
    transaction_id = "e" * 32
    return (
        json.dumps(
            {
                "schema_version": "karkinos.legacy_bootstrap_transaction.v1",
                "phase": phase,
                "transaction_id": transaction_id,
                "commit_sha": "f" * 40,
                "legacy_workdir": str(tmp_path / "legacy"),
                "legacy_plist": str(tmp_path / "legacy.plist"),
                "work_name": f".legacy-bootstrap-work-{transaction_id}",
            },
            sort_keys=True,
        )
        + "\n"
    )


def test_create_app_installs_release_activation_guard() -> None:
    app = create_app({"live_auto_start": False})

    assert any(
        middleware.cls is ReleaseActivationGuardMiddleware
        for middleware in app.user_middleware
    )


def test_journals_dynamically_guard_and_unguard_runtime_home(tmp_path) -> None:
    for name in RELEASE_ACTIVATION_JOURNALS:
        journal = tmp_path / name
        journal.write_text("{}\n", encoding="utf-8")
        assert is_release_activation_guarded(tmp_path) is True
        journal.unlink()
        assert is_release_activation_guarded(tmp_path) is False


def test_only_exact_readiness_phase_releases_scheduler_guard(tmp_path) -> None:
    journal = tmp_path / RELEASE_ACTIVATION_JOURNALS[0]
    journal.write_text(_release_journal(phase="switched"), encoding="utf-8")

    assert is_release_activation_guarded(tmp_path) is True
    assert is_scheduler_release_activation_guarded(tmp_path) is True

    journal.write_text(_release_journal(phase="readiness"), encoding="utf-8")

    assert is_release_activation_guarded(tmp_path) is True
    assert is_scheduler_release_activation_guarded(tmp_path) is False

    legacy = tmp_path / RELEASE_ACTIVATION_JOURNALS[1]
    legacy.write_text(_legacy_journal(tmp_path, phase="healthy"), encoding="utf-8")
    assert is_scheduler_release_activation_guarded(tmp_path) is True
    journal.unlink()
    legacy.write_text(_legacy_journal(tmp_path, phase="readiness"), encoding="utf-8")
    assert is_release_activation_guarded(tmp_path) is True
    assert is_scheduler_release_activation_guarded(tmp_path) is False

    legacy.write_text('{"phase":"readiness"}\n', encoding="utf-8")
    assert is_scheduler_release_activation_guarded(tmp_path) is True
    legacy.unlink()

    journal.write_text('{"phase":"readiness"}\n', encoding="utf-8")
    assert is_scheduler_release_activation_guarded(tmp_path) is True

    journal.unlink()
    assert is_release_activation_guarded(tmp_path) is False
    assert is_scheduler_release_activation_guarded(tmp_path) is False


def test_readiness_phase_keeps_unsafe_http_guard_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KARKINOS_HOME", str(tmp_path))
    journal = tmp_path / RELEASE_ACTIVATION_JOURNALS[0]
    journal.write_text(_release_journal(phase="readiness"), encoding="utf-8")
    calls: list[str] = []
    app = FastAPI()
    app.add_middleware(ReleaseActivationGuardMiddleware)

    @app.post("/unsafe")
    async def mutate() -> dict[str, str]:
        calls.append("mutated")
        return {"status": "ok"}

    response = TestClient(app).post("/unsafe")

    assert response.status_code == 503
    assert response.json() == {"detail": RELEASE_ACTIVATION_GUARD_DETAIL}
    assert calls == []


def test_guard_allows_status_reads_and_rejects_unsafe_methods_until_removed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KARKINOS_HOME", str(tmp_path))
    journal = tmp_path / RELEASE_ACTIVATION_JOURNALS[0]
    journal.write_text("{}\n", encoding="utf-8")
    calls: list[str] = []
    app = FastAPI()
    app.add_middleware(ReleaseActivationGuardMiddleware)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/settings/live/status")
    async def live_status() -> dict[str, bool]:
        return {
            "running": True,
            "initialized": True,
            "activation_guarded": is_release_activation_guarded(),
        }

    async def mutate() -> dict[str, str]:
        calls.append("mutated")
        return {"status": "ok"}

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        app.add_api_route("/unsafe", mutate, methods=[method])

    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "alive"}
    assert client.get("/api/settings/live/status").json() == {
        "running": True,
        "initialized": True,
        "activation_guarded": True,
    }
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, "/unsafe")
        assert response.status_code == 503
        assert response.json() == {"detail": RELEASE_ACTIVATION_GUARD_DETAIL}
    assert calls == []

    journal.unlink()
    response = client.post("/unsafe")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == ["mutated"]


def test_background_guard_resumes_after_removal_without_restart() -> None:
    guarded = True
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal guarded
        sleeps.append(delay)
        guarded = False

    asyncio.run(
        wait_for_release_activation(
            activation_guarded=lambda: guarded,
            sleep=sleep,
        )
    )

    assert sleeps == [0.2]
