"""Real, sanitized Unicode PDF bytes exercise the status reader, not an OCR stub."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from data.market.capture import capture_provider_payload
from data.providers.szse_suspension import (
    SZSE_SUSPENSION_ADAPTER_VERSION,
    SZSE_SUSPENSION_PAYLOAD_FORMAT,
    read_szse_suspension_status,
)
from data.storage.objects import ContentAddressedObjectStore, ObjectIntegrityError

AT = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
TEXT = (
    "证券代码：001212 证券简称：样例 公告编号：2025-007。"
    "公司股票（证券代码：001212）自2025年3月28日（星期五）开市起停牌，"
    "预计停牌时间不超过2个交易日。"
    "公司股票（证券代码：001212）自2025年4月1日（星期二）上午开市起复牌。"
)
URL = "https://static.cninfo.com.cn/finalpage/2025-04-01/1234567890.PDF"


def _pdf(text=TEXT, *, pages=1, encrypted=False):
    """PdfWriter emits a valid text PDF using an identity Unicode CMap."""
    writer = PdfWriter()
    cmap = DecodedStreamObject()
    cmap.set_data(
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /Identity-UCS def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        b"1 beginbfrange\n<0000> <FFFF> <0000>\nendbfrange\nendcmap\n"
        b"CMapName currentdict /CMap defineresource pop\nend\nend"
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/STSong-Light"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/ToUnicode"): writer._add_object(cmap),
            NameObject("/DescendantFonts"): ArrayObject(),
        }
    )
    for _ in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        content = DecodedStreamObject()
        content.set_data(
            b"BT /F1 10 Tf 40 700 Td <"
            + text.encode("utf-16-be").hex().encode()
            + b"> Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("fixture-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _capture(tmp_path, *, text=TEXT, raw=None, request=None, **overrides):
    objects = ContentAddressedObjectStore(tmp_path / "objects")
    capture = capture_provider_payload(
        objects,
        **{
            "provider": "szse_disclosure",
            "operation": "suspension_announcement",
            "request": request or {"symbol": "001212", "url": URL},
            "raw_payload": _pdf(text) if raw is None else raw,
            "adapter_version": SZSE_SUSPENSION_ADAPTER_VERSION,
            "payload_format": SZSE_SUSPENSION_PAYLOAD_FORMAT,
            "started_at": AT - timedelta(seconds=1),
            "completed_at": AT,
            **overrides,
        },
    )
    return objects, capture


def test_original_unicode_pdf_dates_status_and_actual_availability(tmp_path):
    objects, capture = _capture(tmp_path)
    actual, request, statuses = read_szse_suspension_status(
        objects, capture.capture_ref
    )
    assert actual == capture and actual.completed_at == AT
    assert str(request.start_date) == "2025-03-28"
    assert str(request.end_date) == "2025-04-01"
    assert {str(day): next(iter(row.values())) for day, row in statuses.items()} == {
        "2025-03-28": "0",
        "2025-03-29": "0",
        "2025-03-30": "0",
        "2025-03-31": "0",
        "2025-04-01": "not_full_day",
    }
    assert all(tuple(row) == request.instruments for row in statuses.values())
    assert objects.read_bytes(capture.raw_object_ref) == _pdf()


@pytest.mark.parametrize(
    "text",
    [
        TEXT.replace("001212", "001213"),
        TEXT.replace("证券代码：", "不明代码："),
        TEXT + "证券代码：001213。",
        TEXT.replace("开市起停牌", "停牌"),
        TEXT.replace("上午开市起复牌", "复牌"),
        TEXT.replace("公司股票（证券代码：001212）自2025年3", "公司股票预计自2025年3"),
        TEXT.replace("公司股票（证券代码：001212）自2025年4", "公司股票预计自2025年4"),
        TEXT.replace("自2025年4", "拟于2025年4"),
        TEXT.replace("自2025年3", "若批准则自2025年3"),
        TEXT.replace("上午开市起复牌", "下午13:00起复牌"),
        TEXT.replace("开市起停牌", "09:30至10:30停牌"),
        TEXT + "公司股票自2025年3月27日开市起停牌。",
        TEXT + "公司股票自2025年4月2日开市起复牌。",
        TEXT + "公司股票于2025年4月2日复牌。",
        TEXT.replace("3月28日（星期五）", "4月3日（星期四）"),
        TEXT.replace("3月28日（星期五）", "3月28日（星期一）"),
        TEXT.replace("公司股票", "公司债券"),
        TEXT.replace("自2025年4", "公司申请尚需满足条件，自2025年4"),
        TEXT.replace("上午开市起复牌。", "上午开市起复牌，但须满足条件。"),
        TEXT.replace("上午开市起复牌。", "上午开市起复牌，尚待批准。"),
        TEXT.replace("上午开市起复牌。", "上午开市起复牌，若审核通过。"),
    ],
)
def test_unknown_ambiguous_conditional_intraday_or_conflicting_text_rejected(
    tmp_path, text
):
    objects, capture = _capture(tmp_path, text=text)
    with pytest.raises(ValueError, match="szse_suspension_"):
        read_szse_suspension_status(objects, capture.capture_ref)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "szse"},
        {"operation": "daily_bars"},
        {"adapter_version": "v0"},
        {"payload_format": "text/plain"},
        {"record_count": 0},
        {"started_at": datetime(2025, 4, 1, 6, tzinfo=timezone.utc)},
    ],
)
def test_capture_contract_and_actual_time_fence(tmp_path, overrides):
    objects, capture = _capture(tmp_path, **overrides)
    with pytest.raises(ValueError, match="szse_suspension_"):
        read_szse_suspension_status(objects, capture.capture_ref)


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("https:", "http:"),
        URL.replace("static.cninfo.com.cn", "evil.test"),
        URL.replace("static.cninfo.com.cn", "static.cninfo.com.cn.evil.test"),
        URL.replace("https://", "https://user@"),
        URL + "?redirect=evil",
        URL + "#x",
        URL.replace("static.cninfo.com.cn", "static.cninfo.com.cn:443"),
        URL.replace("/finalpage/", "/../finalpage/"),
        URL.replace(".PDF", ".html"),
    ],
)
def test_only_closed_official_https_urls(tmp_path, url):
    objects, capture = _capture(tmp_path, request={"symbol": "001212", "url": url})
    with pytest.raises(ValueError, match="szse_suspension_"):
        read_szse_suspension_status(objects, capture.capture_ref)


@pytest.mark.parametrize(
    "raw",
    [
        b"not a PDF",
        b"%PDF-1.7\nbroken",
        b"%PDF-" + b"x" * (4 * 1024 * 1024),
        _pdf(""),
        _pdf(pages=21),
        _pdf(encrypted=True),
    ],
)
def test_non_pdf_broken_empty_oversize_encrypted_or_many_pages_rejected(tmp_path, raw):
    objects, capture = _capture(tmp_path, raw=raw)
    with pytest.raises(ValueError, match="szse_suspension_"):
        read_szse_suspension_status(objects, capture.capture_ref)


def test_next_cold_read_rehashes_original_bytes(tmp_path):
    objects, capture = _capture(tmp_path)
    read_szse_suspension_status(objects, capture.capture_ref)
    digest = capture.raw_object_ref.digest
    path = objects.root / "sha256" / digest[:2] / digest[2:]
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError):
        read_szse_suspension_status(objects, capture.capture_ref)
