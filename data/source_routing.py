"""Runtime source routing from versioned policy plus configured provider registry."""

from __future__ import annotations

from dataclasses import dataclass

from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.market.reconciliation import (
    BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1,
    STRICT_DAILY_RECONCILIATION,
    DailyBarReconciliationPolicy,
)
from data.provider_registry import ProviderRegistry, build_provider_registry
from data.source import DataSource
from data.source_policy import (
    MarketDataUseCase,
    MarketSourcePolicy,
    SourceRoute,
    source_policy_for_config,
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


def configured_legacy_provider_names(
    config: object,
    use_case: MarketDataUseCase,
) -> tuple[str, ...]:
    route = route_for_config(config, use_case)
    registry = provider_registry_for_config(config, include_tdx=False)
    available = set(registry.legacy_sources())
    return tuple(name for name in route.candidates if name in available)


def preferred_legacy_provider(
    config: object,
    use_case: MarketDataUseCase,
) -> str:
    candidates = configured_legacy_provider_names(config, use_case)
    if not candidates:
        raise MarketSourceRoutingError(
            f"market_source_route_unavailable:{use_case.value}"
        )
    return candidates[0]


def legacy_sources_for_use_case(
    config: object,
    use_case: MarketDataUseCase,
) -> dict[str, DataSource]:
    """Resolve one legacy adapter route through the injectable manager seam."""
    route = route_for_config(config, use_case)
    # Import lazily so route tests and extension providers can replace the
    # historical build_sources seam without contacting real providers.
    from data import manager as data_manager

    sources = data_manager.build_sources(
        data_source=getattr(config, "data_source", None),
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
    )
    resolved = {name: sources[name] for name in route.candidates if name in sources}
    if not resolved:
        raise MarketSourceRoutingError(
            f"market_source_route_unavailable:{use_case.value}"
        )
    return resolved


def resolve_daily_bar_verification_pair(
    policy: MarketSourcePolicy,
    registry: ProviderRegistry,
    request: DailyBarRequest,
) -> DailyBarVerificationPair:
    """Resolve the first deterministic independent pair for one daily request."""
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
            descriptor.supports_daily_bars(
                instrument.instrument_type,
                price_basis=route.price_basis,
            )
            for instrument in request.instruments
        ):
            eligible.append((name, provider))

    for index, (primary_name, primary) in enumerate(eligible):
        for comparison_name, comparison in eligible[index + 1 :]:
            if (
                route.require_independent_upstream
                and primary.descriptor.upstream_group
                == comparison.descriptor.upstream_group
            ):
                continue
            return DailyBarVerificationPair(
                policy_id=policy.policy_id,
                route=route,
                primary_name=primary_name,
                comparison_name=comparison_name,
                primary=primary,
                comparison=comparison,
                reconciliation_policy=_daily_bar_reconciliation_policy(
                    primary,
                    comparison,
                ),
            )

    raise MarketSourceRoutingError("market_source_verified_daily_pair_unavailable")


def daily_bar_verification_pair_for_config(
    config: object,
    request: DailyBarRequest,
    *,
    include_tdx: bool = False,
) -> DailyBarVerificationPair:
    """Resolve a verified daily-bar pair using runtime config and credentials."""
    return resolve_daily_bar_verification_pair(
        source_policy_for_config(config),
        provider_registry_for_config(config, include_tdx=include_tdx),
        request,
    )


def _daily_bar_reconciliation_policy(
    primary: DailyBarProvider,
    comparison: DailyBarProvider,
) -> DailyBarReconciliationPolicy:
    upstreams = frozenset(
        {
            primary.descriptor.upstream_group,
            comparison.descriptor.upstream_group,
        }
    )
    if upstreams == frozenset({"baostock", "tencent"}):
        return BAOSTOCK_TENCENT_DAILY_RECONCILIATION_V1
    return STRICT_DAILY_RECONCILIATION
