"""A 股交易日历工具。"""

from __future__ import annotations

from datetime import date, timedelta


def is_trading_day(d: date) -> bool:
    """判断是否为交易日（简化版：排除周末）。

    完整版需要接入交易日历 API，此处仅排除周六日。
    """
    return d.weekday() < 5


def next_trading_day(d: date) -> date:
    """下一个交易日。"""
    d = d + timedelta(days=1)
    while not is_trading_day(d):
        d = d + timedelta(days=1)
    return d


def trading_days_between(start: date, end: date) -> list[date]:
    """两个日期之间的交易日列表。"""
    days = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days
