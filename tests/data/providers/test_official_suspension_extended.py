"""Sanitized real PDF bytes exercise explicit source/grammar boundaries."""

from datetime import datetime, timezone

import pytest

from data.providers.szse_suspension import (
    SSE_SUSPENSION_ADAPTER_VERSION,
    SZSE_SUSPENSION_ADAPTER_VERSION,
    SZSE_SUSPENSION_V2_ADAPTER_VERSION,
    read_sse_suspension_status,
    read_szse_suspension_status,
    read_szse_suspension_status_v2,
)
from data.storage.objects import ObjectIntegrityError
from tests.data.providers.test_szse_suspension import _capture, _pdf

SZ = (
    "证券代码：301218 公告编号：2026-003。"
    "公司股票（证券代码：301218）自2026年1月13日（星期二）开市起停牌。"
    "因为相关事项需进一步协商，公司预计无法在2026年1月15日（星期四）上午开市起复牌。"
    "经公司申请，公司股票自2026年1月15日（星期四）上午开市起继续停牌。"
    "公司股票将于2026年1月20日（星期二）开市起复牌。"
)
SSE = (
    "A股代码：688981 A股简称：样例 港股代码：00981。"
    "公司A股股票（证券代码：688981）自2025年9月1日（星期一）开市起停牌，"
    "预计停牌时间不超过10个交易日。"
    "公司A股股票（证券代码：688981）自2025年9月9日（星期二）开市起复牌。"
)
SSE_URL = (
    "https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/"
    "2025-09-09/688981_20250909_2BQ9.pdf"
)
SZ_URL = "https://static.cninfo.com.cn/finalpage/2026-01-20/1234567890.PDF"


def make(tmp_path, *, sse=False, text=None, **overrides):
    options = {
        "provider": "sse_disclosure" if sse else "szse_disclosure",
        "adapter_version": (
            SSE_SUSPENSION_ADAPTER_VERSION
            if sse
            else SZSE_SUSPENSION_V2_ADAPTER_VERSION
        ),
        "request": {
            "symbol": "688981" if sse else "301218",
            "url": SSE_URL if sse else SZ_URL,
        },
        **overrides,
    }
    return _capture(tmp_path, text=text or (SSE if sse else SZ), **options)


@pytest.mark.parametrize("sse", [False, True])
def test_explicit_tags_closed_interval_and_no_resumption_zero(tmp_path, sse):
    store, cap = make(tmp_path, sse=sse)
    read = read_sse_suspension_status if sse else read_szse_suspension_status_v2
    actual, request, statuses = read(store, cap.capture_ref)
    assert actual == cap
    assert str(request.start_date) == ("2025-09-01" if sse else "2026-01-13")
    assert str(request.end_date) == ("2025-09-09" if sse else "2026-01-20")
    assert statuses[request.end_date] == {request.instruments[0]: "not_full_day"}
    assert all(
        row == {request.instruments[0]: "0"}
        for day, row in statuses.items()
        if day < request.end_date
    )
    assert read(store, cap.capture_ref) == (actual, request, statuses)


def test_explicit_opening_at_grammar_keeps_old_v1_behavior(tmp_path):
    text = (
        "证券代码：301218。公司股票于2026年1月13日开市时停牌。"
        "公司股票将于2026年1月20日开市起复牌。"
    )
    store, cap = make(tmp_path, text=text)
    assert str(
        read_szse_suspension_status_v2(store, cap.capture_ref)[1].start_date
    ) == ("2026-01-13")
    with pytest.raises(ValueError, match="szse_suspension_source_invalid"):
        read_szse_suspension_status(store, cap.capture_ref)
    _, legacy = make(
        tmp_path, text=text, adapter_version=SZSE_SUSPENSION_ADAPTER_VERSION
    )
    with pytest.raises(ValueError, match="unique_opening_interval"):
        read_szse_suspension_status(store, legacy.capture_ref)
    with pytest.raises(ValueError, match="official_suspension_source_invalid"):
        read_szse_suspension_status_v2(store, legacy.capture_ref)


def test_company_notice_identifies_same_security_and_affirmative_tail(tmp_path):
    notice = "样例股份有限公司（证券简称：样例，证券代码：301218）将于2026年1月20日开市起复牌。"
    store, cap = make(tmp_path, text=notice + SZ)
    read_szse_suspension_status_v2(store, cap.capture_ref)
    for bad in ("并未于", "没有于", "尚未于"):
        _, cap = make(tmp_path, text=notice.replace("将于", bad) + SZ)
        with pytest.raises(ValueError, match="suspension_"):
            read_szse_suspension_status_v2(store, cap.capture_ref)


@pytest.mark.parametrize("suffix", ["，但实际未复牌", "时间调整为收市后"])
def test_only_actual_resumption_suffix_cannot_negate_or_retime_it(tmp_path, suffix):
    text = SZ.replace(
        "公司股票将于2026年1月20日（星期二）开市起复牌。",
        "公司股票将于2026年1月20日（星期二）开市起复牌" + suffix + "。",
    )
    store, cap = make(tmp_path, text=text)
    with pytest.raises(ValueError, match="suspension_"):
        read_szse_suspension_status_v2(store, cap.capture_ref)


def test_separate_transaction_uncertainty_is_not_a_negated_stock_fact(tmp_path):
    text = SZ + "鉴于审计工作尚未完成，公司不召开审议交易事项的股东会。"
    store, cap = make(tmp_path, text=text)
    read_szse_suspension_status_v2(store, cap.capture_ref)


