"""Publication HTTP work stays off the event loop and owns its Dataset reads."""

from __future__ import annotations

import asyncio
import threading
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from data.dataset import reader
from data.storage.objects import ContentAddressedObjectStore
from server.http.ai_shadow_research_automation import create_router
from server.routes.ai_strategy_research import _raise_http
from tests.server.test_verified_interval_dataset import _verified_day

POLICY_PATH = "/api/ai/strategy-research/automatic-publication-policy"
REVOKE = {
    "enabled": False,
    "expected_generation": "grant-1",
    "updated_by": "human:fixture",
    "confirmation": "revoke_automatic_account_recommendation_publication",
}


@pytest.mark.asyncio
async def test_publication_write_accepts_the_previewed_board_binding_only_on_write(
    monkeypatch,
):
    from server.services.account_board_permissions import freeze_entry_board_policy

    policy = freeze_entry_board_policy(SimpleNamespace(), "2026-08-24")
    writes = []
    service = SimpleNamespace(
        update_publication_policy=lambda payload: (
            writes.append(payload) or {"status": "active"}
        ),
    )
    app, _ = _app(monkeypatch, service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        preview = await client.post(
            f"{POLICY_PATH}/preview", json={"entry_board_policy": policy}
        )
        assert preview.status_code == 422
        response = await client.put(
            POLICY_PATH,
            json={**REVOKE, "entry_board_policy": policy},
        )
    assert response.status_code == 200
    assert writes == [{**REVOKE, "entry_board_policy": policy}]


def _app(monkeypatch, service, *, build_error=None):
    state = object()
    builder_calls = []
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)

    def build(kind, actual_state):
        assert actual_state is state
        builder_calls.append((kind, threading.get_ident()))
        if build_error is not None:
            raise build_error
        return service

    app = FastAPI()
    app.include_router(
        create_router(
            build_read_service=lambda actual_state: build("read", actual_state),
            build_write_service=lambda actual_state: build("write", actual_state),
            build_job_scheduler=lambda _: pytest.fail("scheduler is unrelated"),
            raise_http=_raise_http,
        )
    )

    @app.get("/light")
    async def light():
        return {"responsive": True}

    return app, builder_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload", "builder_kind"),
    [
        ("GET", POLICY_PATH, None, "read"),
        (
            "POST",
            f"{POLICY_PATH}/preview",
            {"allocation_scope": "fixture", "incumbent_strategy_id": None},
            "read",
        ),
        ("PUT", POLICY_PATH, REVOKE, "write"),
    ],
)
async def test_publication_requests_leave_other_api_responsive_and_reads_request_scoped(
    tmp_path, monkeypatch, method, path, payload, builder_kind
):
    root = tmp_path / "research"
    ref = _verified_day(root, date(2026, 8, 21))
    objects = ContentAddressedObjectStore(root / "objects")
    cold_read = reader._read_daily_bar_dataset
    cold_reads = []

    def counted_read(store, dataset_ref):
        cold_reads.append(dataset_ref)
        return cold_read(store, dataset_ref)

    monkeypatch.setattr(reader, "_read_daily_bar_dataset", counted_read)
    entered, release = threading.Event(), threading.Event()
    service_calls = []
    current_status = ["active"]

    def blocking_service(*args):
        service_calls.append((args, threading.get_ident()))
        first = reader.read_daily_bar_dataset(objects, ref)
        second = reader.read_daily_bar_dataset(objects, ref)
        assert first.bars is second.bars
        if len(service_calls) == 1:
            entered.set()
            release.wait(timeout=3)
        return {"status": current_status[0]}

    service = SimpleNamespace(
        get_publication_policy=blocking_service,
        preview_publication_policy=blocking_service,
        update_publication_policy=blocking_service,
    )
    app, builder_calls = _app(monkeypatch, service)
    loop_thread = threading.get_ident()
    request_kwargs = {} if payload is None else {"json": payload}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        task = asyncio.create_task(client.request(method, path, **request_kwargs))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(client.get("/light"), timeout=1)
            assert response.json() == {"responsive": True}
            assert not task.done()
            assert service_calls[0][1] != loop_thread
        finally:
            release.set()
        first_response = await asyncio.wait_for(task, timeout=1)
        assert first_response.status_code == 200
        assert first_response.json() == {"status": "active"}

        # A new request rereads immutable bytes and the current authority service.
        current_status[0] = "disabled"
        second_response = await client.request(method, path, **request_kwargs)
        assert second_response.status_code == 200
        assert second_response.json() == {"status": "disabled"}

    assert cold_reads == [ref, ref]
    assert builder_calls == [(builder_kind, loop_thread)] * 2
    expected_args = () if payload is None else (payload,)
    assert [call[0] for call in service_calls] == [expected_args, expected_args]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("invalid"), PermissionError("denied")])
@pytest.mark.parametrize("fail_build", [False, True])
async def test_publication_update_keeps_service_and_builder_http_errors(
    monkeypatch, error, fail_build
):
    def update(_inputs):
        raise error

    app, _ = _app(
        monkeypatch,
        SimpleNamespace(update_publication_policy=update),
        build_error=error if fail_build else None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.put(POLICY_PATH, json=REVOKE)
    assert response.status_code == (403 if isinstance(error, PermissionError) else 422)
    assert response.json() == {"detail": str(error)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", f"{POLICY_PATH}/preview", {"unknown": True}),
        ("POST", f"{POLICY_PATH}/preview", {"max_final_tests": 0}),
        ("PUT", POLICY_PATH, {"confirmation": REVOKE["confirmation"]}),
        ("PUT", POLICY_PATH, {**REVOKE, "unknown": True}),
    ],
)
async def test_publication_payload_validation_precedes_service_build(
    monkeypatch, method, path, payload
):
    app, builder_calls = _app(monkeypatch, SimpleNamespace())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.request(method, path, json=payload)
    assert response.status_code == 422
    assert builder_calls == []
