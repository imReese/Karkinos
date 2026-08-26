"""Typed, secret-aware contracts for provider connectivity checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlparse

CONNECTIVITY_CONFIRMATION = (
    "run_external_ai_connectivity_check_without_financial_context"
)
CONNECTIVITY_PROBE_VERSION = "karkinos.ai.connectivity_probe.v1"
CONNECTIVITY_PROBE_TOKEN = "KARKINOS_AI_CONNECTIVITY_OK"


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


@dataclass(frozen=True)
class ProviderProbeResponse:
    http_status: int
    request_payload_fingerprint: str
    response_fingerprint: str
    response_model: str
    usage: dict[str, int]


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


__all__ = [
    "CONNECTIVITY_CONFIRMATION",
    "CONNECTIVITY_PROBE_TOKEN",
    "CONNECTIVITY_PROBE_VERSION",
    "ConnectivityCheckRequest",
    "ConnectivityCheckResult",
    "ConnectivityConfigurationError",
    "ConnectivityStatus",
    "HttpJsonResponse",
    "JsonHttpTransport",
    "ProviderConnectivitySettings",
    "ProviderProbeError",
    "ProviderProbeResponse",
]
