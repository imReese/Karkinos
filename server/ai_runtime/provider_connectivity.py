"""Explicit, provider-neutral external-model connectivity verification.

The probe sends one fixed non-financial prompt through an OpenAI-compatible
HTTPS endpoint.  It never receives account facts, cannot request tools, and
persists only redacted metadata in ``ai_*`` tables.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import httpx

from server.config import AIProviderConfig, BacktestConfig

from .contracts import (
    ModelRegistration,
    ProviderRegistration,
    canonical_json,
    content_fingerprint,
)
from .registry import AiRuntimeRegistry
from .store import AiAuditStore, IdempotencyConflict

CONNECTIVITY_CONFIRMATION = (
    "run_external_ai_connectivity_check_without_financial_context"
)
CONNECTIVITY_PROBE_VERSION = "karkinos.ai.connectivity_probe.v1"
CONNECTIVITY_PROBE_TOKEN = "KARKINOS_AI_CONNECTIVITY_OK"

_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_PROVIDER_ENV_PATTERN = re.compile(r"[^A-Z0-9]+")


class ConnectivityStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class ConnectivityConfigurationError(ValueError):
    """Raised when an explicitly requested external provider is not usable."""


class ProviderProbeError(RuntimeError):
    """A sanitized provider failure safe to persist and return."""

    def __init__(self, code: str, *, http_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class ProviderConnectivitySettings:
    provider_id: str
    model_name: str
    base_url: str
    api_key: str = field(repr=False)
    credential_source: str = "environment"
    adapter_kind: str = "openai_compatible_https"
    enabled: bool = False
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not self.enabled:
            raise ConnectivityConfigurationError("AI provider is disabled")
        for field_name in ("provider_id", "model_name", "adapter_kind"):
            if not str(getattr(self, field_name)).strip():
                raise ConnectivityConfigurationError(
                    f"AI provider {field_name} must not be empty"
                )
        if self.adapter_kind != "openai_compatible_https":
            raise ConnectivityConfigurationError(
                "only the reviewed openai_compatible_https adapter is allowed"
            )
        if not self.api_key.strip():
            raise ConnectivityConfigurationError(
                "AI provider API key is not configured"
            )
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ConnectivityConfigurationError(
                "AI provider base_url must be a credential-free HTTPS origin/path"
            )
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ConnectivityConfigurationError(
                "AI provider timeout must be within (0, 60] seconds"
            )

    @property
    def model_id(self) -> str:
        return f"{self.provider_id}:{self.model_name}"

    @property
    def endpoint_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def endpoint_origin(self) -> str:
        parsed = urlparse(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class ConnectivityCheckRequest:
    idempotency_key: str
    requested_by: str
    confirmation: str

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if not self.requested_by.strip():
            raise ValueError("requested_by must not be empty")
        if self.confirmation != CONNECTIVITY_CONFIRMATION:
            raise PermissionError(
                "external AI connectivity check requires explicit confirmation"
            )


@dataclass(frozen=True)
class HttpJsonResponse:
    status_code: int
    payload: object


class JsonHttpTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse: ...


class UrllibJsonTransport:
    """Small dependency-free HTTPS transport with sanitized failure codes."""

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse:
        request = Request(
            url,
            data=canonical_json(payload).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=timeout_seconds,
            ) as response:  # noqa: S310
                body = response.read(1_048_576)
                status_code = int(response.status)
        except HTTPError as exc:
            body = exc.read(1_048_576)
            status_code = int(exc.code)
        except TimeoutError as exc:
            raise ProviderProbeError("provider_timeout") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", None)
            code = (
                "provider_timeout"
                if isinstance(reason, TimeoutError)
                else "network_error"
            )
            raise ProviderProbeError(code) from exc
        try:
            decoded: object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        return HttpJsonResponse(status_code=status_code, payload=decoded)


class HttpxDeadlineJsonTransport:
    """HTTPS JSON transport with a real end-to-end wall-clock deadline.

    The AI orchestrators invoke provider adapters in a worker thread, so this
    synchronous protocol method can own a short-lived async loop.  Cancelling
    the async request closes the connection instead of leaving a blocking
    urllib read alive after the workflow has failed closed.
    """

    _MAX_RESPONSE_BYTES = 1_048_576

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._transport = transport

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise ProviderProbeError("provider_transport_requires_worker_thread")
        return asyncio.run(
            self._post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> HttpJsonResponse:
        body = bytearray()
        try:
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=None,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers=dict(headers),
                        content=canonical_json(payload).encode("utf-8"),
                    ) as response:
                        status_code = int(response.status_code)
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > self._MAX_RESPONSE_BYTES:
                                body.clear()
                                break
                            body.extend(chunk)
        except TimeoutError as exc:
            raise ProviderProbeError("provider_timeout") from exc
        except httpx.TimeoutException as exc:
            raise ProviderProbeError("provider_timeout") from exc
        except httpx.RequestError as exc:
            raise ProviderProbeError("network_error") from exc
        try:
            decoded: object = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = None
        return HttpJsonResponse(status_code=status_code, payload=decoded)


class _NoRedirectHandler(HTTPRedirectHandler):
    """Fail closed instead of following an endpoint-controlled redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class ProviderProbeResponse:
    http_status: int
    request_payload_fingerprint: str
    response_fingerprint: str
    response_model: str
    usage: dict[str, int]


