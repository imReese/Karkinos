"""Runtime source routing from versioned policy plus configured provider registry."""

from __future__ import annotations

from dataclasses import dataclass

from core.types import InstrumentType
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.market.reconciliation import (
    BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    BAOSTOCK_TUSHARE_AMOUNT_RECONCILIATION_V1,
    EASTMONEY_TUSHARE_BSE_RECONCILIATION_V1,
    STRICT_DAILY_RECONCILIATION,
    TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1,
    DailyBarReconciliationPolicy,
)
from data.provider_registry import ProviderRegistry, build_provider_registry
from data.source import DataSource
from data.source_policy import (
    MarketDataUseCase,
    MarketSourcePolicy,
    SourceRoute,
    source_policy_for_config,
    verification_source_policy_for_config,
)


class MarketSourceRoutingError(RuntimeError):
    """No configured provider can satisfy a required source route."""


@dataclass(frozen=True, slots=True)
class DailyBarVerificationPair:
    """Two deterministic providers satisfying one verified daily-bar route."""

    policy_id: str
    route: SourceRoute
    primary_name: str
    comparison_name: str
    primary: DailyBarProvider
    comparison: DailyBarProvider
    reconciliation_policy: DailyBarReconciliationPolicy

    def __post_init__(self) -> None:
        if self.primary_name == self.comparison_name:
            raise ValueError("market_source_verification_pair_provider_duplicate")
        if self.primary.descriptor.provider != self.primary_name:
            raise ValueError("market_source_verification_pair_primary_mismatch")
        if self.comparison.descriptor.provider != self.comparison_name:
            raise ValueError("market_source_verification_pair_comparison_mismatch")
        if (
            self.route.require_independent_upstream
            and self.primary.descriptor.upstream_group
            == self.comparison.descriptor.upstream_group
        ):
            raise ValueError("market_source_verification_pair_upstream_duplicate")


def provider_registry_for_config(
    config: object,
    *,
    include_tdx: bool = False,
) -> ProviderRegistry:
    return build_provider_registry(
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
        include_tdx=include_tdx,
    )


def route_for_config(
    config: object,
    use_case: MarketDataUseCase,
) -> SourceRoute:
    return source_policy_for_config(config).route(use_case)


def configured_data_provider_names(
    config: object,
    use_case: MarketDataUseCase,
    *,
    include_tdx: bool = False,
) -> tuple[str, ...]:
    route = route_for_config(config, use_case)
    registry = provider_registry_for_config(config, include_tdx=include_tdx)
    available = set(registry.data_sources())
    return tuple(name for name in route.candidates if name in available)


configured_legacy_provider_names = configured_data_provider_names


def preferred_data_provider(
    config: object,
    use_case: MarketDataUseCase,
    *,
    include_tdx: bool = False,
) -> str:
    candidates = configured_data_provider_names(
        config, use_case, include_tdx=include_tdx
    )
    if not candidates:
        raise MarketSourceRoutingError(
            f"market_source_route_unavailable:{use_case.value}"
        )
    return candidates[0]


preferred_legacy_provider = preferred_data_provider


def data_sources_for_use_case(
    config: object,
    use_case: MarketDataUseCase,
) -> dict[str, DataSource]:
    """Resolve one data adapter route through the injectable manager seam."""
    route = route_for_config(config, use_case)
    # Import lazily so route tests and extension providers can replace the
    # historical build_sources seam without contacting real providers.
    from data import manager as data_manager

    sources = data_manager.build_sources(
        data_source=getattr(config, "data_source", None),
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
        source_policy=source_policy_for_config(config),
    )
    resolved = {name: sources[name] for name in route.candidates if name in sources}
    if not resolved:
        raise MarketSourceRoutingError(
            f"market_source_route_unavailable:{use_case.value}"
        )
    return resolved


legacy_sources_for_use_case = data_sources_for_use_case


