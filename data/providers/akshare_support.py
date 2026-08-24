"""Provider-network and value normalization for the AKShare adapter."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pandas as pd

_OPEN_END_FUND_NOISE = ("发起式", "发起", "A类", "C类", "（", "）", "(", ")", " ")
_CHINA_MARKET_TZ = timezone(timedelta(hours=8))
_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


def _looks_like_open_end_fund_code(value: str) -> bool:
    return value.isdigit() and len(value) == 6 and value.startswith("0")


def _row_float(row, *columns: str) -> float | None:
    for column in columns:
        if column not in row.index:
            continue
        value = pd.to_numeric(row.get(column), errors="coerce")
        if not pd.isna(value):
            return float(value)
    return None


def _previous_weekday(value: date) -> date:
    previous = value - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def _date_from_epoch_ms(value) -> str | None:
    if value in {None, ""}:
        return None
    try:
        return (
            datetime.fromtimestamp(float(value) / 1000, tz=_CHINA_MARKET_TZ)
            .date()
            .isoformat()
        )
    except (TypeError, ValueError):
        return None


def _dict_float(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _provider_uses_proxy() -> bool:
    value = os.environ.get("KARKINOS_PROVIDER_USE_PROXY", "")
    return value.lower() in {"1", "true", "yes", "on"}


@contextmanager
def _provider_network_env():
    """Keep provider calls from inheriting broken local proxy settings by default."""
    if _provider_uses_proxy():
        yield
        return

    original = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    for key in _PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


OPEN_END_FUND_NOISE = _OPEN_END_FUND_NOISE
CHINA_MARKET_TZ = _CHINA_MARKET_TZ
looks_like_open_end_fund_code = _looks_like_open_end_fund_code
row_float = _row_float
previous_weekday = _previous_weekday
date_from_epoch_ms = _date_from_epoch_ms
dict_float = _dict_float
provider_network_env = _provider_network_env
