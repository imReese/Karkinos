from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.providers.baostock_daily import (
    BAOSTOCK_DAILY_BAR_DESCRIPTOR,
    BaoStockDailyBarError,
    BaoStockDailyBarProvider,
    BaoStockDailyBarRequestError,
    BaoStockDailyBarResponseError,
)

DAY = date(2026, 9, 17)
AFTER_CLOSE = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(
        self,
        rows: list[list[str]],
        *,
        error_code: str = "0",
        fields: list[str] | None = None,
    ) -> None:
        self.error_code = error_code
        self.error_msg = "success" if error_code == "0" else "fixture error"
        self.fields = fields or [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adjustflag",
            "tradestatus",
        ]
        self._rows = rows
        self._index = -1

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._index]


class FakeBaoStock:
    __version__ = "00.9.30"

    def __init__(self) -> None:
        self.login_calls = 0
        self.logout_calls = 0
        self.query_calls: list[dict[str, object]] = []
        self.results: dict[str, FakeResult] = {}

    def login(self, user_id="anonymous", password="123456"):
        self.login_calls += 1
        print("login success!")
        return SimpleNamespace(error_code="0", error_msg="success")

    def logout(self, user_id="anonymous"):
        self.logout_calls += 1
        print("logout success!")
        return SimpleNamespace(error_code="0", error_msg="success")

    def query_history_k_data_plus(
        self,
        code,
        fields,
        start_date=None,
        end_date=None,
        frequency="d",
        adjustflag="3",
    ):
        self.query_calls.append(
            {
                "code": code,
                "fields": fields,
                "start_date": start_date,
                "end_date": end_date,
                "frequency": frequency,
                "adjustflag": adjustflag,
            }
        )
        return self.results.get(code, FakeResult([]))


def _row(
    code: str,
    *,
    close: str = "9.0600",
    volume: str = "45671103",
    amount: str = "414887057.3900",
    adjustflag: str = "3",
    tradestatus: str = "1",
) -> list[str]:
    return [
        DAY.isoformat(),
        code,
        "9.1000",
        "9.1400",
        "9.0300",
        close,
        volume,
        amount,
        adjustflag,
        tradestatus,
    ]


def _request(*items: InstrumentKey) -> DailyBarRequest:
    return DailyBarRequest(tuple(items), DAY, DAY)


def test_baostock_provider_satisfies_canonical_protocol() -> None:
    provider = BaoStockDailyBarProvider(FakeBaoStock(), clock=lambda: AFTER_CLOSE)
    assert isinstance(provider, DailyBarProvider)
    assert provider.descriptor == BAOSTOCK_DAILY_BAR_DESCRIPTOR
    assert provider.descriptor.provider == "baostock"
    assert provider.descriptor.upstream_group == "baostock"
    assert provider.descriptor.supports_daily_bars(
        InstrumentType.STOCK, price_basis="unadjusted"
    )
    assert provider.descriptor.supports_daily_bars(
        InstrumentType.ETF, price_basis="unadjusted"
    )


def test_baostock_fetches_stock_and_etf_as_unadjusted_daily_bars(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeBaoStock()
    client.results["sh.510300"] = FakeResult(
        [
            _row(
                "sh.510300",
                close="4.5320",
                volume="507546102",
                amount="2304178588.0000",
            )
        ]
    )
    client.results["sh.600000"] = FakeResult([_row("sh.600000")])

    result = BaoStockDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(
        _request(
            InstrumentKey("600000", InstrumentType.STOCK),
            InstrumentKey("510300", InstrumentType.ETF),
        )
    )

    assert client.login_calls == 1
    assert client.logout_calls == 1
    assert capsys.readouterr().out == ""
    assert [call["code"] for call in client.query_calls] == ["sh.510300", "sh.600000"]
    for call in client.query_calls:
        assert call["frequency"] == "d"
        assert call["adjustflag"] == "3"
        assert call["start_date"] == DAY.isoformat()
        assert call["end_date"] == DAY.isoformat()

    assert [row.instrument for row in result.rows] == [
        InstrumentKey("510300", InstrumentType.ETF),
        InstrumentKey("600000", InstrumentType.STOCK),
    ]
    etf, stock = result.rows
    assert etf.close_value == Decimal("4.5320")
    assert etf.volume == Decimal("507546102")
    assert etf.amount == Decimal("2304178588.0000")
    assert stock.volume == Decimal("45671103")
    assert stock.amount == Decimal("414887057.3900")
    assert all(row.available_at is None for row in result.rows)
    assert all(
        row.event_time == datetime(2026, 9, 17, 7, 0, tzinfo=timezone.utc)
        for row in result.rows
    )


def test_baostock_preserves_stable_sdk_rows_as_raw_evidence() -> None:
    client = FakeBaoStock()
    client.results["sh.600000"] = FakeResult([_row("sh.600000")])

    result = BaoStockDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))

    payload = json.loads(result.raw_payload)
    assert payload["schema"] == "baostock.history_k_data_plus.rows.v1"
    assert payload["request"]["adjustflag"] == "3"
    assert payload["request"]["frequency"] == "d"
    assert payload["calls"][0]["code"] == "sh.600000"
    assert payload["calls"][0]["rows"] == [_row("sh.600000")]


