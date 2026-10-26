"""Replay complete native SZSE single-stock suspension event streams.

Literal S/R columns establish the state between actual events. Repeated S does
not close or reset a halt. No missing row establishes a halt or active state.
Separate, explicitly supplied identity announcements may map an old code onto
one frozen current InstrumentKey; the original request and bytes never change.
All availability remains capture-time evidence, never historical PIT.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.market.capture import read_provider_capture, read_provider_raw_payload
from data.market.contracts import DailyBarRequest

SZSE_MEMO_ADAPTER_VERSION = "operation.szse.memo.native_probe.v1"
SZSE_MEMO_PAYLOAD_FORMAT = "szse.memo.raw_response.v1"
_IDENTITY_ADAPTER = "operation.szse.security_identity.native_probe.v1"
_IDENTITY_FORMAT = "szse.security_identity.raw_pdf.v1"
_URL = "https://www.szse.cn/api/report/ShowReport/data"
_TZ = ZoneInfo("Asia/Shanghai")
_FIELDS = {"zqdm", "zqjc", "tpkssj", "fpkssj", "tpsj", "tpyy"}
_COLS = {
    "zqdm": "证券代码",
    "zqjc": "证券简称",
    "tpkssj": "停牌时间",
    "fpkssj": "复牌时间",
    "tpsj": "停牌期限",
    "tpyy": "停牌原因",
}


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("szse_memo_duplicate_JSON_key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("szse_memo_nonfinite_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _stock(symbol):
    return isinstance(symbol, str) and re.fullmatch(r"(?:00|30)[0-9]{4}", symbol)


def _day(text):
    if (
        not isinstance(text, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text) is None
    ):
        raise ValueError("szse_memo_date_invalid")
    return date.fromisoformat(text)


def _instant(text):
    match = re.fullmatch(
        r"([0-9]{4}-[0-9]{2}-[0-9]{2}) (开市|[0-9]{2}:[0-9]{2}:[0-9]{2})", text
    )
    if match is None:
        raise ValueError("szse_memo_timestamp_invalid")
    day = _day(match[1])
    opening = match[2] == "开市"
    clock = time(9, 30) if opening else time.fromisoformat(match[2])
    if not time(9, 30) <= clock <= time(15):
        raise ValueError("szse_memo_timestamp_outside_session")
    return datetime.combine(day, clock, _TZ), opening


def _require_identity_statements(text, old, new, effective):
    """Close every supported identity assertion, not just positive snippets.

    These are the finite current implementation-announcement facts. Additional
    statements about the same effective opening, entity continuity or holders'
    share category/quantity must fit their affirmative literal contract too.
    Other disclosure prose does not become identity evidence.
    """
    day = f"{effective.year}年{effective.month}月{effective.day}日"
    stock = f"公司股票自{day}开市起启用变更后的证券简称及证券代码"
    continuity = {"公司法人主体存续", "上市主体没有发生实质变化"}
    shares = {
        "投资者证券账户中（包括投资者信用账户）持有公司股份数量不变",
        "投资者持有股份的证券类别和持有数量与代码变更完成前一致",
    }
    dates = {
        f"变更后的证券简称及证券代码启用日期：{day}",
        f"本次变更后的证券简称及证券代码启用日期为{day}",
        f"（一）公司证券简称和证券代码变更的时间安排如下：本次变更后的证券简称及证券代码启用日期为{day}",
    }
    table = (
        r"本次变更证券简称、英文简称、证券代码的情况如下：项目变更前变更后"
        r"证券简称[\u4e00-\u9fffA-Za-z*]{1,40}英文简称[A-Za-z]{1,40}证券代码"
        + old
        + new
        + re.escape(f"本次变更后的证券简称及证券代码启用日期为{day}")
    )
    supported = {
        stock,
        "公司依照《深圳证券交易所创业板股票上市规则》及相关业务处理要求，经向深圳证券交易所申请，"
        + stock
        + "，启用当日股票交易设置涨跌幅限制",
        *continuity,
        "公司法人主体存续，上市主体没有发生实质变化",
        "公司重大资产重组事项已于前期充分披露，本次变更公司证券简称和证券代码后，"
        "公司法人主体存续，上市主体没有发生实质变化，对公司的生产经营及投资价值不产生实质性影响",
        *shares,
        "公司向深圳证券交易所及中国证券登记结算有限责任公司深圳分公司申请，"
        "根据证券代码变更股权登记日（T-1日）登记在册的股东名册，"
        f"在证券代码变更日（T日）将证券代码“{old}”股份变更为证券代码“{new}”股份，"
        "投资者证券账户中（包括投资者信用账户）持有公司股份数量不变",
        "（二）各项相关业务的具体处理安排：1、投资者证券持有的处理：投资者所持上市公司股份，"
        f"T-1日前（含T-1日）证券代码为“{old}”，T日后（含T日）证券代码变更为“{new}”，"
        "代码变更完成后，投资者持有股份的证券类别和持有数量与代码变更完成前一致",
        *dates,
        f"（一）公司证券简称和证券代码变更的时间安排如下：本次变更后的证券简称及证券代码启用日期为{day}，启用当日设置涨跌幅限制",
    }
    previous_identity = False
    for statement in re.split(r"[。；！？•]", text):
        if not statement:
            continue
        relevant = (
            re.search(
                r"公司股票|公司(?:的)?(?:法人)?主体|上市主体|股份数量|股数|持有数量|证券类别|持股数量|股份类别|启用日期|生效日期",
                statement,
            )
            is not None
        )
        if relevant:
            # Commas retain the same grammatical subject. Accept the complete
            # supported sentence, never a positive fragment of that sentence.
            if statement not in supported and re.fullmatch(table, statement) is None:
                raise ValueError("szse_security_identity_statement_unsupported")
        elif previous_identity and re.match(
            r"(?:但|然而|不过|而|实际|以上|上述|该项)", statement
        ):
            # An explicit continuation without a new subject still belongs to
            # the preceding identity claim. No such extra statement is in this
            # finite contract; it cannot silently override the affirmed fact.
            raise ValueError("szse_security_identity_continuation_unsupported")
        previous_identity = relevant


def read_szse_security_identity_relation(store, capture_ref):
    """Return (original capture, old STOCK key, new STOCK key, effective date).

    This narrow implementation-announcement contract requires literal code,
    effective-opening, entity-continuity and unchanged-share-category/quantity
    statements. It is identity provenance, neither status nor a security master.
    """
    from pypdf import PdfReader

    _json(store.read_bytes(capture_ref))
    capture = read_provider_capture(store, capture_ref)
    request = _json(capture.request_json)
    if (
        capture.provider != "szse_disclosure"
        or capture.operation != "security_identity_announcement"
        or capture.adapter_version != _IDENTITY_ADAPTER
        or capture.payload_format != _IDENTITY_FORMAT
        or capture.record_count is not None
        or not isinstance(request, dict)
        or set(request) != {"url"}
        or not isinstance(request["url"], str)
    ):
        raise ValueError("szse_security_identity_source_invalid")
    url = re.fullmatch(
        r"https://disc\.static\.szse\.cn/download/disc/disk03/finalpage/"
        r"([0-9]{4}-[0-9]{2}-[0-9]{2})/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.PDF",
        request["url"],
    )
    if url is None or _day(url[1]) > capture.started_at.astimezone(_TZ).date():
        raise ValueError("szse_security_identity_URL_or_time_invalid")
    raw = read_provider_raw_payload(store, capture)
    if not 0 < len(raw) <= 4 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
        raise ValueError("szse_security_identity_PDF_invalid")
    try:
        pdf = PdfReader(io.BytesIO(raw))
        if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 8:
            raise ValueError("szse_security_identity_PDF_invalid")
        text = "".join(
            re.sub(r"\s+", "", page.extract_text() or "") for page in pdf.pages
        )
    except Exception as exc:
        raise ValueError("szse_security_identity_PDF_invalid") from exc
    old = re.findall(
        r"^证券代码：((?:00|30)[0-9]{4})证券简称：[^：]{1,20}公告编号：[0-9]{4}-[0-9]{3}",
        text,
    )
    new = re.findall(
        r"变更后的证券代码：((?:00|30)[0-9]{4})(?:[•]|变更后的英文简称)", text
    )
    effective = re.findall(
        r"(?:^|[。；，：:•])公司股票自([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日开市起启用变更后的证券简称及证券代码",
        text,
    )
    if len(old) != 1 or len(new) != 1 or old == new or len(effective) != 1:
        raise ValueError("szse_security_identity_literal_relation_missing")
    old, new = old[0], new[0]
    effective = date(*(int(value) for value in effective[0]))
    date_text = f"{effective.year}年{effective.month}月{effective.day}日"
    declared = re.findall(
        r"变更后的证券简称及证券代码启用日期(?:为|：)([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)",
        text,
    )
    if (
        effective > capture.started_at.astimezone(_TZ).date()
        or "关于变更公司证券简称及证券代码的实施公告" not in text
        or f"证券代码{old}{new}" not in text
        or f"原证券代码“{old}”变更为“{new}”" not in text
        or re.search(r"(?:^|[。；，])公司法人主体存续，上市主体没有发生实质变化", text)
        is None
        or re.search(
            r"(?:^|[。；，])投资者持有股份的证券类别和持有数量与代码变更完成前一致",
            text,
        )
        is None
        or f"本次变更后的证券简称及证券代码启用日期为{date_text}。" not in text
        or not declared
        or set(declared) != {date_text}
    ):
        raise ValueError("szse_security_identity_continuity_or_effective_missing")
    _require_identity_statements(text, old, new, effective)
    return (
        capture,
        InstrumentKey(old, InstrumentType.STOCK),
        InstrumentKey(new, InstrumentType.STOCK),
        effective,
    )


def _markers(rows, *, symbol, start, end, captured_at):
    events, uncertain = [], []
    seen = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != _FIELDS
            or not all(isinstance(value, str) for value in row.values())
            or row["zqdm"] != symbol
        ):
            raise ValueError("szse_memo_native_row_identity_or_shape_invalid")
        frozen = tuple(row[key] for key in sorted(_FIELDS))
        if frozen in seen:
            raise ValueError("szse_memo_duplicate_native_row")
        seen.add(frozen)
        stop, resume = row["tpkssj"], row["fpkssj"]
        left = _instant(stop) if stop else None
        right = _instant(resume) if resume else None
        if left is not None and right is not None and left[0] >= right[0]:
            raise ValueError("szse_memo_native_interval_not_positive")
        known = (bool(stop), bool(resume), row["tpsj"]) in {
            (True, False, "停牌"),
            (False, True, "取消停牌"),
            (True, True, "1天"),
            (True, True, ""),
        }
        if not known or any(
            item is not None and item[0] > captured_at for item in (left, right)
        ):
            # A locatable uncertain event must survive same/cross-capture
            # aggregation. It is neither an active state nor a full-day halt.
            uncertain.append(
                (left[0].date() if left else start, right[0].date() if right else end)
            )
            continue
        for kind, item in (("S", left), ("R", right)):
            if item is not None:
                events.append((item[0], kind, item[1]))
    events.sort()
    ambiguous = {
        at
        for at, _, _ in events
        if len({kind for when, kind, _ in events if when == at}) > 1
    }
    pending = None
    intervals = []
    for at, kind, opening in events:
        if at in ambiguous:
            uncertain.append((pending[0].date() if pending else at.date(), end))
            continue
        if kind == "S":
            if pending is None:
                pending = at, opening
        elif pending is not None:
            intervals.append((pending, (at, opening)))
            pending = None
        else:
            intervals.append(((at, False), (at, opening)))
    if pending is not None:
        uncertain.append((pending[0].date(), end))
    result = {}

    def add(first, last, value):
        day = max(first, start)
        while day <= min(last, end):
            previous = result.get(day)
            if previous is not None and previous != value:
                if "0" in (previous, value):
                    raise ValueError("szse_memo_native_statuses_conflict")
                value = "unknown"
            result[day] = value
            day += timedelta(days=1)

    for (left, opening), (right, _) in intervals:
        first, last = left.date(), right.date()
        if first < last:
            if opening:
                add(first, last - timedelta(days=1), "0")
            else:
                add(first, first, "not_full_day")
                add(first + timedelta(days=1), last - timedelta(days=1), "0")
        add(last, last, "not_full_day")
    for first, last in uncertain:
        add(first, last, "unknown")
    return result


def read_szse_structured_suspension_status(
    store, capture_ref, *, selected_instruments, identity_capture_refs=()
):
    """Return the original capture, frozen-consumer request and dated markers.

    Only a complete native single-stock page is accepted. The caller must also
    bind each supplied identity capture in membership.source_observation_ids,
    independently replay its identity contract and include its completion in
    the membership availability maximum. This function does not replace that
    Dataset ownership. The original native request is never rewritten.
    """
    if (
        not isinstance(selected_instruments, tuple)
        or not selected_instruments
        or any(not isinstance(key, InstrumentKey) for key in selected_instruments)
        or len(set(selected_instruments)) != len(selected_instruments)
        or not isinstance(identity_capture_refs, tuple)
        or len(set(identity_capture_refs)) != len(identity_capture_refs)
    ):
        raise ValueError("szse_memo_selected_roster_or_identity_refs_invalid")
    selected = {
        key.symbol: key
        for key in selected_instruments
        if key.instrument_type is InstrumentType.STOCK and _stock(key.symbol)
    }
    _json(store.read_bytes(capture_ref))
    capture = read_provider_capture(store, capture_ref)
    if (
        capture.provider != "szse_memo"
        or capture.operation != "suspension_status_probe"
        or capture.adapter_version != SZSE_MEMO_ADAPTER_VERSION
        or capture.payload_format != SZSE_MEMO_PAYLOAD_FORMAT
        or capture.record_count is not None
    ):
        raise ValueError("szse_memo_source_invalid")
    request = _json(capture.request_json)
    if (
        not isinstance(request, dict)
        or set(request) != {"url", "params"}
        or request["url"] != _URL
    ):
        raise ValueError("szse_memo_request_invalid")
    params = request["params"]
    if (
        not isinstance(params, dict)
        or set(params)
        != {
            "SHOWTYPE",
            "CATALOGID",
            "TABKEY",
            "txtDmorjc",
            "txtKsrq",
            "txtZzrq",
            "PAGENO",
        }
        or any(
            params[field] != value
            for field, value in {
                "SHOWTYPE": "JSON",
                "CATALOGID": "1798",
                "TABKEY": "tab1",
                "PAGENO": "1",
            }.items()
        )
        or not _stock(params["txtDmorjc"])
    ):
        raise ValueError("szse_memo_request_invalid")
    start, end = _day(params["txtKsrq"]), _day(params["txtZzrq"])
    if (
        end < start
        or (end - start).days >= 3653
        or capture.started_at < datetime.combine(end, time(15), _TZ)
    ):
        raise ValueError("szse_memo_request_window_not_closed")
    symbol, key, effective = (
        params["txtDmorjc"],
        selected.get(params["txtDmorjc"]),
        None,
    )
    relations = [
        read_szse_security_identity_relation(store, ref)
        for ref in identity_capture_refs
    ]
    matching = [
        relation
        for relation in relations
        if relation[1].symbol == symbol and relation[2].symbol in selected
    ]
    if matching:
        if key is not None or len(matching) != 1:
            raise ValueError("szse_memo_alias_selection_ambiguous")
        _, _, key, effective = matching[0]
    if key is None:
        raise ValueError("szse_memo_consumer_identity_unbound")
    raw = read_provider_raw_payload(store, capture)
    if not 0 < len(raw) <= 4 * 1024 * 1024:
        raise ValueError("szse_memo_raw_size_invalid")
    body = _json(raw)
    if (
        not isinstance(body, list)
        or len(body) != 1
        or not isinstance(body[0], dict)
        or set(body[0]) != {"metadata", "data", "error"}
        or body[0]["error"] is not None
    ):
        raise ValueError("szse_memo_native_schema_invalid")
    metadata, rows = body[0]["metadata"], body[0]["data"]
    if (
        not isinstance(metadata, dict)
        or metadata.get("catalogid") != "1798"
        or metadata.get("tabkey") != "tab1"
        or metadata.get("name") != "停复牌提示"
        or metadata.get("cols") != _COLS
        or not isinstance(rows, list)
        or any(
            type(metadata.get(field)) is not int
            for field in ("pagesize", "pageno", "pagecount", "recordcount")
        )
        or metadata["pagesize"] != 10
        or metadata["pageno"] != 1
        or metadata["recordcount"] != len(rows)
        or metadata["pagecount"] != (len(rows) + 9) // 10
        or len(rows) > 10
    ):
        raise ValueError("szse_memo_native_page_not_complete")
    conditions = metadata.get("conditions")
    if (
        not isinstance(conditions, list)
        or len(conditions) != 4
        or any(not isinstance(item, dict) for item in conditions)
    ):
        raise ValueError("szse_memo_native_conditions_invalid")
    names = [item.get("name") for item in conditions]
    if len(set(names)) != 4 or set(names) != {
        "txtDmorjc",
        "txtKsrq",
        "txtZzrq",
        "txtKsrq-txtZzrq",
    }:
        raise ValueError("szse_memo_native_conditions_invalid")
    if any(
        item.get("defaultValue") != params[item["name"]]
        for item in conditions
        if item["name"] != "txtKsrq-txtZzrq"
    ):
        raise ValueError("szse_memo_native_query_identity_mismatch")
    markers = _markers(
        rows, symbol=symbol, start=start, end=end, captured_at=capture.started_at
    )
    statuses = {
        day: {key: marker}
        for day, marker in markers.items()
        if effective is None or day < effective
    }
    return capture, DailyBarRequest((key,), start, end), statuses
