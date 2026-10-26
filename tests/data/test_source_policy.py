from types import SimpleNamespace

import pytest

from data.source_policy import (
    CN_RESEARCH_V1,
    FREE_CN_RESEARCH_V1,
    TENCENT_EASTMONEY_RESEARCH_V1,
    TUSHARE_TENCENT_RESEARCH_V1,
    MarketDataUseCase,
    legacy_preferred_provider_policy,
    resolve_market_source_policy,
    source_policy_for_config,
    verification_source_policy_for_config,
)


def test_cn_research_policy_requires_independent_raw_daily_sources() -> None:
    route = CN_RESEARCH_V1.route(MarketDataUseCase.DAILY_BARS)
    assert route.candidates == ("tushare", "tdx", "akshare")
    assert route.min_sources == 2
    assert route.verification_required
    assert route.require_independent_upstream
    assert route.price_basis == "unadjusted"


def test_free_cn_research_policy_prioritizes_zero_subscription_daily_sources() -> None:
    route = FREE_CN_RESEARCH_V1.route(MarketDataUseCase.DAILY_BARS)
    assert route.candidates == (
        "baostock",
        "akshare_tencent",
        "akshare",
        "tushare",
        "tdx",
    )
    assert route.min_sources == 2
    assert route.verification_required
    assert route.require_independent_upstream
    assert route.price_basis == "unadjusted"
    assert FREE_CN_RESEARCH_V1.route(MarketDataUseCase.REALTIME_QUOTES).candidates == (
        "tdx",
        "tencent",
        "akshare",
        "tushare",
    )


def test_use_cases_have_distinct_source_routes() -> None:
    assert CN_RESEARCH_V1.route(MarketDataUseCase.REALTIME_QUOTES).candidates == (
        "tdx",
        "tushare",
        "tencent",
        "akshare",
    )
    assert CN_RESEARCH_V1.route(MarketDataUseCase.INDEX_BARS).candidates == (
        "tdx",
        "akshare",
    )
    assert CN_RESEARCH_V1.route(MarketDataUseCase.FUND_NAV).candidates == (
        "tushare",
        "akshare",
    )


def test_tushare_tencent_policy_changes_only_verified_daily_candidates() -> None:
    route = TUSHARE_TENCENT_RESEARCH_V1.route(MarketDataUseCase.DAILY_BARS)
    assert route.candidates == ("tushare", "akshare_tencent")
    assert route.min_sources == 2
    assert route.require_independent_upstream
    assert route.price_basis == "unadjusted"
    assert route.verification_required
    for use_case, original in FREE_CN_RESEARCH_V1.routes:
        if use_case is not MarketDataUseCase.DAILY_BARS:
            assert TUSHARE_TENCENT_RESEARCH_V1.route(use_case) is original


def test_tushare_tencent_registered_policy_can_change_only_verification_config() -> (
    None
):
    for name in (
        TUSHARE_TENCENT_RESEARCH_V1.policy_id,
        "tushare_tencent_research_v1",
    ):
        assert resolve_market_source_policy(name) is TUSHARE_TENCENT_RESEARCH_V1
    config = SimpleNamespace(
        market_data_source_policy=FREE_CN_RESEARCH_V1.policy_id,
        market_data_verification_source_policy=TUSHARE_TENCENT_RESEARCH_V1.policy_id,
    )
    assert source_policy_for_config(config) is FREE_CN_RESEARCH_V1
    assert verification_source_policy_for_config(config) is TUSHARE_TENCENT_RESEARCH_V1


def test_policy_alias_resolves_to_stable_identity() -> None:
    assert resolve_market_source_policy("free_cn_research_v1") is FREE_CN_RESEARCH_V1
    assert (
        resolve_market_source_policy(FREE_CN_RESEARCH_V1.policy_id)
        is FREE_CN_RESEARCH_V1
    )
    assert resolve_market_source_policy("cn_research_v1") is CN_RESEARCH_V1
    assert resolve_market_source_policy(CN_RESEARCH_V1.policy_id) is CN_RESEARCH_V1


def test_tencent_eastmoney_policy_is_an_explicit_independent_daily_route() -> None:
    policy = TENCENT_EASTMONEY_RESEARCH_V1
    for name in (policy.policy_id, "tencent_eastmoney_research_v1"):
        assert resolve_market_source_policy(name) is policy
    route = policy.route(MarketDataUseCase.DAILY_BARS)
    assert route.candidates == ("akshare_tencent", "akshare")
    assert route.min_sources == 2
    assert route.require_independent_upstream
    assert route.price_basis == "unadjusted"
    for use_case, original in FREE_CN_RESEARCH_V1.routes:
        if use_case is not MarketDataUseCase.DAILY_BARS:
            assert policy.route(use_case) is original
    config = SimpleNamespace(
        market_data_source_policy=FREE_CN_RESEARCH_V1.policy_id,
        market_data_verification_source_policy=policy.policy_id,
    )
    assert source_policy_for_config(config) is FREE_CN_RESEARCH_V1
    assert verification_source_policy_for_config(config) is policy


def test_unknown_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="market_source_policy_unsupported"):
        resolve_market_source_policy("unknown")


def test_legacy_provider_is_only_a_compatibility_ordering() -> None:
    policy = legacy_preferred_provider_policy("akshare")
    assert policy.route(MarketDataUseCase.DAILY_BARS).candidates == (
        "akshare",
        "tushare",
        "tdx",
    )
    assert policy.route(MarketDataUseCase.DAILY_BARS).min_sources == 2


def test_new_policy_config_wins_over_legacy_provider_compatibility() -> None:
    config = SimpleNamespace(
        market_data_source_policy=CN_RESEARCH_V1.policy_id,
        data_source="akshare",
    )
    assert source_policy_for_config(config) is CN_RESEARCH_V1


def test_missing_policy_defaults_to_free_cn_research() -> None:
    assert resolve_market_source_policy(None) is FREE_CN_RESEARCH_V1
    config = SimpleNamespace(
        market_data_source_policy="",
        data_source="",
    )
    assert source_policy_for_config(config) is FREE_CN_RESEARCH_V1


def test_verification_policy_is_independent_of_collection_policy() -> None:
    config = SimpleNamespace(market_data_source_policy=CN_RESEARCH_V1.policy_id)
    assert source_policy_for_config(config) is CN_RESEARCH_V1
    assert verification_source_policy_for_config(config) is FREE_CN_RESEARCH_V1

    config.market_data_verification_source_policy = CN_RESEARCH_V1.policy_id
    assert verification_source_policy_for_config(config) is CN_RESEARCH_V1


def test_legacy_compat_policy_id_preserves_explicit_provider_order() -> None:
    policy = resolve_market_source_policy("karkinos.market.source.compat.tushare.v1")
    route = policy.route(MarketDataUseCase.DAILY_BARS)
    assert policy.policy_id == "karkinos.market.source.compat.tushare.v1"
    assert route.candidates[:3] == ("tushare", "tdx", "akshare")
