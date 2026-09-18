"""Runtime source routing from versioned policy plus configured provider registry."""

from __future__ import annotations

from data.provider_registry import ProviderRegistry, build_provider_registry
from data.source import DataSource
from data.source_policy import (
    MarketDataUseCase,
    SourceRoute,
    source_policy_for_config,
)


class MarketSourceRoutingError(RuntimeError):
    """No configured provider can satisfy a required source route."""


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
