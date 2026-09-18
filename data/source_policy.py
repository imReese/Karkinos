"""Versioned market-data source routing policy.

A policy selects source roles by use case.  It does not own credentials, SDK
instances, retries, or provider I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


def _provider_name(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("market_source_provider_name_must_be_text")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("market_source_provider_name_missing")
    return normalized


class MarketDataUseCase(str, Enum):
    DAILY_BARS = "daily_bars"
    REALTIME_QUOTES = "realtime_quotes"
    FUND_NAV = "fund_nav"
    SECURITY_MASTER = "security_master"
    MARKET_CALENDAR = "market_calendar"
    INDEX_BARS = "index_bars"
    GOLD_BARS = "gold_bars"
    BOND_BARS = "bond_bars"


@dataclass(frozen=True, slots=True)
class SourceRoute:
    candidates: tuple[str, ...]
    min_sources: int = 1
    require_independent_upstream: bool = False
    price_basis: str | None = None

    def __post_init__(self) -> None:
        normalized = tuple(_provider_name(item) for item in self.candidates)
        if not normalized:
            raise ValueError("market_source_route_candidates_empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("market_source_route_candidate_duplicate")
        if isinstance(self.min_sources, bool) or self.min_sources <= 0:
            raise ValueError("market_source_route_min_sources_invalid")
        if self.min_sources > len(normalized):
            raise ValueError("market_source_route_min_sources_exceeds_candidates")
        if not isinstance(self.require_independent_upstream, bool):
            raise TypeError("market_source_route_independent_flag_invalid")
        if self.price_basis is not None and not str(self.price_basis).strip():
            raise ValueError("market_source_route_price_basis_invalid")
        object.__setattr__(self, "candidates", normalized)
        if self.price_basis is not None:
            object.__setattr__(self, "price_basis", str(self.price_basis).strip())

    @property
    def verification_required(self) -> bool:
        return self.min_sources >= 2


@dataclass(frozen=True, slots=True)
class MarketSourcePolicy:
    policy_id: str
    routes: tuple[tuple[MarketDataUseCase, SourceRoute], ...]

    def __post_init__(self) -> None:
        policy_id = str(self.policy_id).strip()
        if not policy_id:
            raise ValueError("market_source_policy_id_missing")
        seen: set[MarketDataUseCase] = set()
        normalized: list[tuple[MarketDataUseCase, SourceRoute]] = []
        for use_case, route in self.routes:
            if not isinstance(use_case, MarketDataUseCase):
                raise TypeError("market_source_policy_use_case_invalid")
            if not isinstance(route, SourceRoute):
                raise TypeError("market_source_policy_route_invalid")
            if use_case in seen:
                raise ValueError("market_source_policy_route_duplicate")
            seen.add(use_case)
            normalized.append((use_case, route))
        if not normalized:
            raise ValueError("market_source_policy_routes_empty")
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "routes", tuple(normalized))

    def route(self, use_case: MarketDataUseCase) -> SourceRoute:
        for candidate_use_case, route in self.routes:
            if candidate_use_case is use_case:
                return route
        raise KeyError(f"market_source_policy_route_missing:{use_case.value}")


CN_RESEARCH_V1 = MarketSourcePolicy(
    policy_id="karkinos.market.source.cn_research.v1",
    routes=(
        (
            MarketDataUseCase.DAILY_BARS,
            SourceRoute(
                candidates=("tushare", "tdx", "akshare"),
                min_sources=2,
                require_independent_upstream=True,
                price_basis="unadjusted",
            ),
        ),
        (
            MarketDataUseCase.REALTIME_QUOTES,
            SourceRoute(candidates=("tushare", "akshare")),
        ),
        (
            MarketDataUseCase.FUND_NAV,
            SourceRoute(candidates=("tushare", "akshare")),
        ),
        (
            MarketDataUseCase.SECURITY_MASTER,
            SourceRoute(candidates=("tushare", "akshare")),
        ),
        (
            MarketDataUseCase.MARKET_CALENDAR,
            SourceRoute(candidates=("tushare", "akshare")),
        ),
        (
            MarketDataUseCase.INDEX_BARS,
            SourceRoute(candidates=("akshare",)),
        ),
        (
            MarketDataUseCase.GOLD_BARS,
            SourceRoute(candidates=("akshare",)),
        ),
        (
            MarketDataUseCase.BOND_BARS,
            SourceRoute(candidates=("akshare",)),
        ),
    ),
)

_POLICY_ALIASES = {
    "cn_research_v1": CN_RESEARCH_V1.policy_id,
}
_POLICIES = {
    CN_RESEARCH_V1.policy_id: CN_RESEARCH_V1,
}


def resolve_market_source_policy(policy_id: str | None) -> MarketSourcePolicy:
    normalized = str(policy_id or CN_RESEARCH_V1.policy_id).strip()
    normalized = _POLICY_ALIASES.get(normalized, normalized)
    try:
        return _POLICIES[normalized]
    except KeyError as exc:
        raise ValueError(f"market_source_policy_unsupported:{normalized}") from exc


def legacy_preferred_provider_policy(provider: str) -> MarketSourcePolicy:
    """Compatibility-only route ordering for old runtime/test inputs.

    New production configuration must use an explicit versioned policy id.
    """
    preferred = _provider_name(provider)
    base = CN_RESEARCH_V1
    routes: list[tuple[MarketDataUseCase, SourceRoute]] = []
    for use_case, route in base.routes:
        candidates = (preferred,) + tuple(
            candidate for candidate in route.candidates if candidate != preferred
        )
        routes.append(
            (
                use_case,
                SourceRoute(
                    candidates=candidates,
                    min_sources=route.min_sources,
                    require_independent_upstream=route.require_independent_upstream,
                    price_basis=route.price_basis,
                ),
            )
        )
    return MarketSourcePolicy(
        policy_id=f"karkinos.market.source.compat.{preferred}.v1",
        routes=tuple(routes),
    )


def source_policy_for_config(config: object) -> MarketSourcePolicy:
    policy_id = getattr(config, "market_data_source_policy", None)
    if policy_id:
        return resolve_market_source_policy(str(policy_id))
    legacy_provider = getattr(config, "data_source", None)
    if legacy_provider:
        return legacy_preferred_provider_policy(str(legacy_provider))
    return CN_RESEARCH_V1


def source_candidates_for_config(
    config: object,
    use_case: MarketDataUseCase,
) -> tuple[str, ...]:
    return source_policy_for_config(config).route(use_case).candidates


def preferred_source_for_config(
    config: object,
    use_case: MarketDataUseCase,
) -> str:
    return source_candidates_for_config(config, use_case)[0]
