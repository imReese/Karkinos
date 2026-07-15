from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from server.ai_runtime.contracts import ProviderRegistration
from server.ai_runtime.provider_connectivity import (
    CONNECTIVITY_CONFIRMATION,
    CONNECTIVITY_PROBE_TOKEN,
    ConnectivityCheckRequest,
    ConnectivityConfigurationError,
    ConnectivityStatus,
    HttpJsonResponse,
    HttpxDeadlineJsonTransport,
    ProviderConnectivityAuditStore,
    ProviderConnectivityService,
    ProviderConnectivitySettings,
    ProviderProbeError,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.config import AIProviderConfig


class FixtureTransport:
    def __init__(self, response: HttpJsonResponse) -> None:
        self.response = response
        self.calls = []
        self._lock = threading.Lock()

    def post_json(self, **kwargs) -> HttpJsonResponse:
        with self._lock:
            self.calls.append(kwargs)
        return self.response


def _settings(api_key: str = "fixture-secret") -> ProviderConnectivitySettings:
    return ProviderConnectivitySettings(
        provider_id="fixture-provider",
        model_name="fixture-model",
        base_url="https://ai.example.test/v1",
        api_key=api_key,
        credential_source="test-only",
        enabled=True,
    )


def _request(
    idempotency_key: str = "connectivity-001",
    requested_by: str = "human:reese",
) -> ConnectivityCheckRequest:
    return ConnectivityCheckRequest(
        idempotency_key=idempotency_key,
        requested_by=requested_by,
        confirmation=CONNECTIVITY_CONFIRMATION,
    )


def _service(tmp_path, transport: FixtureTransport) -> ProviderConnectivityService:
    db_path = tmp_path / "app.db"
    ai_store = AiAuditStore(db_path)
    audit_store = ProviderConnectivityAuditStore(db_path)
    ai_store.init()
    audit_store.init()
    ticks = iter((10.0, 10.012, 20.0, 20.012, 30.0, 30.012))
    return ProviderConnectivityService(
        settings=_settings(),
        audit_store=audit_store,
        ai_store=ai_store,
        transport=transport,
        now=lambda: "2026-07-14T04:00:00.000+00:00",
        monotonic=lambda: next(ticks),
    )


def _successful_response() -> HttpJsonResponse:
    return HttpJsonResponse(
        status_code=200,
        payload={
            "id": "response-private-id",
            "model": "fixture-model-20260714",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": CONNECTIVITY_PROBE_TOKEN,
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 21,
                "completion_tokens": 7,
                "total_tokens": 28,
            },
        },
    )


