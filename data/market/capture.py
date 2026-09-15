"""Provider 数据抓取证据。

本模块记录一次外部数据获取事实，包括请求身份、抓取时间和原始数据对象。

ProviderCapture 是 Market Data lineage 的起点：

Provider
    ↓
ProviderCapture
    ↓
Raw Object
    ↓
Normalize
    ↓
MarketRevision

本模块不负责解释行情字段，也不负责生成 canonical market data。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
)

logger = logging.getLogger(__name__)


PROVIDER_CAPTURE_SCHEMA_VERSION = "karkinos.provider_capture.v1"


class ProviderCaptureError(RuntimeError):
    """Provider Capture 基础异常。"""


class ProviderCaptureIntegrityError(ProviderCaptureError):
    """Capture manifest 或 lineage 完整性校验失败。"""


@dataclass(frozen=True, slots=True)
class ProviderCapture:
    """一次不可变的 Provider 数据抓取记录。

    capture_ref 指向 Capture Manifest；
    raw_object_ref 指向 Provider 原始响应内容。

    Capture 表示“我们在什么时候，通过什么请求，看到了什么”，
    不表示这些数据经过规范化后对应哪一版 Market Data。
    """

    capture_ref: ObjectRef
    raw_object_ref: ObjectRef

    provider: str
    operation: str

    request_fingerprint: str
    request_json: str

    payload_format: str
    adapter_version: str

    started_at: datetime
    completed_at: datetime

    record_count: int | None = None

    @property
    def capture_id(self) -> str:
        """Capture 的稳定内容身份。"""
        return self.capture_ref.object_id

    @property
    def elapsed_ms(self) -> int:
        """本次 Provider 调用耗时，单位毫秒。"""
        duration = self.completed_at - self.started_at
        return max(0, int(duration.total_seconds() * 1000))


def capture_provider_payload(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    operation: str,
    request: Mapping[str, Any],
    raw_payload: bytes,
    payload_format: str,
    adapter_version: str,
    started_at: datetime,
    completed_at: datetime,
    record_count: int | None = None,
) -> ProviderCapture:
    """固化一次 Provider 调用及其原始数据。

    ``request`` 必须是不含认证信息的可 JSON 序列化请求描述。
    API Key、Token、密码等秘密信息禁止进入 Capture Manifest。

    ``raw_payload`` 是 Provider 原始响应的稳定字节表示。
    如何把 SDK 原生对象转换成这些字节，由具体 Provider Adapter 负责。
    """
    provider = _require_non_empty_text(
        provider,
        field="provider",
    )
    operation = _require_non_empty_text(
        operation,
        field="operation",
    )
    payload_format = _require_non_empty_text(
        payload_format,
        field="payload_format",
    )
    adapter_version = _require_non_empty_text(
        adapter_version,
        field="adapter_version",
    )

    if not isinstance(raw_payload, bytes):
        raise TypeError("provider_capture_raw_payload_must_be_bytes")

    started_at = _utc_instant(
        started_at,
        field="started_at",
    )
    completed_at = _utc_instant(
        completed_at,
        field="completed_at",
    )

    if completed_at < started_at:
        raise ValueError("provider_capture_completed_before_started")

    if record_count is not None:
        if (
            isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count < 0
        ):
            raise ValueError("provider_capture_record_count_invalid")

    _reject_sensitive_request_fields(request)

    request_json = _canonical_json(request)
    request_fingerprint = _sha256_text(request_json)

    # 先固化 Provider 原始响应。
    # 同样的原始内容会自然得到同一个 ObjectRef。
    raw_object_ref = store.put_bytes(raw_payload)

    manifest_payload = {
        "schema_version": PROVIDER_CAPTURE_SCHEMA_VERSION,
        "provider": provider,
        "operation": operation,
        "request": json.loads(request_json),
        "request_fingerprint": request_fingerprint,
        "payload_format": payload_format,
        "adapter_version": adapter_version,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "record_count": record_count,
        "raw_object": _object_ref_payload(raw_object_ref),
    }

    # Capture Manifest 本身也是 immutable object。
    # 因此 capture_id 就是 manifest bytes 的 SHA-256 ObjectID。
    manifest_bytes = _canonical_json(manifest_payload).encode("utf-8")
    capture_ref = store.put_bytes(manifest_bytes)

    capture = ProviderCapture(
        capture_ref=capture_ref,
        raw_object_ref=raw_object_ref,
        provider=provider,
        operation=operation,
        request_fingerprint=request_fingerprint,
        request_json=request_json,
        payload_format=payload_format,
        adapter_version=adapter_version,
        started_at=started_at,
        completed_at=completed_at,
        record_count=record_count,
    )

    logger.info(
        "Provider 数据抓取已固化 "
        "provider=%s operation=%s capture_id=%s "
        "raw_object_id=%s bytes=%d records=%s elapsed_ms=%d",
        capture.provider,
        capture.operation,
        capture.capture_id,
        capture.raw_object_ref.object_id,
        capture.raw_object_ref.size_bytes,
        capture.record_count,
        capture.elapsed_ms,
    )

    return capture


def read_provider_capture(
    store: ContentAddressedObjectStore,
    capture_ref: ObjectRef,
) -> ProviderCapture:
    """读取并验证一份 Provider Capture Manifest。"""
    manifest_bytes = store.read_bytes(capture_ref)

    try:
        payload = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderCaptureIntegrityError(
            "provider_capture_manifest_invalid_json"
        ) from exc

    if not isinstance(payload, dict):
        raise ProviderCaptureIntegrityError("provider_capture_manifest_must_be_object")

    if payload.get("schema_version") != PROVIDER_CAPTURE_SCHEMA_VERSION:
        raise ProviderCaptureIntegrityError(
            "provider_capture_schema_version_unsupported"
        )

    try:
        provider = _require_non_empty_text(
            payload["provider"],
            field="provider",
        )
        operation = _require_non_empty_text(
            payload["operation"],
            field="operation",
        )
        payload_format = _require_non_empty_text(
            payload["payload_format"],
            field="payload_format",
        )
        adapter_version = _require_non_empty_text(
            payload["adapter_version"],
            field="adapter_version",
        )

        request = payload["request"]

        if not isinstance(request, dict):
            raise ProviderCaptureIntegrityError("provider_capture_request_invalid")

        _reject_sensitive_request_fields(request)

        request_json = _canonical_json(request)
        request_fingerprint = _sha256_text(request_json)

        if payload.get("request_fingerprint") != request_fingerprint:
            raise ProviderCaptureIntegrityError(
                "provider_capture_request_fingerprint_mismatch"
            )

        started_at = _utc_instant(
            datetime.fromisoformat(payload["started_at"]),
            field="started_at",
        )
        completed_at = _utc_instant(
            datetime.fromisoformat(payload["completed_at"]),
            field="completed_at",
        )

        if completed_at < started_at:
            raise ProviderCaptureIntegrityError("provider_capture_time_order_invalid")

        record_count = payload.get("record_count")

        if record_count is not None and (
            isinstance(record_count, bool)
            or not isinstance(record_count, int)
            or record_count < 0
        ):
            raise ProviderCaptureIntegrityError("provider_capture_record_count_invalid")

        raw_object_ref = _object_ref_from_payload(payload["raw_object"])

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        if isinstance(exc, ProviderCaptureIntegrityError):
            raise

        raise ProviderCaptureIntegrityError(
            "provider_capture_manifest_invalid"
        ) from exc

    return ProviderCapture(
        capture_ref=capture_ref,
        raw_object_ref=raw_object_ref,
        provider=provider,
        operation=operation,
        request_fingerprint=request_fingerprint,
        request_json=request_json,
        payload_format=payload_format,
        adapter_version=adapter_version,
        started_at=started_at,
        completed_at=completed_at,
        record_count=record_count,
    )


def read_provider_raw_payload(
    store: ContentAddressedObjectStore,
    capture: ProviderCapture,
) -> bytes:
    """读取 Capture 对应的原始 Provider 数据。

    ObjectStore 会再次校验 SHA-256，因此损坏的数据不会进入后续
    normalization 流程。
    """
    return store.read_bytes(capture.raw_object_ref)


def _canonical_json(value: Any) -> str:
    """生成稳定 JSON 表示，用于请求和 Manifest 身份计算。"""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("provider_capture_value_not_json_serializable") from exc


def _sha256_text(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _utc_instant(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"provider_capture_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"provider_capture_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


def _require_non_empty_text(
    value: Any,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"provider_capture_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"provider_capture_{field}_missing")

    return normalized


def _object_ref_payload(
    ref: ObjectRef,
) -> dict[str, object]:
    return {
        "object_id": ref.object_id,
        "size_bytes": ref.size_bytes,
    }


def _object_ref_from_payload(
    value: Any,
) -> ObjectRef:
    if not isinstance(value, dict):
        raise ProviderCaptureIntegrityError("provider_capture_object_ref_invalid")

    try:
        return ObjectRef(
            object_id=value["object_id"],
            size_bytes=value["size_bytes"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderCaptureIntegrityError(
            "provider_capture_object_ref_invalid"
        ) from exc


_SENSITIVE_REQUEST_KEYS = frozenset(
    {
        "authorization",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "key",
        "credential",
        "credentials",
    }
)


def _reject_sensitive_request_fields(
    value: Any,
) -> None:
    """禁止把认证秘密写入可长期保存的 Capture Manifest。"""
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")

            if normalized_key in _SENSITIVE_REQUEST_KEYS:
                raise ValueError("provider_capture_request_contains_secret")

            _reject_sensitive_request_fields(child)

        return

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for child in value:
            _reject_sensitive_request_fields(child)
