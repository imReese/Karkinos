from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.citic_history_xls import (
    CITIC_HISTORY_XLS_COLUMNS,
    CITIC_HISTORY_XLS_MAX_BYTES,
    parse_citic_history_xls,
    recognized_non_financial_activity_count,
)


@dataclass
class _FakeSheet:
    rows: list[list[Any]]
    name: str = "\ufeff历史成交"

    @property
    def nrows(self) -> int:
        return len(self.rows)

    @property
    def ncols(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    def cell_value(self, row: int, column: int) -> Any:
        return self.rows[row][column]


@dataclass
class _FakeWorkbook:
    sheet: _FakeSheet
    datemode: int = 0
    released: bool = False

    def sheets(self) -> list[_FakeSheet]:
        return [self.sheet]

    def release_resources(self) -> None:
        self.released = True


def _install_workbook(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...] = CITIC_HISTORY_XLS_COLUMNS,
) -> None:
    header = [f"\ufeff{column}" for column in columns]
    values = [
        [
            f"\ufeff{row[column]}" if isinstance(row[column], str) else row[column]
            for column in columns
        ]
        for row in rows
    ]

    def open_workbook(**_: Any) -> _FakeWorkbook:
        return _FakeWorkbook(_FakeSheet([header, *values]))

    monkeypatch.setattr(
        "account_truth.citic_history_xls.xlrd.open_workbook",
        open_workbook,
    )


def _row(
    *,
    symbol: str = "600001",
    name: str = "合成样例股票A",
    occurred_date: str | int | float = "2026-05-05",
    trade_time: str = "09:35:00",
    settled_date: str | int | float = "2026-05-06",
    application_id: str = "APP-SYN-001",
    side: str = "买入",
    price: str = "10",
    quantity: int = 100,
    gross_amount: str = "1000",
    net_amount: str = "-1005",
    broker_order_id: str = "ORDER-SYN-001",
    business_name: str = "证券买入",
    exchange: str = "上海A股",
    note: str = "SENSITIVE_RAW_NOTE",
) -> dict[str, Any]:
    return {
        "证券代码": symbol,
        "证券名称": name,
        "发生日期": occurred_date,
        "成交时间": trade_time,
        "清算日期": settled_date,
        "申请编号": application_id,
        "买卖标志": side,
        "成交价格": price,
        "成交数量": quantity,
        "成交金额": gross_amount,
        "清算金额": net_amount,
        "委托编号": broker_order_id,
        "业务名称": business_name,
        "股东代码": "SENSITIVE_SHAREHOLDER_CODE",
        "资金账号": "SENSITIVE_FUND_ACCOUNT",
        "客户代码": "SENSITIVE_CUSTOMER_CODE",
        "股东姓名": "SENSITIVE_SHAREHOLDER_NAME",
        "交易所名称": exchange,
        "备注": note,
    }


def test_citic_history_xls_normalizes_reviewed_rows_without_private_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        _row(occurred_date=20260505, settled_date=20260506),
        _row(
            occurred_date="2026-05-07",
            trade_time="10:15:00",
            settled_date="2026-05-08",
            application_id="APP-SYN-002",
            side="卖出",
            price="12",
            quantity=100,
            gross_amount="1200",
            net_amount="1193",
            broker_order_id="ORDER-SYN-002",
            business_name="证券卖出",
        ),
        _row(
            occurred_date="2026-05-11",
            trade_time="15:00:00",
            settled_date="2026-05-11",
            application_id="APP-SYN-003",
            side="红利",
            price="0.5",
            quantity=0,
            gross_amount="50",
            net_amount="40",
            broker_order_id="",
            business_name="股息入账",
        ),
    ]
    _install_workbook(monkeypatch, rows)
    content = b"synthetic-citic-xls"

    preview = parse_citic_history_xls(content)

    assert preview.source_type == "citic_history_xls_preview"
    assert preview.file_fingerprint == hashlib.sha256(content).hexdigest()
    assert preview.row_count == 3
    assert preview.valid_row_count == 3
    assert preview.invalid_row_count == 0
    assert preview.validation_status == "blocked"
    assert [event.event_type for event in preview.events] == [
        "trade_buy",
        "trade_sell",
        "dividend",
    ]
    assert [event.row_number for event in preview.events] == [2, 3, 4]
    assert preview.events[0].quantity == Decimal("100")
    assert preview.events[0].gross_amount == Decimal("1000")
    assert preview.events[0].net_amount == Decimal("-1005")
    assert preview.events[0].broker_order_id == "ORDER-SYN-001"
    assert preview.events[0].client_order_id == ""
    assert preview.events[0].fee == Decimal("0")
    assert preview.events[0].tax == Decimal("0")
    assert preview.events[0].transfer_fee == Decimal("0")
    assert preview.events[0].occurred_at == "2026-05-05T09:35:00+08:00"
    assert preview.events[2].settled_at == "2026-05-11"
    assert {error.code for error in preview.errors} == {
        "citic_history_xls_settlement_components_missing"
    }

    rendered = repr(preview)
    for secret in (
        "SENSITIVE_SHAREHOLDER_CODE",
        "SENSITIVE_FUND_ACCOUNT",
        "SENSITIVE_CUSTOMER_CODE",
        "SENSITIVE_SHAREHOLDER_NAME",
        "SENSITIVE_RAW_NOTE",
    ):
        assert secret not in rendered


