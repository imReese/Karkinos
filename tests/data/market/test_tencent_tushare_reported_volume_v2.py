"""Per-row reported compatibility never becomes broad volume tolerance."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    DailyBarReconciliationPolicy,
    _tencent_tushare_reported_volume_compatible,
    reconcile_daily_bars,
)
from data.market.reconciliation import (
    TENCENT_TUSHARE_REPORTED_VOLUME_AMOUNT_RECONCILIATION_V2 as POLICY,
)
from data.storage.objects import ContentAddressedObjectStore

# Reuse the unchanged sanitized v1 native fixtures and complete Dataset journey.
spec = importlib.util.spec_from_file_location(
    "volume_v2_native_fixtures",
    Path(__file__).with_name("test_tencent_tushare_reported_amount.py"),
)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


@pytest.mark.parametrize(
    "tu,tx,compatible",
    [
        ("123456", "123500", True),
        ("123449", "123400", True),
        ("123450", "123500", True),
        ("123451", "123500", True),
        ("123449", "123500", False),
        ("123450", "123400", False),
        ("123456", "123499", False),
        ("123456", "123501", False),
        ("123450.1", "123500", False),
        ("123451", "123450", False),
        ("0", "0", True),
        ("0", "100", False),
        ("49", "0", False),
        ("50", "50", True),
        ("1155", "1155", True),
        ("123456", "123456", True),
        ("NaN", "100", False),
        ("Infinity", "100", False),
        ("-1", "100", False),
        ("1e1000000", "100", False),
        ("1e-1000000", "100", False),
    ],
)
def test_exact_or_one_integer_half_up_projection(tu, tx, compatible):
    assert (
        _tencent_tushare_reported_volume_compatible(Decimal(tu), Decimal(tx))
        is compatible
    )


def test_integer_arithmetic_does_not_round_intermediate_values():
    base = 10**79
    with localcontext() as ctx:
        ctx.prec = 3
        assert _tencent_tushare_reported_volume_compatible(
            Decimal(base + 50), Decimal(base + 100)
        )
        assert not _tencent_tushare_reported_volume_compatible(
            Decimal(base + 49), Decimal(base + 100)
        )
        assert not _tencent_tushare_reported_volume_compatible(
            Decimal(10**80 + 50), Decimal(10**80 + 100)
        )


def arguments(reverse=False):
    return dict(
        primary_revision_id="primary",
        comparison_revision_id="comparison",
        primary_provider="akshare_tencent" if reverse else "tushare",
        comparison_provider="tushare" if reverse else "akshare_tencent",
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_opt_in_preserves_original_volumes_and_v1_stays_exact(reverse):
    tu, tx = (
        legacy._bar(volume=Decimal(123456)),
        legacy._bar("100000", volume=Decimal(123500)),
    )
    primary, comparison = (tx, tu) if reverse else (tu, tx)
    for policy in (legacy.POLICY, STRICT_DAILY_RECONCILIATION):
        assert not reconcile_daily_bars(
            (primary,), (comparison,), policy=policy, **arguments(reverse)
        ).matched
    assert reconcile_daily_bars(
        (primary,), (comparison,), policy=POLICY, **arguments(reverse)
    ).matched
    assert tu.volume == 123456 and tx.volume == 123500
    assert POLICY.volume_tolerance == 0
    assert (
        POLICY.source_precision_policy
        == "karkinos.tencent_tushare.reported_volume_amount_resolution.v2"
    )


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"close": Decimal("10.01")}, "close"),
        ({"event_time": legacy.EVENT + timedelta(seconds=1)}, "event_time"),
        ({"amount": Decimal("100100")}, "amount"),
    ],
)
def test_volume_relation_never_relaxes_other_fields(changes, field):
    report = reconcile_daily_bars(
        (legacy._bar(volume=Decimal(123456), **changes),),
        (legacy._bar("100000", volume=Decimal(123500)),),
        policy=POLICY,
        **arguments(),
    )
    assert not report.matched
    assert field in {item.field for item in report.differences}


def test_suspension_stays_exact_even_with_zero_activity():
    report = reconcile_daily_bars(
        (legacy._bar("0", volume=Decimal(0), suspended=True),),
        (legacy._bar("0", volume=Decimal(0)),),
        policy=POLICY,
        **arguments(),
    )
    assert not report.matched
    assert "suspended" in {item.field for item in report.differences}


@pytest.mark.parametrize(
    "left,right,matched",
    [
        ("0.01", "0", False),
        ("0", "0", True),
        ("100099.99", "100000", True),
        ("100100", "100000", False),
    ],
)
def test_amount_and_zero_boundaries_remain_v1(left, right, matched):
    report = reconcile_daily_bars(
        (legacy._bar(left, volume=Decimal(123456)),),
        (legacy._bar(right, volume=Decimal(123500)),),
        policy=POLICY,
        **arguments(),
    )
    assert report.matched is matched


def test_named_stock_pair_only_and_no_numeric_volume_allowance():
    for volume in ("1", "99"):
        with pytest.raises(ValueError, match="source_precision_policy_invalid"):
            DailyBarReconciliationPolicy(
                volume_tolerance=Decimal(volume),
                amount_tolerance=Decimal("99.99"),
                source_precision_policy=POLICY.source_precision_policy,
            )
    with pytest.raises(ValueError, match="source_precision_pair_invalid"):
        reconcile_daily_bars(
            (legacy._bar(),),
            (legacy._bar("100000"),),
            policy=POLICY,
            **{**arguments(), "comparison_provider": "baostock"},
        )
    for key in (
        InstrumentKey("920123", InstrumentType.STOCK),
        InstrumentKey("510300", InstrumentType.ETF),
        InstrumentKey("700001", InstrumentType.STOCK),
    ):
        with pytest.raises(ValueError, match="source_precision_evidence_invalid"):
            reconcile_daily_bars(
                (legacy._bar(instrument=key),),
                (legacy._bar("100000", instrument=key),),
                policy=POLICY,
                **arguments(),
            )


@pytest.mark.parametrize(
    "version,market", [(3, False), (3, True), (4, False), (4, True)]
)
def test_both_reviewed_native_contracts_replay(tmp_path, version, market):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    tx, tu = legacy._payloads(version, market)
    tx["calls"][0]["frame"]["data"][0][5] = 123500
    tx_revision = legacy._publish(
        store,
        "akshare_tencent",
        tx,
        legacy._bar("100000", volume=Decimal(123500)),
        version,
    )
    tu_revision = legacy._publish(store, "tushare", tu, legacy._bar())
    assert legacy._reconcile(store, tx_revision, tu_revision, policy=POLICY).matched
    assert not legacy._reconcile(
        store, tx_revision, tu_revision, policy=legacy.POLICY
    ).matched


@pytest.mark.parametrize(
    "provider,mutation",
    [
        ("akshare_tencent", "sdk"),
        ("akshare_tencent", "marker"),
        ("akshare_tencent", "volume_marker"),
        ("akshare_tencent", "adjust"),
        ("akshare_tencent", "volume"),
        ("tushare", "ts_code"),
        ("tushare", "duplicate"),
        ("tushare", "volume"),
    ],
)
def test_v2_cannot_borrow_valid_relation_for_forged_raw(
    tmp_path, monkeypatch, provider, mutation
):
    monkeypatch.setattr(legacy, "POLICY", POLICY)
    legacy.test_unverifiable_raw_cannot_borrow_amount_tolerance(
        tmp_path, provider, mutation
    )


@pytest.mark.parametrize(
    "changes,error",
    [
        (
            {"available_at": legacy.CAPTURED - timedelta(seconds=1)},
            "source_precision_evidence_invalid",
        ),
        (
            {"captured_at": legacy.CAPTURED + timedelta(seconds=1)},
            "market_revision_capture_time_mismatch",
        ),
    ],
)
def test_v2_rejects_bar_availability_not_equal_to_actual_capture(
    tmp_path, changes, error
):
    store = ContentAddressedObjectStore(tmp_path / "objects")
    tx, tu = legacy._payloads()
    tx_revision = legacy._publish(store, "akshare_tencent", tx, legacy._bar("100000"))
    with pytest.raises(ValueError, match=error):
        tu_revision = legacy._publish(store, "tushare", tu, legacy._bar(**changes))
        legacy._reconcile(store, tx_revision, tu_revision, policy=POLICY)


def test_complete_fresh_dataset_cold_journey_retains_finer_primary(
    tmp_path, monkeypatch
):
    payloads = legacy._payloads

    def with_reported_volume(*args, **kwargs):
        tx, tu = payloads(*args, **kwargs)
        tx["calls"][0]["frame"]["data"][0][5] = 123500
        return tx, tu

    monkeypatch.setattr(legacy, "_payloads", with_reported_volume)
    monkeypatch.setattr(legacy, "POLICY", POLICY)
    legacy.test_native_dataset_cold_replay_retains_policy_and_finer_primary(tmp_path)
