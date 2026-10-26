"""Sanitized native envelopes; the JS boundary returns synthetic decoded rows.

Actual K2 decoding is separately exercised read-only against public captures.
All publication in this file is restricted to pytest's temporary object store.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, Inexact, getcontext, localcontext

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
    BseAuctionRelation,
    DailyBarReconciliationPolicy,
    reconcile_daily_bar_revisions,
)
from data.market.revision import publish_daily_bar_revision
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import (
    MarketVerificationEvidenceIntegrityError,
    publish_market_verification_evidence,
    read_market_verification_evidence,
)
from data.providers.bse_sina_history import canonical_rows, request_for
from data.storage.objects import ContentAddressedObjectStore

DAY = date(2025, 1, 2)
CHECKED = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
KEY = InstrumentKey("920001", InstrumentType.STOCK)
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def block(*, code="830001", quantity=20, price=5, contract="one", subtype="B"):
    return {
        "hqbcjhth": "buy-" + contract,
        "hqbjydy": "buyer",
        "hqcjjg": price,
        "hqcjsj": "150000",
        "hqcjsl": quantity,
        "hqfcbj": "2",
        "hqjsrq": "20250102",
        "hqscjhth": "sell-" + contract,
        "hqsjydy": "seller",
        "hqzqdm": code,
        "hqzqjc": "fixture",
        "xxzrlx": subtype,
    }


@pytest.fixture
def pair(tmp_path, monkeypatch):
    def make(
        *,
        component=True,
        records=None,
        future=None,
        off_volume=None,
        off_amount=None,
        history_days=1,
        sina_amount=1000,
    ):
        import py_mini_racer

        store = ContentAddressedObjectStore(tmp_path / "objects")
        sina_values = dict(zip(FIELDS, (10, 11, 9, 10, 100, sina_amount)))
        state = {
            "rows": [
                {
                    "date": (DAY + timedelta(days=i)).isoformat() + "T00:00:00.000Z",
                    **sina_values,
                }
                for i in range(history_days)
            ],
            "decoder_calls": [],
            "trace": {
                "p_a": 0,
                "p_v": 0,
                "p_p": 0,
                "q_a": 1,
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
                state["decoder_calls"].append(self.traced)
                result = copy.deepcopy(state["rows"])
                if self.traced:
                    for row in result:
                        row["__precision_trace"] = dict(state["trace"])
                return result

        monkeypatch.setattr(py_mini_racer, "MiniRacer", SyntheticJS)

        def capture(role, provider, operation, request, raw, fmt, version):
            at = (
                CHECKED + timedelta(seconds=1)
                if future == role
                else CHECKED
                - timedelta(
                    minutes={"sina": 40, "official": 30, "block": 20, "mapping": 10}[
                        role
                    ]
                )
            )
            return capture_provider_payload(
                store,
                provider=provider,
                operation=operation,
                request=request,
                raw_payload=raw,
                payload_format=fmt,
                adapter_version=version,
                started_at=at - timedelta(seconds=1),
                completed_at=at,
                record_count=None,
            )

        sina_cap = capture(
            "sina",
            "sina_native_public_probe",
            "raw_history_encoded_js_bse_probe",
            request_for("sina", KEY.symbol),
            b'var KLC_K2_bj920001="K2Fixture"; /* ABC */',
            "sina.stock.history.encoded_js.bse_http_body.probe.v1",
            "operation.sina.native_bse_history_js_probe.v1",
        )
        official_values = {
            **sina_values,
            "volume": off_volume
            if off_volume is not None
            else (120 if component else 100),
            "amount": off_amount
            if off_amount is not None
            else (1100.49 if component else 1000.49),
        }
        raw_official = {
            "jsrq": "20250102",
            "jrkp": 10,
            "drzd": 11,
            "drzx": 9,
            "jrsp": 10,
            "zrsp": 10,
            "cjl": official_values["volume"],
            "cjje": official_values["amount"],
        }
        official_cap = capture(
            "official",
            "bse_official_kline_probe",
            "public_kline_probe",
            request_for("bse_official", KEY.symbol),
            (
                "karkinosHistoricalKlineRead("
                + json.dumps(
                    {
                        "data": [
                            {
                                **raw_official,
                                "jsrq": (DAY + timedelta(days=i)).strftime("%Y%m%d"),
                            }
                            for i in range(history_days)
                        ],
                        "status": 0,
                        "msg": "",
                    }
                )
                + ")"
            ).encode(),
            "bse.companyEcharts.kline.raw_public_response.probe.v1",
            "operation.bse.official_kline.public_probe.v1",
        )
        sina_bar = canonical_rows(sina_cap, KEY, {DAY: sina_values})[0][DAY]
        official_bar = canonical_rows(official_cap, KEY, {DAY: official_values})[0][DAY]
        mapping_id, page_ids = None, []
        if component:
            html = "<table><tr><th>序号</th><th>证券简称</th><th>上市日期</th><th>旧代码</th><th>新代码</th></tr>"
            html += (
                "".join(
                    f"<tr><td>{i}</td><td>fixture</td><td>2020/1/1</td><td>{830000 + i}</td><td>{920000 + i}</td></tr>"
                    for i in range(1, 249)
                )
                + "</table>"
            )
            body = html.encode()
            mapping_at = (
                CHECKED + timedelta(seconds=1)
                if future == "mapping"
                else CHECKED - timedelta(minutes=10)
            )
            mapping_request = {
                "kind": "official_bse_code_mapping",
                "url": "https://www.bse.cn/service/code_mapping.html",
                "method": "GET",
                "headers": {
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.bse.cn/",
                },
                "timeout_seconds_per_get": 20,
                "maximum_gets": 2,
                "session": "anonymous",
                "http_response_sequence": [
                    {
                        "method": "GET",
                        "url": "https://www.bse.cn/service/code_mapping.html",
                        "started_at": (mapping_at - timedelta(seconds=1)).isoformat(),
                        "completed_at": mapping_at.isoformat(),
                        "status": 200,
                        "location": None,
                        "response_body_bytes": len(body),
                    }
                ],
            }
            mapping_id = capture(
                "mapping",
                "bse",
                "code_mapping_html",
                mapping_request,
                body,
                "bse.code_mapping.html.v1",
                "karkinos.bse.code_mapping.operation.v1",
            ).capture_id
            records = [block()] if records is None else records
            pages = max(1, (len(records) + 19) // 20)
            for index in range(pages):
                content = records[index * 20 : (index + 1) * 20]
                page = {
                    "content": content,
                    "firstPage": index == 0,
                    "lastPage": index == pages - 1,
                    "number": index,
                    "numberOfElements": len(content),
                    "size": 20,
                    "sort": None,
                    "totalElements": len(records),
                    "totalPages": pages,
                }
                req = {
                    "method": "POST",
                    "url": "https://www.bse.cn/tnqfgkcjxxController/btcjxxList.do",
                    "headers": {
                        "Referer": "https://www.bse.cn/disclosure/agreement_transfer.html",
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Encoding": "identity",
                    },
                    "data": {
                        "btzqdm": "",
                        "callback": "karkinosBlockComponentRead",
                        "keywords": "",
                        "position": "now",
                        "sortfield": "hqjsrq",
                        "sorttype": "desc",
                        "xxfcbj": "2",
                        "xxfcbjs[]": "2",
                        "startDate": DAY.isoformat(),
                        "endDate": DAY.isoformat(),
                        "page": str(index),
                    },
                }
                body = (
                    "karkinosBlockComponentRead([[" + json.dumps(page) + "], ''])"
                ).encode()
                page_ids.append(
                    capture(
                        "block",
                        "bse_official_block_probe",
                        "public_block_trade_probe",
                        req,
                        body,
                        "bse.block_trade.raw_public_response.probe.v1",
                        "operation.bse.fixed_date_block.raw_probe.v1",
                    ).capture_id
                )
        relation = BseAuctionRelation(tuple(page_ids), mapping_id)

        def materialize(cap, bar):
            return publish_daily_bar_revision(
                store, capture=cap, bars=(bar,), normalizer_version="fixture.native.v1"
            )

        revisions = [
            materialize(sina_cap, sina_bar),
            materialize(official_cap, official_bar),
        ]

        def reconcile(
            *,
            relation_override=relation,
            checked_at=CHECKED,
            policy=STRICT_DAILY_RECONCILIATION,
        ):
            return reconcile_daily_bar_revisions(
                store,
                primary_revision=revisions[0][0],
                primary_materialization=revisions[0][1],
                comparison_revision=revisions[1][0],
                comparison_materialization=revisions[1][1],
                policy=policy,
                component_relation=relation_override,
                component_checked_at=checked_at,
            )

        def publish():
            qualities = [
                publish_market_quality_evidence(
                    store,
                    evaluate_daily_bar_revision(
                        store,
                        revision=revision,
                        materialization=materialization,
                        policy=RESEARCH_STRICT_DAILY,
                        expected_instruments=(KEY,),
                        checked_at=CHECKED,
                    ),
                )
                for revision, materialization in revisions
            ]
            descriptors = [
                MarketDataProviderDescriptor(
                    cap.provider, group, cap.adapter_version, ()
                )
                for cap, group in ((sina_cap, "sina"), (official_cap, "bse_official"))
            ]
            return publish_market_verification_evidence(
                store,
                report=reconcile(),
                primary_quality=qualities[0],
                comparison_quality=qualities[1],
                primary_descriptor=descriptors[0],
                comparison_descriptor=descriptors[1],
                policy=STRICT_DAILY_RECONCILIATION,
                checked_at=CHECKED,
                component_relation=relation,
            )

        def dataset(*, official_selected=False, cutoff=CHECKED, verification=None):
            verification = verification or publish()
            revision, materialization = revisions[int(official_selected)]
            return publish_daily_bar_dataset_manifest(
                store,
                DailyBarDatasetSnapshot(
                    start_date=DAY,
                    end_date=DAY,
                    cutoff=cutoff,
                    instruments=(KEY,),
                    resolver_policy_id="fixture.explicit_auction.v1",
                    market_schema_version=DAILY_BAR_SCHEMA_VERSION,
                    partitions=(
                        DailyBarDatasetPartition(
                            DAY,
                            revision.provider,
                            revision.ref.revision_id,
                            materialization.materialization_id,
                            verification_id=verification.verification_id,
                        ),
                    ),
                ),
            )

        return {
            "store": store,
            "relation": relation,
            "reconcile": reconcile,
            "publish": publish,
            "dataset": dataset,
            "sina": sina_bar,
            "official": official_bar,
            "revisions": revisions,
            "materialize": materialize,
            "sina_cap": sina_cap,
            "official_cap": official_cap,
            "state": state,
        }

    return make


@pytest.mark.parametrize("component", [False, True])
def test_actual_reported_relation_roundtrips_and_selects_unmodified_sina(
    pair, component
):
    p = pair(component=component)
    assert not p["reconcile"](relation_override=None).matched
    assert p["reconcile"]().matched
    evidence = p["publish"]()
    assert read_market_verification_evidence(p["store"], evidence.ref) == evidence
    raw = json.loads(p["store"].read_bytes(evidence.ref))
    assert raw["schema_version"] == "karkinos.market_verification_evidence.v2"
    assert raw["policy"]["volume_tolerance"] == "0"
    assert raw["policy"]["amount_tolerance"] == "0"
    assert evidence.comparison_upstream_group == "bse_official"
    assert read_daily_bar_dataset(
        p["store"], p["dataset"](verification=evidence)
    ).bars == (p["sina"],)
    assert p["official"].volume == (120 if component else 100)


def test_volume_difference_cannot_use_empty_component_refs(pair):
    with pytest.raises(ValueError, match="exact_quantity"):
        pair()["reconcile"](relation_override=BseAuctionRelation())


@pytest.mark.parametrize("source", ["sina", "official", "block", "mapping"])
def test_every_actual_source_must_precede_verification(pair, source):
    with pytest.raises(ValueError, match="after_verification"):
        pair(future=source)["reconcile"]()


@pytest.mark.parametrize(
    "records, volume, amount, error",
    [
        ([block(quantity=21)], None, None, "exact_quantity"),
        ([block(price=6)], None, None, "quantization"),
        ([block(subtype="")], None, None, "explicit_B"),
        ([block(), block(code="920001", contract="two")], 140, 1200.49, "dual_code"),
        ([block(), block()], 140, 1200.49, "duplicate_contract"),
        ([block(quantity=True)], None, None, "record_invalid"),
        ([block(price=0)], None, None, "record_invalid"),
        ([block(code="999999")], None, None, "explicit_B"),
    ],
)
def test_components_fail_closed(pair, records, volume, amount, error):
    p = pair(records=records, off_volume=volume, off_amount=amount)
    with pytest.raises((ValueError, TypeError), match=error):
        p["reconcile"]()


def test_unknown_off_mask_record_is_preserved_without_counting_as_B(pair):
    p = pair(
        records=[
            block(),
            block(code="999999", subtype="", quantity=500, contract="other"),
        ]
    )
    assert p["reconcile"]().matched


def test_missing_or_repeated_page_cannot_explain_activity(pair):
    rows = [block(quantity=1, contract=str(i)) for i in range(21)]
    p = pair(records=rows, off_volume=121, off_amount=1105.49)
    assert p["reconcile"]().matched
    truncated = replace(
        p["relation"], block_page_capture_ids=p["relation"].block_page_capture_ids[:1]
    )
    with pytest.raises(ValueError, match="incomplete_page_series"):
        p["reconcile"](relation_override=truncated)
    with pytest.raises(ValueError, match="refs_invalid"):
        replace(
            p["relation"],
            block_page_capture_ids=(p["relation"].block_page_capture_ids[0],) * 2,
        )


@pytest.mark.parametrize(
    "field, value",
    [
        ("open", Decimal(9)),
        ("high", Decimal(12)),
        ("close", Decimal(11)),
        ("event_time", datetime(2025, 1, 2, 6, tzinfo=timezone.utc)),
        ("suspended", True),
    ],
)
def test_price_event_or_status_conflict_has_no_component_shortcut(pair, field, value):
    p = pair()
    changes = {field: value}
    if field == "suspended":
        changes.update(volume=Decimal(0), amount=Decimal(0))
    altered = replace(p["sina"], **changes)
    p["revisions"][0] = p["materialize"](p["sina_cap"], altered)
    with pytest.raises(ValueError, match="exact_identity|exact_auction_prices"):
        p["reconcile"]()


def test_matching_forged_materialized_values_cannot_replace_original_raw(pair):
    p = pair()
    for index, role in enumerate(("sina", "official")):
        altered = replace(p[role], amount=p[role].amount + 1)
        p["revisions"][index] = p["materialize"](p[role + "_cap"], altered)
    with pytest.raises(ValueError, match="original_materialization"):
        p["reconcile"]()


def test_dataset_cold_replay_rejects_official_side_and_future_cutoff(pair):
    p = pair()
    evidence = p["publish"]()
    with pytest.raises(DatasetReaderIntegrityError, match="auction_requires_sina"):
        read_daily_bar_dataset(
            p["store"], p["dataset"](official_selected=True, verification=evidence)
        )
    with pytest.raises(DatasetReaderIntegrityError, match="verification_after_cutoff"):
        read_daily_bar_dataset(
            p["store"],
            p["dataset"](cutoff=CHECKED - timedelta(seconds=1), verification=evidence),
        )


def test_actual_quantum_and_half_up_are_required_not_an_absolute_tolerance(pair):
    p = pair(component=False, off_amount=1000.5)
    with pytest.raises(ValueError, match="quantization"):
        p["reconcile"]()
    p["state"]["trace"]["q_a"] = 2
    with pytest.raises(ValueError, match="precision_grid"):
        p["reconcile"]()
    with pytest.raises(ValueError, match="native_pair"):
        p["reconcile"](
            policy=DailyBarReconciliationPolicy(amount_tolerance=Decimal(1000000))
        )


def test_cold_reader_replays_native_bytes_not_just_persisted_matched_status(pair):
    p = pair()
    evidence = p["publish"]()
    ref = p["dataset"](verification=evidence)
    p["state"]["rows"][0]["amount"] += 1
    with pytest.raises(DatasetReaderIntegrityError, match="verification_unreadable"):
        read_daily_bar_dataset(p["store"], ref)


def test_unknown_relation_and_v1_extra_fields_are_rejected(pair):
    p = pair()
    evidence = p["publish"]()
    payload = json.loads(p["store"].read_bytes(evidence.ref))
    payload["component_relation"]["kind"] = "invented"
    ref = p["store"].put_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(
        MarketVerificationEvidenceIntegrityError, match="component_kind"
    ):
        read_market_verification_evidence(p["store"], ref)
    payload["schema_version"] = "karkinos.market_verification_evidence.v1"
    ref = p["store"].put_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(MarketVerificationEvidenceIntegrityError, match="root_fields"):
        read_market_verification_evidence(p["store"], ref)


def _two_day_dataset(p):
    original = list(p["revisions"])
    partitions = []
    for day in (DAY, DAY + timedelta(days=1)):
        for index, role in enumerate(("sina", "official")):
            cap = p[role + "_cap"]
            bar = canonical_rows(
                cap, KEY, {day: {field: getattr(p[role], field) for field in FIELDS}}
            )[0][day]
            p["revisions"][index] = p["materialize"](cap, bar)
        evidence = p["publish"]()
        revision, materialization = p["revisions"][0]
        partitions.append(
            DailyBarDatasetPartition(
                day,
                revision.provider,
                revision.ref.revision_id,
                materialization.materialization_id,
                verification_id=evidence.verification_id,
            )
        )
    p["revisions"][:] = original
    return publish_daily_bar_dataset_manifest(
        p["store"],
        DailyBarDatasetSnapshot(
            start_date=DAY,
            end_date=DAY + timedelta(days=1),
            cutoff=CHECKED,
            instruments=(KEY,),
            resolver_policy_id="fixture.two_day_auction.v1",
            market_schema_version=DAILY_BAR_SCHEMA_VERSION,
            partitions=tuple(partitions),
        ),
    )


def test_complete_cold_dataset_reuses_only_decoding_and_rechecks_every_day(
    pair, monkeypatch
):
    import data.market.revision as revisions

    p = pair(component=False, history_days=2)
    ref = _two_day_dataset(p)
    p["state"]["decoder_calls"].clear()
    parquet_calls = []
    read_parquet = revisions.read_parquet

    def counted_parquet(*args, **kwargs):
        parquet_calls.append(1)
        return read_parquet(*args, **kwargs)

    monkeypatch.setattr(revisions, "read_parquet", counted_parquet)
    assert len(read_daily_bar_dataset(p["store"], ref).bars) == 2
    # Original and instrumented decoder execute once each for both sessions.
    assert p["state"]["decoder_calls"] == [False, True]
    # Each session still replays both sides; Dataset consumes that same replay.
    assert len(parquet_calls) == 4
    assert len(read_daily_bar_dataset(p["store"], ref).bars) == 2
    assert len(parquet_calls) == 8
    assert p["state"]["decoder_calls"] == [False, True] * 2
    p["state"]["rows"][1]["amount"] += 1
    with pytest.raises(DatasetReaderIntegrityError, match="verification_unreadable"):
        read_daily_bar_dataset(p["store"], ref)


def test_native_decode_scope_is_immutable_fresh_after_exception_and_root_specific(
    pair, tmp_path
):
    from shutil import copytree

    from data.providers.bse_sina_history import bse_native_read_scope, read_sina_rows

    p = pair(component=False, history_days=2)
    other = ContentAddressedObjectStore(tmp_path / "other-objects")
    copytree(p["store"].root, other.root)
    with pytest.raises(RuntimeError, match="scope_end"):
        with bse_native_read_scope():
            _, rows, precision, _ = read_sina_rows(
                p["store"], p["sina_cap"].capture_id, KEY
            )
            assert precision[DAY] is precision[DAY + timedelta(days=1)]
            with pytest.raises(TypeError):
                rows[DAY]["amount"] = 999
            with pytest.raises(TypeError):
                precision[DAY]["q_a"] = 999
            read_sina_rows(
                p["store"],
                p["sina_cap"].capture_id,
                KEY,
                session_date=DAY + timedelta(days=1),
            )
            assert p["state"]["decoder_calls"] == [False, True]
            read_sina_rows(other, p["sina_cap"].capture_id, KEY)
            assert p["state"]["decoder_calls"] == [False, True] * 2
            raise RuntimeError("scope_end")
    with bse_native_read_scope():
        read_sina_rows(p["store"], p["sina_cap"].capture_id, KEY)
    assert p["state"]["decoder_calls"] == [False, True] * 3


def test_decode_hit_still_rejects_raw_corruption_and_changed_decoder(pair, monkeypatch):
    import akshare.stock.cons as cons

    from data.providers.bse_sina_history import bse_native_read_scope, read_sina_rows
    from data.storage.objects import ObjectIntegrityError

    p = pair(component=False)
    with bse_native_read_scope():
        read_sina_rows(p["store"], p["sina_cap"].capture_id, KEY)
        with monkeypatch.context() as changed:
            changed.setattr(cons, "hk_js_decode", cons.hk_js_decode + " ")
            with pytest.raises(ValueError, match="decoder_unreviewed"):
                read_sina_rows(p["store"], p["sina_cap"].capture_id, KEY)
        path = p["store"]._path_for(p["sina_cap"].raw_object_ref.object_id)
        path.chmod(0o600)
        path.write_bytes(b"corrupted")
        with pytest.raises(ObjectIntegrityError):
            read_sina_rows(p["store"], p["sina_cap"].capture_id, KEY)


def test_cold_dataset_does_not_join_an_outer_decode_scope(pair):
    from data.providers.bse_sina_history import bse_native_read_scope, read_sina_rows

    p = pair(component=False)
    ref = p["dataset"]()
    p["state"]["decoder_calls"].clear()
    with bse_native_read_scope():
        read_sina_rows(p["store"], p["sina_cap"].capture_id, KEY)
        assert p["state"]["decoder_calls"] == [False, True]
        read_daily_bar_dataset(p["store"], ref)
        assert p["state"]["decoder_calls"] == [False, True] * 2
        read_sina_rows(p["store"], p["sina_cap"].capture_id, KEY)
        assert p["state"]["decoder_calls"] == [False, True] * 2


def test_canonical_reencoded_verification_cannot_hide_late_aux_capture(pair):
    p = pair()
    evidence = p["publish"]()
    payload = json.loads(p["store"].read_bytes(evidence.ref))
    payload["checked_at"] = (
        (CHECKED - timedelta(minutes=15))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    forged_ref = p["store"].put_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(
        MarketVerificationEvidenceIntegrityError, match="component_replay_failed"
    ):
        read_market_verification_evidence(p["store"], forged_ref)
    forged = replace(
        evidence, ref=forged_ref, checked_at=CHECKED - timedelta(minutes=15)
    )
    with pytest.raises(DatasetReaderIntegrityError, match="verification_unreadable"):
        read_daily_bar_dataset(p["store"], p["dataset"](verification=forged))


def test_cross_page_duplicate_and_unknown_type_are_not_components(pair):
    rows = [block(quantity=1, contract=str(i)) for i in range(20)]
    p = pair(records=rows + [rows[0]], off_volume=121, off_amount=1105.49)
    with pytest.raises(ValueError, match="duplicate_contract"):
        p["reconcile"]()
    p = pair(records=[block(subtype="X")])
    with pytest.raises(ValueError, match="record_invalid"):
        p["reconcile"]()


def test_missing_sina_day_cannot_become_a_derived_or_nontrading_bar(pair):
    p = pair()
    p["state"]["rows"][0]["date"] = "2025-01-03T00:00:00.000Z"
    with pytest.raises(ValueError, match="native_row_missing"):
        p["reconcile"]()


def test_negative_precision_exponent_uses_actual_two_CNY_quantum(pair):
    p = pair(component=False, off_amount=1000.5)
    p["state"]["trace"].update(p_a=-1, q_a=2)
    assert p["reconcile"]().matched
    p["state"]["trace"].update(p_a=3, q_a=0.1)
    with pytest.raises(ValueError, match="quantization"):
        p["reconcile"]()


def test_large_native_notional_cannot_round_into_false_agreement(pair):
    quantity, price = 12345678901234567891, 1234567891
    exact_notional = quantity * price  # Independent exact integer oracle.
    with localcontext() as prior:
        prior.prec = 28
        rounded_notional = int(Decimal(quantity) * Decimal(price))
    assert exact_notional - rounded_notional == 1
    official_amount = rounded_notional + 1000
    assert official_amount - exact_notional == 999
    p = pair(
        records=[block(quantity=quantity, price=price)],
        off_volume=quantity + 100,
        off_amount=official_amount,
    )
    with pytest.raises(ValueError, match="quantization"):
        p["reconcile"]()


def test_large_but_canonical_exact_notional_is_supported(pair):
    quantity, price = 12345678901234567891, 1234567891
    p = pair(
        records=[block(quantity=quantity, price=price)],
        off_volume=quantity + 100,
        off_amount=quantity * price + 1000,
    )
    assert p["reconcile"]().matched


@pytest.mark.parametrize(
    "residual, reported", [(1000.4999, 1000), (1000.5, 1001), (1000.5001, 1001)]
)
def test_only_explicit_final_half_up_rounds_at_supported_boundary(
    pair, residual, reported
):
    p = pair(component=False, off_amount=residual, sina_amount=reported)
    assert p["reconcile"]().matched


def test_native_component_arithmetic_does_not_inherit_or_change_caller_precision(pair):
    p = pair()
    with localcontext() as caller:
        caller.prec = 6
        caller.traps[Inexact] = True
        caller.clear_flags()
        assert p["reconcile"]().matched
        assert getcontext().prec == 6
        assert caller.traps[Inexact] is True
        assert not any(caller.flags.values())


@pytest.mark.parametrize(
    "value, field",
    [
        (Decimal("1e30"), "amount"),
        (Decimal("0.000000001"), "amount"),
        (Decimal("0.000000001"), "block_price"),
        (10**30, "block_quantity"),
    ],
)
def test_unsupported_numeric_extremes_are_explicitly_rejected(value, field):
    from data.providers.bse_sina_history import number

    with pytest.raises(ValueError, match="numeric_contract_exceeded"):
        number(value, field)


def test_canonical_decimal_and_existing_quantum_limits_remain_exact():
    from data.providers.bse_sina_history import number, source_quantum

    limit = Decimal("9" * 30 + "." + "9" * 8)
    assert number(limit, "amount") == limit
    with localcontext() as caller:
        caller.prec = 6
        caller.traps[Inexact] = True
        assert source_quantum(30) == Decimal("1e-10")
        assert source_quantum(-30) == Decimal("1e10")
        assert number(Decimal("1e-10"), "quantum") == Decimal("1e-10")
