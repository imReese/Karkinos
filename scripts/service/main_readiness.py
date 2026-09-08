"""Read-only startup probes for the source API and its current workers."""

from __future__ import annotations

import http.client
import json
import re
from datetime import datetime, timezone

_HTTP_TIMEOUT_SECONDS = 0.5
_MAX_RESPONSE_BYTES = 65536


def _read_json(port: int, path: str) -> dict:
    # HTTPConnection does not consult proxy environment variables or redirect.
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=_HTTP_TIMEOUT_SECONDS
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("startup probe did not return HTTP 200")
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("startup probe response exceeds size limit")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("startup probe did not return an object")
        return payload
    finally:
        connection.close()


def _worker_ready(
    state: object,
    prefix: str,
    started_at: datetime,
    now: datetime,
    *,
    pid: int | None = None,
) -> bool:
    if not isinstance(state, dict) or state.get("status") != "ready":
        return False
    heartbeat = state.get("latest_attempt")
    if not isinstance(heartbeat, dict) or heartbeat.get("status") != "ready":
        return False
    owner = heartbeat.get("owner")
    expected_pid = str(pid) if pid is not None else r"[1-9][0-9]*"
    if (
        not isinstance(owner, str)
        or re.fullmatch(rf"{re.escape(prefix)}:{expected_pid}:[0-9a-f]{{32}}", owner)
        is None
    ):
        return False
    try:
        stamp = datetime.fromisoformat(heartbeat["as_of"])
        return (
            stamp.tzinfo is not None
            and started_at <= stamp <= now
            and (now - stamp).total_seconds() < 90
        )
    except (KeyError, TypeError, ValueError):
        return False


def startup_ready(port: int, research_pid: int, started_at: datetime) -> bool:
    """Require fresh process evidence without gating last-good financial reads."""
    if started_at.tzinfo is None or research_pid <= 0:
        return False
    try:
        health = _read_json(port, "/api/health")
        if not (
            health.get("schema_version") == "karkinos.service_health.v1"
            and health.get("service") == "karkinos"
            and health.get("status") == "alive"
            and health.get("scope") == "process_liveness_only"
            and health.get("financial_readiness_claimed") is False
            and health.get("authorizes_execution") is False
        ):
            return False
        readiness = _read_json(port, "/api/health/readiness")
        if (
            readiness.get("schema_version") != "karkinos.system_readiness.v1"
            or readiness.get("authorizes_execution") is not False
        ):
            return False
        states = readiness.get("subsystems")
        if not isinstance(states, dict):
            return False
        for name in ("api", "database"):
            state = states.get(name)
            if not isinstance(state, dict) or state.get("status") != "ready":
                return False
        now = datetime.now(timezone.utc)
        if not _worker_ready(
            states.get("research_worker"),
            "research-worker",
            started_at,
            now,
            pid=research_pid,
        ):
            return False
        background = states.get("background_worker")
        return (
            isinstance(background, dict) and background.get("status") == "disabled"
        ) or _worker_ready(background, "data-worker", started_at, now)
    except (OSError, http.client.HTTPException, TypeError, ValueError):
        return False