def test_citic_history_xls_event_identity_and_duplicates_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    _install_workbook(monkeypatch, [row, row])

    first = parse_citic_history_xls(b"same-file")
    second = parse_citic_history_xls(b"same-file")

    assert first.events[0].event_id == second.events[0].event_id
    assert first.events[0].row_fingerprint == second.events[0].row_fingerprint
    assert first.duplicate_row_count == 1
    assert first.events[1].is_duplicate is True
    assert first.events[1].duplicate_of_row_number == 2
    assert first.events[1].row_number == 3


def test_citic_history_xls_isolates_reviewed_non_financial_designation_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_workbook(
        monkeypatch,
        [
            _row(
                symbol="799999",
                name="指定交易",
                side="指定",
                price="0",
                quantity=0,
                gross_amount="0",
                net_amount="0",
                business_name="指定交易",
            )
        ],
    )

    preview = parse_citic_history_xls(b"synthetic-designation")

    assert preview.validation_status == "blocked"
    assert preview.valid_row_count == 0
    assert preview.invalid_row_count == 0
    assert recognized_non_financial_activity_count(preview) == 1
    assert preview.events == []
    assert [error.code for error in preview.errors] == [
        "citic_history_xls_non_financial_activity_ignored"
    ]


@pytest.mark.parametrize(
    "updates",
    [
        {"symbol": "799998"},
        {"name": "登记指定"},
        {"exchange": "深圳A股"},
        {"gross_amount": "1"},
        {"application_id": ""},
        {"broker_order_id": ""},
    ],
)
def test_citic_history_xls_blocks_designation_shape_drift(
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, Any],
) -> None:
    row: dict[str, Any] = {
        "symbol": "799999",
        "name": "指定交易",
        "side": "指定",
        "price": "0",
        "quantity": 0,
        "gross_amount": "0",
        "net_amount": "0",
        "business_name": "指定交易",
    }
    row.update(updates)
    _install_workbook(monkeypatch, [_row(**row)])

    preview = parse_citic_history_xls(b"synthetic-designation-shape-drift")

    assert preview.validation_status == "blocked"
    assert preview.valid_row_count == 0
    assert preview.invalid_row_count == 1
    assert recognized_non_financial_activity_count(preview) == 0
    assert preview.events == []
    assert preview.errors[0].code == (
        "citic_history_xls_invalid_non_financial_activity"
    )


def test_citic_history_xls_blocks_schema_drift_even_for_private_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns = tuple(
        column for column in CITIC_HISTORY_XLS_COLUMNS if column != "资金账号"
    )
    _install_workbook(monkeypatch, [_row()], columns=columns)

    preview = parse_citic_history_xls(b"synthetic-schema-drift")

    assert preview.validation_status == "blocked"
    assert preview.events == []
    assert preview.errors[0].code == "citic_history_xls_schema_drift"


@pytest.mark.parametrize(
    ("updates", "expected_code"),
    [
        ({"gross_amount": "999"}, "citic_history_xls_trade_amount_mismatch"),
        ({"net_amount": "1005"}, "citic_history_xls_invalid_buy_cash_sign"),
        ({"broker_order_id": ""}, "citic_history_xls_missing_broker_order_id"),
        ({"exchange": "未知市场"}, "citic_history_xls_unsupported_instrument"),
    ],
)
def test_citic_history_xls_blocks_ambiguous_trade_facts(
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, Any],
    expected_code: str,
) -> None:
    _install_workbook(monkeypatch, [_row(**updates)])

    preview = parse_citic_history_xls(b"synthetic-invalid-row")

    assert preview.validation_status == "blocked"
    assert preview.events == []
    assert preview.errors[0].code == expected_code


def test_citic_history_xls_rejects_corrupt_binary_without_exception() -> None:
    preview = parse_citic_history_xls(b"not-an-xls-workbook")

    assert preview.validation_status == "blocked"
    assert preview.row_count == 0
    assert preview.events == []
    assert preview.errors[0].code == "citic_history_xls_invalid_file"


def test_citic_history_xls_blocks_oversized_input_before_workbook_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_opened(**_: Any) -> None:
        raise AssertionError("oversized input must not reach xlrd")

    monkeypatch.setattr(
        "account_truth.citic_history_xls.xlrd.open_workbook",
        fail_if_opened,
    )

    preview = parse_citic_history_xls(b"x" * (CITIC_HISTORY_XLS_MAX_BYTES + 1))

    assert preview.validation_status == "blocked"
    assert preview.errors[0].code == "citic_history_xls_file_too_large"


def test_blocked_citic_history_preview_cannot_stage_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_workbook(monkeypatch, [_row()])
    preview = parse_citic_history_xls(b"synthetic-staging-boundary")
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")

    import_run = repository.save_preview(
        preview,
        source_name="synthetic-citic-history.xls",
    )

    assert import_run.validation_status == "blocked"
    assert repository.list_events(import_run.import_run_id) == []
