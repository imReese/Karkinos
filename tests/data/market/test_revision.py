"""Market Data Revision 测试。"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.revision import (
    MARKET_REVISION_SCHEMA_VERSION,
    MarketRevisionIntegrityError,
    MarketRevisionRef,
    daily_bar_content_fingerprint,
    publish_daily_bar_revision,
    read_market_revision,
    read_market_revision_materialization,
    validate_daily_bar_materialization,
)
from data.market.schema import daily_bars_to_table
from data.storage.objects import ContentAddressedObjectStore
from data.storage.parquet import ParquetIntegrityError

_SESSION_DATE = date(2026, 9, 15)

_EVENT_TIME = datetime(
    2026,
    9,
    15,
    7,
    0,
    tzinfo=timezone.utc,
)

_AVAILABLE_AT = datetime(
    2026,
    9,
    15,
    7,
    1,
    tzinfo=timezone.utc,
)

_CAPTURED_AT = datetime(
    2026,
    9,
    15,
    7,
    3,
    tzinfo=timezone.utc,
)


def _instrument(
    symbol: str,
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _capture(
    store: ContentAddressedObjectStore,
    *,
    provider: str = "tdx",
    completed_at: datetime = _CAPTURED_AT,
):
    return capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": "2026-09-15",
            "end_date": "2026-09-15",
            "instruments": [
                {
                    "symbol": "000001",
                    "instrument_type": "stock",
                },
                {
                    "symbol": "600000",
                    "instrument_type": "stock",
                },
            ],
        },
        raw_payload=b"provider-daily-response",
        payload_format=f"{provider}.daily_bars.v1",
        adapter_version=f"karkinos.{provider}.v1",
        started_at=completed_at - timedelta(milliseconds=842),
        completed_at=completed_at,
        record_count=2,
    )


def _bar(
    *,
    symbol: str,
    captured_at: datetime = _CAPTURED_AT,
    available_at: datetime = _AVAILABLE_AT,
    close: str,
):
    if symbol == "600000":
        open_value = "10.31"
        high_value = "10.52"
        low_value = "10.20"
    else:
        open_value = "12.10"
        high_value = "12.50"
        low_value = "12.00"

    return normalize_daily_bar(
        instrument=_instrument(symbol),
        session_date=_SESSION_DATE,
        event_time=_EVENT_TIME,
        available_at=available_at,
        captured_at=captured_at,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close,
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )


def _bars(
    *,
    captured_at: datetime = _CAPTURED_AT,
    available_at: datetime = _AVAILABLE_AT,
    close_600000: str = "10.48",
):
    return (
        _bar(
            symbol="600000",
            captured_at=captured_at,
            available_at=available_at,
            close=close_600000,
        ),
        _bar(
            symbol="000001",
            captured_at=captured_at,
            available_at=available_at,
            close="12.34",
        ),
    )


def _object_path(
    store: ContentAddressedObjectStore,
    object_id: str,
) -> Path:
    digest = object_id.removeprefix("sha256:")

    return store.root / "sha256" / digest[:2] / digest[2:]


def test_same_facts_and_same_capture_are_idempotent(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)
    bars = _bars()

    first_revision, first_materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version="karkinos.market.normalize.v1",
    )

    second_revision, second_materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version="karkinos.market.normalize.v1",
    )

    assert first_revision == second_revision
    assert first_materialization == second_materialization


def test_same_facts_from_different_captures_share_revision(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first_capture = _capture(
        store,
        completed_at=_CAPTURED_AT,
    )

    second_capture_time = _CAPTURED_AT + timedelta(minutes=5)
    second_capture = _capture(
        store,
        completed_at=second_capture_time,
    )

    first_revision, first_materialization = publish_daily_bar_revision(
        store,
        capture=first_capture,
        bars=_bars(
            captured_at=first_capture.completed_at,
        ),
        normalizer_version="karkinos.market.normalize.v1",
    )

    second_revision, second_materialization = publish_daily_bar_revision(
        store,
        capture=second_capture,
        bars=_bars(
            captured_at=second_capture.completed_at,
        ),
        normalizer_version="karkinos.market.normalize.v1",
    )

    # 抓取事件不同。
    assert first_capture.capture_id != second_capture.capture_id

    # Parquet 中包含 captured_at，因此物理对象也不同。
    assert (
        first_materialization.artifact.object_ref
        != second_materialization.artifact.object_ref
    )

    # 但金融市场事实完全相同，因此仍然属于同一个 Revision。
    assert first_revision.ref == second_revision.ref
    assert first_revision.content_fingerprint == second_revision.content_fingerprint

    # 不同 Capture 会产生不同的 provenance materialization。
    assert (
        first_materialization.materialization_id
        != second_materialization.materialization_id
    )


def test_availability_evidence_does_not_change_revision_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    first = daily_bars_to_table(
        _bars(
            available_at=_AVAILABLE_AT,
        )
    )

    second = daily_bars_to_table(
        _bars(
            available_at=(_AVAILABLE_AT + timedelta(seconds=30)),
        )
    )

    # available_at 属于 PIT provenance，
    # 不属于市场价格事实本身。
    assert daily_bar_content_fingerprint(first) == daily_bar_content_fingerprint(second)


def test_price_change_creates_new_revision(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    first_revision, _ = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(
            close_600000="10.48",
        ),
        normalizer_version="karkinos.market.normalize.v1",
    )

    corrected_revision, _ = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(
            close_600000="10.49",
        ),
        normalizer_version="karkinos.market.normalize.v1",
    )

    assert first_revision.content_fingerprint != corrected_revision.content_fingerprint

    assert first_revision.ref != corrected_revision.ref


def test_input_order_does_not_change_revision_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    bars = _bars()

    forward_revision, forward_materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version="karkinos.market.normalize.v1",
    )

    reverse_revision, reverse_materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=tuple(reversed(bars)),
        normalizer_version="karkinos.market.normalize.v1",
    )

    assert forward_revision == reverse_revision

    assert (
        forward_materialization.artifact.object_ref
        == reverse_materialization.artifact.object_ref
    )


def test_same_facts_from_different_providers_are_different_revisions(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    tdx_capture = _capture(
        store,
        provider="tdx",
    )

    akshare_capture = _capture(
        store,
        provider="akshare",
    )

    bars = _bars()

    tdx_revision, _ = publish_daily_bar_revision(
        store,
        capture=tdx_capture,
        bars=bars,
        normalizer_version="karkinos.market.normalize.v1",
    )

    akshare_revision, _ = publish_daily_bar_revision(
        store,
        capture=akshare_capture,
        bars=bars,
        normalizer_version="karkinos.market.normalize.v1",
    )

    # canonical 市场事实相同。
    assert tdx_revision.content_fingerprint == akshare_revision.content_fingerprint

    # Provider 是 Revision identity 的一部分。
    assert tdx_revision.ref != akshare_revision.ref


def test_normalizer_version_does_not_change_revision_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)
    bars = _bars()

    first_revision, first_materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version="normalizer.v1",
    )

    second_revision, second_materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version="normalizer.v2",
    )

    # normalizer 的实现版本属于 provenance，不属于市场事实身份。
    assert first_revision.ref == second_revision.ref

    # 物化证据必须保留实际使用的 normalizer 版本。
    assert (
        first_materialization.materialization_id
        != second_materialization.materialization_id
    )


def test_revision_manifest_round_trip(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    revision, _ = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    restored = read_market_revision(
        store,
        revision.ref,
    )

    assert restored == revision
    assert restored.ref.revision_id == revision.ref.revision_id


def test_materialization_manifest_round_trip(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    _, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    restored = read_market_revision_materialization(
        store,
        materialization.manifest_ref,
    )

    assert restored == materialization


def test_valid_materialization_replays_revision(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    # 成功时不返回值，只要不抛异常即表示完整 lineage 可重放。
    validate_daily_bar_materialization(
        store,
        revision=revision,
        materialization=materialization,
    )


def test_materialization_rejects_wrong_capture_provider(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    tdx_capture = _capture(
        store,
        provider="tdx",
    )

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=tdx_capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    wrong_capture = _capture(
        store,
        provider="akshare",
    )

    forged = replace(
        materialization,
        capture_ref=wrong_capture.capture_ref,
    )

    with pytest.raises(
        MarketRevisionIntegrityError,
        match="market_revision_provider_mismatch",
    ):
        validate_daily_bar_materialization(
            store,
            revision=revision,
            materialization=forged,
        )


def test_materialization_rejects_wrong_capture_time(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    original_capture = _capture(store)

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=original_capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    later_capture = _capture(
        store,
        completed_at=(_CAPTURED_AT + timedelta(minutes=5)),
    )

    forged = replace(
        materialization,
        capture_ref=later_capture.capture_ref,
    )

    with pytest.raises(
        MarketRevisionIntegrityError,
        match="market_revision_capture_time_mismatch",
    ):
        validate_daily_bar_materialization(
            store,
            revision=revision,
            materialization=forged,
        )


def test_materialization_rejects_forged_revision_row_count(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    forged_revision = replace(
        revision,
        row_count=revision.row_count + 1,
    )

    with pytest.raises(
        MarketRevisionIntegrityError,
        match="market_revision_row_count_mismatch",
    ):
        validate_daily_bar_materialization(
            store,
            revision=forged_revision,
            materialization=materialization,
        )


def test_corrupted_parquet_materialization_fails_closed(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    path = _object_path(
        store,
        materialization.artifact.object_ref.object_id,
    )

    # 测试主动绕过只读权限，模拟磁盘损坏或外部篡改。
    os.chmod(path, 0o644)
    path.write_bytes(b"corrupted parquet")

    with pytest.raises(ParquetIntegrityError):
        validate_daily_bar_materialization(
            store,
            revision=revision,
            materialization=materialization,
        )


def test_unsupported_revision_schema_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    revision, _ = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=_bars(),
        normalizer_version="karkinos.market.normalize.v1",
    )

    payload = json.loads(store.read_bytes(revision.ref.manifest_ref))

    assert payload["schema_version"] == MARKET_REVISION_SCHEMA_VERSION

    payload["schema_version"] = "karkinos.market_revision.v999"

    forged_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    forged_ref = MarketRevisionRef(manifest_ref=store.put_bytes(forged_bytes))

    with pytest.raises(
        MarketRevisionIntegrityError,
        match="market_revision_schema_version_unsupported",
    ):
        read_market_revision(
            store,
            forged_ref,
        )


def test_revision_rejects_multiple_partition_dates(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    second_day = normalize_daily_bar(
        instrument=_instrument("000001"),
        session_date=date(2026, 9, 14),
        event_time=datetime(
            2026,
            9,
            14,
            7,
            0,
            tzinfo=timezone.utc,
        ),
        available_at=datetime(
            2026,
            9,
            14,
            7,
            1,
            tzinfo=timezone.utc,
        ),
        captured_at=capture.completed_at,
        open_value="12.10",
        high_value="12.50",
        low_value="12.00",
        close_value="12.34",
        volume="123456",
        amount="1283912.42",
        suspended=False,
    )

    with pytest.raises(
        ValueError,
        match="market_revision_multiple_partitions",
    ):
        publish_daily_bar_revision(
            store,
            capture=capture,
            bars=(
                _bars()[0],
                second_day,
            ),
            normalizer_version="karkinos.market.normalize.v1",
        )


def test_revision_rejects_empty_batch(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    capture = _capture(store)

    with pytest.raises(
        ValueError,
        match="market_revision_daily_bars_empty",
    ):
        publish_daily_bar_revision(
            store,
            capture=capture,
            bars=(),
            normalizer_version="karkinos.market.normalize.v1",
        )