@pytest.mark.parametrize(
    "text",
    [
        SZ.replace("1月15日（星期四）上午开市起继续停牌", "1月21日开市起继续停牌"),
        SZ.replace("1月15日（星期四）上午开市起继续停牌", "1月12日开市起继续停牌"),
        SZ.replace("开市起继续停牌", "开市起停牌"),
        SZ.replace("开市起继续停牌", "下午13:00继续停牌"),
        SZ.replace("开市起继续停牌", "开市起继续复牌"),
        SZ.replace("开市起复牌。", "开市起复牌，但须满足条件。"),
        SZ.replace("公司股票将于", "公司股票预计于"),
        SZ.replace("公司股票将于", "若获批准，公司股票将于"),
        SZ.replace("1月20日（星期二）", "1月20日（星期一）"),
        SZ.replace("公司股票将于2026年1月20日（星期二）开市起复牌。", ""),
        SZ.replace("开市起停牌。", "停牌。", 1),
        SZ.replace("公司股票", "公司债券"),
        SZ + "公司股票自2026年1月21日开市起复牌。",
        SZ + "公司股票在2026年1月21日开市起复牌。",
        SZ + "公司股票预计在2026年1月20日开市起复牌。",
        SZ.replace(
            "预计无法在2026年1月15日（星期四）", "预计无法在2026年1月20日（星期二）"
        ),
        SZ.replace("上午开市起继续停牌", "上午开市起继续停牌", 1).replace(
            "经公司申请，公司股票自2026年1月15日（星期四）上午开市起继续停牌。", ""
        ),
        SZ + "公司股票于2026年1月12日停牌。",
        SZ + "公司股票在2026年1月20日不复牌。",
        SZ + "公司股票在2026年1月13日不停牌。",
        SZ + "公司股票在2026年1月20日收市后复牌。",
        SZ + "公司股票在2026年1月20日上午十点复牌。",
        SZ + "公司股票并未于2026年1月20日开市起复牌。",
        SZ + "公司股票未在2026年1月20日复牌。",
        SZ + "公司股票并未复牌。",
        SZ + "公司股票没有停牌。",
        SZ + "公司股票截至目前尚未复牌。",
        SZ + "样例股份有限公司（证券代码：301218）在2026年1月20日不复牌。",
        SZ + "样例股份有限公司（证券代码：301218）没有在2026年1月20日复牌。",
        SZ + "样例股份有限公司（证券代码：301218）于2026年1月20日收市后复牌。",
        SZ + "样例股份有限公司（证券代码：301218）并未复牌。",
        SZ.replace("开市起复牌。", "开市起复牌，但实际未复牌。"),
        SZ.replace("开市起复牌。", "开市起复牌时间调整为收市后。"),
        SZ + "公司股票于2026年1月20日复牌，但实际未复牌。",
        SZ + "公司股票没有于2026年1月13日开市起停牌。",
        SZ.replace("公司股票将于", "公司股票并未于"),
        SZ.replace("公司股票将于", "公司股票尚未于"),
        SZ.replace("公司股票将于", "公司股票不曾于"),
        SZ.replace(
            "公司股票（证券代码：301218）自", "公司股票（证券代码：301218）没有于"
        ),
        SZ + "公司股票于2026年1月20日复牌，但须满足条件。",
        SZ.replace("预计无法在", "若审核通过，公司预计无法在"),
        SZ.replace("上午开市起复牌。", "上午开市起复牌，但本次实际复牌尚待批准。", 1),
        SZ + "证券代码：301219。",
    ],
)
def test_continuation_is_not_a_boundary_or_conditional_waiver(tmp_path, text):
    store, cap = make(tmp_path, text=text)
    with pytest.raises(ValueError, match="suspension_"):
        read_szse_suspension_status_v2(store, cap.capture_ref)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "szse_disclosure"},
        {"adapter_version": SZSE_SUSPENSION_V2_ADAPTER_VERSION},
        {"operation": "daily_bars"},
        {"payload_format": "text/plain"},
        {"record_count": 0},
        {"started_at": datetime(2025, 9, 9, 6, tzinfo=timezone.utc)},
        {"request": {"symbol": "688981", "url": SSE_URL + "?redirect=x"}},
        {"request": {"symbol": "688981", "url": SSE_URL + "#x"}},
        {"request": {"symbol": "688981", "url": SSE_URL.replace("https:", "http:")}},
        {"request": {"symbol": "688981", "url": SSE_URL.replace(".cn/", ".cn.evil/")}},
        {"request": {"symbol": "688982", "url": SSE_URL}},
        {"request": {"symbol": "301218", "url": SSE_URL}},
        {"request": {"symbol": "688981", "url": SSE_URL, "alias": "00981"}},
    ],
)
def test_sse_identity_source_url_and_actual_capture_fence(tmp_path, overrides):
    store, cap = make(tmp_path, sse=True, **overrides)
    with pytest.raises(ValueError, match="suspension_"):
        read_sse_suspension_status(store, cap.capture_ref)


@pytest.mark.parametrize(
    "raw",
    [
        b"not PDF",
        b"%PDF-broken",
        _pdf(""),
        _pdf(SSE, encrypted=True),
        _pdf(SSE, pages=21),
    ],
)
def test_new_readers_retain_native_pdf_integrity_bounds(tmp_path, raw):
    store, cap = make(tmp_path, sse=True, raw=raw)
    with pytest.raises(ValueError, match="suspension_"):
        read_sse_suspension_status(store, cap.capture_ref)


def test_new_cold_read_rehashes_raw_bytes(tmp_path):
    store, cap = make(tmp_path, sse=True)
    read_sse_suspension_status(store, cap.capture_ref)
    path = (
        store.root
        / "sha256"
        / cap.raw_object_ref.digest[:2]
        / cap.raw_object_ref.digest[2:]
    )
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError):
        read_sse_suspension_status(store, cap.capture_ref)
