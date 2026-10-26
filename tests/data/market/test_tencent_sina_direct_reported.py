"""Sanitized source envelopes, real immutable lineage and fresh Dataset replay."""

import copy
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DailyBarDatasetPartition, DailyBarDatasetSnapshot
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.capture import capture_provider_payload
from data.market.contracts import MarketDataProviderDescriptor
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import publish_market_quality_evidence
from data.market.reconciliation import (
    STRICT_DAILY_RECONCILIATION,
    DailyBarReconciliationPolicy,
    _tencent_sina_reported_amount_compatible,
    reconcile_daily_bar_revisions,
    reconcile_daily_bars,
)
from data.market.reconciliation import (
    TENCENT_SINA_REPORTED_AMOUNT_RECONCILIATION_V1 as POLICY,
)
from data.market.revision import publish_daily_bar_revision
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import publish_market_verification_evidence
from data.providers.bse_sina_history import (
    SINA_JS_DISTRIBUTION,
    bse_native_read_scope,
    read_sina_a_share_rows,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectIntegrityError
from tests.data.market import test_tencent_tushare_reported_amount as prior

KEY, DAY, CAPTURED = prior.INSTRUMENT, prior.SESSION, prior.CAPTURED


@pytest.fixture
def pair(tmp_path, monkeypatch):
    import py_mini_racer

    def make(
        *,
        sina_amount="1230046",
        tc_amount="1230000",
        volume=123456,
        metadata=None,
        sdk=None,
    ):
        store = ContentAddressedObjectStore(
            tmp_path / ("objects" + str(len(list(tmp_path.iterdir()))))
        )
        bar = prior._bar(sina_amount, volume=Decimal(volume))
        state = {
            "row": {
                "date": DAY.isoformat() + "T00:00:00.000Z",
                **{
                    f: float(getattr(bar, f))
                    for f in ("open", "high", "low", "close", "volume", "amount")
                },
            },
            "extra": [],
            "trace": {
                "p_a": 6,
                "p_v": 0,
                "p_p": 0,
                "q_a": 0.01,
                "q_v": 1,
                "q_p": 1,
                "b_avp": 0,
                "b_sep": 0,
            },
        }

        class SyntheticJS:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def eval(self, source, **_kwargs):
                self.traced = "__precision_trace" in source

            def call(self, *_args, **_kwargs):
                result = copy.deepcopy([state["row"], *state["extra"]])
                if self.traced:
                    for row in result:
                        row["__precision_trace"] = dict(state["trace"])
                return result

        monkeypatch.setattr(py_mini_racer, "MiniRacer", SyntheticJS)
        request = {
            "method": "GET",
            "url": "https://finance.sina.com.cn/realstock/company/sh600096/hisdata_klc2/klc_kl.js",
            "symbol": "sh600096",
            "headers": {"Accept-Encoding": "identity"},
        }
        values = dict(
            provider="sina_native_public_probe",
            operation="raw_history_encoded_js_probe",
            request=request,
            raw_payload=b'var KLC_K2_sh600096="K2Fixture"; /* ABC */',
            payload_format="sina.stock.history.encoded_js.http_body.probe.v1",
            adapter_version="operation.sina.native_history_js_probe.v1",
            started_at=CAPTURED - timedelta(seconds=1),
            completed_at=CAPTURED,
            record_count=None,
        )
        values.update(metadata or {})
        cap = capture_provider_payload(store, **values)
        sina = publish_daily_bar_revision(
            store, capture=cap, bars=(bar,), normalizer_version="fixture.actual_sina.v1"
        )
        payload, _ = prior._payloads()
        payload["calls"][0]["frame"]["data"][0][5] = volume
        payload["calls"][0]["frame"]["data"][0][6] = float(tc_amount)
        if sdk is not None:
            payload["sdk_version"] = sdk
        tencent = prior._publish(
            store,
            "akshare_tencent",
            payload,
            prior._bar(tc_amount, volume=Decimal(volume)),
        )

        def reconcile(policy=POLICY, s=sina, t=tencent):
            return reconcile_daily_bar_revisions(
                store,
                primary_revision=s[0],
                primary_materialization=s[1],
                comparison_revision=t[0],
                comparison_materialization=t[1],
                policy=policy,
            )

        return dict(
            store=store,
            cap=cap,
            bar=bar,
            sina=sina,
            tencent=tencent,
            state=state,
            reconcile=reconcile,
        )

    return make


def publish_dataset(p):
    checked = CAPTURED + timedelta(seconds=10)
    qs = []
    for revision, materialization in (p["sina"], p["tencent"]):
        report = evaluate_daily_bar_revision(
            p["store"],
            revision=revision,
            materialization=materialization,
            policy=RESEARCH_STRICT_DAILY,
            expected_instruments=(KEY,),
            checked_at=checked,
        )
        qs.append(publish_market_quality_evidence(p["store"], report))
    evidence = publish_market_verification_evidence(
        p["store"],
        report=p["reconcile"](),
        primary_quality=qs[0],
        comparison_quality=qs[1],
        primary_descriptor=MarketDataProviderDescriptor(
            "sina_native_public_probe",
            "sina",
            "operation.sina.native_history_js_probe.v1",
            (),
        ),
        comparison_descriptor=MarketDataProviderDescriptor(
            "akshare_tencent", "tencent", "karkinos.akshare_tencent.daily_bar.v4", ()
        ),
        policy=POLICY,
        checked_at=checked,
    )
    revision, materialization = p["sina"]
    ref = publish_daily_bar_dataset_manifest(
        p["store"],
        DailyBarDatasetSnapshot(
            start_date=DAY,
            end_date=DAY,
            cutoff=checked,
            instruments=(KEY,),
            resolver_policy_id="fixture.sina_tencent_explicit.v1",
            market_schema_version=DAILY_BAR_SCHEMA_VERSION,
            partitions=(
                DailyBarDatasetPartition(
                    DAY,
                    revision.provider,
                    revision.ref.revision_id,
                    materialization.materialization_id,
                    verification_id=evidence.verification_id,
                ),
            ),
        ),
    )
    return ref


def test_exact_other_fields_direct_projection_and_default_strict_retained(pair):
    p = pair()
    assert p["reconcile"]().matched
    assert not p["reconcile"](STRICT_DAILY_RECONCILIATION).matched
    assert (
        POLICY.price_tolerance
        == POLICY.volume_tolerance
        == POLICY.amount_tolerance
        == 0
    )
    assert p["bar"].amount == Decimal("1230046")
    ref = publish_dataset(p)
    dataset = read_daily_bar_dataset(p["store"], ref)
    assert dataset.bars == (p["bar"],)
    p["state"]["row"]["amount"] += 1
    with pytest.raises(DatasetReaderIntegrityError):
        read_daily_bar_dataset(p["store"], ref)


@pytest.mark.parametrize(
    "sina,tc,expected",
    [
        ("100049.99", "100000", True),
        ("100050", "100100", True),
        ("100050", "100000", False),
        ("100049.57", "100100", False),
        ("100000", "100100", False),
        ("100046", "100024", False),
        ("0", "0", False),
        ("-1", "100", False),
        ("1e200", "1e200", False),
        ("100.001", "100", False),
    ],
)
def test_exact_rational_direct_projection_boundaries(sina, tc, expected):
    with localcontext() as ctx:
        ctx.prec = 2
        assert (
            _tencent_sina_reported_amount_compatible(Decimal(sina), Decimal(tc))
            is expected
        )


@pytest.mark.parametrize("sina,tc", [("100050", "100000"), ("100049.57", "100100")])
def test_sub100_difference_and_double_rounding_do_not_pass(pair, sina, tc):
    p = pair(sina_amount=sina, tc_amount=tc)
    result = p["reconcile"]()
    assert not result.matched and {d.field for d in result.differences} == {"amount"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", Decimal(9)),
        ("volume", Decimal(123457)),
        ("event_time", prior.EVENT - timedelta(minutes=1)),
    ],
)
def test_exact_ohlcv_event_suspension_never_suppressed(pair, field, value):
    p = pair()
    bar = replace(p["bar"], **{field: value})
    report = reconcile_daily_bars(
        (bar,),
        (prior._bar("1230000"),),
        primary_revision_id="s",
        comparison_revision_id="t",
        primary_provider="sina_native_public_probe",
        comparison_provider="akshare_tencent",
        policy=POLICY,
    )
    assert not report.matched


