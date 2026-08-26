"""Secret-free audit mapping at the provider connectivity persistence edge."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from server.contracts.idempotency import IdempotencyConflict

from .contracts import canonical_json, content_fingerprint
from .persistence.provider_connectivity import ProviderConnectivitySqliteRepository
from .provider_connectivity_contracts import (
    CONNECTIVITY_PROBE_VERSION,
    ConnectivityCheckRequest,
    ConnectivityCheckResult,
    ConnectivityStatus,
    ProviderConnectivitySettings,
    ProviderProbeError,
    ProviderProbeResponse,
)


class ProviderConnectivityAuditStore:
    """Append-oriented, secret-free audit storage for external probes."""

    def __init__(self, db_path: str | Path) -> None:
        self._repository = ProviderConnectivitySqliteRepository(db_path)

    def init(self) -> None:
        self._repository.init()

    def create_or_get(
        self,
        *,
        request: ConnectivityCheckRequest,
        settings: ProviderConnectivitySettings,
        request_fingerprint: str,
        started_at: str,
    ) -> tuple[ConnectivityCheckResult, bool]:
        check_id = (
            "ai-connectivity-"
            + content_fingerprint(
                {
                    "idempotency_key": request.idempotency_key,
                    "request_fingerprint": request_fingerprint,
                }
            )[:24]
        )
        row, should_invoke = self._repository.create_or_get(
            check_id=check_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
            requested_by=request.requested_by,
            provider_id=settings.provider_id,
            model_id=settings.model_id,
            model_name=settings.model_name,
            adapter_kind=settings.adapter_kind,
            endpoint_origin=settings.endpoint_origin,
            status=ConnectivityStatus.RUNNING.value,
            probe_version=CONNECTIVITY_PROBE_VERSION,
            credential_source=settings.credential_source,
            started_at=started_at,
        )
        if row is None:
            raise RuntimeError("provider connectivity audit creation failed")
        if str(row["request_fingerprint"]) != request_fingerprint:
            raise IdempotencyConflict(
                "connectivity idempotency key was reused with different input"
            )
        return result_from_mapping(row), should_invoke

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
        row = self._repository.finalize(
            check_id=check_id,
            expected_status=ConnectivityStatus.RUNNING.value,
            status=status.value,
            request_payload_fingerprint=(
                probe.request_payload_fingerprint if probe else None
            ),
            response_fingerprint=probe.response_fingerprint if probe else None,
            response_model=probe.response_model if probe else None,
            usage_json=canonical_json(probe.usage if probe else {}),
            http_status=(
                probe.http_status if probe else (error.http_status if error else None)
            ),
            error_code=error.code if error else None,
            finished_at=finished_at,
            latency_ms=latency_ms,
        )
        if row is None:
            raise LookupError(f"AI provider connectivity check not found: {check_id}")
        return result_from_mapping(row)


def result_from_mapping(row: Mapping[str, Any]) -> ConnectivityCheckResult:
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


__all__ = ["ProviderConnectivityAuditStore", "result_from_mapping"]
