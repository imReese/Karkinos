"""Provider construction and capability registry for market-data source policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from data.market.contracts import (
    DailyBarProvider,
    MarketDataProviderDescriptor,
)
from data.source import DataSource


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    name: str
    upstream_group: str
    legacy_factory: Callable[[], DataSource] | None = None
    daily_bar_factory: Callable[[], DailyBarProvider] | None = None

    def __post_init__(self) -> None:
        name = _text(self.name, field="name")
        upstream_group = _text(self.upstream_group, field="upstream_group")
        if self.legacy_factory is None and self.daily_bar_factory is None:
            raise ValueError("provider_registration_has_no_capabilities")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "upstream_group", upstream_group)


class ProviderRegistry:
    """Credential-aware provider factory registry.

    Registry membership means the runtime can construct the adapter.  It does
    not claim remote availability or successful authentication.
    """

    def __init__(self, registrations: tuple[ProviderRegistration, ...]) -> None:
        by_name: dict[str, ProviderRegistration] = {}
        for registration in registrations:
            if not isinstance(registration, ProviderRegistration):
                raise TypeError("provider_registry_registration_invalid")
            if registration.name in by_name:
                raise ValueError("provider_registry_duplicate")
            by_name[registration.name] = registration
        self._registrations = by_name

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def registration(self, name: str) -> ProviderRegistration:
        normalized = _text(name, field="name")
        try:
            return self._registrations[normalized]
        except KeyError as exc:
            raise KeyError(f"provider_not_registered:{normalized}") from exc

    def build_legacy(self, name: str) -> DataSource:
        registration = self.registration(name)
        if registration.legacy_factory is None:
            raise ValueError(
                f"provider_legacy_capability_unavailable:{registration.name}"
            )
        return registration.legacy_factory()

    def build_daily_bar(self, name: str) -> DailyBarProvider:
        registration = self.registration(name)
        if registration.daily_bar_factory is None:
            raise ValueError(
                f"provider_daily_bar_capability_unavailable:{registration.name}"
            )
        provider = registration.daily_bar_factory()
        descriptor = provider.descriptor
        self._validate_descriptor(registration, descriptor)
        return provider

    def legacy_sources(
        self,
        candidates: tuple[str, ...] | None = None,
    ) -> dict[str, DataSource]:
        names = candidates or self.names
        result: dict[str, DataSource] = {}
        for name in names:
            registration = self._registrations.get(name)
            if registration is None or registration.legacy_factory is None:
                continue
            result[name] = registration.legacy_factory()
        return result

    def daily_bar_providers(
        self,
        candidates: tuple[str, ...],
    ) -> tuple[tuple[str, DailyBarProvider], ...]:
        result: list[tuple[str, DailyBarProvider]] = []
        for name in candidates:
            registration = self._registrations.get(name)
            if registration is None or registration.daily_bar_factory is None:
                continue
            result.append((name, self.build_daily_bar(name)))
        return tuple(result)

    @staticmethod
    def _validate_descriptor(
        registration: ProviderRegistration,
        descriptor: MarketDataProviderDescriptor,
    ) -> None:
        if descriptor.provider != registration.name:
            raise ValueError("provider_registry_descriptor_name_mismatch")
        if descriptor.upstream_group != registration.upstream_group:
            raise ValueError("provider_registry_descriptor_upstream_mismatch")


def build_provider_registry(
    *,
    tushare_token: str = "",
    include_tdx: bool = True,
) -> ProviderRegistry:
    """Build the supported local provider registry without performing I/O."""
    from data.providers.akshare_daily import AkshareDailyBarProvider
    from data.providers.akshare_source import AKShareSource
    from data.providers.akshare_tencent_daily import AkshareTencentDailyBarProvider
    from data.providers.baostock_daily import BaoStockDailyBarProvider
    from data.providers.tdx import TdxDailyBarProvider
    from data.providers.tencent import TencentDailyBarProvider, TencentSource
    from data.providers.tushare_daily import TushareDailyBarProvider
    from data.providers.tushare_source import TushareSource

    registrations: list[ProviderRegistration] = [
        ProviderRegistration(
            name="tencent",
            upstream_group="tencent",
            legacy_factory=TencentSource,
            daily_bar_factory=TencentDailyBarProvider,
        ),
        ProviderRegistration(
            name="akshare_tencent",
            upstream_group="tencent",
            legacy_factory=TencentSource,
            daily_bar_factory=AkshareTencentDailyBarProvider,
        ),
        ProviderRegistration(
            name="akshare",
            upstream_group="eastmoney",
            legacy_factory=AKShareSource,
            daily_bar_factory=AkshareDailyBarProvider,
        ),
        ProviderRegistration(
            name="baostock",
            upstream_group="baostock",
            daily_bar_factory=BaoStockDailyBarProvider,
        ),
    ]
    if tushare_token:
        registrations.append(
            ProviderRegistration(
                name="tushare",
                upstream_group="tushare",
                legacy_factory=lambda: TushareSource(token=tushare_token),
                daily_bar_factory=lambda: TushareDailyBarProvider(token=tushare_token),
            )
        )
    if include_tdx:
        registrations.append(
            ProviderRegistration(
                name="tdx",
                upstream_group="tdx",
                daily_bar_factory=TdxDailyBarProvider,
            )
        )
    return ProviderRegistry(tuple(registrations))


def configured_legacy_sources(
    config: object,
    *,
    candidates: tuple[str, ...] | None = None,
) -> dict[str, DataSource]:
    return build_provider_registry(
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
        include_tdx=False,
    ).legacy_sources(candidates)


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"provider_registry_{field}_must_be_text")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"provider_registry_{field}_missing")
    return normalized
