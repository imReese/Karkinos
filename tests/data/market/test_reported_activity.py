"""Cold replay must preserve the auction bar and reject unexplained differences."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.capture import capture_provider_payload
from data.market.contracts import DailyBarRequest
from data.market.reconciliation import (
    EASTMONEY_TUSHARE_BSE_RECONCILIATION,
    STRICT_DAILY_RECONCILIATION,
    TENCENT_EASTMONEY_STOCK_RECONCILIATION,
    reconcile_daily_bar_revisions,
)
from data.market.reported_activity import (
    REPORTED_ACTIVITY_KIND,
    TushareEastmoneyActivity,
)
from data.market.revision import publish_daily_bar_revision
from data.storage.objects import ContentAddressedObjectStore
from tests.data.market import test_tencent_tushare_reported_amount as tencent
from tests.data.market.test_bse_auction_relation import CHECKED, DAY
from tests.data.market.test_bse_auction_relation import pair as native_pair  # noqa: F401


def eastmoney_raw(bar):
    symbol = bar.instrument.symbol
    day = bar.session_date
    trade = day.strftime("%Y%m%d")
    call = {
        "endpoint": "stock_zh_a_hist",
        "symbol": symbol,
        "request": {
            "symbol": symbol,
            "start_date": trade,
            "end_date": trade,
            "period": "daily",
            "adjust": "",
        },
        "frame": {
            "columns": [
                "日期",
                "股票代码",
                "开盘",
                "最高",
                "最低",
                "收盘",
                "成交量",
                "成交额",
            ],
            "data": [
                [
                    day.isoformat(),
                    symbol,
                    10,
                    11,
                    9,
                    10,
                    str(bar.volume / 100),
                    str(bar.amount),
                ]
            ],
        },
    }
    if symbol.startswith("92"):
        call["volume_precision"] = "karkinos.eastmoney.bse.whole_hand_resolution.v1"
    return {
        "schema": "akshare.eastmoney.daily_bar.dataframe.v2",
        "sdk_version": "1.18.97",
        "calls": [call],
    }


def market_pair(
    p, *, symbol, tu_vol, em_vol, tu_amount, em_amount, forged_volume=False
):
    key = InstrumentKey(symbol, InstrumentType.STOCK)
    trade = DAY.strftime("%Y%m%d")
    request = DailyBarRequest((key,), DAY, DAY).to_capture_request()
    sides = []
    for provider, vol, amt in (
        ("tushare", tu_vol, tu_amount),
        ("akshare", em_vol, em_amount),
    ):
        bar = replace(
            p["official"],
            instrument=key,
            volume=Decimal(vol),
            amount=Decimal(amt),
            available_at=CHECKED,
            captured_at=CHECKED,
        )
        hand = str((bar.volume + int(forged_volume and provider == "tushare")) / 100)
        if provider == "tushare":
            code = symbol + (".BJ" if symbol.startswith("92") else ".SH")
            schema = "tushare.pro.daily_bar.dataframe.v1"
            raw = {
                "schema": schema,
                "calls": [
                    {
                        "endpoint": "daily",
                        "ts_code": code,
                        "frame": {
                            "columns": [
                                "ts_code",
                                "trade_date",
                                "open",
                                "high",
                                "low",
                                "close",
                                "vol",
                                "amount",
                            ],
                            "data": [
                                [
                                    code,
                                    trade,
                                    10,
                                    11,
                                    9,
                                    10,
                                    hand,
                                    str(bar.amount / 1000),
                                ]
                            ],
                        },
                    }
                ],
            }
        else:
            raw = eastmoney_raw(bar)
            schema = raw["schema"]
        capture = capture_provider_payload(
            p["store"],
            provider=provider,
            operation="daily_bars",
            request=request,
            raw_payload=json.dumps(raw).encode(),
            payload_format=schema,
            adapter_version=f"karkinos.{provider}.daily_bar.v2",
            started_at=CHECKED,
            completed_at=CHECKED,
        )
        sides.append(
            publish_daily_bar_revision(
                p["store"], capture=capture, bars=(bar,), normalizer_version="fixture"
            )
        )

    def replay(relation):
        return reconcile_daily_bar_revisions(
            p["store"],
            primary_revision=sides[0][0],
            primary_materialization=sides[0][1],
            comparison_revision=sides[1][0],
            comparison_materialization=sides[1][1],
            policy=EASTMONEY_TUSHARE_BSE_RECONCILIATION,
            component_relation=relation,
            component_checked_at=CHECKED,
        )

    return replay


def test_star_whole_hands_need_exact_projection_and_original_cells(native_pair):
    assert REPORTED_ACTIVITY_KIND == "karkinos.tushare_eastmoney.reported_activity"
    p = native_pair()
    args = dict(
        symbol="688001",
        tu_vol=123450,
        em_vol=123500,
        tu_amount="1000.49",
        em_amount="1000.49",
    )
    replay = market_pair(p, **args)
    relation = TushareEastmoneyActivity()
    assert not replay(None).matched and replay(relation).matched
    with pytest.raises(ValueError, match="whole_hand_mismatch"):
        market_pair(p, **{**args, "em_vol": 123400})(relation)
    with pytest.raises(ValueError, match="native_row_mismatch"):
        market_pair(p, **args, forged_volume=True)(relation)


def test_bse_requires_both_official_totals_and_full_published_blocks(native_pair):
    p = native_pair()
    refs = p["relation"]
    relation = TushareEastmoneyActivity(
        refs.block_page_capture_ids,
        refs.mapping_capture_id,
        (("920001", p["official_cap"].capture_id),),
    )
    args = dict(
        symbol="920001",
        tu_vol=100,
        em_vol=100,
        tu_amount="1000.49",
        em_amount="1100.49",
    )
    replay = market_pair(p, **args)
    assert not replay(None).matched and replay(relation).matched
    with pytest.raises(ValueError, match="disclosure_coverage_mismatch"):
        replay(TushareEastmoneyActivity())
    with pytest.raises(ValueError, match="official_disclosure_mismatch"):
        market_pair(p, **{**args, "tu_amount": "1000.48"})(relation)


@pytest.mark.parametrize(("amount", "matched"), [("100046", True), ("100050", False)])
def test_tencent_eastmoney_requires_exact_raw_amount_projection(
    tmp_path, amount, matched
):
    assert (
        TENCENT_EASTMONEY_STOCK_RECONCILIATION.source_precision_policy
        == "karkinos.tencent_eastmoney.reported_amount"
    )
    store = ContentAddressedObjectStore(tmp_path / "objects")
    coarse = tencent._bar("100000", volume=Decimal("123500"))
    precise = replace(coarse, amount=Decimal(amount))
    raw_tx, _ = tencent._payloads()
    raw_tx["calls"][0]["frame"]["data"][0][-2] = int(coarse.volume)
    tx = tencent._publish(store, "akshare_tencent", raw_tx, coarse)
    raw_em = eastmoney_raw(precise)
    capture = capture_provider_payload(
        store,
        provider="akshare",
        operation="daily_bars",
        request=DailyBarRequest(
            (precise.instrument,), precise.session_date, precise.session_date
        ).to_capture_request(),
        raw_payload=json.dumps(raw_em).encode(),
        payload_format=raw_em["schema"],
        adapter_version="karkinos.akshare.daily_bar.v2",
        started_at=precise.captured_at,
        completed_at=precise.captured_at,
    )
    em = publish_daily_bar_revision(
        store, capture=capture, bars=(precise,), normalizer_version="fixture"
    )
    assert not tencent._reconcile(
        store, tx, em, policy=STRICT_DAILY_RECONCILIATION
    ).matched
    assert (
        tencent._reconcile(
            store, tx, em, policy=TENCENT_EASTMONEY_STOCK_RECONCILIATION
        ).matched
        is matched
    )
    tampered = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=(replace(precise, volume=precise.volume + 100),),
        normalizer_version="fixture",
    )
    with pytest.raises(ValueError, match="native_row_mismatch"):
        tencent._reconcile(
            store, tx, tampered, policy=TENCENT_EASTMONEY_STOCK_RECONCILIATION
        )
