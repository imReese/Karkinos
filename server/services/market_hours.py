from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_SH_TZ = ZoneInfo("Asia/Shanghai")
_MORNING_OPEN = time(9, 30)
_MORNING_CLOSE = time(11, 30)
_AFTERNOON_OPEN = time(13, 0)
_AFTERNOON_CLOSE = time(15, 0)


def get_shanghai_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(_SH_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=_SH_TZ)
    return now.astimezone(_SH_TZ)


def is_cn_trading_session(now: datetime | None = None) -> bool:
    current = get_shanghai_now(now)
    if current.weekday() >= 5:
        return False
    current_time = current.time()
    return (
        _MORNING_OPEN <= current_time <= _MORNING_CLOSE
        or _AFTERNOON_OPEN <= current_time <= _AFTERNOON_CLOSE
    )
