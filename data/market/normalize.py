"""Market Data 的 canonical normalization。

本模块负责把已经由 Provider Adapter 提取出的通用字段转换为
Karkinos 的 canonical market value。

这里不理解 TDX、TuShare、AKShare 等供应商自己的字段名和响应格式，
也不执行网络请求、持久化、质量评估或数据修复。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core.types import InstrumentKey
from data.market.model import DailyBarObservation


def normalize_daily_bar(
    *,
    instrument: InstrumentKey,
    session_date: date | str,
    event_time: datetime,
    available_at: datetime,
    captured_at: datetime,
    open_value: Decimal | int | float | str,
    high_value: Decimal | int | float | str,
    low_value: Decimal | int | float | str,
    close_value: Decimal | int | float | str,
    volume: Decimal | int | float | str,
    amount: Decimal | int | float | str,
    suspended: bool,
) -> DailyBarObservation:
    """将 Provider Adapter 提取出的日线字段规范化为 canonical 日线记录。

    Provider Adapter 负责解释供应商字段，例如：

    - TDX 的字段名和时间格式；
    - AKShare 的中文列名；
    - TuShare 的 ts_code；
    - Provider 自己的停牌状态。

    本函数只负责将已经明确语义的数据转换为 Karkinos 的标准类型。

    ``available_at`` 必须由调用方显式提供。本层不会猜测信息何时可用。
    如果 Provider 没有更强的可用时间证据，Adapter 应显式使用
    Capture 的完成时间作为保守的 ``available_at``。
    """
    if not isinstance(instrument, InstrumentKey):
        raise TypeError("daily_bar_normalize_instrument_must_be_instrument_key")

    if not isinstance(suspended, bool):
        raise TypeError("daily_bar_normalize_suspended_must_be_bool")

    return DailyBarObservation(
        instrument=instrument,
        session_date=normalize_session_date(session_date),
        event_time=event_time,
        available_at=available_at,
        captured_at=captured_at,
        open=normalize_decimal(
            open_value,
            field="open",
        ),
        high=normalize_decimal(
            high_value,
            field="high",
        ),
        low=normalize_decimal(
            low_value,
            field="low",
        ),
        close=normalize_decimal(
            close_value,
            field="close",
        ),
        volume=normalize_decimal(
            volume,
            field="volume",
        ),
        amount=normalize_decimal(
            amount,
            field="amount",
        ),
        suspended=suspended,
    )


def normalize_decimal(
    value: Decimal | int | float | str,
    *,
    field: str,
) -> Decimal:
    """将常见 Provider 数值类型转换为精确 Decimal。

    float 使用其十进制字符串表示进行转换，例如：

        10.31 -> Decimal("10.31")

    这里不会进行四舍五入，也不会接受 "--"、百分号、千分位等
    Provider 特有格式；这些格式应由对应 Adapter 先行解释。
    """
    if isinstance(value, bool):
        raise TypeError(f"market_normalize_{field}_must_be_numeric")

    if isinstance(value, Decimal):
        result = value

    elif isinstance(value, int):
        result = Decimal(value)

    elif isinstance(value, float):
        result = _decimal_from_text(
            str(value),
            field=field,
        )

    elif isinstance(value, str):
        text = value.strip()

        if not text:
            raise ValueError(f"market_normalize_{field}_missing")

        result = _decimal_from_text(
            text,
            field=field,
        )

    else:
        raise TypeError(f"market_normalize_{field}_must_be_numeric")

    if not result.is_finite():
        raise ValueError(f"market_normalize_{field}_must_be_finite")

    return result


def normalize_session_date(
    value: date | str,
) -> date:
    """将明确的交易日表示转换为 ``date``。

    这里只接受 ``date`` 或 ISO ``YYYY-MM-DD`` 字符串。

    ``datetime`` 不会被自动截断为日期，因为带时间的数据应由
    Provider Adapter 明确解释其市场时区和交易日归属。
    """
    if isinstance(value, datetime):
        raise TypeError("market_normalize_session_date_must_be_date")

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        text = value.strip()

        if not text:
            raise ValueError("market_normalize_session_date_missing")

        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("market_normalize_session_date_invalid") from exc

        if parsed.isoformat() != text:
            raise ValueError("market_normalize_session_date_invalid")

        return parsed

    raise TypeError("market_normalize_session_date_must_be_date")


def canonicalize_daily_bars(
    bars: Iterable[DailyBarObservation],
) -> tuple[DailyBarObservation, ...]:
    """验证批次唯一性并产生确定性的 canonical 行顺序。

    canonical 顺序固定为：

        session_date
        → instrument_type
        → symbol

    相同交易日、相同 InstrumentKey 只能存在一条记录。

    本函数不会选择“哪一条更正确”，重复数据说明上游 normalization
    或 Provider 数据存在歧义，必须显式失败。
    """
    normalized: list[DailyBarObservation] = []
    seen: set[tuple[date, str, str]] = set()

    for bar in bars:
        if not isinstance(bar, DailyBarObservation):
            raise TypeError("daily_bar_batch_contains_invalid_value")

        key = (
            bar.session_date,
            bar.instrument.instrument_type.value,
            bar.instrument.symbol,
        )

        if key in seen:
            raise ValueError("daily_bar_duplicate_instrument_session")

        seen.add(key)
        normalized.append(bar)

    return tuple(
        sorted(
            normalized,
            key=_daily_bar_sort_key,
        )
    )


def _daily_bar_sort_key(
    bar: DailyBarObservation,
) -> tuple[date, str, str]:
    return (
        bar.session_date,
        bar.instrument.instrument_type.value,
        bar.instrument.symbol,
    )


def _decimal_from_text(
    value: str,
    *,
    field: str,
) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"market_normalize_{field}_invalid") from exc
