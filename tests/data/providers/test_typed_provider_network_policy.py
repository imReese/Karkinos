"""Typed SDK calls honor the existing explicit provider-network policy."""

import os
import urllib.request
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProviderUnavailableError, DailyBarRequest
from data.providers.eastmoney import AkshareDailyBarProvider
from data.providers.tencent import AkshareTencentDailyBarProvider


@pytest.mark.parametrize("kind", ["eastmoney", "tencent"])
@pytest.mark.parametrize("use_proxy", [False, True])
@pytest.mark.parametrize("sdk_failure", [False, True])
def test_typed_sdk_uses_canonical_network_policy_and_always_restores_environment(
    monkeypatch, kind, use_proxy, sdk_failure
):
    keys = (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "NO_PROXY",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://inherited-proxy.invalid:3128")
    monkeypatch.setenv("http_proxy", "http://inherited-proxy.invalid:3129")
    monkeypatch.setenv("ALL_PROXY", "socks5://inherited-proxy.invalid:1080")
    monkeypatch.setenv("NO_PROXY", "existing.invalid")
    if use_proxy:
        monkeypatch.setenv("KARKINOS_PROVIDER_USE_PROXY", "true")
    else:
        monkeypatch.delenv("KARKINOS_PROVIDER_USE_PROXY", raising=False)
    before = {key: os.environ.get(key) for key in keys}
    proxy_map = {"https": "http://inherited-proxy.invalid:3128"}

    def original_getproxies():
        return dict(proxy_map)

    monkeypatch.setattr(urllib.request, "getproxies", original_getproxies)
    calls = []

    def sdk_call(**kwargs):
        calls.append(kwargs)
        observed = {key: os.environ.get(key) for key in keys}
        assert observed == (
            before
            if use_proxy
            else {key: "*" if key == "NO_PROXY" else None for key in keys}
        )
        assert urllib.request.getproxies() == (proxy_map if use_proxy else {})
        if sdk_failure:
            raise ConnectionError("synthetic_fixture_network_failure")
        return pd.DataFrame()

    endpoint = "stock_zh_a_hist" if kind == "eastmoney" else "stock_zh_a_hist_tx"
    client = SimpleNamespace(__version__="1.18.97", **{endpoint: sdk_call})
    provider_type = (
        AkshareDailyBarProvider
        if kind == "eastmoney"
        else AkshareTencentDailyBarProvider
    )
    provider = provider_type(
        client, clock=lambda: datetime(2026, 9, 17, 8, tzinfo=timezone.utc)
    )
    request = DailyBarRequest(
        (InstrumentKey("600000", InstrumentType.STOCK),),
        date(2026, 9, 17),
        date(2026, 9, 17),
    )
    if sdk_failure:
        with pytest.raises(DailyBarProviderUnavailableError) as failure:
            provider.fetch_daily_bars(request)
        assert isinstance(failure.value.__cause__, ConnectionError)
    else:
        assert provider.fetch_daily_bars(request).rows == ()
    assert len(calls) == 1
    assert {key: os.environ.get(key) for key in keys} == before
    assert urllib.request.getproxies is original_getproxies