def test_baostock_explicit_trading_status_maps_to_suspended() -> None:
    client = FakeBaoStock()
    client.results["sh.600000"] = FakeResult(
        [
            _row(
                "sh.600000",
                volume="0",
                amount="0",
                tradestatus="0",
            )
        ]
    )

    result = BaoStockDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))

    assert result.rows[0].suspended is True
    assert result.rows[0].volume == Decimal("0")
    assert result.rows[0].amount == Decimal("0")


def test_baostock_empty_success_is_preserved_as_empty_batch() -> None:
    client = FakeBaoStock()
    result = BaoStockDailyBarProvider(
        client, clock=lambda: AFTER_CLOSE
    ).fetch_daily_bars(_request(InstrumentKey("600000", InstrumentType.STOCK)))
    assert result.rows == ()
    assert result.record_count == 0
    assert client.logout_calls == 1


def test_baostock_rejects_session_before_close_without_login() -> None:
    client = FakeBaoStock()
    provider = BaoStockDailyBarProvider(
        client,
        clock=lambda: datetime(2026, 9, 17, 6, 59, tzinfo=timezone.utc),
    )
    with pytest.raises(
        BaoStockDailyBarRequestError, match="baostock_daily_bar_session_not_closed"
    ):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )
    assert client.login_calls == 0


def test_baostock_rejects_beijing_exchange_until_provider_supports_it() -> None:
    client = FakeBaoStock()
    with pytest.raises(
        BaoStockDailyBarRequestError, match="baostock_beijing_exchange_unsupported"
    ):
        BaoStockDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
            _request(InstrumentKey("920001", InstrumentType.STOCK))
        )
    assert client.login_calls == 0


def test_baostock_query_failure_still_logs_out() -> None:
    client = FakeBaoStock()
    client.results["sh.600000"] = FakeResult([], error_code="100")
    provider = BaoStockDailyBarProvider(client, clock=lambda: AFTER_CLOSE)

    with pytest.raises(BaoStockDailyBarError, match="baostock_history_query_rejected"):
        provider.fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )

    assert client.login_calls == 1
    assert client.logout_calls == 1


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda row: row.__setitem__(1, "sz.000001"),
            "baostock_response_code_mismatch",
        ),
        (
            lambda row: row.__setitem__(8, "2"),
            "baostock_response_adjustflag_invalid",
        ),
        (
            lambda row: row.__setitem__(9, "unknown"),
            "baostock_response_tradestatus_invalid",
        ),
        (
            lambda row: row.__setitem__(5, "nan"),
            "baostock_response_number_invalid:close",
        ),
    ],
)
def test_baostock_rejects_ambiguous_or_invalid_rows(mutator, code) -> None:
    client = FakeBaoStock()
    row = _row("sh.600000")
    mutator(row)
    client.results["sh.600000"] = FakeResult([row])

    with pytest.raises(BaoStockDailyBarResponseError, match=code):
        BaoStockDailyBarProvider(client, clock=lambda: AFTER_CLOSE).fetch_daily_bars(
            _request(InstrumentKey("600000", InstrumentType.STOCK))
        )
    assert client.logout_calls == 1