@pytest.mark.unit
def test_connectivity_probe_is_non_financial_audited_and_secret_free(tmp_path):
    transport = FixtureTransport(_successful_response())
    service = _service(tmp_path, transport)
    db_path = tmp_path / "app.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE oms_orders (id TEXT PRIMARY KEY);
            CREATE TABLE ledger_entries (id TEXT PRIMARY KEY);
            CREATE TABLE risk_decisions (id TEXT PRIMARY KEY);
            CREATE TABLE capital_authorizations (id TEXT PRIMARY KEY);
            INSERT INTO oms_orders VALUES ('oms-before');
            INSERT INTO ledger_entries VALUES ('ledger-before');
            INSERT INTO risk_decisions VALUES ('risk-before');
            INSERT INTO capital_authorizations VALUES ('capital-before');
            """)

    result = service.run(_request())

    assert result.status == ConnectivityStatus.PASSED
    payload = result.to_dict()
    assert payload["probe_verified"] is True
    assert payload["financial_context_sent"] is False
    assert payload["context_snapshot_id"] is None
    assert payload["valuation_snapshot_id"] is None
    assert payload["ledger_cutoff_id"] is None
    assert payload["tool_calls_allowed"] is False
    assert payload["workflow_started"] is False
    assert payload["artifact_created"] is False
    assert payload["authority_effect"] == "none"
    assert payload["broker_action_count"] == 0
    assert payload["usage"] == {
        "prompt_tokens": 21,
        "completion_tokens": 7,
        "total_tokens": 28,
    }
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == "https://ai.example.test/v1/chat/completions"
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer fixture-secret"
    assert set(transport.calls[0]["payload"]) == {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "stream",
    }
    with sqlite3.connect(db_path) as conn:
        dump = "\n".join(conn.iterdump())
        protected_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "oms_orders",
                "ledger_entries",
                "risk_decisions",
                "capital_authorizations",
            )
        }
        provider_count = conn.execute(
            "SELECT COUNT(*) FROM ai_provider_registrations"
        ).fetchone()[0]
        model_count = conn.execute(
            "SELECT COUNT(*) FROM ai_model_registrations"
        ).fetchone()[0]
    assert protected_counts == {
        "oms_orders": 1,
        "ledger_entries": 1,
        "risk_decisions": 1,
        "capital_authorizations": 1,
    }
    assert provider_count == 1
    assert model_count == 1
    assert "fixture-secret" not in dump
    assert CONNECTIVITY_PROBE_TOKEN not in dump
    assert "response-private-id" not in dump


@pytest.mark.unit
def test_exact_duplicate_reuses_audit_result_without_second_provider_charge(tmp_path):
    transport = FixtureTransport(_successful_response())
    service = _service(tmp_path, transport)

    first = service.run(_request())
    second = service.run(_request())

    assert second == first
    assert len(transport.calls) == 1
    with sqlite3.connect(tmp_path / "app.db") as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM ai_provider_connectivity_checks"
        ).fetchone()[0]
    assert count == 1


@pytest.mark.unit
def test_concurrent_exact_duplicate_invokes_provider_once(tmp_path):
    transport = FixtureTransport(_successful_response())
    service = _service(tmp_path, transport)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.run(_request()), range(2)))

    assert results[0].check_id == results[1].check_id
    assert len(transport.calls) == 1


@pytest.mark.unit
def test_idempotency_key_rejects_changed_operator_input(tmp_path):
    service = _service(tmp_path, FixtureTransport(_successful_response()))
    service.run(_request())

    with pytest.raises(IdempotencyConflict, match="different input"):
        service.run(_request(requested_by="human:someone-else"))


@pytest.mark.unit
def test_provider_failure_is_sanitized_and_audited_without_response_body(tmp_path):
    secret = "fixture-secret"
    leaked_provider_message = "upstream echoed fixture-secret and private details"
    transport = FixtureTransport(
        HttpJsonResponse(
            status_code=401,
            payload={"error": {"message": leaked_provider_message}},
        )
    )
    service = _service(tmp_path, transport)

    result = service.run(_request())

    assert result.status == ConnectivityStatus.FAILED
    assert result.error_code == "provider_authentication_failed"
    assert result.http_status == 401
    assert result.response_fingerprint is None
    assert result.to_dict()["probe_verified"] is False
    with sqlite3.connect(tmp_path / "app.db") as conn:
        dump = "\n".join(conn.iterdump())
    assert secret not in dump
    assert leaked_provider_message not in dump


@pytest.mark.unit
def test_registration_conflict_fails_before_network_and_closes_audit_row(tmp_path):
    db_path = tmp_path / "app.db"
    ai_store = AiAuditStore(db_path)
    ai_store.init()
    ai_store.register_provider(
        ProviderRegistration(
            provider_id="fixture-provider",
            display_name="conflicting-registration",
            adapter_kind="different-adapter",
            enabled=True,
        )
    )
    transport = FixtureTransport(_successful_response())
    service = _service(tmp_path, transport)

    result = service.run(_request())

    assert result.status == ConnectivityStatus.FAILED
    assert result.error_code == "provider_registration_rejected"
    assert transport.calls == []
    with sqlite3.connect(db_path) as conn:
        stored_status, stored_error = conn.execute(
            "SELECT status, error_code FROM ai_provider_connectivity_checks"
        ).fetchone()
    assert stored_status == "failed"
    assert stored_error == "provider_registration_rejected"


@pytest.mark.unit
def test_confirmation_is_required_before_any_provider_request(tmp_path):
    transport = FixtureTransport(_successful_response())
    service = _service(tmp_path, transport)

    with pytest.raises(PermissionError, match="explicit confirmation"):
        service.run(
            ConnectivityCheckRequest(
                idempotency_key="connectivity-no-confirmation",
                requested_by="human:reese",
                confirmation="not-confirmed",
            )
        )

    assert transport.calls == []


@pytest.mark.unit
def test_settings_loader_supports_generic_env_and_ignored_config_migration(tmp_path):
    local_config = AIProviderConfig(
        enabled=True,
        provider="deepseek",
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        api_keys={"deepseek": "local-secret"},
    )
    environment_config = AIProviderConfig(
        enabled=True,
        provider="compatible-provider",
        model="compatible-model",
        base_url="https://compatible.example/v1",
    )

    local = load_provider_connectivity_settings(local_config, environ={})
    env = load_provider_connectivity_settings(
        environment_config,
        environ={
            "KARKINOS_AI_API_KEY": "environment-secret",
        },
    )

    assert local.base_url == "https://api.deepseek.com"
    assert local.model_name == "deepseek-v4-pro"
    assert local.credential_source == "ignored_local_config"
    assert "local-secret" not in repr(local)
    assert env.provider_id == "compatible-provider"
    assert env.base_url == "https://compatible.example/v1"
    assert env.credential_source == "environment:KARKINOS_AI_API_KEY"
    assert "environment-secret" not in repr(env)


@pytest.mark.unit
@pytest.mark.parametrize(
    "ai",
    [
        {
            "enabled": False,
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "api_keys": {"deepseek": "secret"},
        },
        {
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
            "api_keys": {},
        },
    ],
)
def test_settings_fail_closed_when_disabled_missing_secret_or_not_https(ai):
    config = AIProviderConfig(**ai)

    with pytest.raises(ConnectivityConfigurationError):
        load_provider_connectivity_settings(config, environ={})


@pytest.mark.unit
def test_httpx_transport_enforces_end_to_end_deadline_and_closes_request():
    closed = threading.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(0.2)
            return httpx.Response(200, json={"ok": True})
        finally:
            closed.set()

    transport = HttpxDeadlineJsonTransport(transport=httpx.MockTransport(slow_handler))

    with pytest.raises(ProviderProbeError, match="provider_timeout"):
        transport.post_json(
            url="https://ai.example.test/chat/completions",
            headers={"Authorization": "Bearer fixture-secret"},
            payload={"model": "fixture-model"},
            timeout_seconds=0.01,
        )

    assert closed.wait(timeout=0.2)


@pytest.mark.unit
def test_httpx_transport_returns_bounded_json_without_following_redirects():
    observed = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["body"] = json.loads((await request.aread()).decode("utf-8"))
        return httpx.Response(200, json={"model": "fixture-model", "choices": []})

    transport = HttpxDeadlineJsonTransport(transport=httpx.MockTransport(handler))

    response = transport.post_json(
        url="https://ai.example.test/chat/completions",
        headers={"Content-Type": "application/json"},
        payload={"model": "fixture-model", "stream": False},
        timeout_seconds=1.0,
    )

    assert response.status_code == 200
    assert response.payload == {"model": "fixture-model", "choices": []}
    assert observed == {
        "url": "https://ai.example.test/chat/completions",
        "body": {"model": "fixture-model", "stream": False},
    }
