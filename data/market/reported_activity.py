"""Replay reported stock turnover against immutable daily sources and BSE disclosures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from data.market.capture import read_provider_capture, read_provider_raw_payload
from data.market.normalize import reported_whole_hand_volume_matches
from data.providers.bse_sina_history import (
    exact_bse_arithmetic,
    read_block_components,
    read_official,
    require_capture_before,
)
from data.providers.eastmoney import _daily_event_time
from data.providers.tushare import _request_target

REPORTED_ACTIVITY_KIND = "karkinos.tushare_eastmoney.reported_activity"


@dataclass(frozen=True, slots=True)
class TushareEastmoneyActivity:
    """The exchange's complete block pages and exact K-line capture per affected stock."""

    block_page_capture_ids: tuple[str, ...] = ()
    mapping_capture_id: str | None = None
    official_history_ids: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        from data.market.reconciliation import BseAuctionRelation

        BseAuctionRelation(self.block_page_capture_ids, self.mapping_capture_id)
        keys = [symbol for symbol, _ in self.official_history_ids]
        if (
            not isinstance(self.official_history_ids, tuple)
            or keys != sorted(set(keys))
            or bool(keys) != bool(self.block_page_capture_ids)
            or any(
                not re.fullmatch(r"92[0-9]{4}", symbol)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", identity)
                for symbol, identity in self.official_history_ids
            )
        ):
            raise ValueError("market_reported_activity_disclosures_invalid")


def require_native_reported_activity(store, materialization, bars, checked_at):
    """Reopen both original share/hand and CNY/thousand-CNY representations."""
    capture = read_provider_capture(store, materialization.capture_ref)
    require_capture_before(capture, checked_at)
    raw = json.loads(read_provider_raw_payload(store, capture))
    request = json.loads(capture.request_json)
    if capture.provider == "tushare":
        version = "karkinos.tushare.daily_bar.v2"
        schema = "tushare.pro.daily_bar.dataframe.v1"
        columns = ("open", "high", "low", "close", "vol", "amount")
    elif capture.provider == "akshare":
        version = "karkinos.akshare.daily_bar.v2"
        schema = "akshare.eastmoney.daily_bar.dataframe.v2"
        columns = ("开盘", "最高", "最低", "收盘", "成交量", "成交额")
        if raw["sdk_version"] != "1.18.97":
            raise ValueError("market_reported_activity_sdk_unreviewed")
    else:
        raise ValueError("market_reported_activity_provider_invalid")
    if (
        capture.adapter_version != version
        or capture.payload_format != schema
        or raw["schema"] != schema
        or capture.operation != "daily_bars"
        or request["kind"] != "daily_bars"
        or request["frequency"] != "1d"
    ):
        raise ValueError("market_reported_activity_capture_invalid")
    start, end = (date.fromisoformat(request[k]) for k in ("start_date", "end_date"))
    day = bars[0].session_date
    wanted = {b.instrument.symbol: b for b in bars}
    requested = {
        r["symbol"] for r in request["instruments"] if r["instrument_type"] == "stock"
    }
    if not set(wanted) <= requested or not start <= day <= end:
        raise ValueError("market_reported_activity_request_mismatch")
    found = set()
    for call in raw["calls"]:
        is_tushare = capture.provider == "tushare"
        symbol = call["ts_code"].split(".")[0] if is_tushare else call["symbol"]
        if symbol not in wanted:
            continue
        bar = wanted[symbol]
        code = _request_target(bar.instrument)[1]
        if is_tushare:
            if call["endpoint"] != "daily" or call["ts_code"] != code:
                raise ValueError("market_reported_activity_request_mismatch")
        elif call["endpoint"] != "stock_zh_a_hist" or call["request"] != {
            "symbol": symbol,
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "period": "daily",
            "adjust": "",
        }:
            raise ValueError("market_reported_activity_request_mismatch")
        if (
            not is_tushare
            and symbol.startswith(("4", "8", "92"))
            and call.get("volume_precision")
            != "karkinos.eastmoney.bse.whole_hand_resolution.v1"
        ):
            raise ValueError("market_reported_activity_source_precision_invalid")
        frame = call["frame"]
        if len(frame["columns"]) != len(set(frame["columns"])):
            raise ValueError("market_reported_activity_duplicate_columns")
        for values in frame["data"]:
            row = dict(zip(frame["columns"], values, strict=True))
            if str(row["trade_date"] if is_tushare else row["日期"]) != (
                day.strftime("%Y%m%d") if is_tushare else day.isoformat()
            ):
                continue
            if (row["ts_code"] if is_tushare else row["股票代码"]) != (
                code if is_tushare else symbol
            ):
                raise ValueError("market_reported_activity_instrument_mismatch")
            op, hi, lo, cl, vol, amt = (Decimal(str(row[k])) for k in columns)
            if (
                symbol in found
                or bar.session_date != day
                or bar.event_time != _daily_event_time(day)
                or bar.available_at != capture.completed_at
                or bar.captured_at != capture.completed_at
                or (op, hi, lo, cl, vol * 100, amt * (1000 if is_tushare else 1))
                != (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount)
                or (not is_tushare and vol != vol.to_integral_value())
            ):
                raise ValueError("market_reported_activity_native_row_mismatch")
            found.add(symbol)
    if found != set(wanted):
        raise ValueError("market_reported_activity_native_row_missing")
    return capture.request_json


