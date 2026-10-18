"""Provider-network and value normalization for the AKShare adapter."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from threading import Lock

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
_PROVIDER_NETWORK_LOCK = Lock()
_provider_network_users = 0
_provider_original_proxy_env: dict[str, str | None] = {}
_provider_original_getproxies: Callable[[], dict[str, str]] | None = None


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
    global _provider_network_users
    global _provider_original_proxy_env, _provider_original_getproxies

    if _provider_uses_proxy():
        yield
        return

    import urllib.request

    # The environment is process-global. Overlapping and nested calls share one
    # snapshot; the lock must not serialize the provider network work itself.
    with _PROVIDER_NETWORK_LOCK:
        if _provider_network_users == 0:
            _provider_original_getproxies = urllib.request.getproxies
            _provider_original_proxy_env = {
                key: os.environ.get(key) for key in (*_PROXY_ENV_KEYS, "NO_PROXY")
            }
            for key in _PROXY_ENV_KEYS:
                os.environ.pop(key, None)
            os.environ["NO_PROXY"] = "*"
            urllib.request.getproxies = lambda: {}
        _provider_network_users += 1
    try:
        yield
    finally:
        with _PROVIDER_NETWORK_LOCK:
            _provider_network_users -= 1
            if _provider_network_users == 0:
                assert _provider_original_getproxies is not None
                urllib.request.getproxies = _provider_original_getproxies
                for key, value in _provider_original_proxy_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                _provider_original_proxy_env = {}
                _provider_original_getproxies = None


def call_with_retry(
    func,
    *,
    max_retries: int,
    retry_delay_seconds: float,
    logger,
    **kwargs,
):
    """Apply the legacy AKShare retry and proxy policy to one upstream call."""
    retries = max(int(max_retries), 1)
    retry_delay = max(float(retry_delay_seconds), 0.0)
    last_error = None
    for attempt in range(retries):
        try:
            with _provider_network_env():
                return func(**kwargs)
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                logger.warning(
                    "AKShare 调用失败 (第%d次), %.3fs 后重试: %s",
                    attempt + 1,
                    retry_delay,
                    exc,
                )
                if retry_delay:
                    time.sleep(retry_delay)
    assert last_error is not None
    raise last_error


OPEN_END_FUND_NOISE = _OPEN_END_FUND_NOISE
CHINA_MARKET_TZ = _CHINA_MARKET_TZ
looks_like_open_end_fund_code = _looks_like_open_end_fund_code
row_float = _row_float
previous_weekday = _previous_weekday
date_from_epoch_ms = _date_from_epoch_ms
dict_float = _dict_float
provider_network_env = _provider_network_env