def resolve_daily_bar_verification_pairs(
    policy: MarketSourcePolicy,
    registry: ProviderRegistry,
    request: DailyBarRequest,
) -> tuple[DailyBarVerificationPair, ...]:
    """Resolve every deterministic independent pair in policy preference order."""
    if not isinstance(policy, MarketSourcePolicy):
        raise TypeError("market_source_policy_invalid")
    if not isinstance(registry, ProviderRegistry):
        raise TypeError("market_source_registry_invalid")
    if not isinstance(request, DailyBarRequest):
        raise TypeError("market_source_daily_bar_request_invalid")

    route = policy.route(MarketDataUseCase.DAILY_BARS)
    if route.min_sources != 2:
        raise MarketSourceRoutingError(
            f"market_source_daily_bar_min_sources_unsupported:{route.min_sources}"
        )

    eligible: list[tuple[str, DailyBarProvider]] = []
    for name, provider in registry.daily_bar_providers(route.candidates):
        descriptor = provider.descriptor
        if all(
            descriptor.supports_daily_bar_instrument(
                instrument,
                price_basis=route.price_basis,
            )
            for instrument in request.instruments
        ):
            eligible.append((name, provider))

    pairs: list[DailyBarVerificationPair] = []
    for index, (primary_name, primary) in enumerate(eligible):
        for comparison_name, comparison in eligible[index + 1 :]:
            if (
                route.require_independent_upstream
                and primary.descriptor.upstream_group
                == comparison.descriptor.upstream_group
            ):
                continue
            bse_pair = {primary_name, comparison_name} == {
                "akshare",
                "tushare",
            } and any(
                key.instrument_type is InstrumentType.STOCK
                and key.symbol.startswith(("4", "8", "92"))
                for key in request.instruments
            )
            # Preserve exact TuShare shares for capacity decisions; Eastmoney
            # independently checks the reported whole-hand resolution.
            first_name, first = (
                (comparison_name, comparison)
                if bse_pair and comparison_name == "tushare"
                else (primary_name, primary)
            )
            second_name, second = (
                (primary_name, primary)
                if first is comparison
                else (comparison_name, comparison)
            )
            pairs.append(
                DailyBarVerificationPair(
                    policy_id=policy.policy_id,
                    route=route,
                    primary_name=first_name,
                    comparison_name=second_name,
                    primary=first,
                    comparison=second,
                    reconciliation_policy=EASTMONEY_TUSHARE_BSE_RECONCILIATION_V1
                    if bse_pair
                    else _daily_bar_reconciliation_policy(
                        primary,
                        comparison,
                        request,
                    ),
                )
            )

    if not pairs:
        raise MarketSourceRoutingError("market_source_verified_daily_pair_unavailable")
    return tuple(pairs)


def resolve_daily_bar_verification_pair(
    policy: MarketSourcePolicy,
    registry: ProviderRegistry,
    request: DailyBarRequest,
) -> DailyBarVerificationPair:
    """Resolve the preferred deterministic independent pair for compatibility."""
    return resolve_daily_bar_verification_pairs(policy, registry, request)[0]


def daily_bar_verification_pair_for_config(
    config: object,
    request: DailyBarRequest,
    *,
    include_tdx: bool = False,
) -> DailyBarVerificationPair:
    """Resolve a verified daily-bar pair using runtime config and credentials."""
    return resolve_daily_bar_verification_pair(
        verification_source_policy_for_config(config),
        provider_registry_for_config(config, include_tdx=include_tdx),
        request,
    )


def _daily_bar_reconciliation_policy(
    primary: DailyBarProvider,
    comparison: DailyBarProvider,
    request: DailyBarRequest,
) -> DailyBarReconciliationPolicy:
    upstreams = frozenset(
        {
            primary.descriptor.upstream_group,
            comparison.descriptor.upstream_group,
        }
    )
    if upstreams == frozenset({"baostock", "tencent"}):
        return BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1
    if upstreams == frozenset({"baostock", "tushare"}):
        return BAOSTOCK_TUSHARE_AMOUNT_RECONCILIATION_V1
    if (
        upstreams == frozenset({"tushare", "tencent"})
        and {primary.descriptor.provider, comparison.descriptor.provider}
        == {"tushare", "akshare_tencent"}
        and all(
            key.instrument_type is InstrumentType.STOCK
            and not key.symbol.startswith(("4", "8", "92"))
            for key in request.instruments
        )
    ):
        return TENCENT_TUSHARE_REPORTED_AMOUNT_RECONCILIATION_V1
    return STRICT_DAILY_RECONCILIATION
