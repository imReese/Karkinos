"""Reported amount agreement must replay actual raw units and exact other fields."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    DailyBarReconciliationPolicy,
    reconcile_daily_bar_revisions,
    reconcile_daily_bars,
)
from data.market.reconciliation import (
    TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1 as POLICY,
)
from data.market.revision import publish_daily_bar_revision
from data.storage.objects import ContentAddressedObjectStore

SESSION = date(2022, 3, 11)
CAPTURED = datetime(2026, 10, 18, 16, tzinfo=timezone.utc)
EVENT = datetime(2022, 3, 11, 7, tzinfo=timezone.utc)
INSTRUMENT = InstrumentKey("600096", InstrumentType.STOCK)


def _bar(amount="100046", **changes):
    bar = normalize_daily_bar(
        instrument=INSTRUMENT,
        session_date=SESSION,
        event_time=EVENT,
        available_at=CAPTURED,
        captured_at=CAPTURED,
        open_value=10,
        high_value=11,
        low_value=9,
        close_value=10,
        volume=123456,
        amount=amount,
        suspended=False,
    )
    return replace(bar, **changes)


def _payloads(version=4, market=False):
    tencent = {
        "schema": f"akshare.tencent.stock_zh_a_hist_tx.dataframe.v{version}",
        "sdk_version": "1.18.97",
        "calls": [
            {
                "symbol": "sh600096",
                "request": {
                    "symbol": "sh600096",
                    "start_date": "20220311",
                    "end_date": "20220311",
                    "adjust": "",
                },
                "volume_scale_to_shares": "1",
                "amount_normalization": "karkinos.akshare.1.18.97.tencent.amount_10000_one_binary_ulp.v1",
                "frame": {
                    "columns": [
                        "date",
                        "open",
                        "close",
                        "high",
                        "low",
                        "volume",
                        "amount",
                    ],
                    "data": [["2022-03-11", 10, 10, 11, 9, 123456, 100000.0]],
                },
            }
        ],
    }
    if version == 4:
        tencent["calls"][0]["volume_normalization"] = (
            "karkinos.akshare.1.18.97.tencent.volume_100_one_binary_ulp.v1"
        )
    tushare = {
        "schema": "tushare.pro.market_daily.dataframe.v2"
        if market
        else "tushare.pro.daily_bar.dataframe.v1",
        "calls": [
            {
                "endpoint": "daily",
                "frame": {
                    "columns": [
                        "ts_code",
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "vol",
                        "amount",
                    ],
                    "data": [
                        ["600096.SH", "20220311", 10, 11, 9, 10, 1234.56, 100.046]
                    ],
                },
            }
        ],
    }
    if market:
        tushare["calls"][0]["request"] = {"trade_date": "20220311"}
        # A real whole-market response may retain rows outside the selected subset.
        tushare["calls"][0]["frame"]["data"].append(
            ["600000.SH", "20220311", 1, 1, 1, 1, 10, 10]
        )
    else:
        tushare["calls"][0]["ts_code"] = "600096.SH"
    return tencent, tushare


def _publish(store, provider, payload, bar, version=4):
    capture = capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": "2022-03-11",
            "end_date": "2022-03-11",
            "instruments": [{"symbol": "600096", "instrument_type": "stock"}],
        },
        raw_payload=json.dumps(payload, allow_nan=False).encode(),
        payload_format=payload["schema"],
        adapter_version=f"karkinos.akshare_tencent.daily_bar.v{version}"
        if provider == "akshare_tencent"
        else "karkinos.tushare.daily_bar.v2",
        started_at=CAPTURED - timedelta(seconds=1),
        completed_at=CAPTURED,
    )
    return publish_daily_bar_revision(
        store,
        capture=capture,
        bars=(bar,),
        normalizer_version="karkinos.market.normalize.v1",
    )


def _reconcile(store, tencent, tushare, **kwargs):
    return reconcile_daily_bar_revisions(
        store,
        primary_revision=tushare[0],
        primary_materialization=tushare[1],
        comparison_revision=tencent[0],
        comparison_materialization=tencent[1],
        policy=kwargs.get("policy", POLICY),
    )


@pytest.mark.parametrize(
    "version,market", [(3, False), (3, True), (4, False), (4, True)]
)
def test_raw_replay_keeps_finer_tushare_amount_and_strict_conflict(
    tmp_path, version, market
):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    tx, tu = _payloads(version, market)
    tx_revision = _publish(store, "akshare_tencent", tx, _bar("100000"), version)
    tu_revision = _publish(store, "tushare", tu, _bar())
    assert _reconcile(store, tx_revision, tu_revision).matched
    assert not _reconcile(
        store, tx_revision, tu_revision, policy=STRICT_DAILY_RECONCILIATION
    ).matched
    reverse = reconcile_daily_bar_revisions(
        store,
        primary_revision=tx_revision[0],
        primary_materialization=tx_revision[1],
        comparison_revision=tu_revision[0],
        comparison_materialization=tu_revision[1],
        policy=POLICY,
    )
    assert reverse.matched
    from data.market.revision import validate_daily_bar_materialization

    assert validate_daily_bar_materialization(
        store, revision=tu_revision[0], materialization=tu_revision[1]
    )[0].amount == Decimal("100046")


@pytest.mark.parametrize(
    "provider,mutation",
    [
        ("akshare_tencent", "sdk"),
        ("akshare_tencent", "marker"),
        ("akshare_tencent", "adjust"),
        ("akshare_tencent", "volume_marker"),
        ("akshare_tencent", "non_grid"),
        ("akshare_tencent", "beyond_ulp"),
        ("akshare_tencent", "date"),
        ("akshare_tencent", "duplicate"),
        ("akshare_tencent", "missing"),
        ("akshare_tencent", "open"),
        ("akshare_tencent", "volume"),
        ("tushare", "ts_code"),
        ("tushare", "call_code"),
        ("tushare", "date"),
        ("tushare", "duplicate"),
        ("tushare", "missing"),
        ("tushare", "sub_cent"),
        ("tushare", "open"),
        ("tushare", "volume"),
        ("tushare", "amount"),
    ],
)
def test_unverifiable_raw_cannot_borrow_amount_tolerance(tmp_path, provider, mutation):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    tx, tu = _payloads()
    payload = tx if provider == "akshare_tencent" else tu
    call = payload["calls"][0]
    frame = call["frame"]
    columns, values = frame["columns"], frame["data"][0]
    if mutation == "sdk":
        payload["sdk_version"] = "future"
    elif mutation == "marker":
        call.pop("amount_normalization")
    elif mutation == "volume_marker":
        call["volume_normalization"] = "unknown"
    elif mutation == "adjust":
        call["request"]["adjust"] = "qfq"
    elif mutation == "non_grid":
        values[columns.index("amount")] = 100000.01
    elif mutation == "beyond_ulp":
        values[columns.index("amount")] = 99999.99999
    elif mutation == "date":
        values[
            columns.index("date" if provider == "akshare_tencent" else "trade_date")
        ] = "2022-03-10"
    elif mutation == "duplicate":
        frame["data"].append(copy.deepcopy(values))
    elif mutation == "missing":
        frame["data"].clear()
    elif mutation == "ts_code":
        values[columns.index("ts_code")] = "600096.SZ"
    elif mutation == "call_code":
        call["ts_code"] = "600000.SH"
    elif mutation == "sub_cent":
        values[columns.index("amount")] = 100.046001
    elif mutation == "open":
        values[columns.index("open")] = 10.01
    elif mutation == "volume":
        values[columns.index("volume" if provider == "akshare_tencent" else "vol")] += 1
    elif mutation == "amount":
        values[columns.index("amount")] = 100.047
    tx_revision = _publish(store, "akshare_tencent", tx, _bar("100000"))
    tu_revision = _publish(store, "tushare", tu, _bar())
    with pytest.raises(ValueError, match="source_precision_evidence_invalid"):
        _reconcile(store, tx_revision, tu_revision)


@pytest.mark.parametrize(
    "delta,matched",
    [("99.99", True), ("-99.99", True), ("100", False), ("-100", False)],
)
def test_policy_has_fixed_sub_reported_unit_bound(delta, matched):
    report = reconcile_daily_bars(
        (_bar(str(Decimal("100000") + Decimal(delta))),),
        (_bar("100000"),),
        primary_revision_id="tu",
        comparison_revision_id="tx",
        primary_provider="tushare",
        comparison_provider="akshare_tencent",
        policy=POLICY,
    )
    assert report.matched is matched


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"volume": Decimal(123457)}, "volume"),
        ({"close": Decimal("10.01")}, "close"),
        ({"event_time": EVENT + timedelta(seconds=1)}, "event_time"),
    ],
)
def test_price_volume_and_event_are_exact(changes, field):
    report = reconcile_daily_bars(
        (_bar(**changes),),
        (_bar("100000"),),
        primary_revision_id="tu",
        comparison_revision_id="tx",
        primary_provider="tushare",
        comparison_provider="akshare_tencent",
        policy=POLICY,
    )
    assert field in [difference.field for difference in report.differences]


def test_zero_and_suspension_are_exact():
    arguments = dict(
        primary_revision_id="tu",
        comparison_revision_id="tx",
        primary_provider="tushare",
        comparison_provider="akshare_tencent",
        policy=POLICY,
    )
    assert not reconcile_daily_bars((_bar("0.01"),), (_bar("0"),), **arguments).matched
    assert reconcile_daily_bars((_bar("0"),), (_bar("0"),), **arguments).matched
    report = reconcile_daily_bars(
        (_bar("0", volume=Decimal(0), suspended=True),),
        (_bar("0", volume=Decimal(0)),),
        **arguments,
    )
    assert "suspended" in [difference.field for difference in report.differences]


def test_policy_is_named_pair_and_stock_only():
    for volume in ("1", "99"):
        with pytest.raises(ValueError, match="source_precision_policy_invalid"):
            DailyBarReconciliationPolicy(
                volume_tolerance=Decimal(volume),
                amount_tolerance=Decimal("99.99"),
                source_precision_policy=POLICY.source_precision_policy,
            )
    args = dict(
        primary_revision_id="tu",
        comparison_revision_id="tx",
        primary_provider="tushare",
        comparison_provider="akshare_tencent",
        policy=POLICY,
    )
    with pytest.raises(ValueError, match="source_precision_pair_invalid"):
        reconcile_daily_bars(
            (_bar(),), (_bar("100000"),), **{**args, "comparison_provider": "baostock"}
        )
    for instrument in (
        InstrumentKey("920123", InstrumentType.STOCK),
        InstrumentKey("510300", InstrumentType.ETF),
    ):
        with pytest.raises(ValueError, match="source_precision_evidence_invalid"):
            reconcile_daily_bars(
                (_bar(instrument=instrument),),
                (_bar("100000", instrument=instrument),),
                **args,
            )


def test_native_dataset_cold_replay_retains_policy_and_finer_primary(tmp_path):
    import pandas as pd

    from data.dataset.manifest import publish_daily_bar_dataset_manifest
    from data.dataset.reader import read_daily_bar_dataset
    from data.dataset.resolver import (
        DailyBarDatasetResolverPolicy,
        resolve_daily_bar_dataset,
    )
    from data.market.contracts import DailyBarRequest
    from data.market.cross_source import ingest_cross_source_daily_bars
    from data.market.quality import RESEARCH_STRICT_DAILY
    from data.market.verification_evidence import read_market_verification_evidence
    from data.providers.tencent import AkshareTencentDailyBarProvider
    from data.providers.tushare import TushareDailyBarProvider

    tx, tu = _payloads()

    class TencentSDK:
        __version__ = "1.18.97"

        def stock_zh_a_hist_tx(self, **kwargs):
            raw = tx["calls"][0]["frame"]
            return pd.DataFrame(raw["data"], columns=raw["columns"])

    class TushareSDK:
        def daily(self, **kwargs):
            raw = tu["calls"][0]["frame"]
            return pd.DataFrame(raw["data"], columns=raw["columns"])

    store = ContentAddressedObjectStore(tmp_path / "objects")
    result = ingest_cross_source_daily_bars(
        TushareDailyBarProvider(TushareSDK(), clock=lambda: CAPTURED),
        AkshareTencentDailyBarProvider(TencentSDK(), clock=lambda: CAPTURED),
        store,
        request=DailyBarRequest((INSTRUMENT,), SESSION, SESSION),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        reconciliation_policy=POLICY,
        checked_at=CAPTURED,
    )
    assert result.eligible_for_verified_dataset
    evidence = read_market_verification_evidence(store, result.verification.ref)
    assert evidence.policy == POLICY
    snapshot = resolve_daily_bar_dataset(
        store,
        candidates=result.resolution_candidates(),
        start_date=SESSION,
        end_date=SESSION,
        cutoff=CAPTURED,
        instruments=(INSTRUMENT,),
        expected_partition_dates=(SESSION,),
        policy=DailyBarDatasetResolverPolicy(
            policy_id="test.finer_tushare",
            provider_priority=("tushare", "akshare_tencent"),
            required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
        ),
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    cold_store = ContentAddressedObjectStore(tmp_path / "objects")
    replayed = read_daily_bar_dataset(cold_store, ref)
    assert replayed.row_count == 1
    assert replayed.bars[0].amount == Decimal("100046")
    assert replayed.bars[0].captured_at == CAPTURED
    assert replayed.bars[0].available_at == CAPTURED
    assert replayed.snapshot.partitions[0].provider == "tushare"
