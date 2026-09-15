"""Provider Capture 测试。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.market.capture import (
    PROVIDER_CAPTURE_SCHEMA_VERSION,
    ProviderCaptureIntegrityError,
    capture_provider_payload,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectIntegrityError,
)

_BASE_TIME = datetime(
    2026,
    9,
    15,
    7,
    0,
    tzinfo=timezone.utc,
)


def _request() -> dict[str, object]:
    return {
        "symbols": ["600000.SH"],
        "period": "1d",
        "start": "2026-09-01",
        "end": "2026-09-15",
    }


def _capture(
    store: ContentAddressedObjectStore,
    *,
    request: dict[str, object] | None = None,
    raw_payload: bytes = b"provider-response",
    started_at: datetime = _BASE_TIME,
    completed_at: datetime | None = None,
):
    return capture_provider_payload(
        store,
        provider="tdx",
        operation="daily_bars",
        request=request or _request(),
        raw_payload=raw_payload,
        payload_format="tdx.daily_bars.v1",
        adapter_version="karkinos.tdx.v1",
        started_at=started_at,
        completed_at=completed_at or started_at + timedelta(milliseconds=842),
        record_count=11,
    )


def _object_path(
    store: ContentAddressedObjectStore,
    object_id: str,
) -> Path:
    digest = object_id.removeprefix("sha256:")
    return store.root / "sha256" / digest[:2] / digest[2:]


def test_capture_persists_raw_payload(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(
        store,
        raw_payload=b"raw-tdx-payload",
    )

    assert (
        read_provider_raw_payload(
            store,
            capture,
        )
        == b"raw-tdx-payload"
    )

    assert store.verify(capture.raw_object_ref) is True
    assert store.verify(capture.capture_ref) is True


def test_same_raw_payload_reuses_same_raw_object(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _capture(
        store,
        started_at=_BASE_TIME,
    )
    second = _capture(
        store,
        started_at=_BASE_TIME + timedelta(minutes=5),
    )

    assert first.raw_object_ref == second.raw_object_ref


def test_same_capture_inputs_produce_same_capture_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _capture(store)
    second = _capture(store)

    assert first.capture_ref == second.capture_ref
    assert first.capture_id == second.capture_id
    assert first.raw_object_ref == second.raw_object_ref


def test_same_payload_at_different_times_is_different_capture(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _capture(
        store,
        started_at=_BASE_TIME,
    )

    second = _capture(
        store,
        started_at=_BASE_TIME + timedelta(minutes=5),
    )

    # 原始内容没有变化，因此仍然是同一个 Raw Object。
    assert first.raw_object_ref == second.raw_object_ref

    # Capture 表示一次观察事件，抓取时间不同就应当是不同 Capture。
    assert first.capture_ref != second.capture_ref


def test_different_raw_payload_produces_different_raw_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _capture(
        store,
        raw_payload=b"revision-a",
    )
    second = _capture(
        store,
        raw_payload=b"revision-b",
    )

    assert first.raw_object_ref.object_id != second.raw_object_ref.object_id


def test_request_key_order_does_not_change_request_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _capture(
        store,
        request={
            "symbols": ["600000.SH"],
            "period": "1d",
            "start": "2026-09-01",
            "end": "2026-09-15",
        },
    )

    second = _capture(
        store,
        request={
            "end": "2026-09-15",
            "start": "2026-09-01",
            "period": "1d",
            "symbols": ["600000.SH"],
        },
    )

    assert first.request_fingerprint == second.request_fingerprint

    assert first.request_json == second.request_json

    # 其他 Capture 条件也完全一致，因此完整 Capture 身份也相同。
    assert first.capture_ref == second.capture_ref


def test_capture_normalizes_times_to_utc(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    shanghai = timezone(timedelta(hours=8))

    capture = _capture(
        store,
        started_at=datetime(
            2026,
            9,
            15,
            15,
            0,
            tzinfo=shanghai,
        ),
        completed_at=datetime(
            2026,
            9,
            15,
            15,
            0,
            1,
            tzinfo=shanghai,
        ),
    )

    assert capture.started_at == datetime(
        2026,
        9,
        15,
        7,
        0,
        tzinfo=timezone.utc,
    )

    assert capture.completed_at == datetime(
        2026,
        9,
        15,
        7,
        0,
        1,
        tzinfo=timezone.utc,
    )


def test_capture_reports_elapsed_milliseconds(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(
        store,
        started_at=_BASE_TIME,
        completed_at=_BASE_TIME + timedelta(milliseconds=842),
    )

    assert capture.elapsed_ms == 842


@pytest.mark.parametrize(
    "field",
    [
        "started_at",
        "completed_at",
    ],
)
def test_capture_rejects_naive_datetime(
    tmp_path,
    field: str,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    kwargs = {
        "store": store,
        "provider": "tdx",
        "operation": "daily_bars",
        "request": _request(),
        "raw_payload": b"payload",
        "payload_format": "tdx.daily_bars.v1",
        "adapter_version": "karkinos.tdx.v1",
        "started_at": _BASE_TIME,
        "completed_at": _BASE_TIME + timedelta(seconds=1),
        "record_count": 1,
    }

    kwargs[field] = datetime(
        2026,
        9,
        15,
        7,
        0,
    )

    with pytest.raises(
        ValueError,
        match=(f"provider_capture_{field}" "_must_be_timezone_aware"),
    ):
        capture_provider_payload(**kwargs)


def test_capture_rejects_completion_before_start(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        ValueError,
        match="provider_capture_completed_before_started",
    ):
        _capture(
            store,
            started_at=_BASE_TIME,
            completed_at=_BASE_TIME - timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    "record_count",
    [
        -1,
        True,
        1.5,
        "1",
    ],
)
def test_capture_rejects_invalid_record_count(
    tmp_path,
    record_count,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        ValueError,
        match="provider_capture_record_count_invalid",
    ):
        capture_provider_payload(
            store,
            provider="tdx",
            operation="daily_bars",
            request=_request(),
            raw_payload=b"payload",
            payload_format="tdx.daily_bars.v1",
            adapter_version="karkinos.tdx.v1",
            started_at=_BASE_TIME,
            completed_at=_BASE_TIME + timedelta(seconds=1),
            record_count=record_count,
        )


@pytest.mark.parametrize(
    "request_payload",
    [
        {
            "symbols": ["600000.SH"],
            "api_key": "secret",
        },
        {
            "symbols": ["600000.SH"],
            "auth": {
                "token": "secret",
            },
        },
        {
            "symbols": ["600000.SH"],
            "headers": {
                "Authorization": "Bearer secret",
            },
        },
        {
            "symbols": ["600000.SH"],
            "credentials": {
                "username": "user",
            },
        },
    ],
)
def test_capture_rejects_sensitive_request_fields(
    tmp_path,
    request_payload,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        ValueError,
        match="provider_capture_request_contains_secret",
    ):
        _capture(
            store,
            request=request_payload,
        )


def test_capture_manifest_round_trip(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    original = _capture(store)

    restored = read_provider_capture(
        store,
        original.capture_ref,
    )

    assert restored == original
    assert restored.capture_id == original.capture_id
    assert restored.raw_object_ref == original.raw_object_ref
    assert restored.request_fingerprint == original.request_fingerprint


def test_capture_manifest_contains_expected_schema_version(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(store)

    manifest_bytes = store.read_bytes(capture.capture_ref)

    manifest = json.loads(manifest_bytes)

    assert manifest["schema_version"] == PROVIDER_CAPTURE_SCHEMA_VERSION


def test_corrupted_capture_manifest_fails_closed(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(store)

    path = _object_path(
        store,
        capture.capture_ref.object_id,
    )

    # 测试主动绕过只读权限，模拟磁盘损坏或外部篡改。
    os.chmod(path, 0o644)
    path.write_bytes(b"corrupted manifest")

    with pytest.raises(ObjectIntegrityError):
        read_provider_capture(
            store,
            capture.capture_ref,
        )


def test_forged_request_fingerprint_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(store)

    manifest = json.loads(store.read_bytes(capture.capture_ref))

    manifest["request_fingerprint"] = "sha256:" + "0" * 64

    forged_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    forged_ref = store.put_bytes(forged_bytes)

    with pytest.raises(
        ProviderCaptureIntegrityError,
        match=("provider_capture_request_fingerprint_mismatch"),
    ):
        read_provider_capture(
            store,
            forged_ref,
        )


def test_unsupported_capture_schema_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(store)

    manifest = json.loads(store.read_bytes(capture.capture_ref))

    manifest["schema_version"] = "karkinos.provider_capture.v999"

    forged_ref = store.put_bytes(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )

    with pytest.raises(
        ProviderCaptureIntegrityError,
        match=("provider_capture_schema_version_unsupported"),
    ):
        read_provider_capture(
            store,
            forged_ref,
        )


def test_corrupted_raw_payload_fails_closed(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    capture = _capture(
        store,
        raw_payload=b"trusted-provider-response",
    )

    path = _object_path(
        store,
        capture.raw_object_ref.object_id,
    )

    os.chmod(path, 0o644)
    path.write_bytes(b"corrupted-provider-response")

    with pytest.raises(ObjectIntegrityError):
        read_provider_raw_payload(
            store,
            capture,
        )
