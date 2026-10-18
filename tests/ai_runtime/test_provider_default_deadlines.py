from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest

from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.external_memory_analysis_service import (
    HumanExternalMemoryAnalysisService,
)
from server.ai_runtime.provider_connectivity_audit import ProviderConnectivityAuditStore
from server.ai_runtime.provider_connectivity_contracts import (
    CONNECTIVITY_PROBE_TOKEN,
    ConnectivityStatus,
    ProviderConnectivitySettings,
)
from server.ai_runtime.provider_connectivity_service import ProviderConnectivityService
from server.ai_runtime.store import AiAuditStore
from server.persistence.external_memory_analysis import ExternalMemoryAnalysisStore
from tests.ai_runtime.test_external_memory_informed_analysis import (
    EvidenceAwareTransport,
)
from tests.ai_runtime.test_external_memory_informed_analysis import (
    _request as memory_request,
)
from tests.ai_runtime.test_external_memory_informed_analysis import (
    _settings as memory_settings,
)
from tests.ai_runtime.test_memory_informed_analysis import _prepared_retrieval
from tests.ai_runtime.test_memory_retrieval import _retrieval_service
from tests.ai_runtime.test_provider_connectivity import (
    _request as connectivity_request,
)
from tests.ai_runtime.test_provider_connectivity import (
    _settings as connectivity_settings,
)
from tests.ai_runtime.test_research_tasks import NOW


@pytest.fixture
def drip_endpoint(monkeypatch):
    # Exercise real sockets without external endpoints or TLS fixture machinery.
    # HTTPS settings validation remains covered by the existing contract tests.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    state = SimpleNamespace(request_count=0, response=None, observe=None)
    stopped = Event()

    class DripHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.request_count += 1
            state.observe()
            content = json.dumps(state.response(payload)).encode()
            prefix = b" " * 40
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(prefix) + len(content)))
            self.end_headers()
            try:
                for byte in prefix:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    if stopped.wait(0.025):
                        return
                self.wfile.write(content)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), DripHandler)
    thread = Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/chat/completions"
    monkeypatch.setattr(
        ProviderConnectivitySettings, "endpoint_url", property(lambda _self: url)
    )
    try:
        yield state
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_default_connectivity_transport_times_out_drip_and_keeps_exact_retry(
    tmp_path, drip_endpoint
):
    path = tmp_path / "connectivity.db"
    ai_store = AiAuditStore(path)
    audit_store = ProviderConnectivityAuditStore(path)
    ai_store.init()
    audit_store.init()
    observed = []

    def observe():
        with sqlite3.connect(path) as connection:
            observed.extend(
                row[0]
                for row in connection.execute(
                    "SELECT status FROM ai_provider_connectivity_checks"
                )
            )

    drip_endpoint.observe = observe
    drip_endpoint.response = lambda _payload: {
        "choices": [{"message": {"content": CONNECTIVITY_PROBE_TOKEN}}]
    }
    service = ProviderConnectivityService(
        settings=replace(connectivity_settings(), timeout_seconds=0.25),
        audit_store=audit_store,
        ai_store=ai_store,
        now=lambda: NOW,
    )
    request = connectivity_request()
    result = service.run(request)

    assert observed == ["running"]
    assert result.status == ConnectivityStatus.FAILED
    assert result.error_code == "provider_timeout"
    assert result.finished_at is not None
    assert service.run(request) == result
    assert drip_endpoint.request_count == 1


def test_dns_block_does_not_delay_failure_audit_or_resume_request(
    tmp_path, monkeypatch
):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    path = tmp_path / "connectivity-dns.db"
    ai_store = AiAuditStore(path)
    audit_store = ProviderConnectivityAuditStore(path)
    ai_store.init()
    audit_store.init()
    service = ProviderConnectivityService(
        settings=replace(connectivity_settings(), timeout_seconds=0.1),
        audit_store=audit_store,
        ai_store=ai_store,
        now=lambda: NOW,
    )
    request = connectivity_request()
    resolving, release, finished = Event(), Event(), Event()
    resolver_threads = []
    results, errors = [], []

    def resolve(*_args, **_kwargs):
        resolver_threads.append(current_thread())
        resolving.set()
        release.wait(timeout=5)
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 9),
            )
        ]

    connections = []

    def connect(*args, **_kwargs):
        connections.append(args)
        raise AssertionError("A timed-out request must not connect after DNS returns")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)

    def invoke():
        try:
            results.append(service.run(request))
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = Thread(target=invoke, daemon=True)
    worker.start()
    try:
        assert resolving.wait(timeout=2)
        assert finished.wait(timeout=1.5), "DNS cleanup exceeded the request deadline"
        assert not release.is_set()
        assert errors == []
        result = results[0]
        assert result.status == ConnectivityStatus.FAILED
        assert result.error_code == "provider_timeout"
        assert result.finished_at is not None
        with sqlite3.connect(path) as connection:
            before = connection.execute(
                "SELECT * FROM ai_provider_connectivity_checks"
            ).fetchall()
        assert len(before) == 1
        assert service.run(request) == result
        assert len(resolver_threads) == 1
    finally:
        release.set()
        worker.join(timeout=3)
        for thread in resolver_threads:
            thread.join(timeout=2)
    assert not worker.is_alive()
    assert all(not thread.is_alive() for thread in resolver_threads)
    assert connections == []
    assert service.run(request) == result
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT * FROM ai_provider_connectivity_checks"
            ).fetchall()
            == before
        )
    assert len(resolver_threads) == 1


@pytest.mark.asyncio
async def test_default_memory_transport_times_out_with_terminal_receipt(
    tmp_path, drip_endpoint
):
    path = tmp_path / "memory.db"
    retrieval, _, _ = await _prepared_retrieval(path)
    store = ExternalMemoryAnalysisStore(path)
    store.init()
    observed = []

    def observe():
        with sqlite3.connect(path) as connection:
            observed.extend(
                row[0]
                for row in connection.execute(
                    "SELECT status FROM ai_external_memory_model_calls"
                )
            )

    response = EvidenceAwareTransport()
    drip_endpoint.observe = observe
    drip_endpoint.response = lambda payload: response.post_json(payload=payload).payload
    service = HumanExternalMemoryAnalysisService(
        settings_loader=memory_settings,
        retrieval_service=_retrieval_service(path),
        ai_store=AiAuditStore(path),
        evidence_repository=CanonicalEvidenceRepository(path),
        analysis_store=store,
        now=lambda: NOW,
        model_timeout_seconds=0.25,
    )
    request = memory_request(retrieval.stored.retrieval_id)
    result = await asyncio.to_thread(service.start, request)

    assert observed == ["running"]
    assert result.workflow.status.value == "failed"
    assert result.workflow.failure_code == "external_memory_timeout"
    receipts = store.list_model_calls(result.workflow.workflow_id)
    assert len(receipts) == 1
    assert receipts[0].status == "failed"
    assert receipts[0].error_code == "provider_timeout"
    assert receipts[0].finished_at is not None
    assert result.artifacts == ()
    assert result.to_dict()["authority_effect"] == "none"
    retry = await asyncio.to_thread(service.start, request)
    assert retry.reused is True
    assert retry.record.analysis_id == result.record.analysis_id
    assert retry.workflow.status.value == "failed"
    assert store.list_model_calls(result.workflow.workflow_id) == receipts
    assert drip_endpoint.request_count == 1
