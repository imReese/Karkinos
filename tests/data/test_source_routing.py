from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.provider_registry import build_provider_registry
from data.source_policy import (
    FREE_CN_RESEARCH_V1,
    MarketDataUseCase,
    MarketSourcePolicy,
    SourceRoute,
)
from data.source_routing import (
    MarketSourceRoutingError,
    configured_legacy_provider_names,
    daily_bar_verification_pair_for_config,
    preferred_legacy_provider,
    resolve_daily_bar_verification_pair,
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


def _daily_request(
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> DailyBarRequest:
    symbol = "510300" if instrument_type is InstrumentType.ETF else "600000"
    day = date(2026, 9, 17)
    return DailyBarRequest(
        (InstrumentKey(symbol, instrument_type),),
        day,
        day,
    )


def test_free_policy_resolves_baostock_and_tencent_without_credentials() -> None:
    registry = build_provider_registry(tushare_token="", include_tdx=False)
    pair = resolve_daily_bar_verification_pair(
        FREE_CN_RESEARCH_V1,
        registry,
        _daily_request(),
    )

    assert pair.policy_id == FREE_CN_RESEARCH_V1.policy_id
    assert (pair.primary_name, pair.comparison_name) == (
        "baostock",
        "akshare_tencent",
    )
    assert pair.primary.descriptor.upstream_group == "baostock"
    assert pair.comparison.descriptor.upstream_group == "tencent"
    assert pair.reconciliation_policy.price_tolerance == 0
    assert pair.reconciliation_policy.volume_tolerance == 99
    assert pair.reconciliation_policy.amount_tolerance == Decimal("99.99")


def test_free_policy_pair_supports_etf_unadjusted_daily_bars() -> None:
    pair = resolve_daily_bar_verification_pair(
        FREE_CN_RESEARCH_V1,
        build_provider_registry(tushare_token="", include_tdx=False),
        _daily_request(InstrumentType.ETF),
    )
    assert pair.primary.descriptor.supports_daily_bars(
        InstrumentType.ETF,
        price_basis="unadjusted",
    )
    assert pair.comparison.descriptor.supports_daily_bars(
        InstrumentType.ETF,
        price_basis="unadjusted",
    )


def test_config_helper_uses_free_default_without_tushare_or_tdx() -> None:
    config = SimpleNamespace(
        market_data_source_policy=FREE_CN_RESEARCH_V1.policy_id,
        tushare_token="",
    )
    pair = daily_bar_verification_pair_for_config(
        config,
        _daily_request(),
        include_tdx=False,
    )
    assert (pair.primary_name, pair.comparison_name) == (
        "baostock",
        "akshare_tencent",
    )


def test_verified_pair_fails_closed_when_only_one_capable_source_exists() -> None:
    policy = MarketSourcePolicy(
        policy_id="fixture.single.v1",
        routes=(
            (
                MarketDataUseCase.DAILY_BARS,
                SourceRoute(
                    candidates=("baostock", "tushare"),
                    min_sources=2,
                    require_independent_upstream=True,
                    price_basis="unadjusted",
                ),
            ),
        ),
    )
    registry = build_provider_registry(tushare_token="", include_tdx=False)

    with pytest.raises(
        MarketSourceRoutingError,
        match="market_source_verified_daily_pair_unavailable",
    ):
        resolve_daily_bar_verification_pair(
            policy,
            registry,
            _daily_request(),
        )


def test_verified_pair_rejects_route_requiring_more_than_two_sources() -> None:
    policy = MarketSourcePolicy(
        policy_id="fixture.three.v1",
        routes=(
            (
                MarketDataUseCase.DAILY_BARS,
                SourceRoute(
                    candidates=("baostock", "akshare", "tushare"),
                    min_sources=3,
                    require_independent_upstream=True,
                    price_basis="unadjusted",
                ),
            ),
        ),
    )
    with pytest.raises(
        MarketSourceRoutingError,
        match="market_source_daily_bar_min_sources_unsupported:3",
    ):
        resolve_daily_bar_verification_pair(
            policy,
            build_provider_registry(tushare_token="", include_tdx=False),
            _daily_request(),
        )
