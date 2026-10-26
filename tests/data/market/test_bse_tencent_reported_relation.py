"""Sanitized native reports; object writes are confined to pytest tmp_path.

The relationship means per-cell reported-value compatibility. It never states
raw six-field equality or a provider-wide rounding/true-error guarantee.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from urllib.parse import urlencode

import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DailyBarDatasetPartition, DailyBarDatasetSnapshot
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.market.capture import capture_provider_payload, read_provider_raw_payload
from data.market.contracts import MarketDataProviderDescriptor
from data.market.quality import RESEARCH_STRICT_DAILY, evaluate_daily_bar_revision
from data.market.quality_evidence import publish_market_quality_evidence
from data.market.reconciliation import (
    BSE_TENCENT_REPORTED_RELATION_KIND,
    STRICT_DAILY_RECONCILIATION,
    BseTencentReportedRelation,
    DailyBarReconciliationPolicy,
    reconcile_daily_bar_revisions,
)
from data.market.schema import DAILY_BAR_SCHEMA_VERSION
from data.market.verification_evidence import (
    MarketVerificationEvidenceIntegrityError,
    publish_market_verification_evidence,
    read_market_verification_evidence,
)
from data.providers.bse_sina_history import (
    TENCENT_BSE_NATIVE_ADAPTERS,
    bse_native_read_scope,
    canonical_rows,
    read_block_components,
    read_tencent_rows,
)
from tests.data.market import test_bse_auction_relation as original
from tests.data.market.test_bse_auction_relation import pair as native_pair  # noqa: F401

DAY = date(2021, 6, 30)
CHECKED = original.CHECKED


@pytest.fixture
def pair(native_pair, monkeypatch):
    monkeypatch.setattr(original, "DAY", DAY)

    def make(
        *, amount="1000.49", tencent_amount="0.10", records=None, future=None, old=False
    ):
        if old:
            monkeypatch.setattr(original, "KEY", replace(original.KEY, symbol="920030"))
        key = original.KEY
        p = native_pair(
            component=True,
            records=[] if records is None else records,
            off_volume=100,
            off_amount=float(amount),
            future=future,
        )
        store = p["store"]
        relation = BseTencentReportedRelation(
            p["relation"].block_page_capture_ids,
            p["relation"].mapping_capture_id,
            p["official"].amount,
            Decimal(tencent_amount) * 10000,
        )
        symbol = "bj" + key.symbol
        url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
        params = {
            "_var": "kline_day2021",
            "param": f"{symbol},day,2021-01-01,2022-12-31,640,",
            "r": "0.8205512681390605",
        }
        request = {
            "kind": "Tencent_BJ_native_history_raw_probe"
            if old
            else "Tencent_BJ2021_fixed49_current_native_raw_probe",
            "original_job_id": "1" * 64,
            "actual_source_symbol": symbol,
            "method": "GET",
            "url": url,
            "params": params,
            "headers": {"Accept-Encoding": "identity"},
            "actual_prepared_url": url + "?" + urlencode(params),
            "response_status": 200,
            "response_content_type": "text/html; charset=UTF-8",
            "response_content_encoding": None,
            "redirects_followed": 0,
            "timeout_seconds": 20,
        }
        if old:
            request["actual_mapping_capture_id"] = relation.mapping_capture_id
        else:
            request.update(
                fixed_plan_sha256="sha256:" + "2" * 64,
                original_payload_sha256="sha256:" + "3" * 64,
                mapping_capture_id=relation.mapping_capture_id,
            )
        native = [
            DAY.isoformat(),
            "10.00",
            "10.00",
            "11.00",
            "9.00",
            "1.00",
            "",
            "",
            tencent_amount,
            "",
            "",
        ]
        payload = {"code": 0, "msg": "", "data": {symbol: {"day": [native]}}}
        version = TENCENT_BSE_NATIVE_ADAPTERS[int(not old)]

        def capture(*, body=None, req=None, adapter=version, at=None):
            at = at or CHECKED - timedelta(minutes=5)
            return capture_provider_payload(
                store,
                provider="tencent_native_public_probe",
                operation="annual_unadjusted_history_http_probe",
                request=request if req is None else req,
                raw_payload=("kline_day2021=" + json.dumps(payload) + ";").encode()
                if body is None
                else body,
                payload_format="tencent.newfqkline.native_http_body.v1",
                adapter_version=adapter,
                started_at=at - timedelta(seconds=1),
                completed_at=at,
                record_count=None,
            )

        cap = capture(
            at=CHECKED + timedelta(seconds=1) if future == "tencent" else None
        )
        # These are the exact native reported values; normalization never changes O.
        values = {
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
            "amount": relation.tencent_amount,
        }
        tencent = canonical_rows(cap, key, {DAY: values})[0][DAY]
        revisions = [p["revisions"][1], p["materialize"](cap, tencent)]

        def reconcile(
            *,
            rel=relation,
            revs=None,
            policy=STRICT_DAILY_RECONCILIATION,
            checked_at=CHECKED,
        ):
            pairs = revisions if revs is None else revs
            return reconcile_daily_bar_revisions(
                store,
                primary_revision=pairs[0][0],
                primary_materialization=pairs[0][1],
                comparison_revision=pairs[1][0],
                comparison_materialization=pairs[1][1],
                policy=policy,
                component_relation=rel,
                component_checked_at=checked_at,
            )

        def publish(*, rel=relation, descriptors=None):
            qualities = [
                publish_market_quality_evidence(
                    store,
                    evaluate_daily_bar_revision(
                        store,
                        revision=rev,
                        materialization=mat,
                        policy=RESEARCH_STRICT_DAILY,
                        expected_instruments=(key,),
                        checked_at=CHECKED,
                    ),
                )
                for rev, mat in revisions
            ]
            descriptors = descriptors or [
                MarketDataProviderDescriptor(c.provider, group, c.adapter_version, ())
                for c, group in ((p["official_cap"], "bse_official"), (cap, "tencent"))
            ]
            return publish_market_verification_evidence(
                store,
                report=reconcile(rel=rel),
                primary_quality=qualities[0],
                comparison_quality=qualities[1],
                primary_descriptor=descriptors[0],
                comparison_descriptor=descriptors[1],
                policy=STRICT_DAILY_RECONCILIATION,
                checked_at=CHECKED,
                component_relation=rel,
            )

        def dataset(*, comparison_selected=False, cutoff=CHECKED):
            evidence = publish()
            rev, mat = revisions[int(comparison_selected)]
            ref = publish_daily_bar_dataset_manifest(
                store,
                DailyBarDatasetSnapshot(
                    start_date=DAY,
                    end_date=DAY,
                    cutoff=cutoff,
                    instruments=(key,),
                    resolver_policy_id="fixture.explicit_official_tencent_reported.v1",
                    market_schema_version=DAILY_BAR_SCHEMA_VERSION,
                    partitions=(
                        DailyBarDatasetPartition(
                            DAY,
                            rev.provider,
                            rev.ref.revision_id,
                            mat.materialization_id,
                            verification_id=evidence.verification_id,
                        ),
                    ),
                ),
            )
            return read_daily_bar_dataset(store, ref)

        return {
            **p,
            "key": key,
            "relation": relation,
            "reconcile": reconcile,
            "publish": publish,
            "dataset": dataset,
            "revisions": revisions,
            "tencent": tencent,
            "tencent_cap": cap,
            "capture": capture,
            "request": request,
            "payload": payload,
            "native": native,
        }

    return make


@pytest.mark.parametrize("old", [False, True])
def test_reported_compatibility_preserves_actual_finer_official_bar(pair, old):
    p = pair(old=old)
    assert not p["reconcile"](rel=None).matched
    assert p["reconcile"]().matched
    evidence = p["publish"]()
    assert read_market_verification_evidence(p["store"], evidence.ref) == evidence
    payload = json.loads(p["store"].read_bytes(evidence.ref))
    assert payload["policy_id"] == BSE_TENCENT_REPORTED_RELATION_KIND
    assert payload["policy"]["amount_tolerance"] == "0"
    relation = payload["component_relation"]
    assert relation["amount_representation_grid_CNY"] == "100"
    assert relation["official_amount_CNY"] == "1000.49"
    assert relation["tencent_amount_CNY"] == "1000.00"
    assert relation["tencent_minus_official_amount_CNY"] == "-0.49"
    assert relation["raw_six_fields_exact"] is False
    data = p["dataset"]()
    assert data.bars == (p["official"],)
    assert data.bars[0].amount == Decimal("1000.49")
    with pytest.raises(DatasetReaderIntegrityError, match="requires_official"):
        p["dataset"](comparison_selected=True)
    with pytest.raises(DatasetReaderIntegrityError, match="cutoff"):
        p["dataset"](cutoff=CHECKED - timedelta(seconds=1))


@pytest.mark.parametrize("source", ["official", "tencent", "block", "mapping"])
def test_all_native_and_auxiliary_availability_must_precede_checked(pair, source):
    with pytest.raises(ValueError, match="after_verification"):
        pair(future=source)["reconcile"]()


@pytest.mark.parametrize("which", ["official_amount", "tencent_amount"])
def test_caller_cannot_forge_actual_amount_metadata(pair, which):
    p = pair()
    rel = replace(
        p["relation"], **{which: getattr(p["relation"], which) + Decimal("1")}
    )
    with pytest.raises(ValueError, match="metadata_mismatch"):
        p["reconcile"](rel=rel)


@pytest.mark.parametrize(
    "name,value",
    [
        ("amount_representation_grid_CNY", "1000"),
        ("amount_comparison", "two_stage_or_tolerance"),
        ("tencent_minus_official_amount_CNY", "0"),
        ("raw_six_fields_exact", True),
        ("official_amount_CNY", "1000.00"),
        ("kind", "unknown_kind"),
    ],
)
def test_persisted_comparison_mode_and_amount_metadata_fail_closed(pair, name, value):
    p = pair()
    evidence = p["publish"]()
    payload = json.loads(p["store"].read_bytes(evidence.ref))
    payload["component_relation"][name] = value
    # Re-encode into a truthful new CAS object; checksum-only checks cannot catch this.
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    ref = p["store"].put_bytes(raw)
    with pytest.raises((ValueError, MarketVerificationEvidenceIntegrityError)):
        read_market_verification_evidence(p["store"], ref)


@pytest.mark.parametrize("subtype", ["B", ""])
@pytest.mark.parametrize("code", ["920001", "830001"])
def test_relevant_block_or_unknown_row_rejects_no_component_relation(
    pair, subtype, code
):
    row = {
        **original.block(code=code, subtype=subtype),
        "hqjsrq": DAY.strftime("%Y%m%d"),
    }
    with pytest.raises(ValueError, match="no_relevant_components"):
        pair(records=[row])["reconcile"]()


def test_complete_empty_pages_do_not_make_old_positive_B_relation_valid(pair):
    p = pair()
    rel = p["relation"]
    with pytest.raises(ValueError, match="explicit_B"):
        read_block_components(
            p["store"],
            rel.block_page_capture_ids,
            rel.mapping_capture_id,
            p["key"],
            DAY,
            CHECKED,
        )
    with pytest.raises(ValueError, match="complete_component_pages"):
        replace(rel, block_page_capture_ids=(), mapping_capture_id=None)
    with pytest.raises(ValueError, match="capture_identity_invalid"):
        p["reconcile"](
            rel=replace(rel, block_page_capture_ids=(rel.mapping_capture_id,))
        )


@pytest.mark.parametrize(
    "field,value",
    [("low", Decimal("9.01")), ("volume", Decimal("99")), ("suspended", True)],
)
def test_native_identity_and_prices_and_shares_are_exact(pair, field, value):
    p = pair()
    changed = replace(
        p["tencent"],
        **(
            {"suspended": True, "volume": Decimal(0), "amount": Decimal(0)}
            if field == "suspended"
            else {field: value}
        ),
    )
    revisions = [p["revisions"][0], p["materialize"](p["tencent_cap"], changed)]
    with pytest.raises(ValueError, match="exact_identity"):
        p["reconcile"](revs=revisions)


def test_swapped_sides_unknown_relation_and_non_strict_policy_reject(pair):
    p = pair()
    for args in (
        {"revs": list(reversed(p["revisions"]))},
        {"rel": object()},
        {"policy": DailyBarReconciliationPolicy(amount_tolerance=Decimal("1"))},
    ):
        with pytest.raises(ValueError):
            p["reconcile"](**args)


@pytest.mark.parametrize("amount,tc", [("949.57", "0.10"), ("1049.99", "0.11")])
def test_two_stage_rounding_has_no_fallback_even_inside_one_currency_unit(
    pair, amount, tc
):
    with pytest.raises(ValueError, match="direct_reported_value_projection"):
        pair(amount=amount, tencent_amount=tc)["reconcile"]()


def test_notional_sanity_only_applies_to_new_official_primary_relation(pair):
    with pytest.raises(ValueError, match="notional_sanity"):
        pair(amount="800.01", tencent_amount="0.08")["reconcile"]()


@pytest.mark.parametrize(
    "mutation",
    [
        "trailing",
        "duplicate_key",
        "duplicate_day",
        "wrong_symbol",
        "q",
        "shape",
        "qfq_only",
    ],
)
def test_closed_native_parser_boundaries(pair, mutation):
    p = pair()
    payload = p["payload"]
    symbol = "bj" + p["key"].symbol
    if mutation == "duplicate_day":
        payload["data"][symbol]["day"].append(p["native"])
    elif mutation == "wrong_symbol":
        payload["data"] = {"bj830001": payload["data"][symbol]}
    elif mutation == "q":
        p["native"][8] = "0.100"
    elif mutation == "shape":
        p["native"].append("")
    elif mutation == "qfq_only":
        payload["data"][symbol] = {"qfqday": [p["native"]]}
    body = ("kline_day2021=" + json.dumps(payload) + ";").encode()
    if mutation == "trailing":
        body += b"anotherFunction()"
    elif mutation == "duplicate_key":
        body = body.replace(b'"code": 0', b'"code": 0, "code": 0')
    cap = p["capture"](body=body)
    with pytest.raises(ValueError):
        read_tencent_rows(
            p["store"],
            cap.capture_id,
            p["key"],
            p["relation"].mapping_capture_id,
            session_date=DAY,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_adapter",
        "redirect",
        "fq",
        "other_symbol",
        "mapping",
        "old_adapter_impersonation",
    ],
)
def test_two_exact_capture_contracts_only(pair, mutation):
    p = pair()
    request = json.loads(json.dumps(p["request"]))
    adapter = p["tencent_cap"].adapter_version
    if mutation == "unknown_adapter":
        adapter += "unknown"
    elif mutation == "redirect":
        request["redirects_followed"] = 1
    elif mutation == "fq":
        request["params"]["param"] += "qfq"
    elif mutation == "other_symbol":
        request["actual_source_symbol"] = "bj830001"
    elif mutation == "mapping":
        request["mapping_capture_id"] = "sha256:" + "0" * 64
    elif mutation == "old_adapter_impersonation":
        adapter = TENCENT_BSE_NATIVE_ADAPTERS[0]
    cap = p["capture"](req=request, adapter=adapter)
    with pytest.raises(ValueError):
        read_tencent_rows(
            p["store"],
            cap.capture_id,
            p["key"],
            p["relation"].mapping_capture_id,
            session_date=DAY,
        )


def test_padding_remains_raw_and_never_grants_financial_2020_or_2022_scope(pair):
    p = pair()
    p["payload"]["data"]["bj" + p["key"].symbol]["day"].insert(
        0, ["2020-12-01", *p["native"][1:]]
    )
    cap = p["capture"]()
    rows = read_tencent_rows(
        p["store"],
        cap.capture_id,
        p["key"],
        p["relation"].mapping_capture_id,
        session_date=DAY,
    )[1]
    assert set(rows) == {DAY}
    for day in (date(2020, 12, 1), date(2022, 1, 1)):
        with pytest.raises(ValueError, match="selected_2021"):
            read_tencent_rows(
                p["store"],
                cap.capture_id,
                p["key"],
                p["relation"].mapping_capture_id,
                session_date=day,
            )


def test_low_ambient_decimal_context_and_cache_still_verify_original_bytes(pair):
    p = pair()
    with localcontext() as context:
        context.prec = 3
        assert p["reconcile"]().matched
    from data.storage.objects import ObjectIntegrityError

    with bse_native_read_scope():
        read_tencent_rows(
            p["store"],
            p["tencent_cap"].capture_id,
            p["key"],
            p["relation"].mapping_capture_id,
            session_date=DAY,
        )
        raw_ref = p["tencent_cap"].raw_object_ref
        raw = read_provider_raw_payload(p["store"], p["tencent_cap"])
        path = p["store"]._path_for(raw_ref.object_id)
        path.chmod(0o600)
        path.write_bytes(raw + b"corrupt")
        with pytest.raises(ObjectIntegrityError):
            read_tencent_rows(
                p["store"],
                p["tencent_cap"].capture_id,
                p["key"],
                p["relation"].mapping_capture_id,
                session_date=DAY,
            )


def test_partial_complete_pages_and_duplicate_contracts_fail_without_summing(pair):
    records = [
        {
            **original.block(code="999999", contract=str(i)),
            "hqjsrq": DAY.strftime("%Y%m%d"),
        }
        for i in range(21)
    ]
    p = pair(records=records)
    assert p["reconcile"]().matched
    with pytest.raises(ValueError, match="incomplete_page"):
        p["reconcile"](
            rel=replace(
                p["relation"],
                block_page_capture_ids=p["relation"].block_page_capture_ids[:1],
            )
        )
    records[-1] = {**records[0], "hqcjjg": 6}
    with pytest.raises(ValueError, match="duplicate_contract"):
        pair(records=records)["reconcile"]()


def test_reencoded_evidence_cannot_backdate_native_or_auxiliary_availability(pair):
    p = pair()
    evidence = p["publish"]()
    payload = json.loads(p["store"].read_bytes(evidence.ref))
    payload["checked_at"] = (
        (CHECKED - timedelta(minutes=11))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    ref = p["store"].put_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(
        MarketVerificationEvidenceIntegrityError, match="component_replay_failed"
    ) as error:
        read_market_verification_evidence(p["store"], ref)
    assert isinstance(error.value.__cause__, ValueError)
    assert "after_verification" in str(error.value.__cause__)


def test_unknown_old_alias_cannot_claim_no_components_from_current_literal_only(
    pair, monkeypatch
):
    monkeypatch.setattr(original, "KEY", replace(original.KEY, symbol="920999"))
    p = pair()
    for operation in ("reconcile", "publish", "dataset"):
        with pytest.raises(ValueError, match="actual_mapped_old_identity_required"):
            p[operation]()
    # Preserve the old positive-component contract for an explicitly observed
    # current-code B row even when the historical mapping has no such current.
    row = {**original.block(code="920999"), "hqjsrq": DAY.strftime("%Y%m%d")}
    p = pair(records=[row])
    rel = p["relation"]
    assert read_block_components(
        p["store"],
        rel.block_page_capture_ids,
        rel.mapping_capture_id,
        p["key"],
        DAY,
        CHECKED,
    ) == (Decimal(20), Decimal(100))
