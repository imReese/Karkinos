"""Market Data Serving Projection 测试。"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    capture_provider_payload,
)
from data.market.normalize import (
    normalize_daily_bar,
)
from data.market.revision import (
    publish_daily_bar_revision,
)
from data.market.serving import (
    MarketServingConflictError,
    MarketServingIntegrityError,
    MarketServingStore,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)

_SESSION_DATE = date(
    2026,
    9,
    15,
)


def _instant(
    session_date: date,
    hour: int,
    minute: int,
) -> datetime:
    return datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        hour,
        minute,
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


def _bar(
    symbol: str,
    *,
    instrument_type: InstrumentType = InstrumentType.STOCK,
    session_date: date = _SESSION_DATE,
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    close: str | None = None,
):
    if available_at is None:
        available_at = _instant(
            session_date,
            7,
            1,
        )

    if captured_at is None:
        captured_at = _instant(
            session_date,
            7,
            3,
        )

    event_time = _instant(
        session_date,
        7,
        0,
    )

    if symbol == "000001":
        open_value = "12.10"
        high_value = "12.50"
        low_value = "12.00"
        close_value = close if close is not None else "12.34"
        volume = "100000"
        amount = "1234000"

    elif symbol == "601398":
        open_value = "6.18"
        high_value = "6.25"
        low_value = "6.10"
        close_value = close if close is not None else "6.20"
        volume = "234567"
        amount = "1454321.54"

    else:
        open_value = "10.31"
        high_value = "10.52"
        low_value = "10.20"
        close_value = close if close is not None else "10.48"
        volume = "123456"
        amount = "1283912.42"

    return normalize_daily_bar(
        instrument=_instrument(
            symbol,
            instrument_type,
        ),
        session_date=session_date,
        event_time=event_time,
        available_at=available_at,
        captured_at=captured_at,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close_value,
        volume=volume,
        amount=amount,
        suspended=False,
    )


def _bars(
    *,
    session_date: date = _SESSION_DATE,
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    close_600000: str = "10.48",
):
    return (
        _bar(
            "000001",
            session_date=session_date,
            available_at=available_at,
            captured_at=captured_at,
        ),
        _bar(
            "600000",
            session_date=session_date,
            available_at=available_at,
            captured_at=captured_at,
            close=close_600000,
        ),
    )


def _revision_from_bars(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    bars,
    raw_payload: bytes,
):
    bars = tuple(bars)

    assert bars

    captured_at = bars[0].captured_at

    assert all(bar.captured_at == captured_at for bar in bars)

    capture = capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": (bars[0].session_date.isoformat()),
            "end_date": (bars[0].session_date.isoformat()),
            "instruments": [
                {
                    "symbol": (bar.instrument.symbol),
                    "instrument_type": (bar.instrument.instrument_type.value),
                }
                for bar in bars
            ],
        },
        raw_payload=raw_payload,
        payload_format=(f"{provider}.daily_bars.v1"),
        adapter_version=(f"karkinos.{provider}.v1"),
        started_at=captured_at,
        completed_at=captured_at,
        record_count=len(bars),
    )

    return publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version=("karkinos.market.normalize.v1"),
    )


def _revision(
    store: ContentAddressedObjectStore,
    *,
    provider: str = "tdx",
    session_date: date = _SESSION_DATE,
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    close_600000: str = "10.48",
    raw_payload: bytes = b"provider-response",
):
    return _revision_from_bars(
        store,
        provider=provider,
        bars=_bars(
            session_date=session_date,
            available_at=available_at,
            captured_at=captured_at,
            close_600000=close_600000,
        ),
        raw_payload=raw_payload,
    )


def _object_path(
    store: ContentAddressedObjectStore,
    ref,
):
    return store.root / "sha256" / ref.digest[:2] / ref.digest[2:]


def test_apply_revision_inserts_serving_projection(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    result = serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    assert result.provider == "tdx"

    assert result.revision_id == revision.ref.revision_id

    assert result.materialization_id == materialization.materialization_id

    assert result.inserted_count == 2
    assert result.updated_count == 0
    assert result.unchanged_count == 0
    assert result.stale_skipped_count == 0
    assert result.affected_count == 2


def test_serving_projection_round_trip_preserves_canonical_bars(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert [bar.instrument.symbol for bar in bars] == [
        "000001",
        "600000",
    ]

    assert bars[0].close == Decimal("12.34000000")

    assert bars[1].close == Decimal("10.48000000")

    assert all(bar.session_date == _SESSION_DATE for bar in bars)


def test_reapplying_same_materialization_is_idempotent(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    first = serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    second = serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    assert first.inserted_count == 2

    assert second.inserted_count == 0
    assert second.updated_count == 0
    assert second.unchanged_count == 2
    assert second.stale_skipped_count == 0
    assert second.affected_count == 0


def test_newer_captured_revision_updates_projection(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    early_capture = _instant(
        _SESSION_DATE,
        7,
        3,
    )

    late_capture = _instant(
        _SESSION_DATE,
        9,
        3,
    )

    original_revision, original_materialization = _revision(
        object_store,
        captured_at=early_capture,
        close_600000="10.48",
        raw_payload=b"tdx-r1",
    )

    corrected_revision, corrected_materialization = _revision(
        object_store,
        captured_at=late_capture,
        close_600000="10.49",
        raw_payload=b"tdx-r2",
    )

    assert original_revision.ref != corrected_revision.ref

    serving.apply_daily_bar_revision(
        object_store,
        revision=original_revision,
        materialization=original_materialization,
    )

    result = serving.apply_daily_bar_revision(
        object_store,
        revision=corrected_revision,
        materialization=corrected_materialization,
    )

    # Revision 是整批更新，因此两条 projection 都获得新的 lineage。
    assert result.inserted_count == 0
    assert result.updated_count == 2
    assert result.unchanged_count == 0
    assert result.stale_skipped_count == 0

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    by_symbol = {bar.instrument.symbol: bar for bar in bars}

    assert by_symbol["600000"].close == Decimal("10.49000000")

    assert by_symbol["600000"].captured_at == late_capture


def test_older_revision_does_not_overwrite_newer_projection(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    old_capture = _instant(
        _SESSION_DATE,
        7,
        3,
    )

    new_capture = _instant(
        _SESSION_DATE,
        9,
        3,
    )

    old_revision, old_materialization = _revision(
        object_store,
        captured_at=old_capture,
        close_600000="10.48",
        raw_payload=b"old",
    )

    new_revision, new_materialization = _revision(
        object_store,
        captured_at=new_capture,
        close_600000="10.49",
        raw_payload=b"new",
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=new_revision,
        materialization=new_materialization,
    )

    stale = serving.apply_daily_bar_revision(
        object_store,
        revision=old_revision,
        materialization=old_materialization,
    )

    assert stale.inserted_count == 0
    assert stale.updated_count == 0
    assert stale.unchanged_count == 0
    assert stale.stale_skipped_count == 2

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    by_symbol = {bar.instrument.symbol: bar for bar in bars}

    assert by_symbol["600000"].close == Decimal("10.49000000")


def test_same_capture_with_different_revision_fails_closed(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    captured_at = _instant(
        _SESSION_DATE,
        7,
        3,
    )

    first_revision, first_materialization = _revision(
        object_store,
        captured_at=captured_at,
        close_600000="10.48",
        raw_payload=b"first",
    )

    second_revision, second_materialization = _revision(
        object_store,
        captured_at=captured_at,
        close_600000="10.49",
        raw_payload=b"second",
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=first_revision,
        materialization=first_materialization,
    )

    with pytest.raises(
        MarketServingConflictError,
        match="market_serving_same_capture_conflict",
    ):
        serving.apply_daily_bar_revision(
            object_store,
            revision=second_revision,
            materialization=second_materialization,
        )

    # 冲突不能偷偷覆盖已经存在的数据。
    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    by_symbol = {bar.instrument.symbol: bar for bar in bars}

    assert by_symbol["600000"].close == Decimal("10.48000000")


def test_same_revision_with_later_materialization_updates_provenance(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    early_capture = _instant(
        _SESSION_DATE,
        7,
        3,
    )

    late_capture = _instant(
        _SESSION_DATE,
        9,
        3,
    )

    early_revision, early_materialization = _revision(
        object_store,
        available_at=_instant(
            _SESSION_DATE,
            7,
            1,
        ),
        captured_at=early_capture,
        raw_payload=b"early-capture",
    )

    late_revision, late_materialization = _revision(
        object_store,
        available_at=_instant(
            _SESSION_DATE,
            7,
            1,
        ),
        captured_at=late_capture,
        raw_payload=b"late-capture",
    )

    # 市场事实相同，因此 Revision identity 相同。
    assert early_revision.ref == late_revision.ref

    assert (
        early_materialization.materialization_id
        != late_materialization.materialization_id
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=early_revision,
        materialization=early_materialization,
    )

    result = serving.apply_daily_bar_revision(
        object_store,
        revision=late_revision,
        materialization=late_materialization,
    )

    assert result.updated_count == 2

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert all(bar.captured_at == late_capture for bar in bars)


def test_providers_have_independent_serving_projections(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    tdx_revision, tdx_materialization = _revision(
        object_store,
        provider="tdx",
        close_600000="10.48",
        raw_payload=b"tdx",
    )

    tushare_revision, tushare_materialization = _revision(
        object_store,
        provider="tushare",
        close_600000="10.49",
        raw_payload=b"tushare",
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=tdx_revision,
        materialization=tdx_materialization,
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=tushare_revision,
        materialization=tushare_materialization,
    )

    tdx = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    tushare = serving.read_daily_bars(
        provider="tushare",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert len(tdx) == 2
    assert len(tushare) == 2

    assert {bar.instrument.symbol: bar.close for bar in tdx}["600000"] == Decimal(
        "10.48000000"
    )

    assert {bar.instrument.symbol: bar.close for bar in tushare}["600000"] == Decimal(
        "10.49000000"
    )


def test_read_filters_instruments(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
        instruments=(_instrument("600000"),),
    )

    assert len(bars) == 1

    assert bars[0].instrument == _instrument("600000")


def test_read_empty_instrument_selection_returns_empty(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
        instruments=(),
    )

    assert bars == ()


def test_read_filters_date_range(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    first_date = date(
        2026,
        9,
        15,
    )

    second_date = date(
        2026,
        9,
        16,
    )

    first_revision, first_materialization = _revision(
        object_store,
        session_date=first_date,
        raw_payload=b"day-one",
    )

    second_revision, second_materialization = _revision(
        object_store,
        session_date=second_date,
        raw_payload=b"day-two",
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=first_revision,
        materialization=first_materialization,
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=second_revision,
        materialization=second_materialization,
    )

    bars = serving.read_daily_bars(
        provider="tdx",
        start_date=second_date,
        end_date=second_date,
    )

    assert len(bars) == 2

    assert all(bar.session_date == second_date for bar in bars)


def test_read_order_is_deterministic(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    bars = (
        _bar("600000"),
        _bar("000001"),
    )

    revision, materialization = _revision_from_bars(
        object_store,
        provider="tdx",
        bars=bars,
        raw_payload=b"reverse-order",
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    restored = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert [bar.instrument.symbol for bar in restored] == [
        "000001",
        "600000",
    ]


def test_same_symbol_different_instrument_types_remain_distinct(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    stock = _bar(
        "510300",
        instrument_type=InstrumentType.STOCK,
    )

    etf = _bar(
        "510300",
        instrument_type=InstrumentType.ETF,
    )

    revision, materialization = _revision_from_bars(
        object_store,
        provider="tdx",
        bars=(
            stock,
            etf,
        ),
        raw_payload=b"same-symbol-two-types",
    )

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    restored = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert len(restored) == 2

    assert {bar.instrument for bar in restored} == {
        _instrument(
            "510300",
            InstrumentType.STOCK,
        ),
        _instrument(
            "510300",
            InstrumentType.ETF,
        ),
    }


def test_read_missing_serving_store_returns_empty(
    tmp_path,
) -> None:
    serving = MarketServingStore(tmp_path / "market")

    assert (
        serving.read_daily_bars(
            provider="tdx",
            start_date=_SESSION_DATE,
            end_date=_SESSION_DATE,
        )
        == ()
    )


def test_read_rejects_invalid_date_range(
    tmp_path,
) -> None:
    serving = MarketServingStore(tmp_path / "market")

    with pytest.raises(
        ValueError,
        match="market_serving_date_range_invalid",
    ):
        serving.read_daily_bars(
            provider="tdx",
            start_date=date(
                2026,
                9,
                16,
            ),
            end_date=date(
                2026,
                9,
                15,
            ),
        )


def test_corrupted_materialization_cannot_enter_serving(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    path = _object_path(
        object_store,
        materialization.artifact.object_ref,
    )

    # 主动绕过 immutable 权限，模拟底层 Parquet 损坏。
    os.chmod(
        path,
        0o644,
    )

    path.write_bytes(b"corrupted parquet")

    with pytest.raises(
        MarketServingIntegrityError,
        match=("market_serving_revision_unreadable"),
    ):
        serving.apply_daily_bar_revision(
            object_store,
            revision=revision,
            materialization=materialization,
        )


def test_cross_bound_materialization_is_rejected(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    first_revision, _ = _revision(
        object_store,
        close_600000="10.48",
        raw_payload=b"first",
    )

    _, second_materialization = _revision(
        object_store,
        close_600000="10.49",
        raw_payload=b"second",
    )

    with pytest.raises(
        MarketServingIntegrityError,
        match=("market_serving_materialization_revision_mismatch"),
    ):
        serving.apply_daily_bar_revision(
            object_store,
            revision=first_revision,
            materialization=second_materialization,
        )


def test_serving_rejects_unsupported_schema_version(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    with sqlite3.connect(serving.path) as connection:
        connection.execute("""
            UPDATE serving_metadata
            SET value = '999'
            WHERE key = 'schema_version'
            """)
        connection.commit()

    with pytest.raises(
        MarketServingIntegrityError,
        match=("market_serving_schema_unsupported"),
    ):
        serving.read_daily_bars(
            provider="tdx",
            start_date=_SESSION_DATE,
            end_date=_SESSION_DATE,
        )


def test_serving_rejects_corrupted_projection_row(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    with sqlite3.connect(serving.path) as connection:
        connection.execute("""
            UPDATE daily_bar_projection
            SET suspended = 2
            WHERE symbol = '600000'
            """)
        connection.commit()

    with pytest.raises(
        MarketServingIntegrityError,
        match=("market_serving_projection_invalid"),
    ):
        serving.read_daily_bars(
            provider="tdx",
            start_date=_SESSION_DATE,
            end_date=_SESSION_DATE,
        )


def test_serving_store_can_be_deleted_and_rebuilt(
    tmp_path,
) -> None:
    object_store = ContentAddressedObjectStore(tmp_path / "objects")

    serving = MarketServingStore(tmp_path / "market")

    revision, materialization = _revision(object_store)

    serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    before = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert len(before) == 2

    # Serving DB 只是 projection，可以直接删除。
    serving.path.unlink()

    assert (
        serving.read_daily_bars(
            provider="tdx",
            start_date=_SESSION_DATE,
            end_date=_SESSION_DATE,
        )
        == ()
    )

    # immutable Market history 完全没有受影响。
    assert object_store.verify(revision.ref.manifest_ref)

    assert object_store.verify(materialization.manifest_ref)

    rebuilt = serving.apply_daily_bar_revision(
        object_store,
        revision=revision,
        materialization=materialization,
    )

    assert rebuilt.inserted_count == 2

    after = serving.read_daily_bars(
        provider="tdx",
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
    )

    assert after == before
