"""Provider identity and capability contracts for the unified data plane."""

from core.types import InstrumentType
from data.providers.akshare_source import AKSHARE_PROVIDER_DESCRIPTOR, AKShareSource
from data.providers.tdx import TDX_PROVIDER_DESCRIPTOR, TdxDailyBarProvider
from data.providers.tushare_source import TUSHARE_PROVIDER_DESCRIPTOR, TushareSource


def test_tdx_declares_unadjusted_stock_and_etf_daily_capability() -> None:
    descriptor = TdxDailyBarProvider(client=object()).descriptor
    assert descriptor == TDX_PROVIDER_DESCRIPTOR
    assert descriptor.provider == "tdx"
    assert descriptor.upstream_group == "tdx"
    assert descriptor.supports_daily_bars(
        InstrumentType.STOCK, price_basis="unadjusted"
    )
    assert descriptor.supports_daily_bars(InstrumentType.ETF, price_basis="unadjusted")


def test_tushare_legacy_source_declares_unadjusted_stock_daily_capability() -> None:
    descriptor = TushareSource(token="fixture").descriptor
    assert descriptor == TUSHARE_PROVIDER_DESCRIPTOR
    assert descriptor.provider == "tushare"
    assert descriptor.upstream_group == "tushare"
    assert descriptor.supports_daily_bars(
        InstrumentType.STOCK, price_basis="unadjusted"
    )
    assert not descriptor.supports_daily_bars(InstrumentType.ETF)


def test_akshare_source_declares_unadjusted_stocks_and_qfq_etfs() -> None:
    descriptor = AKShareSource().descriptor
    assert descriptor == AKSHARE_PROVIDER_DESCRIPTOR
    assert descriptor.provider == "akshare"
    assert descriptor.upstream_group == "eastmoney"
    assert not descriptor.supports_daily_bars(InstrumentType.STOCK, price_basis="qfq")
    assert descriptor.supports_daily_bars(InstrumentType.ETF, price_basis="qfq")
    assert descriptor.supports_daily_bars(
        InstrumentType.OPEN_END_FUND,
        price_basis="published_unit_nav",
    )
    assert descriptor.supports_daily_bars(
        InstrumentType.STOCK, price_basis="unadjusted"
    )


def test_verification_sources_can_distinguish_provider_from_upstream() -> None:
    assert TDX_PROVIDER_DESCRIPTOR.provider != TUSHARE_PROVIDER_DESCRIPTOR.provider
    assert (
        TDX_PROVIDER_DESCRIPTOR.upstream_group
        != TUSHARE_PROVIDER_DESCRIPTOR.upstream_group
    )
    assert AKSHARE_PROVIDER_DESCRIPTOR.upstream_group == "eastmoney"
