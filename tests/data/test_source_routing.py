from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.market.reconciliation import (
    BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    BAOSTOCK_TUSHARE_AMOUNT_RECONCILIATION_V1,
    STRICT_DAILY_RECONCILIATION,
    TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1,
)
from data.provider_registry import build_provider_registry
from data.source_policy import (
    FREE_CN_RESEARCH_V1,
    TENCENT_EASTMONEY_RESEARCH_V1,
    TUSHARE_TENCENT_RESEARCH_V1,
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
    resolve_daily_bar_verification_pairs,
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
    ) == ("tencent", "akshare")
    assert (
        preferred_legacy_provider(config, MarketDataUseCase.REALTIME_QUOTES)
        == "tencent"
    )


def test_realtime_route_prefers_tushare_when_token_is_configured() -> None:
    config = _config(token="fixture")
    assert configured_legacy_provider_names(
        config, MarketDataUseCase.REALTIME_QUOTES
    ) == ("tushare", "tencent", "akshare")


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


def test_free_policy_exposes_all_independent_pairs_in_preference_order() -> None:
    pairs = resolve_daily_bar_verification_pairs(
        FREE_CN_RESEARCH_V1,
        build_provider_registry(tushare_token="", include_tdx=False),
        _daily_request(),
    )

    assert [(pair.primary_name, pair.comparison_name) for pair in pairs] == [
        ("baostock", "akshare_tencent"),
        ("baostock", "akshare"),
        ("akshare_tencent", "akshare"),
    ]


@pytest.mark.parametrize("symbol", ["600000", "000001", "689009"])
@pytest.mark.parametrize("token", ["", "fixture"])
def test_tencent_eastmoney_policy_uses_only_its_independent_strict_pair(symbol, token):
    request = DailyBarRequest(
        (InstrumentKey(symbol, InstrumentType.STOCK),),
        date(2026, 10, 19),
        date(2026, 10, 23),
    )
    pairs = resolve_daily_bar_verification_pairs(
        TENCENT_EASTMONEY_RESEARCH_V1,
        build_provider_registry(tushare_token=token, include_tdx=False),
        request,
    )
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.policy_id == TENCENT_EASTMONEY_RESEARCH_V1.policy_id
    assert (pair.primary_name, pair.comparison_name) == ("akshare_tencent", "akshare")
    assert (
        pair.primary.descriptor.upstream_group,
        pair.comparison.descriptor.upstream_group,
    ) == ("tencent", "eastmoney")
    assert pair.reconciliation_policy is STRICT_DAILY_RECONCILIATION


@pytest.mark.parametrize("symbol", ["430001", "830001", "920001"])
def test_tencent_eastmoney_policy_keeps_beijing_scope_unavailable(symbol):
    request = DailyBarRequest(
        (InstrumentKey(symbol, InstrumentType.STOCK),),
        date(2026, 10, 19),
        date(2026, 10, 23),
    )
    with pytest.raises(
        MarketSourceRoutingError, match="verified_daily_pair_unavailable"
    ):
        resolve_daily_bar_verification_pairs(
            TENCENT_EASTMONEY_RESEARCH_V1,
            build_provider_registry(tushare_token="fixture", include_tdx=False),
            request,
        )


@pytest.mark.parametrize("symbol", ["600000", "000001", "689009"])
def test_registered_tushare_tencent_policy_has_only_the_exact_independent_pair(symbol):
    request = DailyBarRequest(
        (InstrumentKey(symbol, InstrumentType.STOCK),),
        date(2026, 10, 19),
        date(2026, 10, 23),
    )
    pairs = resolve_daily_bar_verification_pairs(
        TUSHARE_TENCENT_RESEARCH_V1,
        build_provider_registry(tushare_token="fixture", include_tdx=False),
        request,
    )
    assert len(pairs) == 1
    pair = pairs[0]
    assert (pair.primary_name, pair.comparison_name) == ("tushare", "akshare_tencent")
    assert (
        pair.primary.descriptor.upstream_group,
        pair.comparison.descriptor.upstream_group,
    ) == ("tushare", "tencent")
    assert pair.policy_id == TUSHARE_TENCENT_RESEARCH_V1.policy_id
    assert (
        pair.reconciliation_policy is TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1
    )
    assert (
        pair.comparison.descriptor.adapter_version
        == "karkinos.akshare_tencent.daily_bar.v5"
    )


