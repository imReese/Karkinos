"""DataFrame and native records share exact provider row semantics."""

from copy import deepcopy
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.providers import tencent, tushare
from tests.data.market.test_tencent_tushare_reported_amount import _payloads


def _outcome(call):
    try:
        return "rows", call()
    except (
        tencent.AkshareTencentDailyBarResponseError,
        tushare.TushareDailyBarResponseError,
        ValueError,
        TypeError,
        ArithmeticError,
    ) as exc:
        return type(exc).__name__, str(exc)


@pytest.mark.parametrize("provider", ["tencent", "tushare"])
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "nan",
        "infinity",
        "decimal_nan",
        "none",
        "bool",
        "missing_column",
        "duplicate_column",
        "duplicate_ignored_column",
        "empty_rows",
        "empty_columns",
        "out_of_order",
        "duplicate_date",
        "later_invalid_before_duplicate_check",
        "outside_window",
        "integer_date",
        "float_date",
    ],
)
def test_record_adapter_retains_frame_values_errors_and_order(provider, case):
    adapter = tencent if provider == "tencent" else tushare
    payload = _payloads()[provider == "tushare"]
    columns = payload["calls"][0]["frame"]["columns"]
    values = deepcopy(payload["calls"][0]["frame"]["data"][0])
    date_column = "date" if provider == "tencent" else "trade_date"
    rows = [values]
    kwargs = {
        "instrument": InstrumentKey("600096", InstrumentType.STOCK),
        "expected_session": date(2022, 3, 11),
        "expected_end": date(2022, 3, 12),
    }
    if provider == "tencent":
        kwargs.update(
            sdk_version="1.18.97",
            adapter_version="karkinos.akshare_tencent.daily_bar.v4",
        )
    else:
        kwargs["endpoint"] = "daily"
    bad = {
        "nan": float("nan"),
        "infinity": float("inf"),
        "decimal_nan": Decimal("NaN"),
        "none": None,
        "bool": True,
    }
    if case in bad:
        values[columns.index("open")] = bad[case]
    elif case in {
        "out_of_order",
        "duplicate_date",
        "later_invalid_before_duplicate_check",
    }:
        second = deepcopy(values)
        if case == "out_of_order":
            second[columns.index(date_column)] = (
                "2022-03-12" if provider == "tencent" else "20220312"
            )
            rows = [second, values]
        else:
            rows.append(second)
            if case == "later_invalid_before_duplicate_check":
                third = deepcopy(values)
                third[columns.index("close")] = float("nan")
                rows.append(third)
    elif case == "outside_window":
        values[columns.index(date_column)] = (
            "2022-03-10" if provider == "tencent" else "20220310"
        )
    elif case in {"integer_date", "float_date"}:
        values[columns.index(date_column)] = (
            20220311 if case == "integer_date" else 20220311.0
        )
    frame = pd.DataFrame(rows, columns=columns, dtype=object)
    if case == "missing_column":
        frame = frame.drop(columns="open")
    elif case == "duplicate_column":
        frame = pd.concat([frame, frame[["open"]]], axis=1)
    elif case == "duplicate_ignored_column":
        ignored = pd.DataFrame({"ignored": [1]})
        frame = pd.concat([frame, ignored, ignored], axis=1)
    elif case == "empty_rows":
        frame = pd.DataFrame()
    elif case == "empty_columns":
        frame = pd.DataFrame([[]])
    records = tuple(
        {column: row[column] for column in frame.columns} for _, row in frame.iterrows()
    )
    actual = _outcome(
        lambda: adapter._rows_from_records(
            records, columns=tuple(frame.columns), **kwargs
        )
    )
    assert actual == _outcome(lambda: adapter._rows_from_frame(frame, **kwargs))
    if case == "out_of_order":
        assert [row.session_date for row in actual[1]] == [
            date(2022, 3, 12),
            date(2022, 3, 11),
        ]
    elif case == "later_invalid_before_duplicate_check":
        assert actual[1].endswith("number_invalid:close")
    elif case in {"valid", "duplicate_ignored_column"}:
        assert actual[0] == "rows" and len(actual[1]) == 1


@pytest.mark.parametrize("version,scale", [("v4", "1"), ("v5", "0.01")])
def test_records_keep_reviewed_689_sdk_float_units(version, scale):
    columns = ("date", "open", "high", "low", "close", "volume", "amount")
    record = dict(
        zip(columns, ["2022-03-11", 10, 11, 9, 10, 33359009.000000004, 100000])
    )
    key = InstrumentKey("689001", InstrumentType.STOCK)
    kwargs = {
        "instrument": key,
        "expected_session": date(2022, 3, 11),
        "sdk_version": "1.18.97",
        "adapter_version": "karkinos.akshare_tencent.daily_bar." + version,
        "volume_scale": tencent._sdk_volume_scale(
            key,
            "1.18.97",
            adapter_version="karkinos.akshare_tencent.daily_bar." + version,
        ),
    }
    rows = tencent._rows_from_records((record,), columns=columns, **kwargs)
    assert rows == tencent._rows_from_frame(
        pd.DataFrame([record], dtype=object), **kwargs
    )
    assert kwargs["volume_scale"] == Decimal(scale)
    assert rows[0].volume == Decimal("33359009") * Decimal(scale)
