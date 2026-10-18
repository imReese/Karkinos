"""Typed SDK calls honor the existing explicit provider-network policy."""

import logging
import os
import urllib.request
from contextlib import nullcontext
from datetime import date, datetime, timezone
from threading import Event, Thread
from types import SimpleNamespace

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarProviderUnavailableError, DailyBarRequest
from data.providers.akshare_sdk import call_with_retry, provider_network_env
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


@pytest.mark.parametrize("use_proxy", [False, True])
@pytest.mark.parametrize("sdk_failure", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("first_to_finish", [0, 1])
def test_overlapping_provider_calls_preserve_policy_until_last_exit(
    monkeypatch, use_proxy, sdk_failure, nested, first_to_finish
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
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-proxy.invalid:3128")
    monkeypatch.setenv("NO_PROXY", "synthetic.local")
    if use_proxy:
        monkeypatch.setenv("KARKINOS_PROVIDER_USE_PROXY", "true")
    else:
        monkeypatch.delenv("KARKINOS_PROVIDER_USE_PROXY", raising=False)
    before = {key: os.environ.get(key) for key in keys}
    expected = (
        before
        if use_proxy
        else {key: "*" if key == "NO_PROXY" else None for key in keys}
    )
    original_getproxies = lambda: {"https": "http://synthetic-proxy.invalid:3128"}
    monkeypatch.setattr(urllib.request, "getproxies", original_getproxies)
    entered = [Event(), Event()]
    release = [Event(), Event()]
    observed = []
    failures = []
    unexpected = []

    def worker(index):
        def sdk_call():
            with provider_network_env() if nested else nullcontext():
                observed.append({key: os.environ.get(key) for key in keys})
                entered[index].set()
                assert release[index].wait(5), "provider was not released"
                observed.append({key: os.environ.get(key) for key in keys})
                if sdk_failure and index == first_to_finish:
                    raise ConnectionError("synthetic_provider_failure")

        try:
            call_with_retry(
                sdk_call,
                max_retries=1,
                retry_delay_seconds=0,
                logger=logging.getLogger(__name__),
            )
        except ConnectionError:
            failures.append(index)
        except BaseException as exc:
            unexpected.append(exc)

    threads = [Thread(target=worker, args=(index,), daemon=True) for index in (0, 1)]
    try:
        threads[0].start()
        assert entered[0].wait(5), "first provider did not start"
        threads[1].start()
        # A network call must not hold the lock and serialize other providers.
        assert entered[1].wait(5), "overlapping provider could not start"
        release[first_to_finish].set()
        threads[first_to_finish].join(5)
        assert not threads[first_to_finish].is_alive()
        assert threads[1 - first_to_finish].is_alive()
        assert {key: os.environ.get(key) for key in keys} == expected
        assert urllib.request.getproxies() == (
            original_getproxies() if use_proxy else {}
        )
    finally:
        for event in release:
            event.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(5)

    assert all(not thread.is_alive() for thread in threads)
    assert unexpected == []
    assert failures == ([first_to_finish] if sdk_failure else [])
    assert observed == [expected] * 4
    assert {key: os.environ.get(key) for key in keys} == before
    assert urllib.request.getproxies is original_getproxies
