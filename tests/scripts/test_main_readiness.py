"""Startup requires fresh owned workers, while financial gates stay independent."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.service import main_readiness as readiness


@pytest.fixture
def evidence(monkeypatch):
    started = datetime.now(timezone.utc) - timedelta(seconds=2)
    stamp = (started + timedelta(seconds=1)).isoformat()

    def worker(prefix, pid):
        return {
            "status": "ready",
            "latest_attempt": {
                "status": "ready",
                "owner": f"{prefix}:{pid}:{'a' * 32}",
                "as_of": stamp,
            },
        }

    health = {
        "schema_version": "karkinos.service_health.v1",
        "service": "karkinos",
        "status": "alive",
        "scope": "process_liveness_only",
        "financial_readiness_claimed": False,
        "authorizes_execution": False,
    }
    payload = {
        "schema_version": "karkinos.system_readiness.v1",
        "authorizes_execution": False,
        "subsystems": {
            "api": {"status": "ready"},
            "database": {"status": "ready"},
            "research_worker": worker("research-worker", 1234),
            "background_worker": worker("data-worker", 5678),
            "market_data": {"status": "degraded"},
            "valuation_read": {"status": "unavailable"},
            "decision": {"status": "blocked"},
            "risk": {"status": "blocked"},
            "execution_authority": {"status": "not_evaluated"},
        },
    }
    responses = {"/api/health": health, "/api/health/readiness": payload}
    monkeypatch.setattr(readiness, "_read_json", lambda port, path: responses[path])
    return started, responses


def test_fresh_processes_do_not_require_financial_readiness(evidence):
    started, _ = evidence
    assert readiness.startup_ready(8000, 1234, started)


def test_explicitly_disabled_data_worker_is_supported(evidence):
    started, responses = evidence
    responses["/api/health/readiness"]["subsystems"]["background_worker"] = {
        "status": "disabled"
    }
    assert readiness.startup_ready(8000, 1234, started)


@pytest.mark.parametrize("worker", ["research_worker", "background_worker"])
@pytest.mark.parametrize("failure", ["previous_launch", "future", "stale", "naive"])
def test_heartbeat_must_be_fresh_and_from_this_launch(evidence, worker, failure):
    started, responses = evidence
    heartbeat = responses["/api/health/readiness"]["subsystems"][worker][
        "latest_attempt"
    ]
    if failure == "previous_launch":
        stamp = started - timedelta(milliseconds=1)
    elif failure == "future":
        stamp = datetime.now(timezone.utc) + timedelta(seconds=10)
    elif failure == "stale":
        started -= timedelta(seconds=100)
        stamp = started + timedelta(seconds=1)
    else:
        stamp = datetime.now().replace(tzinfo=None)
    heartbeat["as_of"] = stamp.isoformat()
    assert not readiness.startup_ready(8000, 1234, started)


@pytest.mark.parametrize(
    "owner",
    [
        f"research-worker:123:{'a' * 32}",
        f"research-worker:12345:{'a' * 32}",
        f"data-worker:1234:{'a' * 32}",
        "research-worker:1234:",
        None,
    ],
)
def test_research_heartbeat_binds_exact_child_pid(evidence, owner):
    started, responses = evidence
    responses["/api/health/readiness"]["subsystems"]["research_worker"][
        "latest_attempt"
    ]["owner"] = owner
    assert not readiness.startup_ready(8000, 1234, started)


@pytest.mark.parametrize(
    "name", ["api", "database", "research_worker", "background_worker"]
)
@pytest.mark.parametrize("state", [None, {"status": "unavailable"}])
def test_missing_or_unready_required_subsystem_fails(evidence, name, state):
    started, responses = evidence
    responses["/api/health/readiness"]["subsystems"][name] = state
    assert not readiness.startup_ready(8000, 1234, started)


@pytest.mark.parametrize("name", ["research_worker", "background_worker"])
def test_worker_ready_status_requires_heartbeat(evidence, name):
    started, responses = evidence
    responses["/api/health/readiness"]["subsystems"][name] = {"status": "ready"}
    assert not readiness.startup_ready(8000, 1234, started)


@pytest.mark.parametrize(
    "path,key,value",
    [
        ("/api/health", "service", "other"),
        ("/api/health", "schema_version", "unknown"),
        ("/api/health", "status", "starting"),
        ("/api/health", "financial_readiness_claimed", True),
        ("/api/health/readiness", "schema_version", "unknown"),
        ("/api/health/readiness", "subsystems", None),
        ("/api/health/readiness", "authorizes_execution", True),
    ],
)
def test_unknown_or_invalid_probe_contract_fails(evidence, path, key, value):
    started, responses = evidence
    responses[path][key] = value
    assert not readiness.startup_ready(8000, 1234, started)


def test_network_failure_and_naive_launch_time_fail_closed(evidence, monkeypatch):
    started, _ = evidence

    def unavailable(*args):
        raise TimeoutError("not listening")

    monkeypatch.setattr(readiness, "_read_json", unavailable)
    assert not readiness.startup_ready(8000, 1234, started)
    assert not readiness.startup_ready(8000, 1234, started.replace(tzinfo=None))


@pytest.fixture
def http_probe():
    replies = {}
    requested = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            status, body = replies[self.path]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, replies, requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_probe_is_loopback_only_and_ignores_proxies(http_probe, monkeypatch):
    port, replies, requested = http_probe
    replies["/api/health"] = (200, json.dumps({"status": "alive"}).encode())
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    assert readiness._read_json(port, "/api/health") == {"status": "alive"}
    assert requested == ["/api/health"]


@pytest.mark.parametrize(
    "status,body",
    [(302, b"{}"), (503, b"{}"), (200, b"[]"), (200, b"invalid"), (200, b" " * 65537)],
)
def test_http_probe_rejects_redirects_errors_and_unbounded_responses(
    http_probe, status, body
):
    port, replies, _ = http_probe
    replies["/api/health"] = (status, body)
    with pytest.raises(ValueError):
        readiness._read_json(port, "/api/health")
