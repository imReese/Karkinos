"""Offline native BSE/Sina history readers for explicit reported-basis checks.

Every original capture and raw body is replayed. These functions neither fetch
nor publish data, infer missing status, rename bars or form residual bars.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, time, timezone
from decimal import Decimal, DecimalException, Inexact, localcontext
from types import MappingProxyType
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

DECODER_SHA = "sha256:39a599c94dde4df1c2eb0882d4bff9560160cfd52ead0797cebb04b3122c2f52"
READER_VERSION = "karkinos.operation.bse_sina.actual_reported_quantization.v1"
FIELDS = ("open", "high", "low", "close", "volume", "amount")
OFFICIAL_FIELDS = {"cjje", "cjl", "jrsp", "jrkp", "jsrq", "drzd", "drzx", "zrsp"}

_NATIVE_ROWS: ContextVar[dict | None] = ContextVar(
    "bse_native_input_rows", default=None
)


@contextmanager
def bse_native_read_scope(*, join_existing=False):
    """Reuse immutable decoding within one operation, never financial decisions.

    Each Dataset cold read owns a fresh scope. Every lookup still reopens and
    verifies capture/raw bytes and the actual Sina package and decoder hash.
    """
    if join_existing and _NATIVE_ROWS.get() is not None:
        yield
        return
    rows = {}
    token = _NATIVE_ROWS.set(rows)
    try:
        yield
    finally:
        rows.clear()
        _NATIVE_ROWS.reset(token)


def _native_key(objects, capture):
    return str(objects.root.resolve()), capture.capture_id


def _cached_native(objects, capture):
    rows = _NATIVE_ROWS.get()
    return rows.get(_native_key(objects, capture)) if rows is not None else None


def _store_native(objects, capture, decoded):
    rows = _NATIVE_ROWS.get()
    if rows is not None:
        rows[_native_key(objects, capture)] = decoded


def _immutable_rows(rows, *, share_equal=False):
    if any(
        not isinstance(value, (str, int, float, Decimal, type(None)))
        for row in rows.values()
        for value in row.values()
    ):
        raise ValueError("bse_native_decoded_scalar_required")
    result, shared = {}, {}
    for day, row in rows.items():
        key = tuple((field, type(value), value) for field, value in row.items())
        if share_equal and key in shared:
            result[day] = shared[key]
        else:
            result[day] = MappingProxyType(dict(row))
            if share_equal:
                shared[key] = result[day]
    return MappingProxyType(result)


def _select_day(rows, session_date):
    return (
        rows
        if session_date is None
        else MappingProxyType(
            {session_date: rows[session_date]} if session_date in rows else {}
        )
    )


def request_for(provider, symbol):
    if not isinstance(symbol, str) or re.fullmatch(r"920[0-9]{3}", symbol) is None:
        raise ValueError("bse_history_current920_identity_required")
    if provider == "bse_official":
        return {
            "method": "GET",
            "url": "https://www.bse.cn/companyEchartsController/getKLine/list/"
            + symbol
            + ".do",
            "params": {
                "begin": "0",
                "end": "-1",
                "type": "dayKline",
                "xxfcbj": "2",
                "callback": "karkinosHistoricalKlineRead",
            },
            "headers": {
                "Referer": "https://www.bse.cn/products/neeq_listed_companies/company_time_sharing.html",
                "User-Agent": "Mozilla/5.0",
            },
        }
    if provider == "sina":
        return {
            "method": "GET",
            "symbol": "bj" + symbol,
            "headers": {"Accept-Encoding": "identity"},
            "url": "https://finance.sina.com.cn/realstock/company/bj"
            + symbol
            + "/hisdata_klc2/klc_kl.js",
        }
    raise ValueError("bse_history_provider_unreviewed")


def number(value, field):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float, Decimal))
        or (
            isinstance(value, float)
            and (not math.isfinite(value) or abs(value) >= 2**53)
        )
    ):
        raise ValueError("bse_history_nonfinite_or_unsafe_number:" + field)
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("bse_history_negative_or_nonfinite_number:" + field)
    # Native bar/components must fit the existing Decimal128(38, 8) contract.
    # Precision metadata additionally permits the existing p[-30,30] quantum.
    digits, exponent = list(result.as_tuple().digits), result.as_tuple().exponent
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if digits and (
        len(digits) > 38
        or len(digits) + exponent > 30
        or exponent < (-10 if field == "quantum" else -8)
    ):
        raise ValueError("bse_history_numeric_contract_exceeded:" + field)
    return result


def source_quantum(p):
    """Exact T/P quantum: T(p)=[a,b] -> 2**(-a)*5**(-b), phase zero.

    P's second argument is a precision exponent pair, not Decimal's decimal
    places. In particular p=-1 means a 2-CNY grid, not one decimal place.
    """
    if isinstance(p, bool) or not isinstance(p, int) or not -30 <= p <= 30:
        raise ValueError("bse_sina_encoded_precision_unreviewed")
    sign = -1 if p < 0 else 1
    n, rest = divmod(abs(p), 3)
    a, b = n + int(rest == 1), n + int(rest == 2)
    with exact_bse_arithmetic():
        return Decimal(2) ** (-sign * a) * Decimal(5) ** (-sign * b)


@contextmanager
def exact_bse_arithmetic():
    """Exact bounded native arithmetic, independent of the caller's context.

    At most 200 records combine a 30-digit integer share count with a canonical
    38-digit price coefficient: their exact notional sum needs at most 71
    digits. Eighty digits also cover the original bar and encoded q operations.
    Unsupported input/precision fails; only explicit HALF_UP may round later.
    """
    try:
        with localcontext() as context:
            context.prec = 80
            context.traps[Inexact] = True
            yield
    except DecimalException as exc:
        raise ValueError("bse_auction_exact_arithmetic_unsupported") from exc


def read_capture(objects, capture_id, provider, instrument):
    from core.types import InstrumentType
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    if instrument.instrument_type is not InstrumentType.STOCK:
        raise ValueError("bse_history_stock_required")
    cap = read_provider_capture(objects, objects.resolve_ref(capture_id))
    identity = (
        (
            "bse_official_kline_probe",
            "public_kline_probe",
            "bse.companyEcharts.kline.raw_public_response.probe.v1",
            "operation.bse.official_kline.public_probe.v1",
        )
        if provider == "bse_official"
        else (
            "sina_native_public_probe",
            "raw_history_encoded_js_bse_probe",
            "sina.stock.history.encoded_js.bse_http_body.probe.v1",
            "operation.sina.native_bse_history_js_probe.v1",
        )
    )
    if (
        (cap.provider, cap.operation, cap.payload_format, cap.adapter_version)
        != identity
        or json.loads(cap.request_json) != request_for(provider, instrument.symbol)
        or cap.record_count is not None
    ):
        raise ValueError("bse_history_exact_capture_request_required")
    body = read_provider_raw_payload(objects, cap)
    if not 8 <= len(body) <= 4 * 1024 * 1024:
        raise ValueError("bse_history_raw_size_invalid")
    return cap, body


def canonical_rows(cap, instrument, rows):
    from data.market.normalize import normalize_daily_bar
    from data.market.schema import daily_bars_to_table

    bars, zeros = {}, {}
    for day, values in rows.items():
        event = datetime.combine(day, time(15), ZoneInfo("Asia/Shanghai")).astimezone(
            timezone.utc
        )
        if event > cap.started_at:
            raise ValueError("bse_history_session_not_closed_at_capture")
        values = {field: number(values[field], field) for field in FIELDS}
        if values["volume"] != values["volume"].to_integral_value():
            raise ValueError("bse_history_fractional_shares")
        if values["volume"] == 0 or values["amount"] == 0:
            if values["volume"] != 0 or values["amount"] != 0:
                raise ValueError("bse_history_zero_activity_pair_inconsistent")
            zeros[day] = values
            # Preserve actual zero activity as a separate dated fact. Never fill
            # OHLC from previous close or manufacture suspended=True/price bars.
            continue
        bars[day] = normalize_daily_bar(
            instrument=instrument,
            session_date=day,
            event_time=event,
            available_at=cap.completed_at,
            captured_at=cap.completed_at,
            open_value=values["open"],
            high_value=values["high"],
            low_value=values["low"],
            close_value=values["close"],
            volume=values["volume"],
            amount=values["amount"],
            suspended=False,
        )
    daily_bars_to_table(tuple(bars.values()))
    return bars, zeros


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("bse_history_json_duplicate_key")
        result[key] = value
    return result


def invalid_constant(_value):
    raise ValueError("bse_history_json_nonfinite")


def read_official(objects, capture_id, instrument, *, session_date=None):
    cap, body = read_capture(objects, capture_id, "bse_official", instrument)
    cached = _cached_native(objects, cap)
    if cached is not None:
        return cap, *(_select_day(rows, session_date) for rows in cached)
    match = re.fullmatch(
        r"\s*karkinosHistoricalKlineRead\((\{.*\})\)\s*;?\s*",
        body.decode("utf-8"),
        re.S,
    )
    if match is None:
        raise ValueError("bse_history_closed_jsonp_required")
    value = json.loads(
        match[1],
        parse_float=Decimal,
        object_pairs_hook=unique_pairs,
        parse_constant=invalid_constant,
    )
    if (
        set(value) != {"data", "status", "msg"}
        or type(value["status"]) is not int
        or value["status"] != 0
        or value["msg"] != ""
        or not isinstance(value["data"], list)
        or not 1 <= len(value["data"]) <= 12000
    ):
        raise ValueError("bse_history_official_payload_invalid")
    rows, originals = {}, {}
    for raw in value["data"]:
        if (
            set(raw) != OFFICIAL_FIELDS
            or not isinstance(raw["jsrq"], str)
            or re.fullmatch(r"[0-9]{8}", raw["jsrq"]) is None
        ):
            raise ValueError("bse_history_official_fields_invalid")
        day = datetime.strptime(raw["jsrq"], "%Y%m%d").date()
        if day in rows or day.strftime("%Y%m%d") != raw["jsrq"]:
            raise ValueError("bse_history_duplicate_or_invalid_date")
        number(raw["zrsp"], "zrsp")
        rows[day] = dict(
            zip(
                FIELDS,
                (
                    raw["jrkp"],
                    raw["drzd"],
                    raw["drzx"],
                    raw["jrsp"],
                    raw["cjl"],
                    raw["cjje"],
                ),
            )
        )
        originals[day] = raw
    bars, zeros = canonical_rows(cap, instrument, rows)
    cached = MappingProxyType(bars), _immutable_rows(zeros), _immutable_rows(originals)
    _store_native(objects, cap, cached)
    return cap, *(_select_day(values, session_date) for values in cached)


def read_sina_rows(objects, capture_id, instrument, *, session_date=None):
    """Decode all raw dated BSE rows without changing the original bj contract."""
    cap, body = read_capture(objects, capture_id, "sina", instrument)
    return _read_sina_rows_from_capture(
        objects,
        cap,
        body,
        source_symbol="bj" + instrument.symbol,
        max_rows=12000,
        session_date=session_date,
    )


def _sina_a_share_symbol(instrument):
    from core.types import InstrumentKey, InstrumentType

    if (
        not isinstance(instrument, InstrumentKey)
        or instrument.instrument_type is not InstrumentType.STOCK
        or re.fullmatch(r"[0-9]{6}", instrument.symbol) is None
    ):
        raise ValueError("sina_history_stock_instrument_required")
    if instrument.symbol.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh" + instrument.symbol
    if instrument.symbol.startswith(("000", "001", "002", "003", "300", "301", "302")):
        return "sz" + instrument.symbol
    raise ValueError("sina_history_exchange_not_reviewed")


def read_sina_a_share_rows(objects, capture_id, instrument, *, session_date=None):
    """Read only the actual ordinary A-share K2 probe identity, never an alias."""
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    symbol = _sina_a_share_symbol(instrument)
    cap = read_provider_capture(objects, objects.resolve_ref(capture_id))
    if (
        cap.provider != "sina_native_public_probe"
        or cap.operation != "raw_history_encoded_js_probe"
        or cap.payload_format != "sina.stock.history.encoded_js.http_body.probe.v1"
        or cap.adapter_version != "operation.sina.native_history_js_probe.v1"
        or cap.record_count is not None
        or json.loads(cap.request_json)
        != {
            "method": "GET",
            "url": "https://finance.sina.com.cn/realstock/company/"
            + symbol
            + "/hisdata_klc2/klc_kl.js",
            "symbol": symbol,
            "headers": {"Accept-Encoding": "identity"},
        }
    ):
        raise ValueError("sina_history_capture_source_or_request_invalid")
    body = read_provider_raw_payload(objects, cap)
    if not 8 <= len(body) <= 4 * 1024 * 1024:
        raise ValueError("sina_history_body_invalid")
    result = _read_sina_rows_from_capture(
        objects,
        cap,
        body,
        source_symbol=symbol,
        max_rows=30000,
        session_date=None,
    )
    if any(
        day > cap.completed_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
        for day in result[1]
    ):
        raise ValueError("sina_history_source_session_after_capture")
    return result[0], *(_select_day(values, session_date) for values in result[1:])


def _read_sina_rows_from_capture(
    objects, cap, body, *, source_symbol, max_rows, session_date=None
):
    """Shared pinned K2 codec; source identity belongs to strict wrappers."""
    from akshare.stock.cons import hk_js_decode
    from py_mini_racer import MiniRacer

    match = re.fullmatch(
        r"\s*var\s+KLC_K2_"
        + re.escape(source_symbol)
        + r'\s*=\s*"([A-Za-z0-9+/]+)"\s*;\s*/\* ([A-Za-z0-9+/]+) \*/\s*',
        body.decode("ascii"),
    )
    if (
        match is None
        or not match[1].startswith("K2")
        or importlib.metadata.version("akshare") != "1.18.97"
        or importlib.metadata.version("mini-racer") != "0.14.1"
        or "sha256:" + hashlib.sha256(hk_js_decode.encode()).hexdigest() != DECODER_SHA
    ):
        raise ValueError("bse_sina_assignment_or_decoder_unreviewed")
    cached = _cached_native(objects, cap)
    if cached is not None:
        return cap, *(_select_day(values, session_date) for values in cached)
    start, end = (
        hk_js_decode.index("O = function()"),
        hk_js_decode.index("}, E = function"),
    )
    part = hk_js_decode[start:end]
    if part.count("t.push(i)") != 1:
        raise ValueError("bse_sina_instrumentation_anchor_changed")
    addition = "i.__precision_trace={p_a:r.p_a,p_v:r.p_v,p_p:r.p_p,q_a:P(1,r.p_a),q_v:P(1,r.p_v),q_p:P(1,r.p_p),b_avp:r.b_avp,b_sep:r.b_sep},t.push(i)"
    diagnostic_source = (
        hk_js_decode[:start] + part.replace("t.push(i)", addition) + hk_js_decode[end:]
    )
    with MiniRacer() as js:
        js.eval(hk_js_decode, timeout_sec=5, max_memory=64 * 1024 * 1024)
        normal = js.call("d", match[1], timeout_sec=5, max_memory=64 * 1024 * 1024)
    with MiniRacer() as js:
        js.eval(diagnostic_source, timeout_sec=5, max_memory=64 * 1024 * 1024)
        traced = js.call("d", match[1], timeout_sec=5, max_memory=64 * 1024 * 1024)
    if (
        not isinstance(normal, list)
        or not 1 <= len(normal) <= max_rows
        or not isinstance(traced, list)
    ):
        raise ValueError("bse_sina_decoded_shape_invalid")
    states = [row.pop("__precision_trace") for row in traced]
    if traced != normal:
        raise ValueError("bse_sina_instrumentation_changed_original_fields")
    rows, metadata, originals = {}, {}, {}
    for raw, trace in zip(normal, states, strict=True):
        if (
            not {"date", *FIELDS} <= raw.keys()
            or not isinstance(raw["date"], str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00\.000Z", raw["date"])
            is None
        ):
            raise ValueError("bse_sina_decoded_fields_invalid")
        day = datetime.fromisoformat(raw["date"].replace("Z", "+00:00")).date()
        if day in rows:
            raise ValueError("bse_sina_duplicate_date")
        rows[day] = {field: raw[field] for field in FIELDS}
        for letter, fields in (
            ("a", ("amount",)),
            ("v", ("volume",)),
            ("p", ("open", "high", "low", "close")),
        ):
            q = source_quantum(trace["p_" + letter])
            with exact_bse_arithmetic():
                if number(trace["q_" + letter], "quantum") != q or any(
                    number(raw[field], field) % q for field in fields
                ):
                    raise ValueError("bse_sina_actual_precision_grid_mismatch")
        metadata[day] = {
            **trace,
            "amount_quantum_CNY": source_quantum(trace["p_a"]),
            "amount_phase_CNY": Decimal(0),
        }
        originals[day] = raw
    cached = (
        _immutable_rows(rows),
        _immutable_rows(metadata, share_equal=True),
        _immutable_rows(originals),
    )
    _store_native(objects, cap, cached)
    return cap, *(_select_day(values, session_date) for values in cached)


def read_sina(objects, capture_id, instrument):
    cap, rows, metadata, originals = read_sina_rows(objects, capture_id, instrument)
    bars, zeros = canonical_rows(cap, instrument, rows)
    return cap, bars, zeros, metadata, originals


def require_capture_before(cap, checked_at):
    if (
        not isinstance(checked_at, datetime)
        or checked_at.tzinfo is None
        or cap.completed_at > checked_at
    ):
        raise ValueError("bse_auction_capture_after_verification")


def read_mapping(objects, capture_id, checked_at):
    """Return only actual old/new relationships, never switch-date inference."""
    from bs4 import BeautifulSoup

    from data.market.capture import read_provider_capture, read_provider_raw_payload

    cap = read_provider_capture(objects, objects.resolve_ref(capture_id))
    require_capture_before(cap, checked_at)
    url = "https://www.bse.cn/service/code_mapping.html"
    request = json.loads(cap.request_json, object_pairs_hook=unique_pairs)
    if (
        (cap.provider, cap.operation, cap.payload_format, cap.adapter_version)
        != (
            "bse",
            "code_mapping_html",
            "bse.code_mapping.html.v1",
            "karkinos.bse.code_mapping.operation.v1",
        )
        or cap.record_count is not None
        or set(request)
        != {
            "kind",
            "url",
            "method",
            "headers",
            "timeout_seconds_per_get",
            "maximum_gets",
            "session",
            "http_response_sequence",
        }
        or request["kind"] != "official_bse_code_mapping"
        or request["url"] != url
        or request["method"] != "GET"
        or request["headers"]
        != {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bse.cn/"}
        or request["timeout_seconds_per_get"] != 20
        or request["maximum_gets"] != 2
        or request["session"] != "anonymous"
    ):
        raise ValueError("bse_auction_mapping_capture_identity_invalid")
    body = read_provider_raw_payload(objects, cap)
    trace = request["http_response_sequence"]
    if not isinstance(trace, list) or not 1 <= len(trace) <= 2:
        raise ValueError("bse_auction_mapping_transport_invalid")
    previous = cap.started_at
    for index, item in enumerate(trace):
        if set(item) != {
            "method",
            "url",
            "started_at",
            "completed_at",
            "status",
            "location",
            "response_body_bytes",
        }:
            raise ValueError("bse_auction_mapping_transport_invalid")
        start, end = (
            datetime.fromisoformat(item[key]) for key in ("started_at", "completed_at")
        )
        final = index == len(trace) - 1
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or not previous <= start <= end <= cap.completed_at
            or item["method"] != "GET"
            or item["url"] != url
            or type(item["status"]) is not int
            or item["status"] != (200 if final else 302)
            or (not final and item["location"] != url)
            or type(item["response_body_bytes"]) is not int
            or item["response_body_bytes"] < 0
            or (final and item["response_body_bytes"] != len(body))
        ):
            raise ValueError("bse_auction_mapping_transport_invalid")
        previous = end
    if not 1 <= len(body) <= 2 * 1024 * 1024:
        raise ValueError("bse_auction_mapping_body_invalid")
    soup = BeautifulSoup(body.decode("utf-8"), "html.parser")
    tables = []
    for table in soup.find_all("table"):
        rows = [
            [
                cell.get_text("", strip=True)
                for cell in row.find_all(["td", "th"], recursive=False)
            ]
            for row in table.find_all("tr")
        ]
        if rows and rows[0] == ["序号", "证券简称", "上市日期", "旧代码", "新代码"]:
            tables.append(rows[1:])
    if len(tables) != 1:
        raise ValueError("bse_auction_mapping_table_invalid")
    data, old_codes, new_codes = [], set(), set()
    for row in tables[0]:
        if len(row) == 1 and row[0].startswith("注："):
            continue
        if (
            len(row) != 5
            or row[0] != str(len(data) + 1)
            or not row[1]
            or re.fullmatch(r"[0-9]{6}", row[3]) is None
            or re.fullmatch(r"920[0-9]{3}", row[4]) is None
            or row[3] in old_codes
            or row[4] in new_codes
        ):
            raise ValueError("bse_auction_mapping_row_invalid")
        if re.fullmatch(r"[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}", row[2]) is None:
            raise ValueError("bse_auction_mapping_date_invalid")
        datetime.strptime(row[2], "%Y/%m/%d")
        old_codes.add(row[3])
        new_codes.add(row[4])
        data.append(row)
    if len(data) != 248:
        raise ValueError("bse_auction_mapping_coverage_invalid")
    return {row[4]: row[3] for row in data}


def parse_block_page(body, day, page_index):
    """Parse one closed native page, without interpreting blank types as B."""
    match = re.fullmatch(
        r"karkinosBlockComponentRead\(\[\[(\{.*\})\],\s*''\]\)\s*;?\s*",
        body.decode("utf-8"),
        re.S,
    )
    if match is None:
        raise ValueError("bse_auction_block_closed_jsonp_required")
    page = json.loads(
        match[1],
        parse_float=Decimal,
        object_pairs_hook=unique_pairs,
        parse_constant=invalid_constant,
    )
    if set(page) != {
        "content",
        "firstPage",
        "lastPage",
        "number",
        "numberOfElements",
        "size",
        "sort",
        "totalElements",
        "totalPages",
    }:
        raise ValueError("bse_auction_block_page_fields_invalid")
    if any(
        type(page[k]) is not int
        for k in ("number", "numberOfElements", "size", "totalElements", "totalPages")
    ):
        raise ValueError("bse_auction_block_page_numbers_invalid")
    total, pages = page["totalElements"], page["totalPages"]
    if (
        not 0 <= total <= 200
        or not 0 <= pages <= 10
        or page["number"] != page_index
        or page["size"] != 20
        or page["sort"] is not None
        or type(page["firstPage"]) is not bool
        or type(page["lastPage"]) is not bool
        or (total == 0 and (pages not in (0, 1) or page_index != 0))
        or (total > 0 and (pages != (total + 19) // 20 or not 0 <= page_index < pages))
        or page["firstPage"] != (page_index == 0)
        or page["lastPage"] != (page_index == max(1, pages) - 1)
        or not isinstance(page["content"], list)
        or page["numberOfElements"] != len(page["content"])
        or len(page["content"])
        != (0 if total == 0 else min(20, total - page_index * 20))
    ):
        raise ValueError("bse_auction_block_page_coverage_invalid")
    expected = {
        "hqbcjhth",
        "hqbjydy",
        "hqcjjg",
        "hqcjsj",
        "hqcjsl",
        "hqfcbj",
        "hqjsrq",
        "hqscjhth",
        "hqsjydy",
        "hqzqdm",
        "hqzqjc",
        "xxzrlx",
    }
    for row in page["content"]:
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("bse_auction_block_record_fields_invalid")
        if any(not isinstance(row[k], str) for k in expected - {"hqcjsl", "hqcjjg"}):
            raise ValueError("bse_auction_block_record_text_invalid")
        if (
            row["hqjsrq"] != day.strftime("%Y%m%d")
            or row["hqfcbj"] != "2"
            or row["xxzrlx"] not in ("B", "")
            or re.fullmatch(r"[0-9]{6}", row["hqzqdm"]) is None
            or type(row["hqcjsl"]) is not int
            or row["hqcjsl"] <= 0
            or any(not row[k].strip() for k in ("hqbcjhth", "hqscjhth", "hqzqjc"))
            or re.fullmatch(r"[0-9]{6}", row["hqcjsj"]) is None
            or not isinstance(row["hqcjjg"], (int, Decimal))
            or isinstance(row["hqcjjg"], bool)
            or number(row["hqcjjg"], "block_price") <= 0
        ):
            raise ValueError("bse_auction_block_record_invalid")
        datetime.strptime(row["hqcjsj"], "%H%M%S")
        number(row["hqcjsl"], "block_quantity")
    return page


def _read_relevant_block_rows(
    objects,
    capture_ids,
    mapping_id,
    instrument,
    day,
    checked_at,
    *,
    require_mapped_identity=False,
):
    """Replay complete pages and return rows for actual current/old identities."""
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    mapping = read_mapping(objects, mapping_id, checked_at)
    if require_mapped_identity and instrument.symbol not in mapping:
        raise ValueError("bse_tencent_actual_mapped_old_identity_required")
    codes = {instrument.symbol}
    if instrument.symbol in mapping:
        codes.add(mapping[instrument.symbol])
    pages, rows, seen = [], [], set()
    for index, capture_id in enumerate(capture_ids):
        cap = read_provider_capture(objects, objects.resolve_ref(capture_id))
        require_capture_before(cap, checked_at)
        event = datetime.combine(day, time(15), ZoneInfo("Asia/Shanghai"))
        if event > cap.started_at:
            raise ValueError("bse_auction_block_session_not_closed")
        expected_request = {
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
                "startDate": day.isoformat(),
                "endDate": day.isoformat(),
                "page": str(index),
            },
        }
        if (
            (cap.provider, cap.operation, cap.payload_format, cap.adapter_version)
            != (
                "bse_official_block_probe",
                "public_block_trade_probe",
                "bse.block_trade.raw_public_response.probe.v1",
                "operation.bse.fixed_date_block.raw_probe.v1",
            )
            or cap.record_count is not None
            or json.loads(cap.request_json, object_pairs_hook=unique_pairs)
            != expected_request
        ):
            raise ValueError("bse_auction_block_capture_identity_invalid")
        page = parse_block_page(read_provider_raw_payload(objects, cap), day, index)
        if pages and any(
            page[k] != pages[0][k] for k in ("totalElements", "totalPages")
        ):
            raise ValueError("bse_auction_block_page_series_changed")
        pages.append(page)
        for row in page["content"]:
            identity = tuple(
                row[k] for k in ("hqzqdm", "hqjsrq", "hqcjsj", "hqbcjhth", "hqscjhth")
            )
            if identity in seen:
                raise ValueError("bse_auction_block_duplicate_contract")
            seen.add(identity)
            rows.append(row)
    if (
        not pages
        or len(pages) != max(1, pages[0]["totalPages"])
        or len(rows) != pages[0]["totalElements"]
    ):
        raise ValueError("bse_auction_block_incomplete_page_series")
    relevant = [row for row in rows if row["hqzqdm"] in codes]
    if len({row["hqzqdm"] for row in relevant}) > 1:
        raise ValueError("bse_auction_block_dual_code_ambiguity")
    return relevant


def require_no_reported_block_components(
    objects, capture_ids, mapping_id, instrument, day, checked_at
):
    """Require complete pages with neither current nor mapped-old code rows.

    Absence of published components is not evidence of suspension or inactivity.
    An unknown/blank type for the requested identity is still a relevant row.
    """
    if _read_relevant_block_rows(
        objects,
        capture_ids,
        mapping_id,
        instrument,
        day,
        checked_at,
        require_mapped_identity=True,
    ):
        raise ValueError("bse_tencent_complete_pages_must_have_no_relevant_components")


def read_block_components(
    objects, capture_ids, mapping_id, instrument, day, checked_at
):
    """Complete pages and actual code mapping; return published shares/notional."""
    relevant = _read_relevant_block_rows(
        objects, capture_ids, mapping_id, instrument, day, checked_at
    )
    if not relevant or any(row["xxzrlx"] != "B" for row in relevant):
        raise ValueError("bse_auction_block_explicit_B_required")
    with exact_bse_arithmetic():
        return (
            sum((Decimal(row["hqcjsl"]) for row in relevant), Decimal(0)),
            sum(
                (Decimal(row["hqcjsl"]) * Decimal(row["hqcjjg"]) for row in relevant),
                Decimal(0),
            ),
        )


TENCENT_BSE_NATIVE_ADAPTERS = (
    "operation.tencent.BJ920030.native_annual_http_probe.v1",
    "operation.tencent.BJ2021.fixed49.native_http_probe.v1",
)


def _read_tencent_capture(objects, capture_id, instrument, mapping_id):
    """Replay only the two observed current-literal, unadjusted HTTP contracts."""
    from core.types import InstrumentType
    from data.market.capture import read_provider_capture, read_provider_raw_payload

    symbol = instrument.symbol
    if (
        instrument.instrument_type is not InstrumentType.STOCK
        or re.fullmatch(r"920[0-9]{3}", symbol) is None
    ):
        raise ValueError("bse_tencent_current_stock_required")
    cap = read_provider_capture(objects, objects.resolve_ref(capture_id))
    request = json.loads(cap.request_json, object_pairs_hook=unique_pairs)
    old = cap.adapter_version == TENCENT_BSE_NATIVE_ADAPTERS[0]
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    params = {
        "_var": "kline_day2021",
        "param": f"bj{symbol},day,2021-01-01,2022-12-31,640,",
        "r": "0.8205512681390605",
    }
    common_keys = {
        "kind",
        "original_job_id",
        "actual_source_symbol",
        "method",
        "url",
        "params",
        "headers",
        "actual_prepared_url",
        "response_status",
        "response_content_type",
        "response_content_encoding",
        "redirects_followed",
        "timeout_seconds",
    }
    variant_keys = (
        {"actual_mapping_capture_id"}
        if old
        else {"fixed_plan_sha256", "original_payload_sha256", "mapping_capture_id"}
    )
    mapping_field = "actual_mapping_capture_id" if old else "mapping_capture_id"
    if (
        (cap.provider, cap.operation, cap.payload_format)
        != (
            "tencent_native_public_probe",
            "annual_unadjusted_history_http_probe",
            "tencent.newfqkline.native_http_body.v1",
        )
        or cap.adapter_version not in TENCENT_BSE_NATIVE_ADAPTERS
        or cap.record_count is not None
        or not isinstance(request, dict)
        or set(request) != common_keys | variant_keys
        or request["kind"]
        != (
            "Tencent_BJ_native_history_raw_probe"
            if old
            else "Tencent_BJ2021_fixed49_current_native_raw_probe"
        )
        or old
        and symbol != "920030"
        or request[mapping_field] != mapping_id
        or re.fullmatch(r"[0-9a-f]{64}", request["original_job_id"]) is None
        or not old
        and any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", request[k]) is None
            for k in ("fixed_plan_sha256", "original_payload_sha256")
        )
        or request["actual_source_symbol"] != "bj" + symbol
        or request["method"] != "GET"
        or request["url"] != url
        or request["params"] != params
        or request["actual_prepared_url"] != url + "?" + urlencode(params)
        or type(request["response_status"]) is not int
        or request["response_status"] != 200
        or type(request["redirects_followed"]) is not int
        or request["redirects_followed"] != 0
        or (request["response_content_encoding"] or "identity").lower() != "identity"
        or type(request["timeout_seconds"]) is not int
        or request["timeout_seconds"] != 20
        or not isinstance(request["headers"], dict)
        or request["headers"].get("Accept-Encoding") != "identity"
    ):
        raise ValueError("bse_tencent_exact_native_capture_request_required")
    body = read_provider_raw_payload(objects, cap)
    if not 8 <= len(body) <= 8 * 1024 * 1024:
        raise ValueError("bse_tencent_native_body_size_invalid")
    return cap, body


def read_tencent_rows(objects, capture_id, instrument, mapping_id, *, session_date):
    """Unmodified native reported values, restricted to selected 2021 sessions.

    The actual 2020 padding/2022 rows remain in the raw response and are parsed
    for shape/identity. Their presence grants no new financial scope. Fixed
    two-decimal native amount lexemes represent a 100-CNY grid, not an error
    bound or a proven provider-wide rounding rule.
    """
    if type(session_date) is not date or session_date.year != 2021:
        raise ValueError("bse_tencent_selected_2021_session_required")
    cap, body = _read_tencent_capture(objects, capture_id, instrument, mapping_id)
    cached = _cached_native(objects, cap)
    if cached is None:
        match = re.fullmatch(
            rb"\s*kline_day2021\s*=\s*(\{.*\})\s*;?\s*", body, re.DOTALL
        )
        if match is None:
            raise ValueError("bse_tencent_closed_assignment_required")
        value = json.loads(
            match[1],
            parse_float=Decimal,
            parse_constant=invalid_constant,
            object_pairs_hook=unique_pairs,
        )
        symbol = "bj" + instrument.symbol
        if (
            not isinstance(value, dict)
            or type(value.get("code")) is not int
            or value["code"] != 0
            or not isinstance(value.get("data"), dict)
            or set(value["data"]) != {symbol}
            or not isinstance(value["data"][symbol], dict)
            or "day" not in value["data"][symbol]
        ):
            raise ValueError("bse_tencent_exact_native_symbol_day_required")
        native = value["data"][symbol]["day"]
        if not isinstance(native, list) or not 1 <= len(native) <= 640:
            raise ValueError("bse_tencent_native_row_count_invalid")
        rows = {}
        for row in native:
            if (
                not isinstance(row, list)
                or len(row) != 11
                or not isinstance(row[0], str)
            ):
                raise ValueError("bse_tencent_native_row_shape_invalid")
            day = date.fromisoformat(row[0])
            if (
                day.isoformat() != row[0]
                or day in rows
                or not 2020 <= day.year <= 2022
                or day > cap.started_at.date()
            ):
                raise ValueError("bse_tencent_native_duplicate_or_outside_date")
            values = {}
            with exact_bse_arithmetic():
                for field, index in (
                    ("open", 1),
                    ("high", 3),
                    ("low", 4),
                    ("close", 2),
                    ("volume", 5),
                    ("amount", 8),
                ):
                    if (
                        not isinstance(row[index], str)
                        or re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{2}", row[index])
                        is None
                    ):
                        raise ValueError(
                            "bse_tencent_native_two_decimal_lexeme_required"
                        )
                    scale = (
                        10000 if field == "amount" else 100 if field == "volume" else 1
                    )
                    values[field] = number(
                        number(Decimal(row[index]), field) * scale, field
                    )
            if (
                values["low"] > min(values["open"], values["close"])
                or values["high"] < max(values["open"], values["close"])
                or values["high"] < values["low"]
            ):
                raise ValueError("bse_tencent_native_OHLC_order_invalid")
            rows[day] = values
        cached = _immutable_rows(rows)
        _store_native(objects, cap, cached)
    return cap, _select_day(cached, session_date)
