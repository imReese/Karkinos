"""Real range SDK responses produce unchanged daily facts and strict replay."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
)
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.capture import read_provider_raw_payload
from data.market.contracts import DailyBarProviderUnavailableError, DailyBarRequest
from data.market.cross_source import (
    CrossSourceDailyBarUnavailableError,
    ingest_cross_source_daily_bars,
    ingest_cross_source_daily_bars_range,
)
from data.market.ingestion import DailyBarIngestionCapturedFailure
from data.market.quality import RESEARCH_STRICT_DAILY
from data.market.revision import validate_daily_bar_materialization
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.providers.baostock import (
    BaoStockDailyBarProvider,
    BaoStockDailyBarRequestError,
    BaoStockDailyBarResponseError,
)
from data.providers.eastmoney import (
    AkshareDailyBarProvider,
    AkshareDailyBarRequestError,
    AkshareDailyBarResponseError,
)
from data.providers.tencent import (
    AkshareTencentDailyBarProvider,
    AkshareTencentDailyBarRequestError,
    AkshareTencentDailyBarResponseError,
)
from data.providers.tushare import (
    TushareDailyBarProvider,
    TushareDailyBarRequestError,
    TushareDailyBarResponseError,
)
from data.storage.objects import ContentAddressedObjectStore
from tests.data.providers.test_akshare_tencent_daily import FakeTencent
from tests.data.providers.test_baostock_daily import FakeBaoStock, FakeResult

DAYS = (date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17))
NOW = datetime(2026, 9, 17, 8, tzinfo=timezone.utc)
KEYS = (
    InstrumentKey("600000", InstrumentType.STOCK),
    InstrumentKey("600001", InstrumentType.STOCK),
)


def providers(days=DAYS, keys=KEYS):
    bao = FakeBaoStock()
    tx = FakeTencent()
    for key in keys:
        bao.results["sh." + key.symbol] = FakeResult(
            [
                [
                    day.isoformat(),
                    "sh." + key.symbol,
                    "10",
                    "10.1",
                    "9.9",
                    "10",
                    "10000",
                    "100000",
                    "3",
                    "1",
                ]
                for day in days
            ]
        )
        tx.frames["sh" + key.symbol] = pd.DataFrame(
            [
                {
                    "date": day,
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "volume": 10000,
                    "amount": 100000,
                }
                for day in days
            ]
        )
    return (
        bao,
        tx,
        BaoStockDailyBarProvider(bao, clock=lambda: NOW),
        AkshareTencentDailyBarProvider(tx, clock=lambda: NOW),
    )


def ingest(store, primary, comparison, expected=None, *, request=None, calls=None):
    return ingest_cross_source_daily_bars_range(
        primary,
        comparison,
        store,
        request=request or DailyBarRequest(KEYS, DAYS[0], DAYS[-1]),
        expected_sessions=expected or {day: KEYS for day in DAYS},
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=NOW,
        before_fetch=(lambda descriptor: calls.append(descriptor.provider))
        if calls is not None
        else None,
    )


def test_range_fallback_reuses_captured_primary_without_repeating_provider_budget(
    tmp_path,
):
    bao, _, primary, comparison = providers()
    objects = ContentAddressedObjectStore(tmp_path)
    cache, fetched = {}, []

    def unavailable(request):
        raise DailyBarProviderUnavailableError("fixture_unavailable")

    offline = SimpleNamespace(
        descriptor=replace(
            comparison.descriptor, provider="offline", upstream_group="offline"
        ),
        fetch_daily_bars=unavailable,
    )
    kwargs = dict(
        request=DailyBarRequest(KEYS, DAYS[0], DAYS[-1]),
        expected_sessions={day: KEYS for day in DAYS},
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="fixture.v1",
        checked_at=NOW,
        before_fetch=lambda descriptor: fetched.append(descriptor.provider),
        ingestion_cache=cache,
    )
    with pytest.raises(CrossSourceDailyBarUnavailableError):
        ingest_cross_source_daily_bars_range(primary, offline, objects, **kwargs)
    captured = next(iter(cache.values()))[0].capture
    results = ingest_cross_source_daily_bars_range(
        primary, comparison, objects, **kwargs
    )
    assert len(results) == len(DAYS)
    assert all(
        row.primary.capture == captured and row.eligible_for_verified_dataset
        for row in results
    )
    assert len(bao.query_calls) == len(KEYS)
    assert fetched == ["baostock", "offline", "akshare_tencent"]

    changed = {day: KEYS[:1] if day == DAYS[0] else KEYS for day in DAYS}
    fresh_bao, _, _, _ = providers()
    bao.results = fresh_bao.results
    ingest_cross_source_daily_bars_range(
        primary, comparison, objects, **{**kwargs, "expected_sessions": changed}
    )
    assert len(bao.query_calls) == 2 * len(KEYS)


def manifest(store, results, expected):
    parts = tuple(
        DailyBarDatasetPartition(
            item.primary.revision.partition_date,
            item.primary.revision.provider,
            item.primary.revision.ref.revision_id,
            item.primary.materialization.materialization_id,
            item.verification.verification_id,
            instruments=expected[item.primary.revision.partition_date],
        )
        for item in results
    )
    snapshot = DailyBarDatasetSnapshot(
        start_date=min(expected),
        end_date=max(expected),
        cutoff=NOW,
        instruments=tuple(
            sorted(
                {key for keys in expected.values() for key in keys},
                key=lambda key: key.symbol,
            )
        ),
        resolver_policy_id="fixture.range.verified",
        market_schema_version=DAILY_BAR_SCHEMA_VERSION,
        partitions=parts,
        session_memberships=tuple(
            DailyBarDatasetMembership(day, keys, NOW)
            for day, keys in sorted(expected.items())
        ),
        universe_policy_id="fixture.exploratory.range",
    )
    return publish_daily_bar_dataset_manifest(store, snapshot)


def test_two_real_range_captures_derive_strict_days_and_explicit_projection(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    bao, tx, primary, comparison = providers()
    calls = []
    # SDK also returns rows outside this explicit known-available warmup mask.
    expected = {DAYS[0]: (KEYS[0],), DAYS[-1]: KEYS}
    results = ingest(store, primary, comparison, expected, calls=calls)
    assert len(bao.query_calls) == len(tx.calls) == 2
    assert calls == ["baostock", "akshare_tencent"]
    assert all(
        call["start_date"] == "2026-09-15" and call["end_date"] == "2026-09-17"
        for call in bao.query_calls
    )
    assert all(
        call["start_date"] == "20260915" and call["end_date"] == "20260917"
        for call in tx.calls
    )
    assert [item.primary.revision.partition_date for item in results] == sorted(
        expected
    )
    assert all(item.eligible_for_verified_dataset for item in results)
    assert len({item.primary.capture.capture_id for item in results}) == 1
    assert len({item.comparison.capture.capture_id for item in results}) == 1
    for item in results:
        request = json.loads(item.primary.capture.request_json)
        assert (
            request["start_date"] == "2026-09-15"
            and request["end_date"] == "2026-09-17"
        )
        assert item.primary.capture.record_count == 6
        assert read_provider_raw_payload(store, item.primary.capture)
    ref = manifest(store, results, expected)
    restored = read_daily_bar_dataset(store, ref)
    assert len(restored.bars) == 3 and restored.snapshot.verification_bound
    assert not restored.snapshot.membership_evidence_bound
    assert all(
        bar.available_at == NOW and bar.captured_at == NOW for bar in restored.bars
    )
    assert {bar.instrument for bar in restored.bars if bar.session_date == DAYS[0]} == {
        KEYS[0]
    }


@pytest.mark.parametrize("corrupt", ["primary_raw", "comparison_raw"])
def test_range_materializations_still_check_original_raw_capture(tmp_path, corrupt):
    store = ContentAddressedObjectStore(tmp_path)
    _, _, primary, comparison = providers()
    results = ingest(store, primary, comparison)
    ref = manifest(store, results, {day: KEYS for day in DAYS})
    cap = (
        results[0].primary.capture
        if corrupt == "primary_raw"
        else results[0].comparison.capture
    )
    path = store._path_for(cap.raw_object_ref.object_id)
    path.chmod(0o644)
    path.write_bytes(b"corrupt range fixture")
    with pytest.raises(DatasetReaderIntegrityError):
        read_daily_bar_dataset(store, ref)


def test_missing_expected_member_stays_blocked_not_intersected_and_conflict_stays_blocked(
    tmp_path,
):
    store = ContentAddressedObjectStore(tmp_path)
    bao, tx, primary, comparison = providers()
    tx.frames["sh" + KEYS[1].symbol] = tx.frames["sh" + KEYS[1].symbol].iloc[1:]
    results = ingest(store, primary, comparison)
    assert not results[0].eligible_for_verified_dataset
    assert results[0].verification is None
    assert all(item.eligible_for_verified_dataset for item in results[1:])
    _, tx, primary, comparison = providers()
    tx.frames["sh" + KEYS[0].symbol].loc[0, ["close", "high"]] = [11, 11.1]
    results = ingest(store, primary, comparison)
    assert not results[0].eligible_for_verified_dataset
    assert results[0].verification is not None


def test_completely_missing_day_and_unrequested_row_fail_with_real_capture(tmp_path):
    store = ContentAddressedObjectStore(tmp_path)
    bao, tx, primary, comparison = providers()
    for key in KEYS:
        bao.results["sh." + key.symbol] = FakeResult(
            [
                [
                    day.isoformat(),
                    "sh." + key.symbol,
                    "10",
                    "10.1",
                    "9.9",
                    "10",
                    "10000",
                    "100000",
                    "3",
                    "1",
                ]
                for day in DAYS[1:]
            ]
        )
    with pytest.raises(DailyBarIngestionCapturedFailure) as failure:
        ingest(store, primary, comparison)
    assert read_provider_raw_payload(store, failure.value.capture)
    _, _, primary, comparison = providers()
    real = primary.fetch_daily_bars
    other = InstrumentKey("600002", InstrumentType.STOCK)

    class Outside:
        descriptor = primary.descriptor

        def fetch_daily_bars(self, request):
            batch = real(request)
            return replace(
                batch, rows=(*batch.rows, replace(batch.rows[0], instrument=other))
            )

    with pytest.raises(DailyBarIngestionCapturedFailure):
        ingest(store, Outside(), comparison)


@pytest.mark.parametrize("kind", ["baostock", "tencent", "tushare", "eastmoney"])
@pytest.mark.parametrize("invalid", ["outside", "duplicate", "not_closed"])
def test_each_sdk_range_keeps_bounds_duplicates_and_end_session_close(kind, invalid):
    days = [DAYS[0], DAYS[-1]]
    if invalid == "outside":
        days[0] -= timedelta(days=1)
    if invalid == "duplicate":
        days[1] = days[0]
    now = NOW if invalid != "not_closed" else NOW - timedelta(days=1)
    if kind == "baostock":
        client = FakeBaoStock()
        client.results["sh." + KEYS[0].symbol] = FakeResult(
            [
                [
                    day.isoformat(),
                    "sh." + KEYS[0].symbol,
                    "10",
                    "10.1",
                    "9.9",
                    "10",
                    "10000",
                    "100000",
                    "3",
                    "1",
                ]
                for day in days
            ]
        )
        provider = BaoStockDailyBarProvider(client, clock=lambda: now)
    elif kind == "tencent":
        client = FakeTencent()
        client.frames["sh" + KEYS[0].symbol] = pd.DataFrame(
            [
                {
                    "date": day,
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "volume": 10000,
                    "amount": 100000,
                }
                for day in days
            ]
        )
        provider = AkshareTencentDailyBarProvider(client, clock=lambda: now)
    elif kind == "tushare":
        frame = pd.DataFrame(
            [
                {
                    "trade_date": day.strftime("%Y%m%d"),
                    "open": 10,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10,
                    "vol": 100,
                    "amount": 100,
                }
                for day in days
            ]
        )
        provider = TushareDailyBarProvider(
            SimpleNamespace(daily=lambda **_: frame), clock=lambda: now
        )
    else:
        frame = pd.DataFrame(
            [
                {
                    "日期": str(day),
                    "开盘": 10,
                    "最高": 10.1,
                    "最低": 9.9,
                    "收盘": 10,
                    "成交量": 100,
                    "成交额": 100000,
                }
                for day in days
            ]
        )
        provider = AkshareDailyBarProvider(
            SimpleNamespace(stock_zh_a_hist=lambda **_: frame), clock=lambda: now
        )
    error_types = {
        "baostock": (BaoStockDailyBarRequestError, BaoStockDailyBarResponseError),
        "tencent": (
            AkshareTencentDailyBarRequestError,
            AkshareTencentDailyBarResponseError,
        ),
        "tushare": (TushareDailyBarRequestError, TushareDailyBarResponseError),
        "eastmoney": (AkshareDailyBarRequestError, AkshareDailyBarResponseError),
    }
    with pytest.raises(error_types[kind][0 if invalid == "not_closed" else 1]):
        provider.fetch_daily_bars(DailyBarRequest((KEYS[0],), DAYS[0], DAYS[-1]))


def test_single_day_range_preserves_original_capture_revision_and_verification_identity(
    tmp_path,
):
    store = ContentAddressedObjectStore(tmp_path)
    _, _, primary, comparison = providers(days=(DAYS[-1],))
    request = DailyBarRequest(KEYS, DAYS[-1], DAYS[-1])
    original = ingest_cross_source_daily_bars(
        primary,
        comparison,
        store,
        request=request,
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=NOW,
    )
    _, _, primary, comparison = providers(days=(DAYS[-1],))
    results = ingest(store, primary, comparison, {DAYS[-1]: KEYS}, request=request)
    assert results == (original,)
    for item in results:
        assert validate_daily_bar_materialization(
            store,
            revision=item.primary.revision,
            materialization=item.primary.materialization,
        )


@pytest.mark.parametrize(
    "expected",
    [
        {DAYS[0]: ()},
        {DAYS[0]: KEYS + KEYS},
        {DAYS[0]: (InstrumentKey("600002", InstrumentType.STOCK),)},
        {DAYS[0] - timedelta(days=1): KEYS},
    ],
)
def test_invalid_declared_range_projection_fails_before_sdk(expected, tmp_path):
    bao, tx, primary, comparison = providers()
    with pytest.raises(ValueError, match="range_sessions_invalid"):
        ingest(ContentAddressedObjectStore(tmp_path), primary, comparison, expected)
    assert bao.query_calls == tx.calls == []


@pytest.mark.parametrize("kind", ["tushare", "eastmoney"])
def test_stock_and_etf_ranges_keep_existing_endpoint_units_and_one_sdk_call_each(kind):
    calls = []

    def response(**kwargs):
        calls.append(kwargs)
        if kind == "tushare":
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_date": day.strftime("%Y%m%d"),
                        "open": 10,
                        "high": 10.1,
                        "low": 9.9,
                        "close": 10,
                        "vol": 100,
                        "amount": 100,
                    }
                    for day in DAYS
                ]
            )
        return pd.DataFrame(
            [
                {
                    "日期": str(day),
                    "开盘": 10,
                    "最高": 10.1,
                    "最低": 9.9,
                    "收盘": 10,
                    "成交量": 100,
                    "成交额": 100000,
                }
                for day in DAYS
            ]
        )

    if kind == "tushare":
        provider = TushareDailyBarProvider(
            SimpleNamespace(daily=response, fund_daily=response), clock=lambda: NOW
        )
    else:
        provider = AkshareDailyBarProvider(
            SimpleNamespace(stock_zh_a_hist=response, fund_etf_hist_em=response),
            clock=lambda: NOW,
        )
    keys = (InstrumentKey("510300", InstrumentType.ETF), KEYS[0])
    batch = provider.fetch_daily_bars(DailyBarRequest(keys, DAYS[0], DAYS[-1]))
    assert len(calls) == 2 and len(batch.rows) == 6
    assert all(
        call["start_date"] == "20260915" and call["end_date"] == "20260917"
        for call in calls
    )
    assert all(
        row.volume == Decimal("10000") and row.amount == Decimal("100000")
        for row in batch.rows
    )
    assert all(row.available_at is None for row in batch.rows)