class OpenAICompatibleConnectivityAdapter:
    """One-turn connectivity adapter with no tools or financial context."""

    def __init__(
        self,
        settings: ProviderConnectivitySettings,
        transport: JsonHttpTransport,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def probe(self) -> ProviderProbeResponse:
        payload = {
            "model": self._settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "This is a non-financial connectivity probe. Do not call "
                        "tools. Return only the exact token requested by the user."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Return exactly: {CONNECTIVITY_PROBE_TOKEN}",
                },
            ],
            "max_tokens": 128,
            "temperature": 0,
            "stream": False,
        }
        response = self._transport.post_json(
            url=self._settings.endpoint_url,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Karkinos-AI-Connectivity/1",
            },
            payload=payload,
            timeout_seconds=self._settings.timeout_seconds,
        )
        if response.status_code in {401, 403}:
            raise ProviderProbeError(
                "provider_authentication_failed", http_status=response.status_code
            )
        if response.status_code == 429:
            raise ProviderProbeError(
                "provider_rate_limited", http_status=response.status_code
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderProbeError(
                "provider_http_error", http_status=response.status_code
            )
        body = response.payload
        if not isinstance(body, dict):
            raise ProviderProbeError(
                "provider_invalid_json", http_status=response.status_code
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderProbeError(
                "provider_invalid_response", http_status=response.status_code
            )
        first_choice = choices[0]
        message = (
            first_choice.get("message") if isinstance(first_choice, dict) else None
        )
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or CONNECTIVITY_PROBE_TOKEN not in content:
            raise ProviderProbeError(
                "provider_probe_token_mismatch", http_status=response.status_code
            )
        response_model = str(body.get("model") or self._settings.model_name)
        return ProviderProbeResponse(
            http_status=response.status_code,
            request_payload_fingerprint=content_fingerprint(payload),
            response_fingerprint=content_fingerprint(body),
            response_model=response_model,
            usage=_safe_usage(body.get("usage")),
        )


@dataclass(frozen=True)
class ConnectivityCheckResult:
    check_id: str
    idempotency_key: str
    requested_by: str
    provider_id: str
    model_id: str
    model_name: str
    adapter_kind: str
    endpoint_origin: str
    status: ConnectivityStatus
    request_fingerprint: str
    request_payload_fingerprint: str | None
    response_fingerprint: str | None
    response_model: str | None
    usage: dict[str, int]
    http_status: int | None
    error_code: str | None
    credential_source: str
    started_at: str
    finished_at: str | None
    latency_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.ai.provider_connectivity_result.v1",
            "check_id": self.check_id,
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "adapter_kind": self.adapter_kind,
            "endpoint_origin": self.endpoint_origin,
            "status": self.status.value,
            "probe_version": CONNECTIVITY_PROBE_VERSION,
            "probe_verified": self.status == ConnectivityStatus.PASSED,
            "request_fingerprint": self.request_fingerprint,
            "request_payload_fingerprint": self.request_payload_fingerprint,
            "response_fingerprint": self.response_fingerprint,
            "response_model": self.response_model,
            "usage": dict(self.usage),
            "http_status": self.http_status,
            "error_code": self.error_code,
            "credential_source": self.credential_source,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "latency_ms": self.latency_ms,
            "financial_context_sent": False,
            "context_snapshot_id": None,
            "valuation_snapshot_id": None,
            "ledger_cutoff_id": None,
            "tool_calls_allowed": False,
            "workflow_started": False,
            "artifact_created": False,
            "authority_effect": "none",
            "oms_write_count": 0,
            "ledger_write_count": 0,
            "risk_decision_write_count": 0,
            "capital_authority_write_count": 0,
            "broker_action_count": 0,
        }


_CONNECTIVITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_provider_connectivity_checks (
    check_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    adapter_kind TEXT NOT NULL,
    endpoint_origin TEXT NOT NULL,
    status TEXT NOT NULL,
    probe_version TEXT NOT NULL,
    request_payload_fingerprint TEXT,
    response_fingerprint TEXT,
    response_model TEXT,
    usage_json TEXT NOT NULL,
    http_status INTEGER,
    error_code TEXT,
    credential_source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    latency_ms INTEGER,
    financial_context_sent INTEGER NOT NULL CHECK(financial_context_sent = 0),
    tool_calls_allowed INTEGER NOT NULL CHECK(tool_calls_allowed = 0),
    authority_effect TEXT NOT NULL CHECK(authority_effect = 'none')
);
"""


class ProviderConnectivityAuditStore:
    """Append-oriented, secret-free audit storage for external probes."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_CONNECTIVITY_SCHEMA)

    def create_or_get(
        self,
        *,
        request: ConnectivityCheckRequest,
        settings: ProviderConnectivitySettings,
        request_fingerprint: str,
        started_at: str,
    ) -> tuple[ConnectivityCheckResult, bool]:
        check_id = f"ai-connectivity-{content_fingerprint({'idempotency_key': request.idempotency_key, 'request_fingerprint': request_fingerprint})[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_provider_connectivity_checks WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_fingerprint"]) != request_fingerprint:
                    raise IdempotencyConflict(
                        "connectivity idempotency key was reused with different input"
                    )
                return _result_from_row(existing), False
            conn.execute(
                """
                INSERT INTO ai_provider_connectivity_checks (
                    check_id, idempotency_key, request_fingerprint, requested_by,
                    provider_id, model_id, model_name, adapter_kind,
                    endpoint_origin, status, probe_version,
                    request_payload_fingerprint, response_fingerprint,
                    response_model, usage_json, http_status, error_code,
                    credential_source, started_at, finished_at, latency_ms,
                    financial_context_sent, tool_calls_allowed, authority_effect
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL,
                          '{}', NULL, NULL, ?, ?, NULL, NULL, 0, 0, 'none')
                """,
                (
                    check_id,
                    request.idempotency_key,
                    request_fingerprint,
                    request.requested_by,
                    settings.provider_id,
                    settings.model_id,
                    settings.model_name,
                    settings.adapter_kind,
                    settings.endpoint_origin,
                    ConnectivityStatus.RUNNING.value,
                    CONNECTIVITY_PROBE_VERSION,
                    settings.credential_source,
                    started_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_provider_connectivity_checks WHERE check_id = ?",
                (check_id,),
            ).fetchone()
        assert row is not None
        return _result_from_row(row), True

    def finalize(
        self,
        check_id: str,
        *,
        status: ConnectivityStatus,
        finished_at: str,
        latency_ms: int,
        probe: ProviderProbeResponse | None = None,
        error: ProviderProbeError | None = None,
    ) -> ConnectivityCheckResult:
        if status not in {ConnectivityStatus.PASSED, ConnectivityStatus.FAILED}:
            raise ValueError("connectivity final status must be passed or failed")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE ai_provider_connectivity_checks
                SET status = ?, request_payload_fingerprint = ?,
                    response_fingerprint = ?, response_model = ?, usage_json = ?,
                    http_status = ?, error_code = ?, finished_at = ?, latency_ms = ?
                WHERE check_id = ? AND status = ?
                """,
                (
                    status.value,
                    probe.request_payload_fingerprint if probe else None,
                    probe.response_fingerprint if probe else None,
                    probe.response_model if probe else None,
                    canonical_json(probe.usage if probe else {}),
                    (
                        probe.http_status
                        if probe
                        else (error.http_status if error else None)
                    ),
                    error.code if error else None,
                    finished_at,
                    latency_ms,
                    check_id,
                    ConnectivityStatus.RUNNING.value,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_provider_connectivity_checks WHERE check_id = ?",
                (check_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"AI provider connectivity check not found: {check_id}")
        return _result_from_row(row)


class ProviderConnectivityService:
    """Register and verify one explicitly enabled external model endpoint."""

    def __init__(
        self,
        *,
        settings: ProviderConnectivitySettings,
        audit_store: ProviderConnectivityAuditStore,
        ai_store: AiAuditStore,
        transport: JsonHttpTransport | None = None,
        now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._audit_store = audit_store
        self._ai_store = ai_store
        self._transport = transport or UrllibJsonTransport()
        self._now = now or _utc_now
        self._monotonic = monotonic or time.monotonic

    def run(self, request: ConnectivityCheckRequest) -> ConnectivityCheckResult:
        request_fingerprint = content_fingerprint(
            {
                "idempotency_key": request.idempotency_key,
                "requested_by": request.requested_by,
                "provider_id": self._settings.provider_id,
                "model_id": self._settings.model_id,
                "adapter_kind": self._settings.adapter_kind,
                "endpoint_origin": self._settings.endpoint_origin,
                "endpoint_url_fingerprint": content_fingerprint(
                    self._settings.endpoint_url
                ),
                "probe_version": CONNECTIVITY_PROBE_VERSION,
                "financial_context_sent": False,
                "tool_calls_allowed": False,
                "authority_effect": "none",
            }
        )
        result, should_invoke = self._audit_store.create_or_get(
            request=request,
            settings=self._settings,
            request_fingerprint=request_fingerprint,
            started_at=self._now(),
        )
        if not should_invoke:
            return result

        started = self._monotonic()
        try:
            self._register_runtime_identity()
            adapter = OpenAICompatibleConnectivityAdapter(
                self._settings,
                self._transport,
            )
            probe = adapter.probe()
        except ProviderProbeError as error:
            return self._audit_store.finalize(
                result.check_id,
                status=ConnectivityStatus.FAILED,
                finished_at=self._now(),
                latency_ms=max(0, round((self._monotonic() - started) * 1000)),
                error=error,
            )
        except (IdempotencyConflict, LookupError, PermissionError, ValueError):
            return self._audit_store.finalize(
                result.check_id,
                status=ConnectivityStatus.FAILED,
                finished_at=self._now(),
                latency_ms=max(0, round((self._monotonic() - started) * 1000)),
                error=ProviderProbeError("provider_registration_rejected"),
            )
        return self._audit_store.finalize(
            result.check_id,
            status=ConnectivityStatus.PASSED,
            finished_at=self._now(),
            latency_ms=max(0, round((self._monotonic() - started) * 1000)),
            probe=probe,
        )

    def _register_runtime_identity(self) -> None:
        registry = AiRuntimeRegistry(self._ai_store)
        registry.register_provider(
            ProviderRegistration(
                provider_id=self._settings.provider_id,
                display_name=self._settings.provider_id,
                adapter_kind=self._settings.adapter_kind,
                enabled=True,
                capabilities=("connectivity_probe",),
            )
        )
        registry.register_model(
            ModelRegistration(
                model_id=self._settings.model_id,
                provider_id=self._settings.provider_id,
                model_name=self._settings.model_name,
                enabled=True,
                purposes=("connectivity_probe",),
            )
        )
        registry.require_model(self._settings.model_id)


def load_provider_connectivity_settings(
    runtime_config: BacktestConfig | AIProviderConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> ProviderConnectivitySettings:
    """Resolve one startup-validated provider config and its edge credential."""
    environment = os.environ if environ is None else environ
    if isinstance(runtime_config, AIProviderConfig):
        ai = runtime_config
    elif isinstance(runtime_config, BacktestConfig):
        ai = runtime_config.ai
    else:
        raise ConnectivityConfigurationError("AI startup config is unavailable")
    provider_id = ai.provider.strip()
    model_name = ai.model.strip()
    adapter_kind = ai.adapter_kind.strip()
    base_url = ai.base_url.strip()
    api_key, credential_source = _resolve_api_key(
        ai=ai,
        provider_id=provider_id,
        environment=environment,
    )
    return ProviderConnectivitySettings(
        provider_id=provider_id,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        credential_source=credential_source,
        adapter_kind=adapter_kind,
        enabled=ai.enabled,
        timeout_seconds=ai.timeout_seconds,
    )


def _resolve_api_key(
    *,
    ai: AIProviderConfig,
    provider_id: str,
    environment: Mapping[str, str],
) -> tuple[str, str]:
    generic = str(environment.get("KARKINOS_AI_API_KEY") or "").strip()
    if generic:
        return generic, "environment:KARKINOS_AI_API_KEY"
    configured_env_name = ai.api_key_env.strip()
    if configured_env_name:
        if not _ENV_NAME_PATTERN.fullmatch(configured_env_name):
            raise ConnectivityConfigurationError("AI api_key_env name is invalid")
        configured = str(environment.get(configured_env_name) or "").strip()
        if configured:
            return configured, f"environment:{configured_env_name}"
    provider_env_name = (
        _PROVIDER_ENV_PATTERN.sub("_", provider_id.upper()).strip("_") + "_API_KEY"
    )
    if provider_env_name != "_API_KEY":
        provider_value = str(environment.get(provider_env_name) or "").strip()
        if provider_value:
            return provider_value, f"environment:{provider_env_name}"
    return "", "missing"


def _safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = value.get(key)
        if isinstance(raw, int) and raw >= 0:
            result[key] = raw
    return result


def _result_from_row(row: sqlite3.Row) -> ConnectivityCheckResult:
    usage = json.loads(str(row["usage_json"]))
    return ConnectivityCheckResult(
        check_id=str(row["check_id"]),
        idempotency_key=str(row["idempotency_key"]),
        requested_by=str(row["requested_by"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        model_name=str(row["model_name"]),
        adapter_kind=str(row["adapter_kind"]),
        endpoint_origin=str(row["endpoint_origin"]),
        status=ConnectivityStatus(str(row["status"])),
        request_fingerprint=str(row["request_fingerprint"]),
        request_payload_fingerprint=(
            str(row["request_payload_fingerprint"])
            if row["request_payload_fingerprint"] is not None
            else None
        ),
        response_fingerprint=(
            str(row["response_fingerprint"])
            if row["response_fingerprint"] is not None
            else None
        ),
        response_model=(
            str(row["response_model"]) if row["response_model"] is not None else None
        ),
        usage=usage if isinstance(usage, dict) else {},
        http_status=(
            int(row["http_status"]) if row["http_status"] is not None else None
        ),
        error_code=(str(row["error_code"]) if row["error_code"] is not None else None),
        credential_source=str(row["credential_source"]),
        started_at=str(row["started_at"]),
        finished_at=(
            str(row["finished_at"]) if row["finished_at"] is not None else None
        ),
        latency_ms=(int(row["latency_ms"]) if row["latency_ms"] is not None else None),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