@pytest.mark.parametrize(
    "metadata",
    [
        {"provider": "tushare"},
        {"operation": "fake"},
        {"adapter_version": "operation.sina.native_history_js_probe.v9"},
        {"payload_format": "wrong"},
        {"record_count": 1},
        {"request": {"symbol": "sh600000"}},
        {"raw_payload": b'var KLC_K2_sh600000="K2Fixture"; /* ABC */'},
        {"raw_payload": b'var KLC_K2_sh600096="K2Fixture"; evil()'},
    ],
)
def test_ordinary_sina_source_identity_is_closed(pair, metadata):
    p = pair(metadata=metadata)
    with pytest.raises(ValueError):
        p["reconcile"]()


def test_unknown_sdk_fails_native_guard(pair):
    with pytest.raises(ValueError, match="evidence_invalid"):
        pair(sdk="9.99")["reconcile"]()


@pytest.mark.parametrize(
    "key",
    [
        InstrumentKey("920001", InstrumentType.STOCK),
        InstrumentKey("510300", InstrumentType.ETF),
        InstrumentKey("000001", InstrumentType.INDEX),
    ],
)
def test_non_a_share_stock_cannot_use_new_policy(pair, key):
    p = pair()
    with pytest.raises(ValueError):
        reconcile_daily_bars(
            (replace(p["bar"], instrument=key),),
            (replace(prior._bar("100000"), instrument=key),),
            primary_revision_id="s",
            comparison_revision_id="t",
            primary_provider="sina_native_public_probe",
            comparison_provider="akshare_tencent",
            policy=POLICY,
        )


