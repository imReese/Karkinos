import pytest

from data.provider_registry import build_provider_registry
from data.providers.akshare_daily import AKSHARE_DAILY_BAR_DESCRIPTOR
from data.providers.baostock_daily import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from data.providers.tushare_daily import TUSHARE_DAILY_BAR_DESCRIPTOR


def test_registry_without_paid_or_private_credentials_keeps_free_daily_sources() -> (
    None
):
    registry = build_provider_registry(tushare_token="", include_tdx=False)
    assert registry.names == ("akshare", "baostock")
    assert tuple(registry.legacy_sources()) == ("akshare",)
    providers = dict(
        registry.daily_bar_providers(("baostock", "akshare", "tushare", "tdx"))
    )
    assert tuple(providers) == ("baostock", "akshare")
    assert providers["baostock"].descriptor == BAOSTOCK_DAILY_BAR_DESCRIPTOR
    assert providers["akshare"].descriptor == AKSHARE_DAILY_BAR_DESCRIPTOR


def test_registry_adds_tushare_only_when_credentials_are_available() -> None:
    registry = build_provider_registry(tushare_token="fixture", include_tdx=True)
    assert registry.names == ("akshare", "baostock", "tdx", "tushare")
    assert tuple(registry.legacy_sources(("tushare", "akshare", "tdx"))) == (
        "tushare",
        "akshare",
    )


def test_registry_builds_immutable_adapters_from_same_provider_identity() -> None:
    registry = build_provider_registry(tushare_token="fixture", include_tdx=True)
    akshare = registry.build_daily_bar("akshare")
    baostock = registry.build_daily_bar("baostock")
    tushare = registry.build_daily_bar("tushare")
    assert akshare.descriptor == AKSHARE_DAILY_BAR_DESCRIPTOR
    assert baostock.descriptor == BAOSTOCK_DAILY_BAR_DESCRIPTOR
    assert tushare.descriptor == TUSHARE_DAILY_BAR_DESCRIPTOR


def test_tdx_is_not_a_legacy_datasource() -> None:
    registry = build_provider_registry(tushare_token="fixture", include_tdx=True)
    with pytest.raises(ValueError, match="provider_legacy_capability_unavailable:tdx"):
        registry.build_legacy("tdx")


def test_missing_provider_is_explicit() -> None:
    registry = build_provider_registry(tushare_token="", include_tdx=False)
    with pytest.raises(KeyError, match="provider_not_registered:tushare"):
        registry.registration("tushare")
