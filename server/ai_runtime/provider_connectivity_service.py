"""Application service for explicit provider connectivity verification."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from server.contracts.idempotency import IdempotencyConflict

from .contracts import ModelRegistration, ProviderRegistration, content_fingerprint
from .provider_connectivity_adapter import OpenAICompatibleConnectivityAdapter
from .provider_connectivity_audit import ProviderConnectivityAuditStore
from .provider_connectivity_contracts import (
    CONNECTIVITY_PROBE_VERSION,
    ConnectivityCheckRequest,
    ConnectivityCheckResult,
    ConnectivityStatus,
    JsonHttpTransport,
    ProviderConnectivitySettings,
    ProviderProbeError,
)
from .provider_connectivity_transport import UrllibJsonTransport
from .registry import AiRuntimeRegistry
from .store import AiAuditStore


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
        self._now = now or utc_now
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
            probe = OpenAICompatibleConnectivityAdapter(
                self._settings,
                self._transport,
            ).probe()
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


__all__ = ["ProviderConnectivityService", "utc_now"]