def reconcile_reported_activity(
    store,
    *,
    primary_revision,
    primary_materialization,
    comparison_revision,
    comparison_materialization,
    primary_bars,
    comparison_bars,
    policy,
    relation,
    checked_at,
):
    from data.market.reconciliation import (
        EASTMONEY_TUSHARE_BSE_RECONCILIATION,
        reconcile_daily_bars,
    )

    if (
        (primary_revision.provider, comparison_revision.provider)
        != ("tushare", "akshare")
        or policy != EASTMONEY_TUSHARE_BSE_RECONCILIATION
        or not primary_bars
        or not comparison_bars
    ):
        raise ValueError("market_reported_activity_source_pair_invalid")
    report = reconcile_daily_bars(
        primary_bars,
        comparison_bars,
        primary_revision_id=primary_revision.ref.revision_id,
        comparison_revision_id=comparison_revision.ref.revision_id,
        primary_provider=primary_revision.provider,
        comparison_provider=comparison_revision.provider,
        policy=policy,
    )
    # No other difference, including a missing stock or a price, is explained here.
    if not report.differences or any(
        d.field not in {"volume", "amount"} for d in report.differences
    ):
        raise ValueError("market_reported_activity_unexplained_difference")
    impacted = {d.instrument for d in report.differences}
    primary = {b.instrument: b for b in primary_bars}
    comparison = {b.instrument: b for b in comparison_bars}
    official = dict(relation.official_history_ids)
    if set(official) != {k.symbol for k in impacted if k.symbol.startswith("92")}:
        raise ValueError("market_reported_activity_disclosure_coverage_mismatch")
    with exact_bse_arithmetic():
        primary_request = require_native_reported_activity(
            store, primary_materialization, primary_bars, checked_at
        )
        comparison_request = require_native_reported_activity(
            store, comparison_materialization, comparison_bars, checked_at
        )
        if primary_request != comparison_request:
            raise ValueError("market_reported_activity_request_mismatch")
        for key in impacted:
            tushare, eastmoney = primary[key], comparison[key]
            if (
                tushare.suspended
                or min(
                    tushare.volume, tushare.amount, eastmoney.volume, eastmoney.amount
                )
                <= 0
            ):
                raise ValueError("market_reported_activity_traded_stock_required")
            if key.symbol.startswith(("688", "689")):
                if (
                    tushare.amount != eastmoney.amount
                    or not reported_whole_hand_volume_matches(
                        tushare.volume, eastmoney.volume
                    )
                ):
                    raise ValueError("market_reported_activity_whole_hand_mismatch")
                continue
            if key.symbol not in official:
                raise ValueError("market_reported_activity_venue_unsupported")
            cap, history, _, _ = read_official(
                store, official[key.symbol], key, session_date=tushare.session_date
            )
            require_capture_before(cap, checked_at)
            exchange = history.get(tushare.session_date)
            quantity, notional = read_block_components(
                store,
                relation.block_page_capture_ids,
                relation.mapping_capture_id,
                key,
                tushare.session_date,
                checked_at,
            )
            if (
                exchange is None
                or any(
                    getattr(tushare, field) != getattr(exchange, field)
                    for field in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "event_time",
                        "suspended",
                    )
                )
                or quantity <= 0
                or notional <= 0
                or tushare.volume + quantity != exchange.volume
                or tushare.amount + notional != exchange.amount
                or eastmoney.amount != exchange.amount
                or abs(eastmoney.volume - exchange.volume) >= 100
            ):
                raise ValueError(
                    "market_reported_activity_official_disclosure_mismatch"
                )
    return replace(report, differences=())
