from types import SimpleNamespace

import pytest

from data.source_policy import MarketDataUseCase
from data.source_routing import (
    MarketSourceRoutingError,
    configured_legacy_provider_names,
    preferred_legacy_provider,
)


def _config(*, token: str = ""):
    return SimpleNamespace(
        market_data_source_policy="karkinos.market.source.cn_research.v1",
        tushare_token=token,
    )


def test_realtime_route_skips_unconfigured_tushare() -> None:
    config = _config(token="")
    assert configured_legacy_provider_names(
        config, MarketDataUseCase.REALTIME_QUOTES
    ) == ("akshare",)
    assert (
        preferred_legacy_provider(config, MarketDataUseCase.REALTIME_QUOTES)
        == "akshare"
    )


def test_realtime_route_prefers_tushare_when_token_is_configured() -> None:
    config = _config(token="fixture")
    assert configured_legacy_provider_names(
        config, MarketDataUseCase.REALTIME_QUOTES
    ) == ("tushare", "akshare")


def test_daily_legacy_route_filters_tdx_but_keeps_policy_order() -> None:
    config = _config(token="fixture")
    assert configured_legacy_provider_names(config, MarketDataUseCase.DAILY_BARS) == (
        "tushare",
        "akshare",
    )


def test_unknown_use_case_route_is_not_silently_invented() -> None:
    config = _config(token="")
    with pytest.raises(TypeError, match="market_source_policy_use_case_invalid"):
        preferred_legacy_provider(config, "not-a-use-case")  # type: ignore[arg-type]
