import pytest

from data.provider_registry import build_provider_registry
from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.providers.eastmoney import AKSHARE_DAILY_BAR_DESCRIPTOR
from data.providers.tencent import (
    AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR,
    TENCENT_DAILY_BAR_DESCRIPTOR,
)
from data.providers.tushare import TUSHARE_DAILY_BAR_DESCRIPTOR


def test_registry_without_paid_or_private_credentials_keeps_free_daily_sources() -> (
    None
):
    registry = build_provider_registry(tushare_token="", include_tdx=False)
    assert registry.names == ("akshare", "akshare_tencent", "baostock", "tencent")
    assert set(registry.data_sources()) == {"akshare", "akshare_tencent", "tencent"}
    assert set(registry.legacy_sources()) == {"akshare", "akshare_tencent", "tencent"}
    providers = dict(
        registry.daily_bar_providers(
            ("baostock", "akshare_tencent", "tencent", "akshare", "tushare", "tdx")
        )
    )
    assert tuple(providers) == ("baostock", "akshare_tencent", "tencent", "akshare")
    assert providers["baostock"].descriptor == BAOSTOCK_DAILY_BAR_DESCRIPTOR
    assert (
        providers["akshare_tencent"].descriptor == AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR
    )
    assert providers["tencent"].descriptor == TENCENT_DAILY_BAR_DESCRIPTOR
    assert providers["akshare"].descriptor == AKSHARE_DAILY_BAR_DESCRIPTOR


def test_registry_adds_tushare_only_when_credentials_are_available() -> None:
    registry = build_provider_registry(tushare_token="fixture", include_tdx=True)
    assert registry.names == (
        "akshare",
        "akshare_tencent",
        "baostock",
        "tdx",
        "tencent",
        "tushare",
    )
    assert tuple(registry.data_sources(("tushare", "akshare", "tdx"))) == (
        "tushare",
        "akshare",
        "tdx",
    )
    assert tuple(registry.legacy_sources(("tushare", "akshare", "tdx"))) == (
        "tushare",
        "akshare",
        "tdx",
    )


def test_registry_builds_immutable_adapters_from_same_provider_identity() -> None:
    registry = build_provider_registry(tushare_token="fixture", include_tdx=True)
    akshare = registry.build_daily_bar("akshare")
    tencent = registry.build_daily_bar("akshare_tencent")
    tencent_direct = registry.build_daily_bar("tencent")
    baostock = registry.build_daily_bar("baostock")
    tushare = registry.build_daily_bar("tushare")
    assert akshare.descriptor == AKSHARE_DAILY_BAR_DESCRIPTOR
    assert tencent.descriptor == AKSHARE_TENCENT_DAILY_BAR_DESCRIPTOR
    assert tencent_direct.descriptor == TENCENT_DAILY_BAR_DESCRIPTOR
    assert baostock.descriptor == BAOSTOCK_DAILY_BAR_DESCRIPTOR
    assert tushare.descriptor == TUSHARE_DAILY_BAR_DESCRIPTOR


def test_tdx_provides_data_source() -> None:
    from data.providers.tdx import TdxSource

    registry = build_provider_registry(tushare_token="fixture", include_tdx=True)
    tdx = registry.build_source("tdx")
    assert isinstance(tdx, TdxSource)
    assert isinstance(registry.build_legacy("tdx"), TdxSource)


def test_missing_provider_is_explicit() -> None:
    registry = build_provider_registry(tushare_token="", include_tdx=False)
    with pytest.raises(KeyError, match="provider_not_registered:tushare"):
        registry.registration("tushare")