def test_missing_duplicate_and_future_native_days_are_not_bars(pair):
    p = pair()
    with bse_native_read_scope():
        assert not read_sina_a_share_rows(
            p["store"], p["cap"].capture_id, KEY, session_date=DAY + timedelta(days=1)
        )[1]
    p["state"]["extra"] = [dict(p["state"]["row"])]
    with pytest.raises(ValueError, match="duplicate_date"):
        p["reconcile"]()
    p["state"]["extra"] = [{**p["state"]["row"], "date": "2027-01-01T00:00:00.000Z"}]
    with pytest.raises(ValueError, match="source_session_after_capture"):
        p["reconcile"]()


def test_zero_and_forged_matching_values_are_not_a_precision_shortcut(pair):
    p = pair(sina_amount="0", tc_amount="0")
    with pytest.raises(ValueError):
        p["reconcile"]()
    p = pair()
    fake = prior._bar("100047")
    s = publish_daily_bar_revision(
        p["store"], capture=p["cap"], bars=(fake,), normalizer_version="forged"
    )
    with pytest.raises(ValueError, match="sina_native_evidence_invalid"):
        p["reconcile"](s=s)


def test_new_policy_has_closed_numeric_contract():
    with pytest.raises(ValueError):
        DailyBarReconciliationPolicy(
            amount_tolerance=Decimal("99.99"),
            source_precision_policy=POLICY.source_precision_policy,
        )


def test_valid_suspended_zero_model_cannot_enter_reported_pair(pair):
    p = pair()
    zero = replace(p["bar"], suspended=True, volume=Decimal(0), amount=Decimal(0))
    with pytest.raises(ValueError, match="evidence_invalid"):
        reconcile_daily_bars(
            (zero,),
            (prior._bar("1230000"),),
            primary_revision_id="s",
            comparison_revision_id="t",
            primary_provider="sina_native_public_probe",
            comparison_provider="akshare_tencent",
            policy=POLICY,
        )


def test_locked_platform_js_runtime_preserves_json_dates_and_numbers():
    from data.providers.bse_sina_history import _decode_sina_js

    decoded = _decode_sina_js(
        'function d(value) { return [{date: new Date("2026-01-05T00:00:00.000Z"), '
        "price: Number(value), amount: 123.45}]; }",
        "0.01",
    )
    assert decoded == [
        {"date": "2026-01-05T00:00:00.000Z", "price": 0.01, "amount": 123.45}
    ]


@pytest.mark.parametrize("package", ["akshare", SINA_JS_DISTRIBUTION])
@pytest.mark.parametrize("missing", [False, True])
def test_unknown_sina_decoder_package_fails_closed(pair, monkeypatch, package, missing):
    import importlib.metadata

    p = pair()
    original = importlib.metadata.version

    def version(name):
        if name == package:
            if missing:
                raise importlib.metadata.PackageNotFoundError(package)
            return "unreviewed"
        return original(name)

    monkeypatch.setattr(importlib.metadata, "version", version)
    with pytest.raises(ValueError, match="decoder_unreviewed"):
        p["reconcile"]()


def test_changed_decoder_and_raw_hash_are_not_hidden_by_scope_cache(pair, monkeypatch):
    import akshare.stock.cons

    p = pair()
    decoder = akshare.stock.cons.hk_js_decode
    monkeypatch.setattr(akshare.stock.cons, "hk_js_decode", decoder + " ")
    with pytest.raises(ValueError, match="decoder_unreviewed"):
        p["reconcile"]()
    monkeypatch.setattr(akshare.stock.cons, "hk_js_decode", decoder)
    with bse_native_read_scope():
        assert p["reconcile"]().matched
        digest = p["cap"].raw_object_ref.object_id.split(":")[1]
        path = p["store"].root / "sha256" / digest[:2] / digest[2:]
        path.chmod(0o600)  # Deliberately corrupt only the pytest temporary object.
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(ObjectIntegrityError):
            p["reconcile"]()
