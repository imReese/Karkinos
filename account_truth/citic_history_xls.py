"""Fail-closed preview normalization for CITIC history-trade XLS exports.

The CITIC ``历史成交`` export contains useful transaction and net-settlement
facts, but it does not itemize commission, tax, or transfer fees and it does
not contain cash or position snapshots.  This adapter therefore emits a
read-only canonical preview while deliberately keeping the preview blocked
from evidence-event staging and every authority-bearing consumer.

Private account columns are required as part of the provider schema check but
are never copied into normalized rows, errors, notes, event identities, or row
fingerprints.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any
from zoneinfo import ZoneInfo

import xlrd
from xlrd.compdoc import CompDocError

from account_truth.broker_statement import (
    BROKER_STATEMENT_LIMITATIONS,
    BROKER_STATEMENT_OPTIONAL_COLUMNS,
    BROKER_STATEMENT_REQUIRED_COLUMNS,
    BROKER_STATEMENT_SCHEMA_VERSION,
    BrokerEvidenceEvent,
    BrokerStatementPreview,
    BrokerStatementValidationError,
    parse_broker_statement_csv,
)

CITIC_HISTORY_XLS_SOURCE_TYPE = "citic_history_xls_preview"
CITIC_HISTORY_XLS_MAX_BYTES = 10 * 1024 * 1024

CITIC_HISTORY_XLS_COLUMNS = (
    "证券代码",
    "证券名称",
    "发生日期",
    "成交时间",
    "清算日期",
    "申请编号",
    "买卖标志",
    "成交价格",
    "成交数量",
    "成交金额",
    "清算金额",
    "委托编号",
    "业务名称",
    "股东代码",
    "资金账号",
    "客户代码",
    "股东姓名",
    "交易所名称",
    "备注",
)

CITIC_HISTORY_XLS_PRIVATE_COLUMNS = frozenset(
    {"股东代码", "资金账号", "客户代码", "股东姓名"}
)

CITIC_HISTORY_XLS_LIMITATIONS = [
    *BROKER_STATEMENT_LIMITATIONS,
    (
        "CITIC history-trade XLS omits itemized commission, tax, and transfer "
        "fee evidence; zero component placeholders are preview-only and are "
        "not observed broker facts."
    ),
    (
        "CITIC history-trade XLS has no cash or position snapshots; separate "
        "cash-flow, settlement, and current account snapshots are required for "
        "Account Truth reconciliation."
    ),
    (
        "This provider preview is intentionally blocked from evidence-event "
        "staging, terminal clearance, ledger posting, execution, and capital "
        "authority."
    ),
    (
        "Reviewed designated-trading administration rows are counted as "
        "non-financial activity and never emitted as broker events; any shape "
        "drift remains invalid."
    ),
]

_EXPECTED_SHEET_NAME = "历史成交"
_EVENT_TYPE_BY_BUSINESS_AND_SIDE = {
    ("证券买入", "买入"): "trade_buy",
    ("证券卖出", "卖出"): "trade_sell",
    ("股息入账", "红利"): "dividend",
}
_NON_FINANCIAL_ACTIVITY_CODE = "citic_history_xls_non_financial_activity_ignored"
_REVIEWED_DESIGNATED_TRADING_SHAPE = {
    "business_name": "指定交易",
    "side": "指定",
    "symbol": "799999",
    "instrument_name": "指定交易",
    "exchange": "上海A股",
}
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_SHANGHAI_STOCK_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SHENZHEN_STOCK_PREFIXES = ("000", "001", "002", "003", "300", "301")
_BEIJING_STOCK_PREFIXES = ("4", "8", "9")
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MONEY_TOLERANCE = Decimal("0.005")


class _CiticRowError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_citic_history_xls(content: bytes) -> BrokerStatementPreview:
    """Normalize one CITIC ``历史成交`` BIFF XLS into a blocked preview.

    The returned events expose only the facts that this export actually
    contains.  Because settlement components and account snapshots are absent,
    a structurally valid file still returns ``validation_status='blocked'``.
    ``BrokerEvidenceRepository`` consequently cannot stage these events.
    """

    if not isinstance(content, bytes):
        raise TypeError("CITIC XLS content must be bytes")
    file_fingerprint = hashlib.sha256(content).hexdigest()
    if not content:
        return _blocked_preview(
            file_fingerprint=file_fingerprint,
            code="citic_history_xls_empty_file",
            message="CITIC history-trade XLS is empty.",
        )
    if len(content) > CITIC_HISTORY_XLS_MAX_BYTES:
        return _blocked_preview(
            file_fingerprint=file_fingerprint,
            code="citic_history_xls_file_too_large",
            message="CITIC history-trade XLS exceeds the local preview limit.",
        )

    try:
        workbook = xlrd.open_workbook(
            file_contents=content,
            on_demand=True,
        )
    except (CompDocError, OSError, ValueError, struct.error, xlrd.XLRDError):
        return _blocked_preview(
            file_fingerprint=file_fingerprint,
            code="citic_history_xls_invalid_file",
            message="The file is not a readable legacy XLS workbook.",
        )

    try:
        sheets = workbook.sheets()
        if len(sheets) != 1 or _clean_text(sheets[0].name) != _EXPECTED_SHEET_NAME:
            return _blocked_preview(
                file_fingerprint=file_fingerprint,
                code="citic_history_xls_sheet_mismatch",
                message="Expected exactly one CITIC history-trade worksheet.",
            )

        sheet = sheets[0]
        if sheet.nrows < 1:
            return _blocked_preview(
                file_fingerprint=file_fingerprint,
                code="citic_history_xls_missing_header",
                message="CITIC history-trade XLS has no header row.",
            )
        columns = tuple(
            _clean_text(sheet.cell_value(0, column_index))
            for column_index in range(sheet.ncols)
        )
        if len(columns) != len(set(columns)) or set(columns) != set(
            CITIC_HISTORY_XLS_COLUMNS
        ):
            return _blocked_preview(
                file_fingerprint=file_fingerprint,
                code="citic_history_xls_schema_drift",
                message="CITIC history-trade XLS columns do not match the reviewed schema.",
                normalized_columns=columns,
                row_count=max(0, sheet.nrows - 1),
            )
        raw_rows = [
            {
                column: sheet.cell_value(row_number - 1, column_index)
                for column_index, column in enumerate(columns)
                if column not in CITIC_HISTORY_XLS_PRIVATE_COLUMNS
            }
            for row_number in range(2, sheet.nrows + 1)
        ]
        datemode = int(workbook.datemode)
    except (
        CompDocError,
        IndexError,
        TypeError,
        UnicodeError,
        ValueError,
        struct.error,
        xlrd.XLRDError,
    ):
        return _blocked_preview(
            file_fingerprint=file_fingerprint,
            code="citic_history_xls_read_failed",
            message="CITIC history-trade XLS could not be read deterministically.",
        )
    finally:
        workbook.release_resources()

    if not raw_rows:
        return _blocked_preview(
            file_fingerprint=file_fingerprint,
            code="citic_history_xls_no_rows",
            message="CITIC history-trade XLS contains no rows to preview.",
            normalized_columns=columns,
        )

    canonical_rows: list[dict[str, str]] = []
    source_row_by_canonical_row: dict[int, int] = {}
    provider_errors: list[BrokerStatementValidationError] = []
    recognized_non_financial_count = 0
    for source_row_number, raw_row in enumerate(raw_rows, start=2):
        try:
            if _is_reviewed_non_financial_activity(raw_row, datemode=datemode):
                recognized_non_financial_count += 1
                provider_errors.append(
                    BrokerStatementValidationError(
                        row_number=source_row_number,
                        code=_NON_FINANCIAL_ACTIVITY_CODE,
                        message=(
                            "Reviewed designated-trading administration activity "
                            "was isolated without creating a broker event."
                        ),
                    )
                )
                continue
            canonical_row = _canonical_row(raw_row, datemode=datemode)
        except _CiticRowError as exc:
            provider_errors.append(
                BrokerStatementValidationError(
                    row_number=source_row_number,
                    code=exc.code,
                    message=exc.message,
                )
            )
            continue
        canonical_rows.append(canonical_row)
        source_row_by_canonical_row[len(canonical_rows) + 1] = source_row_number

    canonical_preview = parse_broker_statement_csv(
        _canonical_csv(canonical_rows),
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
    )
    events = [
        _source_numbered_event(event, source_row_by_canonical_row)
        for event in canonical_preview.events
    ]
    canonical_errors = [
        replace(
            error,
            row_number=(
                source_row_by_canonical_row.get(error.row_number, error.row_number)
                if error.row_number is not None
                else None
            ),
        )
        for error in canonical_preview.errors
    ]
    errors = [*provider_errors, *canonical_errors]
    if events:
        errors.append(
            BrokerStatementValidationError(
                row_number=None,
                code="citic_history_xls_settlement_components_missing",
                message=(
                    "History-trade XLS does not itemize commission, tax, and "
                    "transfer fee; provide settlement or cash-flow evidence."
                ),
            )
        )
    elif not errors:
        errors.append(
            BrokerStatementValidationError(
                row_number=None,
                code="citic_history_xls_no_supported_events",
                message="CITIC history-trade XLS has no supported financial events.",
            )
        )

    return replace(
        canonical_preview,
        schema_version=BROKER_STATEMENT_SCHEMA_VERSION,
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        file_fingerprint=file_fingerprint,
        normalized_columns=columns,
        row_count=len(raw_rows),
        valid_row_count=len(events),
        invalid_row_count=(
            len(raw_rows) - len(events) - recognized_non_financial_count
        ),
        validation_status="blocked",
        limitations=list(CITIC_HISTORY_XLS_LIMITATIONS),
        events=events,
        errors=errors,
    )


def recognized_non_financial_activity_count(
    preview: BrokerStatementPreview,
) -> int:
    """Return a fail-closed count for reviewed non-financial provider rows."""

    count_from_rows = (
        preview.row_count - preview.valid_row_count - preview.invalid_row_count
    )
    count_from_errors = sum(
        1 for error in preview.errors if error.code == _NON_FINANCIAL_ACTIVITY_CODE
    )
    if count_from_rows <= 0 or count_from_rows != count_from_errors:
        return 0
    return count_from_rows


def _is_reviewed_non_financial_activity(
    raw_row: dict[str, Any],
    *,
    datemode: int,
) -> bool:
    business_name = _clean_text(raw_row["业务名称"])
    side = _clean_text(raw_row["买卖标志"])
    if (business_name, side) != (
        _REVIEWED_DESIGNATED_TRADING_SHAPE["business_name"],
        _REVIEWED_DESIGNATED_TRADING_SHAPE["side"],
    ):
        return False

    symbol = _symbol(raw_row["证券代码"])
    instrument_name = _required_text(raw_row["证券名称"], "instrument name")
    exchange = _required_text(raw_row["交易所名称"], "exchange")
    occurred_date = _xls_date(raw_row["发生日期"], datemode=datemode)
    _xls_time(raw_row["成交时间"])
    settled_date = _xls_date(raw_row["清算日期"], datemode=datemode)
    if settled_date < occurred_date:
        raise _CiticRowError(
            "citic_history_xls_invalid_settlement_date",
            "Settlement date precedes occurrence date.",
        )
    application_id = _identity(raw_row["申请编号"])
    broker_order_id = _identity(raw_row["委托编号"])
    financial_values = (
        _decimal(raw_row["成交价格"], "price"),
        _decimal(raw_row["成交数量"], "quantity"),
        _decimal(raw_row["成交金额"], "gross amount"),
        _decimal(raw_row["清算金额"], "net settlement amount"),
    )
    if (
        symbol != _REVIEWED_DESIGNATED_TRADING_SHAPE["symbol"]
        or instrument_name != _REVIEWED_DESIGNATED_TRADING_SHAPE["instrument_name"]
        or exchange != _REVIEWED_DESIGNATED_TRADING_SHAPE["exchange"]
        or not application_id
        or not broker_order_id
        or any(value != 0 for value in financial_values)
    ):
        raise _CiticRowError(
            "citic_history_xls_invalid_non_financial_activity",
            (
                "Designated-trading activity does not match the reviewed "
                "non-financial provider shape."
            ),
        )
    return True


def _canonical_row(raw_row: dict[str, Any], *, datemode: int) -> dict[str, str]:
    business_name = _clean_text(raw_row["业务名称"])
    side = _clean_text(raw_row["买卖标志"])
    event_type = _EVENT_TYPE_BY_BUSINESS_AND_SIDE.get((business_name, side))
    if event_type is None:
        raise _CiticRowError(
            "citic_history_xls_unsupported_event",
            "The row is not a reviewed CITIC buy, sell, or dividend event.",
        )

    symbol = _symbol(raw_row["证券代码"])
    instrument_name = _required_text(raw_row["证券名称"], "instrument name")
    exchange = _required_text(raw_row["交易所名称"], "exchange")
    asset_class = _asset_class(symbol=symbol, exchange=exchange)
    occurred_date = _xls_date(raw_row["发生日期"], datemode=datemode)
    occurred_time = _xls_time(raw_row["成交时间"])
    settled_date = _xls_date(raw_row["清算日期"], datemode=datemode)
    if settled_date < occurred_date:
        raise _CiticRowError(
            "citic_history_xls_invalid_settlement_date",
            "Settlement date precedes occurrence date.",
        )

    quantity = _decimal(raw_row["成交数量"], "quantity")
    price = _decimal(raw_row["成交价格"], "price")
    gross_amount = _decimal(raw_row["成交金额"], "gross amount")
    net_amount = _decimal(raw_row["清算金额"], "net settlement amount")
    _validate_financial_shape(
        event_type=event_type,
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        net_amount=net_amount,
    )

    broker_order_id = _identity(raw_row["委托编号"])
    if event_type in {"trade_buy", "trade_sell"} and not broker_order_id:
        raise _CiticRowError(
            "citic_history_xls_missing_broker_order_id",
            "A CITIC trade row must include a broker order identity.",
        )
    application_id = _identity(raw_row["申请编号"])
    occurred_at = datetime.combine(
        occurred_date,
        occurred_time,
        tzinfo=_SHANGHAI_TZ,
    ).isoformat(timespec="seconds")
    decimal_values = {
        "quantity": _decimal_text(quantity),
        "price": _decimal_text(price),
        "gross_amount": _decimal_text(gross_amount),
        "net_amount": _decimal_text(net_amount),
    }
    event_id = _event_id(
        event_type=event_type,
        occurred_at=occurred_at,
        settled_at=settled_date.isoformat(),
        symbol=symbol,
        application_id=application_id,
        broker_order_id=broker_order_id,
        **decimal_values,
    )
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "settled_at": settled_date.isoformat(),
        "symbol": symbol,
        "instrument_name": instrument_name,
        "asset_class": asset_class,
        "currency": "CNY",
        "quantity": decimal_values["quantity"],
        "price": decimal_values["price"],
        "gross_amount": decimal_values["gross_amount"],
        "fee": "0",
        "tax": "0",
        "net_amount": decimal_values["net_amount"],
        "cash_balance": "",
        "position_quantity": "",
        "cost_basis": "",
        "note": (
            f"CITIC {business_name} history preview; settlement components "
            "require separate evidence"
        ),
        "transfer_fee": "0",
        "cost_basis_method": "",
        "broker_order_id": broker_order_id,
        "client_order_id": "",
    }


def _validate_financial_shape(
    *,
    event_type: str,
    quantity: Decimal,
    price: Decimal,
    gross_amount: Decimal,
    net_amount: Decimal,
) -> None:
    if event_type in {"trade_buy", "trade_sell"}:
        if quantity <= 0 or price <= 0 or gross_amount <= 0:
            raise _CiticRowError(
                "citic_history_xls_invalid_trade_amount",
                "Trade quantity, price, and gross amount must be positive.",
            )
        if abs(quantity * price - gross_amount) > _MONEY_TOLERANCE:
            raise _CiticRowError(
                "citic_history_xls_trade_amount_mismatch",
                "Trade gross amount does not reconcile with quantity times price.",
            )
        if event_type == "trade_buy" and net_amount >= 0:
            raise _CiticRowError(
                "citic_history_xls_invalid_buy_cash_sign",
                "Buy settlement cash impact must be negative.",
            )
        if event_type == "trade_sell" and net_amount <= 0:
            raise _CiticRowError(
                "citic_history_xls_invalid_sell_cash_sign",
                "Sell settlement cash impact must be positive.",
            )
        return
    if quantity < 0 or price < 0 or gross_amount <= 0 or net_amount <= 0:
        raise _CiticRowError(
            "citic_history_xls_invalid_dividend_amount",
            "Dividend evidence must have non-negative quantity/price and positive amounts.",
        )


def _asset_class(*, symbol: str, exchange: str) -> str:
    if exchange == "上海A股" and symbol.startswith(_SHANGHAI_STOCK_PREFIXES):
        return "stock"
    if exchange == "深圳A股" and symbol.startswith(_SHENZHEN_STOCK_PREFIXES):
        return "stock"
    if exchange == "北京A股" and symbol.startswith(_BEIJING_STOCK_PREFIXES):
        return "stock"
    raise _CiticRowError(
        "citic_history_xls_unsupported_instrument",
        "The security code and exchange are outside the reviewed A-share scope.",
    )


def _symbol(value: Any) -> str:
    text = _clean_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit() and len(text) < 6:
        text = text.zfill(6)
    if len(text) != 6 or not text.isdigit():
        raise _CiticRowError(
            "citic_history_xls_invalid_symbol",
            "Security code must normalize to exactly six digits.",
        )
    return text


def _identity(value: Any) -> str:
    text = _clean_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text and not _IDENTITY_PATTERN.fullmatch(text):
        raise _CiticRowError(
            "citic_history_xls_invalid_identity",
            "Broker identity contains unsupported characters or length.",
        )
    return text


def _xls_date(value: Any, *, datemode: int) -> date:
    if isinstance(value, bool):
        raise _invalid_date()
    if isinstance(value, (int, float)):
        numeric_text = _clean_text(value)
        if numeric_text.isdigit() and len(numeric_text) == 8:
            try:
                return datetime.strptime(numeric_text, "%Y%m%d").date()
            except ValueError:
                raise _invalid_date() from None
        try:
            return xlrd.xldate_as_datetime(value, datemode).date()
        except (OverflowError, TypeError, ValueError, xlrd.XLDateError):
            raise _invalid_date() from None
    text = _clean_text(value)
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise _invalid_date()


def _invalid_date() -> _CiticRowError:
    return _CiticRowError(
        "citic_history_xls_invalid_date",
        "Occurrence and settlement dates must be valid unambiguous dates.",
    )


def _xls_time(value: Any) -> time:
    if isinstance(value, bool):
        raise _invalid_time()
    if isinstance(value, (int, float)):
        if value < 0 or value >= 1:
            raise _invalid_time()
        total_seconds = int(round(float(value) * 86400))
        if total_seconds >= 86400:
            raise _invalid_time()
        return time(
            hour=total_seconds // 3600,
            minute=(total_seconds % 3600) // 60,
            second=total_seconds % 60,
        )
    text = _clean_text(value)
    for pattern in ("%H:%M:%S", "%H%M%S"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    raise _invalid_time()


def _invalid_time() -> _CiticRowError:
    return _CiticRowError(
        "citic_history_xls_invalid_time",
        "Trade time must be a valid HH:MM:SS value.",
    )


def _decimal(value: Any, field_name: str) -> Decimal:
    text = _clean_text(value)
    if not _DECIMAL_PATTERN.fullmatch(text):
        raise _CiticRowError(
            "citic_history_xls_invalid_decimal",
            f"CITIC {field_name} must be an unambiguous decimal.",
        )
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise _CiticRowError(
            "citic_history_xls_invalid_decimal",
            f"CITIC {field_name} must be an unambiguous decimal.",
        ) from None
    if not result.is_finite():
        raise _CiticRowError(
            "citic_history_xls_invalid_decimal",
            f"CITIC {field_name} must be finite.",
        )
    return result


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _required_text(value: Any, field_name: str) -> str:
    text = _clean_text(value)
    if not text:
        raise _CiticRowError(
            "citic_history_xls_missing_text",
            f"CITIC {field_name} is required.",
        )
    return text


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\ufeff", "").strip()


def _event_id(**identity: str) -> str:
    payload = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"citic-{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _canonical_csv(rows: list[dict[str, str]]) -> str:
    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            *BROKER_STATEMENT_REQUIRED_COLUMNS,
            *BROKER_STATEMENT_OPTIONAL_COLUMNS,
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _source_numbered_event(
    event: BrokerEvidenceEvent,
    source_row_by_canonical_row: dict[int, int],
) -> BrokerEvidenceEvent:
    return replace(
        event,
        row_number=source_row_by_canonical_row[event.row_number],
        duplicate_of_row_number=(
            source_row_by_canonical_row.get(event.duplicate_of_row_number)
            if event.duplicate_of_row_number is not None
            else None
        ),
    )


def _blocked_preview(
    *,
    file_fingerprint: str,
    code: str,
    message: str,
    normalized_columns: tuple[str, ...] = (),
    row_count: int = 0,
) -> BrokerStatementPreview:
    return BrokerStatementPreview(
        schema_version=BROKER_STATEMENT_SCHEMA_VERSION,
        source_type=CITIC_HISTORY_XLS_SOURCE_TYPE,
        generated_at=datetime.now(UTC).isoformat(),
        file_fingerprint=file_fingerprint,
        normalized_columns=normalized_columns,
        row_count=row_count,
        valid_row_count=0,
        invalid_row_count=row_count,
        duplicate_row_count=0,
        validation_status="blocked",
        limitations=list(CITIC_HISTORY_XLS_LIMITATIONS),
        events=[],
        errors=[
            BrokerStatementValidationError(
                row_number=None,
                code=code,
                message=message,
            )
        ],
    )
