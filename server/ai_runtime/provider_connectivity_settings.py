"""Startup configuration and credential resolution for the provider edge."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from server.config import AIProviderConfig, BacktestConfig

from .provider_connectivity_contracts import (
    ConnectivityConfigurationError,
    ProviderConnectivitySettings,
)

_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_PROVIDER_ENV_PATTERN = re.compile(r"[^A-Z0-9]+")


def load_provider_connectivity_settings(
    runtime_config: BacktestConfig | AIProviderConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> ProviderConnectivitySettings:
    """Resolve one startup-validated provider config and its edge credential."""
    environment = os.environ if environ is None else environ
    if isinstance(runtime_config, AIProviderConfig):
        ai = runtime_config
    elif isinstance(runtime_config, BacktestConfig):
        ai = runtime_config.ai
    else:
        raise ConnectivityConfigurationError("AI startup config is unavailable")
    provider_id = ai.provider.strip()
    api_key, credential_source = resolve_api_key(
        ai=ai,
        provider_id=provider_id,
        environment=environment,
    )
    return ProviderConnectivitySettings(
        provider_id=provider_id,
        model_name=ai.model.strip(),
        base_url=ai.base_url.strip(),
        api_key=api_key,
        credential_source=credential_source,
        adapter_kind=ai.adapter_kind.strip(),
        enabled=ai.enabled,
        timeout_seconds=ai.timeout_seconds,
    )


def resolve_api_key(
    *,
    ai: AIProviderConfig,
    provider_id: str,
    environment: Mapping[str, str],
) -> tuple[str, str]:
    generic = str(environment.get("KARKINOS_AI_API_KEY") or "").strip()
    if generic:
        return generic, "environment:KARKINOS_AI_API_KEY"
    configured_env_name = ai.api_key_env.strip()
    if configured_env_name:
        if not _ENV_NAME_PATTERN.fullmatch(configured_env_name):
            raise ConnectivityConfigurationError("AI api_key_env name is invalid")
        configured = str(environment.get(configured_env_name) or "").strip()
        if configured:
            return configured, f"environment:{configured_env_name}"
    provider_env_name = (
        _PROVIDER_ENV_PATTERN.sub("_", provider_id.upper()).strip("_") + "_API_KEY"
    )
    if provider_env_name != "_API_KEY":
        provider_value = str(environment.get(provider_env_name) or "").strip()
        if provider_value:
            return provider_value, f"environment:{provider_env_name}"
    return "", "missing"


__all__ = ["load_provider_connectivity_settings", "resolve_api_key"]