@pytest.mark.parametrize("symbol,token", [("600000", ""), ("920001", "fixture")])
def test_registered_tushare_tencent_policy_never_falls_back_to_other_sources(
    symbol, token
):
    request = DailyBarRequest(
        (InstrumentKey(symbol, InstrumentType.STOCK),),
        date(2026, 10, 19),
        date(2026, 10, 23),
    )
    with pytest.raises(
        MarketSourceRoutingError, match="verified_daily_pair_unavailable"
    ):
        resolve_daily_bar_verification_pairs(
            TUSHARE_TENCENT_RESEARCH_V1,
            build_provider_registry(tushare_token=token, include_tdx=False),
            request,
        )


@pytest.mark.parametrize(
    "candidates", [("tushare", "akshare_tencent"), ("akshare_tencent", "tushare")]
)
def test_explicit_tushare_tencent_stock_pair_uses_existing_reported_policy(candidates):
    policy = MarketSourcePolicy(
        policy_id="fixture.tushare_tencent.v1",
        routes=(
            (
                MarketDataUseCase.DAILY_BARS,
                SourceRoute(
                    candidates=candidates,
                    min_sources=2,
                    require_independent_upstream=True,
                ),
            ),
        ),
    )
    pair = resolve_daily_bar_verification_pair(
        policy,
        build_provider_registry(tushare_token="fixture", include_tdx=False),
        _daily_request(),
    )
    assert (pair.primary_name, pair.comparison_name) == candidates
    assert (
        pair.reconciliation_policy is TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1
    )


def test_tushare_tencent_etf_keeps_strict_policy():
    policy = MarketSourcePolicy(
        policy_id="fixture.tushare_tencent.v1",
        routes=(
            (
                MarketDataUseCase.DAILY_BARS,
                SourceRoute(
                    candidates=("tushare", "akshare_tencent"),
                    min_sources=2,
                    require_independent_upstream=True,
                ),
            ),
        ),
    )
    pair = resolve_daily_bar_verification_pair(
        policy,
        build_provider_registry(tushare_token="fixture", include_tdx=False),
        _daily_request(InstrumentType.ETF),
    )
    assert pair.reconciliation_policy is STRICT_DAILY_RECONCILIATION


def test_tushare_pair_does_not_reorder_free_route_or_change_other_pair_policies():
    pairs = resolve_daily_bar_verification_pairs(
        FREE_CN_RESEARCH_V1,
        build_provider_registry(tushare_token="fixture", include_tdx=False),
        _daily_request(),
    )
    assert [(pair.primary_name, pair.comparison_name) for pair in pairs] == [
        ("baostock", "akshare_tencent"),
        ("baostock", "akshare"),
        ("baostock", "tushare"),
        ("akshare_tencent", "akshare"),
        ("akshare_tencent", "tushare"),
        ("akshare", "tushare"),
    ]
    by_names = {(pair.primary_name, pair.comparison_name): pair for pair in pairs}
    assert pairs[0].reconciliation_policy is BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1
    assert (
        by_names[("baostock", "tushare")].reconciliation_policy
        is BAOSTOCK_TUSHARE_AMOUNT_RECONCILIATION_V1
    )
    assert (
        by_names[("akshare", "tushare")].reconciliation_policy
        is STRICT_DAILY_RECONCILIATION
    )


def test_beijing_preflight_excludes_unsupported_sources_before_provider_io():
    day = date(2026, 9, 17)
    request = DailyBarRequest(
        (InstrumentKey("920001", InstrumentType.STOCK),), day, day
    )
    with pytest.raises(
        MarketSourceRoutingError, match="verified_daily_pair_unavailable"
    ):
        resolve_daily_bar_verification_pairs(
            FREE_CN_RESEARCH_V1, build_provider_registry(include_tdx=False), request
        )
    pairs = resolve_daily_bar_verification_pairs(
        FREE_CN_RESEARCH_V1,
        build_provider_registry(tushare_token="fixture", include_tdx=False),
        request,
    )
    assert [(pair.primary_name, pair.comparison_name) for pair in pairs] == [
        ("tushare", "akshare")
    ]
    assert (
        pairs[0].reconciliation_policy.source_precision_policy
        == "karkinos.eastmoney.bse.whole_hand_resolution.v1"
    )
    assert pairs[0].reconciliation_policy.price_tolerance == 0
    assert pairs[0].reconciliation_policy.amount_tolerance == 0


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


def test_config_helper_uses_verification_policy_without_tushare_or_tdx() -> None:
    config = SimpleNamespace(
        market_data_source_policy="karkinos.market.source.cn_research.v1",
        market_data_verification_source_policy=FREE_CN_RESEARCH_V1.policy_id,
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
    assert pair.policy_id == FREE_CN_RESEARCH_V1.policy_id


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
