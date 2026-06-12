#!/usr/bin/env python3
"""Configure Karkinos local data-source settings safely."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from typing import Any, Callable

Provider = str
TokenReader = Callable[[], str]

SUPPORTED_PROVIDERS = ("akshare", "tushare")


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
    return parser.parse_args(argv)


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text())


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def save_data_source_config(
    *,
    config_path: Path,
    provider: Provider,
    token_reader: TokenReader,
) -> dict[str, Any]:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported data source provider: {provider}")

    config = load_config(config_path)
    config["data_source"] = provider

    if provider == "akshare":
        config.pop("tushare_token", None)
    else:
        token = token_reader().strip()
        if not token:
            raise ValueError("TuShare token is required when provider is tushare")
        config["tushare_token"] = token

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
    provider = args.provider or prompt_provider()

    save_data_source_config(
        config_path=config_path,
        provider=provider,
        token_reader=lambda: getpass.getpass("TuShare token: "),
    )

    print(f"Saved local data source provider: {provider}")
    print(f"Local runtime config: {config_path}")
    print("Do not commit config.json or paste tokens into commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
