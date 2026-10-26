"""Replay explicit opening suspension/resumption facts from official PDF bytes.

Only complete, unambiguous intervals are supported. The actual capture completion
is availability; this backfill does not establish historical decision knowledge.
No PDF script is executed, price bar constructed, or missing record inferred.
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.market.capture import (
    ProviderCapture,
    read_provider_capture,
    read_provider_raw_payload,
)
from data.market.contracts import DailyBarRequest
from data.storage.objects import ContentAddressedObjectStore, ObjectRef

SZSE_SUSPENSION_ADAPTER_VERSION = "karkinos.szse.suspension_announcement.pdf.v1"
SZSE_SUSPENSION_PAYLOAD_FORMAT = "application/pdf"
MAX_PDF_BYTES = 4 * 1024 * 1024
MAX_PDF_PAGES = 20
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DATE = r"(?P<year>[0-9]{4})年(?P<month>[0-9]{1,2})月(?P<day>[0-9]{1,2})日"
_WEEKDAY = r"(?:\(星期(?P<weekday>[一二三四五六日天])\))?"
_OPENING = re.compile(
    r"(?:自|于)"
    + _DATE
    + _WEEKDAY
    + r"(?:上午)?开市(?:时)?起(?:开始)?(?P<action>停牌|复牌)"
)
_OTHER_DATED_ACTION = re.compile(
    r"(?:自|于)"
    + _DATE
    + _WEEKDAY
    + r"(?P<timing>[^，。；;]{0,14}?)(?P<action>停牌|复牌)"
)
_UNCERTAIN = (
    "预计",
    "拟",
    "计划",
    "若",
    "如果",
    "如未",
    "视情况",
    "待",
    "条件",
    "可能",
    "最晚",
    "最早",
    "有望",
    "不超过",
    "不早于",
    "不晚于",
    "不予",
    "并非",
    "不会",
)


def _request(request: object) -> InstrumentKey:
    if (
        not isinstance(request, dict)
        or set(request) != {"symbol", "url"}
        or not isinstance(request["symbol"], str)
        or re.fullmatch(r"(?:000|001|002|003|300|301)[0-9]{3}", request["symbol"])
        is None
        or not isinstance(request["url"], str)
    ):
        raise ValueError("szse_suspension_request_invalid")
    url = urlsplit(request["url"])
    patterns = {
        "static.cninfo.com.cn": r"/finalpage/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]+\.PDF",
        "disc.static.szse.cn": (
            r"/(?:download/)?disc/disk[0-9]{2}/finalpage/"
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}/[a-fA-F0-9-]+\.PDF"
        ),
    }
    if (
        url.scheme != "https"
        or url.hostname not in patterns
        or url.netloc != url.hostname
        or url.query
        or url.fragment
        or re.fullmatch(patterns[url.hostname], url.path) is None
    ):
        raise ValueError("szse_suspension_official_URL_invalid")
    return InstrumentKey(request["symbol"], InstrumentType.STOCK)


def _match_date(match: re.Match[str]) -> date:
    day = date(*(int(match[name]) for name in ("year", "month", "day")))
    weekday = match["weekday"]
    if weekday is not None and weekday not in (
        "一二三四五六日"[day.weekday()],
        "天" if day.weekday() == 6 else "",
    ):
        raise ValueError("szse_suspension_weekday_mismatch")
    return day


def _interval(text: str, key: InstrumentKey) -> tuple[date, date]:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    codes = set(re.findall(r"证券代码[:：]([0-9]{6})(?![0-9])", text))
    if codes != {key.symbol}:
        raise ValueError("szse_suspension_security_header_mismatch")
    sentences = re.split(r"[。；;]", text)
    facts: dict[str, set[date]] = {"停牌": set(), "复牌": set()}
    for sentence in sentences:
        for match in _OPENING.finditer(sentence):
            prefix = sentence[: match.start()]
            # A historical stop may mention its then-estimated duration, but an
            # explicit resumption is still mandatory. No qualifier of either
            # actual opening date may be before or after the matched words.
            certain = re.sub(r"[,，]预计停牌时间不超过[0-9]+个交易日", "", sentence)
            if "股票" not in prefix or any(word in certain for word in _UNCERTAIN):
                raise ValueError("szse_suspension_conditional_or_subject_invalid")
            if "盘中" in sentence or "下午" in sentence:
                raise ValueError("szse_suspension_intraday_unsupported")
            facts[match["action"]].add(_match_date(match))
    if len(facts["停牌"]) != 1 or len(facts["复牌"]) != 1:
        raise ValueError("szse_suspension_unique_opening_interval_required")
    # A second dated statement cannot quietly contradict or qualify the interval.
    # Same-date repetitions without "开市" are counterchecked, never used alone.
    for sentence in sentences:
        for match in _OTHER_DATED_ACTION.finditer(sentence):
            prefix = sentence[: match.start()]
            if "股票" not in prefix:
                continue
            if (
                any(word in prefix for word in _UNCERTAIN)
                or _match_date(match) not in facts[match["action"]]
                or re.search(r"[0-9]{1,2}[:时点]|盘中|下午", match["timing"])
            ):
                raise ValueError("szse_suspension_contradictory_or_intraday_fact")
    start, resume = next(iter(facts["停牌"])), next(iter(facts["复牌"]))
    if not start < resume or (resume - start).days >= 3653:
        raise ValueError("szse_suspension_interval_invalid")
    return start, resume


def read_szse_suspension_status(
    store: ContentAddressedObjectStore, capture_ref: ObjectRef
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    """Rehash/reparse original PDF and return only its explicit bounded interval.

    Calendar dates in [opening suspension, opening resumption) are explicit0;
    the resumption date is not_full_day counterevidence. Consumers intersect their
    own dated calendar. No record outside that interval establishes any status.
    """
    import json

    capture = read_provider_capture(store, capture_ref)
    if (
        capture.provider != "szse_disclosure"
        or capture.operation != "suspension_announcement"
        or capture.adapter_version != SZSE_SUSPENSION_ADAPTER_VERSION
        or capture.payload_format != SZSE_SUSPENSION_PAYLOAD_FORMAT
        or capture.record_count is not None
    ):
        raise ValueError("szse_suspension_source_invalid")
    key = _request(json.loads(capture.request_json))
    raw = read_provider_raw_payload(store, capture)
    if not raw.startswith(b"%PDF-") or not 0 < len(raw) <= MAX_PDF_BYTES:
        raise ValueError("szse_suspension_PDF_bytes_invalid")
    try:
        # The dependency is only imported for this source kind. Strict parsing
        # does not repair malformed PDFs or perform OCR/execute embedded scripts.
        from pypdf import PdfReader

        document = PdfReader(io.BytesIO(raw), strict=True)
        if document.is_encrypted or not 1 <= len(document.pages) <= MAX_PDF_PAGES:
            raise ValueError("szse_suspension_PDF_pages_invalid")
        pages = [page.extract_text() or "" for page in document.pages]
        if sum(map(len, pages)) > 500_000:
            raise ValueError("szse_suspension_PDF_text_too_large")
    except Exception as exc:
        raise ValueError("szse_suspension_PDF_parse_failed") from exc
    first_page = re.sub(r"\s+", "", unicodedata.normalize("NFKC", pages[0]))
    if set(re.findall(r"证券代码[:：]([0-9]{6})(?![0-9])", first_page)) != {key.symbol}:
        raise ValueError("szse_suspension_security_header_mismatch")
    start, resume = _interval("\n".join(pages), key)
    if capture.started_at < datetime.combine(resume, time(15), _SHANGHAI).astimezone(
        timezone.utc
    ):
        raise ValueError("szse_suspension_session_not_closed")
    statuses = {
        start + timedelta(days=index): {key: "0"}
        for index in range((resume - start).days)
    }
    statuses[resume] = {key: "not_full_day"}
    return capture, DailyBarRequest((key,), start, resume), statuses


# The v1 SZSE entry above is deliberately unchanged for persisted captures.
SZSE_SUSPENSION_V2_ADAPTER_VERSION = "karkinos.szse.suspension_announcement.pdf.v2"
SSE_SUSPENSION_ADAPTER_VERSION = "karkinos.sse.suspension_announcement.pdf.v1"
_EXTENDED_OPENING = re.compile(
    r"(?:自|于)"
    + _DATE
    + _WEEKDAY
    + r"(?:上午)?开市(?:(?:时)?起(?:开始)?|时)"
    + r"(?P<continued>继续)?(?P<action>停牌|复牌)"
)
_EXTENDED_DATED_ACTION = re.compile(
    r"(?:自|于|在)"
    + _DATE
    + _WEEKDAY
    + r"(?P<timing>[^，。；;]{0,14}?)(?P<action>停牌|复牌)"
)
_SECURITY_IDENTITY = (
    r"\((?:(?:证券|股票)简称:[^,():]{1,40},)?(?:证券|股票)代码:[0-9]{6}\)"
)


def _sse_request(request: object) -> InstrumentKey:
    if (
        not isinstance(request, dict)
        or set(request) != {"symbol", "url"}
        or not isinstance(request["symbol"], str)
        or re.fullmatch(r"6[0-9]{5}", request["symbol"]) is None
        or not isinstance(request["url"], str)
    ):
        raise ValueError("sse_suspension_request_invalid")
    url = urlsplit(request["url"])
    if (
        url.scheme != "https"
        or url.netloc != "star.sse.com.cn"
        or url.query
        or url.fragment
        or re.fullmatch(
            r"/disclosure/listedinfo/announcement/c/new/"
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}/"
            + re.escape(request["symbol"])
            + r"_[0-9]{8}_[A-Za-z0-9]+\.pdf",
            url.path,
        )
        is None
    ):
        raise ValueError("sse_suspension_official_URL_invalid")
    return InstrumentKey(request["symbol"], InstrumentType.STOCK)


def _official_codes(text: str, *, sse: bool) -> set[str]:
    # A separately labelled five-digit Hong Kong code is not an A-share alias.
    label = r"(?:A股代码|证券代码)" if sse else r"证券代码"
    return set(re.findall(label + r"[:：]([0-9]{6})(?![0-9])", text))


def _affirmative_stock_subject(prefix: str) -> bool:
    # Only security identity parentheses may intervene between the stock
    # subject and its affirmative date marker. A negated/unknown tail cannot
    # become a fact merely because it contains the same opening date.
    without_identity = re.sub(_SECURITY_IDENTITY, "", prefix)
    return (
        "股票" in without_identity
        and without_identity.rsplit("股票", 1)[1] in ("", "将", "已")
    ) or (
        # A company-name notice can identify the same security directly. The
        # whole PDF's six-digit identity has already been required to be unique.
        re.search(r"公司" + _SECURITY_IDENTITY + r"(?:将|已)?$", prefix) is not None
    )


def _extended_interval(
    text: str, key: InstrumentKey, *, sse: bool
) -> tuple[date, date]:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    if _official_codes(text, sse=sse) != {key.symbol}:
        raise ValueError("official_suspension_security_header_mismatch")
    sentences = re.split(r"[。；;]", text)
    facts: dict[str, set[date]] = {"停牌": set(), "复牌": set()}
    continued: set[date] = set()
    for sentence in sentences:
        # A same-stock negative remains counterevidence without a date. Inspect
        # only its lead before the first action, not later transaction risks.
        stock_subjects = re.sub(r"公司" + _SECURITY_IDENTITY, "公司股票", sentence)
        without_identity = re.sub(_SECURITY_IDENTITY, "", stock_subjects)
        for stock in re.finditer("股票", without_identity):
            tail = without_identity[stock.end() :]
            action = re.search("停牌|复牌", tail)
            if action and re.search(r"未|没有|不曾|从未|不", tail[: action.start()]):
                raise ValueError("official_suspension_negated_stock_action")
        for match in _EXTENDED_OPENING.finditer(sentence):
            prefix, suffix = sentence[: match.start()], sentence[match.end() :]
            # Only an exact trailing duration estimate may accompany an actual
            # opening halt. It never supplies either boundary of the interval.
            if match["action"] == "停牌" and re.fullmatch(
                r"[,，]预计停牌时间不超过[0-9]+个交易日", suffix
            ):
                sentence_for_certainty = sentence[: match.end()]
            else:
                sentence_for_certainty = sentence
                if suffix:
                    raise ValueError("official_suspension_unknown_action_suffix")
            if not _affirmative_stock_subject(prefix) or any(
                word in sentence_for_certainty for word in _UNCERTAIN
            ):
                raise ValueError("official_suspension_conditional_or_subject_invalid")
            if "盘中" in sentence or "下午" in sentence:
                raise ValueError("official_suspension_intraday_unsupported")
            day = _match_date(match)
            if match["continued"]:
                if match["action"] != "停牌":
                    raise ValueError("official_suspension_continuation_invalid")
                continued.add(day)
            else:
                facts[match["action"]].add(day)
    if len(facts["停牌"]) != 1 or len(facts["复牌"]) != 1:
        raise ValueError("official_suspension_unique_opening_interval_required")
    start, resume = next(iter(facts["停牌"])), next(iter(facts["复牌"]))
    if not start < resume or (resume - start).days >= 3653:
        raise ValueError("official_suspension_interval_invalid")
    if any(not start <= day < resume for day in continued):
        raise ValueError("official_suspension_continuation_outside_interval")
    for sentence in sentences:
        for match in _EXTENDED_DATED_ACTION.finditer(sentence):
            prefix = sentence[: match.start()]
            day = _match_date(match)
            timing = match["timing"]
            # An explicitly recounted missed estimate can only corroborate an
            # independently confirmed continued halt inside the closed interval.
            # It never supplies an actual resumption or expands that interval.
            if prefix.endswith("公司预计无法"):
                if (
                    match["action"] != "复牌"
                    or day not in continued
                    or re.fullmatch(r"(?:上午)?开市(?:时)?起", timing) is None
                    or sentence[match.end() :]
                    or any(
                        word in prefix.removesuffix("预计无法") for word in _UNCERTAIN
                    )
                ):
                    raise ValueError("official_suspension_historical_estimate_invalid")
                continue
            if (
                "股票" not in prefix
                and re.search(r"公司" + _SECURITY_IDENTITY, prefix) is None
            ):
                continue
            if not _affirmative_stock_subject(prefix):
                raise ValueError("official_suspension_nonaffirmative_stock_subject")
            if sentence[match.end() :] and not (
                match["action"] == "停牌"
                and timing
                and re.fullmatch(
                    r"[,，]预计停牌时间不超过[0-9]+个交易日", sentence[match.end() :]
                )
            ):
                raise ValueError("official_suspension_unknown_action_suffix")
            if "继续" in timing:
                if (
                    match["action"] != "停牌"
                    or day not in continued
                    or re.fullmatch(r"(?:上午)?开市(?:时)?起(?:开始)?继续", timing)
                    is None
                ):
                    raise ValueError("official_suspension_continuation_invalid")
            elif (
                re.fullmatch(r"(?:上午)?开市(?:(?:时)?起(?:开始)?|时)|", timing) is None
                or any(
                    word
                    in (
                        sentence[: match.end()]
                        if match["action"] == "停牌"
                        and timing
                        and re.fullmatch(
                            r"[,，]预计停牌时间不超过[0-9]+个交易日",
                            sentence[match.end() :],
                        )
                        else sentence
                    )
                    for word in _UNCERTAIN
                )
                or day not in facts[match["action"]]
            ):
                raise ValueError("official_suspension_contradictory_or_intraday_fact")
    return start, resume


def _read_extended_suspension_status(
    store: ContentAddressedObjectStore, capture_ref: ObjectRef, *, sse: bool
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    import json

    capture = read_provider_capture(store, capture_ref)
    provider = "sse_disclosure" if sse else "szse_disclosure"
    adapter = (
        SSE_SUSPENSION_ADAPTER_VERSION if sse else SZSE_SUSPENSION_V2_ADAPTER_VERSION
    )
    if (
        capture.provider != provider
        or capture.operation != "suspension_announcement"
        or capture.adapter_version != adapter
        or capture.payload_format != SZSE_SUSPENSION_PAYLOAD_FORMAT
        or capture.record_count is not None
    ):
        raise ValueError("official_suspension_source_invalid")
    request = json.loads(capture.request_json)
    key = _sse_request(request) if sse else _request(request)
    raw = read_provider_raw_payload(store, capture)
    if not raw.startswith(b"%PDF-") or not 0 < len(raw) <= MAX_PDF_BYTES:
        raise ValueError("official_suspension_PDF_bytes_invalid")
    try:
        from pypdf import PdfReader

        document = PdfReader(io.BytesIO(raw), strict=True)
        if document.is_encrypted or not 1 <= len(document.pages) <= MAX_PDF_PAGES:
            raise ValueError("official_suspension_PDF_pages_invalid")
        pages = [page.extract_text() or "" for page in document.pages]
        if sum(map(len, pages)) > 500_000:
            raise ValueError("official_suspension_PDF_text_too_large")
    except Exception as exc:
        raise ValueError("official_suspension_PDF_parse_failed") from exc
    first_page = re.sub(r"\s+", "", unicodedata.normalize("NFKC", pages[0]))
    if _official_codes(first_page, sse=sse) != {key.symbol}:
        raise ValueError("official_suspension_security_header_mismatch")
    start, resume = _extended_interval("\n".join(pages), key, sse=sse)
    if capture.started_at < datetime.combine(resume, time(15), _SHANGHAI).astimezone(
        timezone.utc
    ):
        raise ValueError("official_suspension_session_not_closed")
    statuses = {
        start + timedelta(days=index): {key: "0"}
        for index in range((resume - start).days)
    }
    statuses[resume] = {key: "not_full_day"}
    return capture, DailyBarRequest((key,), start, resume), statuses


def read_szse_suspension_status_v2(
    store: ContentAddressedObjectStore, capture_ref: ObjectRef
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    """Explicit SZSE v2 grammar; v1 persisted captures retain their old reader."""
    return _read_extended_suspension_status(store, capture_ref, sse=False)


def read_sse_suspension_status(
    store: ContentAddressedObjectStore, capture_ref: ObjectRef
) -> tuple[ProviderCapture, DailyBarRequest, dict[date, dict[InstrumentKey, str]]]:
    """Read an SSE-tagged original PDF; no SZSE alias or synthesized price bar."""
    return _read_extended_suspension_status(store, capture_ref, sse=True)
