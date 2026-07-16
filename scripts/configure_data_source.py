#!/usr/bin/env python3
"""Configure Karkinos local data-source settings safely."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from dotenv import set_key

from server.config_contract import SUPPORTED_DATA_SOURCES

Provider = str
TokenReader = Callable[[], str]

SUPPORTED_PROVIDERS = tuple(sorted(SUPPORTED_DATA_SOURCES))
_ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_DEFAULT_TUSHARE_TOKEN_ENV = "KARKINOS_TUSHARE_TOKEN"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Configure the ignored local config.json data source. "
            "Tokens are entered interactively and are never accepted as CLI args."
        )
    )
    parser.add_argument(
        "--config-path",
        default="config.json",
        help="Local runtime config path. Defaults to ./config.json.",
    )
    parser.add_argument(
        "--provider",
        choices=SUPPORTED_PROVIDERS,
        help="Data source provider to configure.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Credential environment file. Defaults to KARKINOS_ENV_FILE or ./.env.",
    )
    return parser.parse_args(argv)


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text())


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def save_tushare_environment_token(
    env_path: Path,
    token: str,
    *,
    env_name: str = _DEFAULT_TUSHARE_TOKEN_ENV,
) -> None:
    """Persist the TuShare credential without placing it in JSON."""
    if not _ENV_NAME_PATTERN.fullmatch(env_name):
        raise ValueError("TuShare token environment variable name is invalid")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.touch(mode=0o600)
    set_key(str(env_path), env_name, token, quote_mode="always")
    env_path.chmod(0o600)


def save_data_source_config(
    *,
    config_path: Path,
    env_path: Path,
    provider: Provider,
    token_reader: TokenReader,
) -> dict[str, Any]:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported data source provider: {provider}")

    config = load_config(config_path)
    raw_data_source = config.get("data_source")
    if isinstance(raw_data_source, dict):
        data_source = dict(raw_data_source)
    elif isinstance(raw_data_source, str):
        data_source = {"provider": raw_data_source}
    else:
        data_source = {}

    raw_provider_config = data_source.get("provider_config")
    if raw_provider_config is None:
        provider_config: dict[str, Any] = {}
    elif isinstance(raw_provider_config, dict):
        provider_config = dict(raw_provider_config)
    else:
        raise ValueError("data_source.provider_config must be an object")
    unknown_provider_fields = sorted(set(provider_config) - {"tushare_token_env"})
    if unknown_provider_fields:
        raise ValueError(
            "data_source.provider_config contains unsupported fields: "
            + ", ".join(unknown_provider_fields)
        )
    tushare_token_env = str(
        provider_config.get("tushare_token_env") or _DEFAULT_TUSHARE_TOKEN_ENV
    )
    if not _ENV_NAME_PATTERN.fullmatch(tushare_token_env):
        raise ValueError(
            "data_source.provider_config.tushare_token_env name is invalid"
        )

    if "tushare_token" in config or "tushare_token" in data_source:
        raise ValueError(
            "tushare_token is not accepted in config.json; remove it and use "
            "the environment variable named by "
            "data_source.provider_config.tushare_token_env"
        )
    if "live_poll_interval" in config:
        data_source["live_poll_interval"] = config.pop("live_poll_interval")
    data_source["provider"] = provider

    if provider == "akshare":
        if env_path.exists():
            env_path.chmod(0o600)
    else:
        token = token_reader().strip()
        if not token:
            raise ValueError("TuShare token is required when provider is tushare")
        save_tushare_environment_token(
            env_path,
            token,
            env_name=tushare_token_env,
        )

    config["data_source"] = data_source
    save_config(config_path, config)
    return config


def prompt_provider() -> Provider:
    print("Choose market data source:")
    print("  1) akshare  - no token required")
    print("  2) tushare  - requires a TuShare token")
    choice = input("Provider [akshare/tushare, default akshare]: ").strip().lower()
    if choice in {"", "1", "akshare"}:
        return "akshare"
    if choice in {"2", "tushare"}:
        return "tushare"
    raise ValueError(f"Unsupported data source provider: {choice}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config_path)
    env_path = Path(args.env_file or os.environ.get("KARKINOS_ENV_FILE") or ".env")
    provider = args.provider or prompt_provider()

    save_data_source_config(
        config_path=config_path,
        env_path=env_path,
        provider=provider,
        token_reader=lambda: getpass.getpass("TuShare token: "),
    )

    print(f"Saved local data source provider: {provider}")
    print(f"Local runtime config: {config_path}")
    print(f"Credential environment file: {env_path}")
    print("Do not commit config.json/.env or paste tokens into commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
