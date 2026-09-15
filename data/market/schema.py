"""Market Data 的 Arrow Schema 与序列化边界。

本模块只负责 canonical market model 与 Arrow Table 之间的确定性转换。
不负责 Provider 访问、数据修复、排序、去重、质量判断或持久化。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation, localcontext

import pyarrow as pa

from core.types import InstrumentKey
from data.market.model import DailyBarObservation

DAILY_BAR_SCHEMA_VERSION = "karkinos.market.daily_bar.v1"

# Canonical Market Data 使用十进制定点数保存价格和成交数据。
# scale=8 足以覆盖当前中国市场日线数据，同时避免 float 带来的二进制误差。
_DECIMAL_SCALE = 8
_DECIMAL_QUANTUM = Decimal("0.00000001")
_MARKET_DECIMAL = pa.decimal128(38, _DECIMAL_SCALE)


DAILY_BAR_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("instrument_type", pa.string(), nullable=False),
        pa.field("session_date", pa.date32(), nullable=False),
        pa.field(
            "event_time",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
        pa.field(
            "available_at",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
        pa.field(
            "captured_at",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
        pa.field("open", _MARKET_DECIMAL, nullable=False),
        pa.field("high", _MARKET_DECIMAL, nullable=False),
        pa.field("low", _MARKET_DECIMAL, nullable=False),
        pa.field("close", _MARKET_DECIMAL, nullable=False),
        pa.field("volume", _MARKET_DECIMAL, nullable=False),
        pa.field("amount", _MARKET_DECIMAL, nullable=False),
        pa.field("suspended", pa.bool_(), nullable=False),
    ],
    metadata={
        b"karkinos.schema_version": DAILY_BAR_SCHEMA_VERSION.encode(),
    },
)


def daily_bars_to_table(
    bars: Sequence[DailyBarObservation],
) -> pa.Table:
    """将 canonical 日线记录转换为固定 Arrow Table。

    本函数保留调用方传入的行顺序。行排序属于 Market Data 规范化语义，
    不能由物理存储层擅自决定。
    """
    rows = [_daily_bar_to_row(bar) for bar in bars]

    try:
        table = pa.Table.from_pylist(
            rows,
            schema=DAILY_BAR_SCHEMA,
        )
    except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError) as exc:
        raise ValueError("daily_bar_arrow_conversion_failed") from exc

    table = table.combine_chunks()
    validate_daily_bar_table(table)

    return table


def daily_bars_from_table(
    table: pa.Table,
) -> tuple[DailyBarObservation, ...]:
    """从 canonical Arrow Table 恢复日线值对象。"""
    validate_daily_bar_table(table)

    bars: list[DailyBarObservation] = []

    for row in table.to_pylist():
        bars.append(
            DailyBarObservation(
                instrument=InstrumentKey.from_values(
                    row["symbol"],
                    row["instrument_type"],
                ),
                session_date=row["session_date"],
                event_time=row["event_time"],
                available_at=row["available_at"],
                captured_at=row["captured_at"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                amount=row["amount"],
                suspended=row["suspended"],
            )
        )

    return tuple(bars)


def validate_daily_bar_table(
    table: pa.Table,
) -> None:
    """验证 Arrow Table 是否严格符合 canonical 日线 Schema。"""
    if not isinstance(table, pa.Table):
        raise TypeError("daily_bar_table_must_be_arrow_table")

    if not table.schema.equals(
        DAILY_BAR_SCHEMA,
        check_metadata=True,
    ):
        raise ValueError("daily_bar_table_schema_mismatch")

    try:
        table.validate(full=True)
    except pa.ArrowInvalid as exc:
        raise ValueError("daily_bar_table_invalid") from exc

    # Arrow 的字段虽然声明 nullable=False，但仍显式检查 null，
    # 避免来自外部构造或损坏数据的空值进入 canonical data plane。
    for column_name in DAILY_BAR_SCHEMA.names:
        if table[column_name].null_count:
            raise ValueError(f"daily_bar_table_null_value:{column_name}")


def _daily_bar_to_row(
    bar: DailyBarObservation,
) -> dict[str, object]:
    if not isinstance(bar, DailyBarObservation):
        raise TypeError("daily_bar_sequence_contains_invalid_value")

    return {
        "symbol": bar.instrument.symbol,
        "instrument_type": bar.instrument.instrument_type.value,
        "session_date": bar.session_date,
        "event_time": bar.event_time,
        "available_at": bar.available_at,
        "captured_at": bar.captured_at,
        "open": _storage_decimal(bar.open, field="open"),
        "high": _storage_decimal(bar.high, field="high"),
        "low": _storage_decimal(bar.low, field="low"),
        "close": _storage_decimal(bar.close, field="close"),
        "volume": _storage_decimal(
            bar.volume,
            field="volume",
        ),
        "amount": _storage_decimal(
            bar.amount,
            field="amount",
        ),
        "suspended": bar.suspended,
    }


def _storage_decimal(
    value: Decimal,
    *,
    field: str,
) -> Decimal:
    """转换为 canonical decimal scale，任何精度损失都直接拒绝。

    例如 10.31 可以安全规范化为 10.31000000；
    但 10.123456789 需要舍入才能进入 scale=8，因此必须失败。
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"daily_bar_{field}_must_be_decimal")

    if not value.is_finite():
        raise ValueError(f"daily_bar_{field}_must_be_finite")

    try:
        # Decimal 默认 context 可能不足以处理大成交额，这里只扩大
        # 运算精度，不改变任何数值或舍入规则。
        with localcontext() as context:
            context.prec = 50
            normalized = value.quantize(_DECIMAL_QUANTUM)
    except InvalidOperation as exc:
        raise ValueError(f"daily_bar_{field}_storage_precision_invalid") from exc

    # canonical storage 不允许静默舍入。
    if normalized != value:
        raise ValueError(f"daily_bar_{field}_exceeds_storage_scale")

    return normalized
