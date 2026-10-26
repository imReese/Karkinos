"""Actual native shape, sanitized identities, literal state and uncertainty."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.providers.szse_memo_suspension import (
    read_szse_security_identity_relation,
    read_szse_structured_suspension_status,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectIntegrityError

AT = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
KEY = InstrumentKey("300000", InstrumentType.STOCK)
NEW = InstrumentKey("302000", InstrumentType.STOCK)


def row(stop="", resume="", period="停牌", **kwargs):
    return {
        "zqdm": KEY.symbol,
        "zqjc": "样例",
        "tpkssj": stop,
        "fpkssj": resume,
        "tpsj": period,
        "tpyy": "重大事项",
        **kwargs,
    }


def capture(
    tmp_path, rows, *, body_change=None, request_change=None, raw=None, **overrides
):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    params = {
        "SHOWTYPE": "JSON",
        "CATALOGID": "1798",
        "TABKEY": "tab1",
        "txtDmorjc": KEY.symbol,
        "txtKsrq": "2020-01-01",
        "txtZzrq": "2026-10-20",
        "PAGENO": "1",
    }
    request = {
        "url": "https://www.szse.cn/api/report/ShowReport/data",
        "params": params,
    }
    body = [
        {
            "metadata": {
                "catalogid": "1798",
                "name": "停复牌提示",
                "tabkey": "tab1",
                "pagesize": 10,
                "pageno": 1,
                "pagecount": (len(rows) + 9) // 10,
                "recordcount": len(rows),
                "conditions": [
                    {"name": k, "defaultValue": params.get(k, "")}
                    for k in ("txtDmorjc", "txtKsrq", "txtZzrq", "txtKsrq-txtZzrq")
                ],
                "cols": {
                    "zqdm": "证券代码",
                    "zqjc": "证券简称",
                    "tpkssj": "停牌时间",
                    "fpkssj": "复牌时间",
                    "tpsj": "停牌期限",
                    "tpyy": "停牌原因",
                },
            },
            "data": rows,
            "error": None,
        }
    ]
    if body_change:
        body_change(body)
    if request_change:
        request_change(request)
    cap = capture_provider_payload(
        objects,
        **{
            "provider": "szse_memo",
            "operation": "suspension_status_probe",
            "request": request,
            "raw_payload": json.dumps(body).encode() if raw is None else raw,
            "adapter_version": "operation.szse.memo.native_probe.v1",
            "payload_format": "szse.memo.raw_response.v1",
            "started_at": AT - timedelta(seconds=1),
            "completed_at": AT,
            **overrides,
        },
    )
    return objects, cap


def read(objects, cap, keys=(KEY,), refs=()):
    return read_szse_structured_suspension_status(
        objects, cap.capture_ref, selected_instruments=keys, identity_capture_refs=refs
    )


def test_literal_S_R_and_reasserted_combined_row_are_the_same_state(tmp_path):
    start = row("2020-01-02 开市")
    end = row(resume="2020-01-07 开市", period="取消停牌")
    objects, cap = capture(tmp_path, [end, start])
    before = objects.read_bytes(cap.raw_object_ref)
    actual, req, statuses = read(objects, cap)
    assert actual == cap and req.instruments == (KEY,)
    assert statuses == {
        date(2020, 1, d): {KEY: "0" if d < 7 else "not_full_day"} for d in range(2, 8)
    }
    assert objects.read_bytes(cap.raw_object_ref) == before
    _, cap2 = capture(
        tmp_path, [row("2020-01-06 开市", "2020-01-07 开市", "1天"), start]
    )
    assert read(objects, cap2)[2] == statuses


def test_partial_start_only_strict_interior_days_are_full(tmp_path):
    objects, cap = capture(
        tmp_path,
        [row("2020-05-26 13:00:00"), row(resume="2020-06-02 开市", period="取消停牌")],
    )
    statuses = read(objects, cap)[2]
    assert (
        statuses[date(2020, 5, 26)]
        == statuses[date(2020, 6, 2)]
        == {KEY: "not_full_day"}
    )
    assert all(
        statuses[d] == {KEY: "0"}
        for d in [
            date(2020, 5, 27),
            date(2020, 5, 28),
            date(2020, 5, 29),
            date(2020, 6, 1),
        ]
    )


def test_same_day_intraday_and_orphan_resume_never_produce_zero(tmp_path):
    objects, cap = capture(
        tmp_path,
        [
            row("2020-01-02 09:30:00", "2020-01-02 10:00:00", ""),
            row(resume="2020-01-07 开市", period="取消停牌"),
        ],
    )
    assert read(objects, cap)[2] == {
        date(2020, 1, 2): {KEY: "not_full_day"},
        date(2020, 1, 7): {KEY: "not_full_day"},
    }


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row("2020-01-02 开市")],
        [row("2020-01-02 开市"), row("2020-01-03 开市")],
        [row("2020-01-02 开市"), row(resume="2026-10-21 开市", period="取消停牌")],
        [row("2020-01-02 开市", period="未知")],
    ],
)
def test_empty_unclosed_unknown_or_future_do_not_create_halt_or_active(tmp_path, rows):
    objects, cap = capture(tmp_path, rows)
    values = [value for day in read(objects, cap)[2].values() for value in day.values()]
    assert not any(value in {"0", "1"} for value in values)
    if rows:
        assert set(values) == {"unknown"}


@pytest.mark.parametrize("reverse", [False, True])
def test_samecell_uncertainty_and_fullhalt_conflict_in_both_orders(tmp_path, reverse):
    rows = [
        row("2020-01-02 开市", "2020-01-07 开市", "1天"),
        row("2020-01-03 开市", period="未知"),
    ]
    objects, cap = capture(tmp_path, rows[::-1] if reverse else rows)
    with pytest.raises(ValueError, match="statuses_conflict"):
        read(objects, cap)


def test_simultaneous_S_R_is_uncertain_not_a_state_continuation(tmp_path):
    objects, cap = capture(
        tmp_path,
        [row("2020-01-02 开市"), row(resume="2020-01-02 开市", period="取消停牌")],
    )
    assert set(v for day in read(objects, cap)[2].values() for v in day.values()) == {
        "unknown"
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b[0]["metadata"].update(pagecount=2),
        lambda b: b[0]["metadata"].update(recordcount=8),
        lambda b: b[0]["metadata"].update(pageno=2),
        lambda b: b[0]["metadata"].update(pagesize=100),
        lambda b: b[0]["metadata"].update(pagecount=True),
        lambda b: b[0]["metadata"]["conditions"][0].update(defaultValue="300009"),
        lambda b: b[0]["data"][0].update(zqdm="300009"),
        lambda b: b[0].update(error="unavailable"),
    ],
)
def test_false_complete_or_wrong_native_identity_is_rejected(tmp_path, change):
    objects, cap = capture(tmp_path, [row("2020-01-02 开市")], body_change=change)
    with pytest.raises(ValueError):
        read(objects, cap)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "other"},
        {"adapter_version": "operation.szse.memo.native_probe.v2"},
        {"payload_format": "other"},
        {"record_count": 0},
    ],
)
def test_unbound_provider_contract_rejected(tmp_path, changes):
    objects, cap = capture(tmp_path, [], **changes)
    with pytest.raises(ValueError, match="source_invalid"):
        read(objects, cap)


def test_duplicate_JSON_and_duplicate_row_and_bad_CAS_are_rejected(tmp_path):
    objects, cap = capture(
        tmp_path, [], raw=b'[{"metadata":{},"metadata":{},"data":[],"error":null}]'
    )
    with pytest.raises(ValueError, match="duplicate_JSON"):
        read(objects, cap)
    r = row("2020-01-02 开市")
    _, cap = capture(tmp_path, [r, r])
    with pytest.raises(ValueError, match="duplicate_native_row"):
        read(objects, cap)
    digest = cap.raw_object_ref.object_id.removeprefix("sha256:")
    path = objects.root / "sha256" / digest[:2] / digest[2:]
    path.chmod(0o600)
    path.write_bytes(b"changed")
    with pytest.raises(ObjectIntegrityError):
        read(objects, cap)


@pytest.mark.parametrize(
    "keys",
    [
        (InstrumentKey("300000", InstrumentType.ETF),),
        (InstrumentKey("600000", InstrumentType.STOCK),),
        (KEY, KEY),
        (),
    ],
)
def test_typed_frozen_scope_required(tmp_path, keys):
    objects, cap = capture(tmp_path, [])
    with pytest.raises(ValueError):
        read(objects, cap, keys)


IDENTITY_TEXT = (
    "证券代码：300000证券简称：样例公告编号：2025-028"
    "关于变更公司证券简称及证券代码的实施公告。"
    "公司股票自2025年2月17日开市起启用变更后的证券简称及证券代码。"
    "变更后的证券代码：302000变更后的英文简称：EX。"
    "证券代码300000302000。原证券代码“300000”变更为“302000”。"
    "公司法人主体存续，上市主体没有发生实质变化。"
    "投资者持有股份的证券类别和持有数量与代码变更完成前一致。"
    "本次变更后的证券简称及证券代码启用日期为2025年2月17日。"
)


def identity(objects, monkeypatch, text=IDENTITY_TEXT, **overrides):
    monkeypatch.setattr(
        "pypdf.PdfReader",
        lambda raw: SimpleNamespace(
            is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda: text)]
        ),
    )
    return capture_provider_payload(
        objects,
        **{
            "provider": "szse_disclosure",
            "operation": "security_identity_announcement",
            "request": {
                "url": "https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/00000000-0000-0000-0000-000000000001.PDF"
            },
            "raw_payload": b"%PDF-sanitized parse-contract fixture",
            "adapter_version": "operation.szse.security_identity.native_probe.v1",
            "payload_format": "szse.security_identity.raw_pdf.v1",
            "started_at": AT - timedelta(seconds=2),
            "completed_at": AT - timedelta(seconds=1),
            **overrides,
        },
    )


def test_alias_needs_actual_identity_and_keeps_native_request_and_effective_boundary(
    tmp_path, monkeypatch
):
    objects, cap = capture(
        tmp_path,
        [
            row("2020-01-02 开市", "2020-01-07 开市", "1天"),
            row("2025-02-17 开市", "2025-02-18 开市", "1天"),
        ],
    )
    with pytest.raises(ValueError, match="identity_unbound"):
        read(objects, cap, (NEW,))
    proof = identity(objects, monkeypatch)
    assert read_szse_security_identity_relation(objects, proof.capture_ref)[1:] == (
        KEY,
        NEW,
        date(2025, 2, 17),
    )
    actual, req, statuses = read(objects, cap, (NEW,), (proof.capture_ref,))
    assert actual == cap and req.instruments == (NEW,)
    assert json.loads(cap.request_json)["params"]["txtDmorjc"] == KEY.symbol
    assert statuses[date(2020, 1, 2)] == {NEW: "0"}
    assert date(2025, 2, 17) not in statuses
    with pytest.raises(ValueError, match="ambiguous"):
        read(objects, cap, (KEY, NEW), (proof.capture_ref,))


@pytest.mark.parametrize(
    "text",
    [
        IDENTITY_TEXT.replace("公司股票自", "并未公司股票自"),
        IDENTITY_TEXT.replace("公司法人主体存续", "并非公司法人主体存续"),
        IDENTITY_TEXT.replace("投资者持有股份", "并非投资者持有股份"),
        IDENTITY_TEXT.replace("证券代码300000302000", "证券代码300000302001"),
        IDENTITY_TEXT.replace("没有发生实质变化", "已发生实质变化"),
        IDENTITY_TEXT.replace("证券类别和持有数量与代码变更完成前一致", "持有数量增加"),
        IDENTITY_TEXT + "变更后的证券简称及证券代码启用日期：2025年2月18日。",
    ],
)
def test_identity_requires_unambiguous_affirmative_literal_continuity(
    tmp_path, monkeypatch, text
):
    objects, cap = capture(tmp_path, [])
    proof = identity(objects, monkeypatch, text)
    with pytest.raises(ValueError):
        read_szse_security_identity_relation(objects, proof.capture_ref)


@pytest.mark.parametrize(
    "extra",
    [
        "公司股票并未于2025年2月17日开市起启用变更后的证券简称及证券代码。",
        "公司法人主体已发生实质变化。",
        "投资者持有股份的证券类别和持有数量与代码变更完成前不一致。",
        "并非公司法人主体存续。",
        "上市主体已经发生实质变化。",
        "公司的法人主体不再存续。",
        "投资者证券账户中（包括投资者信用账户）持有公司股份数量减少。",
        "本次变更后的证券简称及证券代码启用日期并非2025年2月17日。",
        "更正：本次变更后的证券简称及证券代码启用日期为2025年2月17日。",
        "上述生效日期已取消。",
    ],
)
def test_extra_same_identity_counterfacts_or_unsupported_claims_rejected(
    tmp_path, monkeypatch, extra
):
    objects, _ = capture(tmp_path, [])
    proof = identity(objects, monkeypatch, IDENTITY_TEXT + extra)
    with pytest.raises(ValueError, match="identity_.*unsupported"):
        read_szse_security_identity_relation(objects, proof.capture_ref)


@pytest.mark.parametrize(
    "before,after",
    [
        ("证券代码。", "证券代码，但实际未启用。"),
        ("实质变化。", "实质变化，但实际已经变化。"),
        ("变更完成前一致。", "变更完成前一致，但实际不一致。"),
        ("证券代码。", "证券代码。但实际未启用。"),
        ("实质变化。", "实质变化；然而上述事实不成立。"),
    ],
)
def test_same_subject_suffix_never_loses_subject_at_comma_or_explicit_continuation(
    tmp_path, monkeypatch, before, after
):
    objects, _ = capture(tmp_path, [])
    assert before in IDENTITY_TEXT
    proof = identity(objects, monkeypatch, IDENTITY_TEXT.replace(before, after))
    with pytest.raises(ValueError, match="identity_.*unsupported"):
        read_szse_security_identity_relation(objects, proof.capture_ref)
