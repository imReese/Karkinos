from __future__ import annotations


def test_registry_exposes_benchmark_strategy_metadata():
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    info_by_name = {entry["name"]: entry for entry in StrategyRegistry.get_info()}

    assert info_by_name["dual_ma"]["benchmark_role"] == ("etf_rotation_trend_following")
    assert info_by_name["dual_ma"]["benchmark_universe"] == ["etf"]
    assert info_by_name["dual_ma"]["requires_out_of_sample_validation"] is True
    assert info_by_name["dual_ma"]["requires_after_cost_report"] is True
    assert "after-cost" in info_by_name["dual_ma"]["validation_notes"][0]

    assert info_by_name["monthly_rebalance"]["benchmark_role"] == (
        "defensive_allocation"
    )
    assert set(info_by_name["monthly_rebalance"]["benchmark_universe"]) == {
        "equity_etf",
        "bond",
        "gold",
        "cash_proxy",
    }

    assert info_by_name["bollinger"]["benchmark_role"] == (
        "a_share_or_etf_mean_reversion"
    )
    assert set(info_by_name["bollinger"]["benchmark_universe"]) == {"stock", "etf"}


def test_unmapped_strategy_metadata_has_no_benchmark_role():
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    info_by_name = {entry["name"]: entry for entry in StrategyRegistry.get_info()}

    assert info_by_name["rsi"]["benchmark_role"] is None
    assert info_by_name["rsi"]["benchmark_universe"] == []
    assert info_by_name["rsi"]["requires_out_of_sample_validation"] is False
    assert info_by_name["rsi"]["requires_after_cost_report"] is False
