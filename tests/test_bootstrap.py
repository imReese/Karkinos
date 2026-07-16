import asyncio
import base64
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.types import AssetClass, Symbol
from server.bootstrap import (
    build_strategy,
    build_watchlist,
    create_runtime_context,
    load_runtime_config,
    load_runtime_environment_file,
    load_selected_runtime_environment_file,
    resolve_config_path,
    resolve_data_dir,
)
from server.config import (
    AIProviderConfig,
    BacktestConfig,
    BrokerConnectorConfig,
    BrokerFeeScheduleConfig,
    ControlledBridgePolicyConfig,
    DataSourceProviderConfig,
    ServerConfig,
    TrustedOperatorIdentityConfig,
)


def test_runtime_config_defaults_do_not_seed_real_cash():
    assert BacktestConfig().initial_cash == Decimal("0")
    assert ServerConfig().initial_cash == Decimal("0")


def test_load_runtime_config_prefers_json_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"initial_cash": 321000, "strategy": "dual_ma"}')
    monkeypatch.chdir(tmp_path)

    config = load_runtime_config()

    assert config.initial_cash == Decimal("321000")
    assert config.strategy == "dual_ma"


def test_server_config_loads_grouped_runtime_sections(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": 9000,
                    "live_auto_start": False,
                },
                "data_source": {
                    "provider": "tushare",
                    "live_poll_interval": 120,
                    "provider_config": {"tushare_token_env": "LOCAL_TUSHARE_TOKEN"},
                },
                "broker_fee": {
                    "schedule_id": "grouped-fee-schedule",
                    "stock_a_commission_rate": 0.00015,
                    "stock_a_min_commission": 3,
                },
                "ai": {
                    "enabled": False,
                    "provider": "",
                    "model": "",
                },
            }
        ),
        encoding="utf-8",
    )

    config = ServerConfig.from_json(config_path)

    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.live_auto_start is False
    assert config.data_source == "tushare"
    assert config.tushare_token == ""
    assert config.data_source_provider_config == DataSourceProviderConfig(
        tushare_token_env="LOCAL_TUSHARE_TOKEN"
    )
    assert config.live_poll_interval == 120
    assert config.broker_fee_schedule.schedule_id == "grouped-fee-schedule"
    assert config.broker_fee_schedule.stock_a_commission_rate == Decimal("0.00015")
    assert config.broker_fee_schedule.stock_a_min_commission == Decimal("3")
    assert config.ai == AIProviderConfig()


def test_server_config_rejects_grouped_and_flat_field_conflicts(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "host": "0.0.0.0",
                "server": {"host": "127.0.0.1"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="both grouped and flat"):
        ServerConfig.from_json(config_path)


def test_server_config_rejects_unknown_top_level_and_ai_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"server": {}, "typo_port": 9000}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported top-level fields: typo_port"):
        ServerConfig.from_json(config_path)

    config_path.write_text(
        '{"ai": {"enabled": false, "modle": "typo"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported fields: modle"):
        ServerConfig.from_json(config_path)


def test_server_config_rejects_removed_global_ai_authority_switch(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"ai": {"enabled": false, "allow_financial_context": true}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="allow_financial_context was removed"):
        ServerConfig.from_json(config_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"data_source": {"provider": "tushare", "tushare_token": "secret"}},
            "data_source.tushare_token is not accepted",
        ),
        ({"tushare_token": "secret"}, "tushare_token is not accepted"),
        (
            {"ai": {"enabled": False, "api_keys": {"provider": "secret"}}},
            "ai.api_keys is not accepted",
        ),
        (
            {
                "server": {
                    "notification": {
                        "type": "telegram",
                        "telegram_bot_token": "secret",
                    }
                }
            },
            "notification contains unsupported or credential-bearing fields",
        ),
        (
            {
                "server": {
                    "notification": {
                        "type": "wechat",
                        "wechat_sendkey": "secret",
                    }
                }
            },
            "notification contains unsupported or credential-bearing fields",
        ),
    ],
)
def test_server_config_rejects_credentials_in_json(tmp_path, payload, message):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        ServerConfig.from_json(config_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"server": {"port": "8000"}}, "server.port"),
        ({"server": {"live_auto_start": "true"}}, "live_auto_start"),
        ({"server": {"cors_allowed_origins": []}}, "cors_allowed_origins"),
        ({"data_source": {"provider": "unknown"}}, "data_source.provider"),
        (
            {"data_source": {"provider": "akshare", "live_poll_interval": 14}},
            "live_poll_interval",
        ),
        (
            {
                "data_source": {
                    "provider": "tushare",
                    "provider_config": {"tushare_token_env": "not-valid"},
                }
            },
            "tushare_token_env",
        ),
        (
            {
                "data_source": {
                    "provider": "tushare",
                    "provider_config": {"credential": "secret"},
                }
            },
            "unsupported fields: credential",
        ),
        (
            {
                "ai": {
                    "enabled": False,
                    "base_url": "http://insecure.example",
                }
            },
            "ai.base_url",
        ),
        (
            {"ai": {"enabled": True, "provider": "provider", "model": "model"}},
            "requires ai.provider, ai.model, and ai.base_url",
        ),
    ],
)
def test_server_config_rejects_invalid_grouped_value_types(
    tmp_path,
    payload,
    message,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        ServerConfig.from_json(config_path)


def test_runtime_environment_uses_one_typed_ai_override_path(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ai": {
                    "enabled": False,
                    "provider": "file-provider",
                    "model": "file-model",
                    "base_url": "https://file.example/v1",
                    "timeout_seconds": 20,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("KARKINOS_AI_ENABLED", "true")
    monkeypatch.setenv("KARKINOS_AI_PROVIDER", "environment-provider")
    monkeypatch.setenv("KARKINOS_AI_MODEL", "environment-model")
    monkeypatch.setenv("KARKINOS_AI_BASE_URL", "https://environment.example/v1")
    monkeypatch.setenv("KARKINOS_AI_TIMEOUT_SECONDS", "12.5")

    config = load_runtime_config(ServerConfig)

    assert config.ai == AIProviderConfig(
        enabled=True,
        provider="environment-provider",
        model="environment-model",
        base_url="https://environment.example/v1",
        timeout_seconds=12.5,
    )


def test_dotenv_loader_preserves_process_precedence_and_can_require_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KARKINOS_HOST=dotenv-host\nKARKINOS_PORT=9000\n",
        encoding="utf-8",
    )
    environment = {"KARKINOS_HOST": "process-host"}

    loaded = load_runtime_environment_file(env_file, environ=environment)

    assert loaded is True
    assert environment == {
        "KARKINOS_HOST": "process-host",
        "KARKINOS_PORT": "9000",
    }
    assert (
        load_runtime_environment_file(
            tmp_path / "optional-missing.env",
            environ=environment,
        )
        is False
    )
    with pytest.raises(ValueError, match="does not exist"):
        load_runtime_environment_file(
            tmp_path / "required-missing.env",
            environ=environment,
            required=True,
        )


def test_dotenv_loader_fills_allowlisted_empty_process_credentials(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KARKINOS_TUSHARE_TOKEN=dotenv-token\n"
        "KARKINOS_AI_API_KEY=dotenv-ai-key\n"
        "KARKINOS_TELEGRAM_BOT_TOKEN=dotenv-telegram-token\n",
        encoding="utf-8",
    )
    environment = {
        "KARKINOS_TUSHARE_TOKEN": "",
        "KARKINOS_AI_API_KEY": "  ",
        "KARKINOS_TELEGRAM_BOT_TOKEN": "",
    }

    load_runtime_environment_file(env_file, environ=environment)

    assert environment == {
        "KARKINOS_TUSHARE_TOKEN": "dotenv-token",
        "KARKINOS_AI_API_KEY": "dotenv-ai-key",
        "KARKINOS_TELEGRAM_BOT_TOKEN": "dotenv-telegram-token",
    }


def test_selected_runtime_environment_loader_uses_process_path(
    tmp_path,
    monkeypatch,
):
    env_file = tmp_path / "selected.env"
    env_file.write_text("KARKINOS_PORT=9200\n", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KARKINOS_ENV_FILE", str(env_file))
    monkeypatch.delenv("KARKINOS_PORT", raising=False)

    assert load_selected_runtime_environment_file() is True
    assert load_runtime_config(ServerConfig).port == 9200


def test_server_main_check_config_loads_default_dotenv_without_starting(
    tmp_path,
    monkeypatch,
    capsys,
):
    from server import __main__ as server_main

    (tmp_path / ".env").write_text(
        "KARKINOS_HOST=dotenv-host\nKARKINOS_PORT=9100\n",
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KARKINOS_HOST", raising=False)
    monkeypatch.delenv("KARKINOS_PORT", raising=False)
    monkeypatch.delenv("KARKINOS_CONFIG_PATH", raising=False)
    monkeypatch.delenv("KARKINOS_ENV_FILE", raising=False)
    monkeypatch.setattr(sys, "argv", ["python -m server", "--check-config"])

    server_main.main()

    assert "Karkinos configuration valid: config.json" in capsys.readouterr().out


def test_runtime_environment_overrides_file_and_explicit_values_win(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "server": {"host": "file-host", "port": 8000},
                "data_source": {"provider": "akshare", "live_poll_interval": 60},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("KARKINOS_HOST", "env-host")
    monkeypatch.setenv("KARKINOS_PORT", "9000")
    monkeypatch.setenv("KARKINOS_LIVE_AUTO_START", "false")
    monkeypatch.setenv(
        "KARKINOS_CORS_ALLOWED_ORIGINS",
        "https://one.example, https://two.example",
    )
    monkeypatch.setenv("KARKINOS_DATA_SOURCE", "tushare")
    monkeypatch.setenv("KARKINOS_LIVE_POLL_INTERVAL", "120")
    monkeypatch.setenv("KARKINOS_TUSHARE_TOKEN", "env-token")

    config = load_runtime_config(ServerConfig, host="cli-host")

    assert config.host == "cli-host"
    assert config.port == 9000
    assert config.live_auto_start is False
    assert config.cors_allowed_origins == [
        "https://one.example",
        "https://two.example",
    ]
    assert config.data_source == "tushare"
    assert config.live_poll_interval == 120
    assert config.tushare_token == "env-token"


def test_runtime_environment_uses_configured_tushare_credential_name(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "data_source": {
                    "provider": "tushare",
                    "provider_config": {"tushare_token_env": "LOCAL_TUSHARE_TOKEN"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("LOCAL_TUSHARE_TOKEN", "configured-token")
    monkeypatch.setenv("KARKINOS_TUSHARE_TOKEN", "wrong-default-token")
    monkeypatch.setenv("TUSHARE_TOKEN", "obsolete-token")

    config = load_runtime_config(ServerConfig)

    assert config.data_source_provider_config.tushare_token_env == (
        "LOCAL_TUSHARE_TOKEN"
    )
    assert config.tushare_token == "configured-token"


def test_runtime_environment_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("KARKINOS_LIVE_AUTO_START", "treu")

    with pytest.raises(ValueError, match="KARKINOS_LIVE_AUTO_START"):
        load_runtime_config(ServerConfig)


def test_build_watchlist_maps_asset_classes():
    config = BacktestConfig(
        assets=[
            {"symbol": "600519", "asset_class": "stock"},
            {"symbol": "510300", "asset_class": "etf"},
            {"symbol": "Au99.99", "asset_class": "gold"},
        ]
    )

    watchlist = build_watchlist(config)

    assert watchlist == [
        (Symbol("600519"), AssetClass.STOCK),
        (Symbol("510300"), AssetClass.FUND),
        (Symbol("Au99.99"), AssetClass.GOLD),
    ]


def test_build_strategy_uses_registered_params():
    config = BacktestConfig(strategy="dual_ma", short_period=7, long_period=31)
    event_bus = type(
        "Bus",
        (),
        {"subscribe": lambda *args: None, "publish": lambda *args: None},
    )()

    strategy = build_strategy(config, event_bus)

    assert strategy.short_period == 7
    assert strategy.long_period == 31


def test_create_runtime_context_builds_data_manager_with_default_store(monkeypatch):
    created = {}

    class FakeStore:
        def __init__(self, base_path="data/store"):
            created["store_path"] = base_path

    class FakeDataManager:
        def __init__(self, sources, store=None, default_source="akshare"):
            created["sources"] = sources
            created["store"] = store
            created["default_source"] = default_source

        @staticmethod
        def get_instrument(sym, ac):
            return (sym, ac)

    monkeypatch.setattr("server.bootstrap.DataStore", FakeStore)
    monkeypatch.setattr("server.bootstrap.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "server.bootstrap.build_sources",
        lambda data_source, tushare_token: {data_source: object()},
    )

    context = create_runtime_context(BacktestConfig())

    assert created["store_path"] == "data/store"
    assert created["store"].__class__ is FakeStore
    assert created["default_source"] == "akshare"
    assert context.watchlist == []


def test_create_runtime_context_builds_watchlist_from_explicit_assets(monkeypatch):
    class FakeStore:
        def __init__(self, base_path="data/store"):
            pass

    class FakeDataManager:
        def __init__(self, sources, store=None, default_source="akshare"):
            pass

        @staticmethod
        def get_instrument(sym, ac):
            return (sym, ac)

    monkeypatch.setattr("server.bootstrap.DataStore", FakeStore)
    monkeypatch.setattr("server.bootstrap.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "server.bootstrap.build_sources",
        lambda data_source, tushare_token: {data_source: object()},
    )

    context = create_runtime_context(
        BacktestConfig(assets=[{"symbol": "600519", "asset_class": "stock"}])
    )

    assert context.watchlist[0][0] == Symbol("600519")


def test_backtest_tool_uses_loaded_runtime_config_from_json(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"initial_cash": 200000, "start_date": "2025-01-02", "end_date": "2025-01-05", "assets": [{"symbol": "600519", "asset_class": "stock"}], "strategy": "dual_ma"}'
    )
    monkeypatch.chdir(tmp_path)

    from tools import run_backtest

    captured = {}

    class FakeHandler:
        total_bars = 1

    class FakeManager:
        def get_bars(self, *args, **kwargs):
            return FakeHandler()

    class FakeEngine:
        def __init__(self, strategy, instruments, data_handlers, initial_cash):
            captured["initial_cash"] = initial_cash

        def run(self):
            return SimpleNamespace(
                initial_cash=Decimal("200000"),
                final_equity=Decimal("200000"),
                total_return=Decimal("0"),
                duration_days=3,
                equity_curve=[],
            )

    runtime = SimpleNamespace(
        data_manager=FakeManager(),
        watchlist=[(Symbol("600519"), AssetClass.STOCK)],
        instruments={Symbol("600519"): ("600519", AssetClass.STOCK)},
    )

    monkeypatch.setattr(run_backtest, "create_runtime_context", lambda config: runtime)
    monkeypatch.setattr(
        run_backtest, "build_strategy", lambda config, event_bus: object()
    )
    monkeypatch.setattr(run_backtest, "BacktestEngine", FakeEngine)
    monkeypatch.setattr(run_backtest, "generate_report", lambda result: "ok")

    run_backtest.main([])

    assert captured["initial_cash"] == Decimal("200000")


def test_load_runtime_config_allows_live_auto_start_override(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"live_auto_start": true}')
    monkeypatch.chdir(tmp_path)

    config = load_runtime_config(ServerConfig, live_auto_start=False)

    assert config.live_auto_start is False


def test_load_runtime_config_supports_env_config_path(tmp_path, monkeypatch):
    custom_config = tmp_path / "runtime-config.json"
    custom_config.write_text('{"strategy": "dual_ma", "initial_cash": 555000}')
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(custom_config))

    config = load_runtime_config()

    assert resolve_config_path() == custom_config
    assert config.initial_cash == Decimal("555000")


def test_server_config_loads_local_read_only_broker_connector_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_connectors": [
                    {
                        "connector_id": "local-fixture-readonly",
                        "connector_type": "local_export_readonly",
                        "enabled": True,
                        "client_path": "data/private/broker-snapshot.json",
                        "account_alias": "local-review",
                    }
                ]
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.broker_connectors == [
        BrokerConnectorConfig(
            connector_id="local-fixture-readonly",
            connector_type="local_export_readonly",
            enabled=True,
            client_path="data/private/broker-snapshot.json",
            account_alias="local-review",
        )
    ]


def test_server_config_rejects_broker_connector_credential_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_connectors": [
                    {
                        "connector_id": "local-fixture-readonly",
                        "connector_type": "local_export_readonly",
                        "client_path": "data/private/broker-snapshot.json",
                        "account_alias": "local-review",
                        "broker_password": "do-not-store",
                    }
                ]
            }
        )
    )

    with pytest.raises(ValueError, match="broker connector config"):
        ServerConfig.from_json(config_path)


def test_server_config_rejects_non_boolean_broker_connector_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_connectors": [
                    {
                        "connector_id": "local-fixture-readonly",
                        "enabled": "false",
                    }
                ]
            }
        )
    )

    with pytest.raises(ValueError, match="enabled must be boolean"):
        ServerConfig.from_json(config_path)


def test_server_config_loads_controlled_bridge_policy_whitelist(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "controlled_bridge_policy": {
                    "policy_id": "local-controlled-bridge-review",
                    "enabled": True,
                    "allowed_connector_ids": ["local-qmt-readonly"],
                    "allowed_account_aliases": ["local-review"],
                    "allowed_strategy_ids": ["dual_ma"],
                    "allowed_symbols": ["600519"],
                    "per_order_confirmation_required": True,
                    "automation_allowed": False,
                }
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.controlled_bridge_policy == ControlledBridgePolicyConfig(
        policy_id="local-controlled-bridge-review",
        enabled=True,
        allowed_connector_ids=("local-qmt-readonly",),
        allowed_account_aliases=("local-review",),
        allowed_strategy_ids=("dual_ma",),
        allowed_symbols=("600519",),
        per_order_confirmation_required=True,
        automation_allowed=False,
    )


def test_server_config_rejects_controlled_bridge_policy_automation_enabled(
    tmp_path,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "controlled_bridge_policy": {
                    "enabled": True,
                    "automation_allowed": True,
                }
            }
        )
    )

    with pytest.raises(ValueError, match="controlled bridge policy"):
        ServerConfig.from_json(config_path)


def test_server_config_rejects_controlled_bridge_policy_secret_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "controlled_bridge_policy": {
                    "enabled": True,
                    "allowed_connector_ids": ["local-qmt-readonly"],
                    "broker_token": "do-not-store",
                }
            }
        )
    )

    with pytest.raises(ValueError, match="controlled bridge policy"):
        ServerConfig.from_json(config_path)


def test_server_config_loads_public_key_only_trusted_operator_identity(tmp_path):
    public_key_base64 = base64.b64encode(b"\x01" * 32).decode("ascii")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "trusted_operator_identities": [
                    {
                        "operator_id": "local-owner",
                        "key_id": "owner-key-1",
                        "algorithm": "ed25519",
                        "public_key_base64": public_key_base64,
                        "enabled": True,
                    }
                ]
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.trusted_operator_identities == [
        TrustedOperatorIdentityConfig(
            operator_id="local-owner",
            key_id="owner-key-1",
            algorithm="ed25519",
            public_key_base64=public_key_base64,
            enabled=True,
        )
    ]


@pytest.mark.parametrize(
    "identity, message",
    [
        (
            {
                "operator_id": "local-owner",
                "key_id": "owner-key-1",
                "algorithm": "rsa",
                "public_key_base64": base64.b64encode(b"\x01" * 32).decode("ascii"),
                "enabled": True,
            },
            "algorithm",
        ),
        (
            {
                "operator_id": "local-owner",
                "key_id": "owner-key-1",
                "algorithm": "ed25519",
                "public_key_base64": "not-base64",
                "enabled": True,
            },
            "valid base64",
        ),
        (
            {
                "operator_id": "local-owner",
                "key_id": "owner-key-1",
                "algorithm": "ed25519",
                "public_key_base64": base64.b64encode(b"short").decode("ascii"),
                "enabled": True,
            },
            "32 bytes",
        ),
        (
            {
                "operator_id": "local-owner",
                "key_id": "owner-key-1",
                "algorithm": "ed25519",
                "public_key_base64": base64.b64encode(b"\x01" * 32).decode("ascii"),
                "private_key": "must-not-be-accepted",
                "enabled": True,
            },
            "unsupported fields",
        ),
        (
            {
                "operator_id": "local owner with spaces",
                "key_id": "owner-key-1",
                "algorithm": "ed25519",
                "public_key_base64": base64.b64encode(b"\x01" * 32).decode("ascii"),
                "enabled": True,
            },
            "operator_id invalid",
        ),
        (
            {
                "operator_id": "local-owner",
                "key_id": "owner/key/invalid",
                "algorithm": "ed25519",
                "public_key_base64": base64.b64encode(b"\x01" * 32).decode("ascii"),
                "enabled": True,
            },
            "key_id invalid",
        ),
    ],
)
def test_server_config_rejects_invalid_or_private_operator_key_fields(
    tmp_path,
    identity,
    message,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"trusted_operator_identities": [identity]}))

    with pytest.raises(ValueError, match=message):
        ServerConfig.from_json(config_path)


def test_server_config_loads_structured_broker_fee_schedule(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_fee_schedule": {
                    "schedule_id": "local-cash-account",
                    "account_profile_id": "primary-citic-securities",
                    "broker_name": "中信证券",
                    "stock_a_commission_rate": 0.00015,
                    "stock_a_min_commission": 5,
                    "fund_etf_commission_rate": 0.00015,
                    "fund_etf_min_commission": 5,
                    "stamp_tax_rate": 0.0005,
                    "transfer_fee_rate": 0.00001,
                    "exchange_transfer_fee_rates": {
                        "shanghai": 0.00001,
                        "shenzhen": 0,
                    },
                    "other_fee_rate": 0,
                    "limitations": [
                        "transfer_fee_exchange_not_split",
                        "broker_regulatory_fees_assumed_absorbed",
                    ],
                }
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.broker_fee_schedule == BrokerFeeScheduleConfig(
        schedule_id="local-cash-account",
        account_profile_id="primary-citic-securities",
        broker_name="中信证券",
        stock_a_commission_rate=Decimal("0.00015"),
        stock_a_min_commission=Decimal("5"),
        fund_etf_commission_rate=Decimal("0.00015"),
        fund_etf_min_commission=Decimal("5"),
        stamp_tax_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        exchange_transfer_fee_rates={
            "shanghai": Decimal("0.00001"),
            "shenzhen": Decimal("0"),
        },
        other_fee_rate=Decimal("0"),
        limitations=("broker_regulatory_fees_assumed_absorbed",),
    )
    assert config.account_commission_rate == Decimal("0.00015")
    assert config.account_min_commission == Decimal("5")


def test_server_config_migrates_legacy_account_cost_fields_to_broker_fee_schedule(
    tmp_path,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "account_commission_rate": 0.00015,
                "account_min_commission": 3,
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.account_commission_rate == Decimal("0.00015")
    assert config.account_min_commission == Decimal("3")
    assert config.broker_fee_schedule.stock_a_commission_rate == Decimal("0.00015")
    assert config.broker_fee_schedule.stock_a_min_commission == Decimal("3")


def test_server_config_loads_detailed_safe_broker_fee_schedule(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_fee_schedule": {
                    "source": "public_broker_fee_table",
                    "currency": "CNY",
                    "captured_at": "2026-06-22",
                    "account_identifier_saved": False,
                    "screenshots_saved": False,
                    "commission": {
                        "stock_a": {"sh": 0.00015, "sz": 0.00015},
                        "fund_etf": {"rate": 0.00012},
                    },
                    "taxes_and_fees": {
                        "stamp_tax": {"sell": 0.0005},
                        "transfer_fee": {
                            "rate": 0.00001,
                            "sh": 0.00001,
                            "sz": 0,
                        },
                    },
                }
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.broker_fee_schedule.schedule_id == "public_broker_fee_table"
    assert config.broker_fee_schedule.stock_a_commission_rate == Decimal("0.00015")
    assert config.broker_fee_schedule.fund_etf_commission_rate == Decimal("0.00012")
    assert config.broker_fee_schedule.stamp_tax_rate == Decimal("0.0005")
    assert config.broker_fee_schedule.transfer_fee_rate == Decimal("0.00001")
    assert config.broker_fee_schedule.exchange_transfer_fee_rates == {
        "shanghai": Decimal("0.00001"),
        "shenzhen": Decimal("0"),
    }
    assert (
        "nested_fee_schedule_flattened_for_current_contract"
        in config.broker_fee_schedule.limitations
    )


def test_server_config_derives_runtime_terms_from_broker_fee_schedule_rules(
    tmp_path,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_fee_schedule": {
                    "schema_version": "karkinos.broker_fee_schedule.v1",
                    "account_profile_id": "sample-broker-account",
                    "broker_name": "示例券商",
                    "display_name": "示例券商88**16账户费用规则",
                    "account_identifier_saved": False,
                    "screenshots_saved": False,
                    "private_exports_saved": False,
                    "rules": [
                        {
                            "id": "stock_a_commission_sse",
                            "component": "commission",
                            "asset_classes": ["stock"],
                            "instrument_types": ["a_share"],
                            "markets": ["SSE"],
                            "side": "both",
                            "rate": "0.00015",
                            "min_fee": "5.00",
                        },
                        {
                            "id": "fund_etf_commission_sse",
                            "component": "commission",
                            "asset_classes": ["fund", "etf"],
                            "instrument_types": ["etf", "lof"],
                            "markets": ["SSE"],
                            "side": "both",
                            "rate": "0.00012",
                            "min_fee": "3.00",
                        },
                        {
                            "id": "stock_stamp_tax_sell",
                            "component": "stamp_tax",
                            "asset_classes": ["stock"],
                            "markets": ["SSE", "SZSE"],
                            "side": "sell",
                            "rate": "0.00050",
                        },
                        {
                            "id": "stock_transfer_fee_sse",
                            "component": "transfer_fee",
                            "asset_classes": ["stock"],
                            "markets": ["SSE"],
                            "side": "both",
                            "rate": "0.00001",
                        },
                        {
                            "id": "stock_transfer_fee_szse_broker_absorbed",
                            "component": "transfer_fee",
                            "asset_classes": ["stock"],
                            "markets": ["SZSE"],
                            "side": "both",
                            "rate": "0",
                            "included_in_total_fee": False,
                        },
                    ],
                }
            }
        )
    )

    config = ServerConfig.from_json(config_path)

    assert config.broker_fee_schedule.stock_a_commission_rate == Decimal("0.00015")
    assert config.broker_fee_schedule.stock_a_min_commission == Decimal("5.00")
    assert config.broker_fee_schedule.fund_etf_commission_rate == Decimal("0.00012")
    assert config.broker_fee_schedule.fund_etf_min_commission == Decimal("3.00")
    assert config.broker_fee_schedule.stamp_tax_rate == Decimal("0.00050")
    assert config.broker_fee_schedule.transfer_fee_rate == Decimal("0.00001")
    assert config.broker_fee_schedule.exchange_transfer_fee_rates == {
        "shanghai": Decimal("0.00001"),
        "shenzhen": Decimal("0"),
    }


def test_server_config_rejects_broker_fee_schedule_with_saved_private_artifacts(
    tmp_path,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_fee_schedule": {
                    "source": "public_broker_fee_table",
                    "account_identifier_saved": True,
                }
            }
        )
    )

    with pytest.raises(ValueError, match="broker fee schedule"):
        ServerConfig.from_json(config_path)


def test_server_config_rejects_broker_fee_schedule_secret_fields(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "broker_fee_schedule": {
                    "schedule_id": "local-cash-account",
                    "broker_token": "do-not-store",
                }
            }
        )
    )

    with pytest.raises(ValueError, match="broker fee schedule"):
        ServerConfig.from_json(config_path)


def test_example_broker_connector_config_contains_no_credentials() -> None:
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

    assert "config.json" in gitignore
    assert example["server"] == {
        "host": "127.0.0.1",
        "port": 8000,
        "live_auto_start": True,
        "cors_allowed_origins": [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        "notification": {"type": "console"},
    }
    assert example["data_source"] == {
        "provider": "akshare",
        "live_poll_interval": 60,
        "provider_config": {
            "tushare_token_env": "KARKINOS_TUSHARE_TOKEN",
        },
    }
    assert example["ai"] == {
        "enabled": False,
        "provider": "",
        "model": "",
        "base_url": "",
        "adapter_kind": "openai_compatible_https",
        "timeout_seconds": 20,
        "api_key_env": "KARKINOS_AI_API_KEY",
    }
    assert set(example) == {"server", "data_source", "broker_fee", "ai"}
    assert "schema_version" not in example["broker_fee"]
    assert not _contains_sensitive_key(example["broker_fee"])
    assert "api_keys" not in example["ai"]

    environment_template = Path(".env.example").read_text(encoding="utf-8")
    for env_name in (
        "KARKINOS_TUSHARE_TOKEN",
        "KARKINOS_HOST",
        "KARKINOS_PORT",
        "KARKINOS_LIVE_AUTO_START",
        "KARKINOS_CORS_ALLOWED_ORIGINS",
        "KARKINOS_CONFIG_PATH",
        "KARKINOS_DATA_DIR",
        "KARKINOS_DATA_SOURCE",
        "KARKINOS_LIVE_POLL_INTERVAL",
        "KARKINOS_TELEGRAM_BOT_TOKEN",
        "KARKINOS_TELEGRAM_CHAT_ID",
        "KARKINOS_WECHAT_SENDKEY",
        "KARKINOS_AI_ENABLED",
        "KARKINOS_AI_PROVIDER",
        "KARKINOS_AI_MODEL",
        "KARKINOS_AI_BASE_URL",
        "KARKINOS_AI_ADAPTER_KIND",
        "KARKINOS_AI_TIMEOUT_SECONDS",
        "KARKINOS_AI_API_KEY",
    ):
        assert f"{env_name}=" in environment_template

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for env_name in (
        "KARKINOS_TUSHARE_TOKEN",
        "KARKINOS_HOST",
        "KARKINOS_PORT",
        "KARKINOS_LIVE_AUTO_START",
        "KARKINOS_CORS_ALLOWED_ORIGINS",
        "KARKINOS_DATA_SOURCE",
        "KARKINOS_LIVE_POLL_INTERVAL",
        "KARKINOS_TELEGRAM_BOT_TOKEN",
        "KARKINOS_TELEGRAM_CHAT_ID",
        "KARKINOS_WECHAT_SENDKEY",
        "KARKINOS_AI_ENABLED",
        "KARKINOS_AI_PROVIDER",
        "KARKINOS_AI_MODEL",
        "KARKINOS_AI_BASE_URL",
        "KARKINOS_AI_ADAPTER_KIND",
        "KARKINOS_AI_TIMEOUT_SECONDS",
        "KARKINOS_AI_API_KEY",
    ):
        assert f"{env_name}=" in compose


def test_server_main_preserves_live_auto_start_env_for_reload(monkeypatch):
    from server import __main__ as server_main

    captured = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["live_auto_start"] = __import__("os").environ.get(
            "KARKINOS_LIVE_AUTO_START"
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m server", "--reload", "--host", "127.0.0.1", "--port", "8000"],
    )
    monkeypatch.setenv("KARKINOS_LIVE_AUTO_START", "true")
    monkeypatch.setattr("uvicorn.run", fake_run)

    server_main.main()

    assert captured["args"] == ("server.app:create_app",)
    assert captured["kwargs"]["reload"] is True
    assert captured["live_auto_start"] == "true"


def _contains_sensitive_key(value) -> bool:
    sensitive_parts = ("password", "secret", "token", "credential")
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in sensitive_parts)
            or _contains_sensitive_key(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def test_create_runtime_context_supports_env_data_dir(monkeypatch):
    created = {}

    class FakeStore:
        def __init__(self, base_path="data/store"):
            created["store_path"] = base_path

    class FakeDataManager:
        def __init__(self, sources, store=None, default_source="akshare"):
            created["store"] = store

        @staticmethod
        def get_instrument(sym, ac):
            return (sym, ac)

    monkeypatch.setenv("KARKINOS_DATA_DIR", "/tmp/karkinos-data")
    monkeypatch.setattr("server.bootstrap.DataStore", FakeStore)
    monkeypatch.setattr("server.bootstrap.DataManager", FakeDataManager)
    monkeypatch.setattr(
        "server.bootstrap.build_sources",
        lambda data_source, tushare_token: {data_source: object()},
    )

    create_runtime_context(BacktestConfig())

    assert resolve_data_dir() == "/tmp/karkinos-data"
    assert created["store_path"] == "/tmp/karkinos-data"


def test_create_app_accepts_config_overrides():
    from server.app import create_app

    app = create_app({"live_auto_start": False})

    assert app.state.config_overrides == {"live_auto_start": False}


def test_create_app_caches_startup_runtime_config(monkeypatch):
    from server.app import create_app

    monkeypatch.delenv("KARKINOS_LIVE_AUTO_START", raising=False)
    runtime_config = ServerConfig(
        live_auto_start=False,
        cors_allowed_origins=["https://karkinos.example.com"],
    )
    calls = []

    def fake_load_runtime_config(config_cls, **overrides):
        calls.append((config_cls, overrides))
        return runtime_config

    monkeypatch.setattr(
        "server.bootstrap.load_runtime_config", fake_load_runtime_config
    )

    app = create_app({"live_auto_start": False})

    assert calls == [(ServerConfig, {"live_auto_start": False})]
    assert app.state.runtime_config is runtime_config
    assert _cors_middleware_options(app)["allow_origins"] == [
        "https://karkinos.example.com"
    ]


def test_lifespan_reuses_cached_runtime_config(monkeypatch):
    from server import app as app_module

    runtime_config = ServerConfig(live_auto_start=False)
    fake_app = SimpleNamespace(
        state=SimpleNamespace(config_overrides={}, runtime_config=runtime_config)
    )

    class FakeDB:
        async def init(self):
            pass

    class FakeBridge:
        def __init__(self, event_bus, loop):
            pass

        async def get_event(self):
            await asyncio.Event().wait()

        def stop(self):
            pass

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            pass

    monkeypatch.setattr(
        "server.bootstrap.load_runtime_config",
        lambda *args, **kwargs: pytest.fail("config should already be cached"),
    )
    monkeypatch.setattr(app_module, "AppDatabase", FakeDB)
    monkeypatch.setattr(app_module, "EventBusBridge", FakeBridge)
    monkeypatch.setattr(app_module, "TradingScheduler", FakeScheduler)
    monkeypatch.setattr(
        app_module, "TradingControlState", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        "notification.notifier.build_notifier", lambda notification: object()
    )
    monkeypatch.setattr(
        app_module, "_confirm_pending_fund_orders_on_startup", lambda state: None
    )
    app_module._app_state = None

    async def run_lifespan():
        async with app_module.lifespan(fake_app):
            assert app_module.get_app_state().config is runtime_config
            assert fake_app.state.config is runtime_config

    try:
        asyncio.run(run_lifespan())
    finally:
        app_module._app_state = None


def _cors_middleware_options(app):
    middleware = next(
        item for item in app.user_middleware if item.cls.__name__ == "CORSMiddleware"
    )
    return middleware.kwargs


def test_create_app_uses_local_dev_cors_defaults(monkeypatch):
    from server.app import create_app

    monkeypatch.delenv("KARKINOS_CORS_ALLOWED_ORIGINS", raising=False)

    app = create_app()
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert cors_options["allow_credentials"] is True


def test_create_app_accepts_cors_origins_from_config_file(
    tmp_path,
    monkeypatch,
):
    from server.app import create_app

    config_path = tmp_path / "config.json"
    config_path.write_text('{"cors_allowed_origins": ["https://karkinos.example.com"]}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KARKINOS_CORS_ALLOWED_ORIGINS", raising=False)

    app = create_app()
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == ["https://karkinos.example.com"]
    assert cors_options["allow_credentials"] is True


def test_create_app_accepts_cors_origins_from_env(monkeypatch):
    from server.app import create_app

    monkeypatch.setenv(
        "KARKINOS_CORS_ALLOWED_ORIGINS",
        "https://karkinos.example.com, http://localhost:5173",
    )

    app = create_app()
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == [
        "https://karkinos.example.com",
        "http://localhost:5173",
    ]
    assert cors_options["allow_credentials"] is True


def test_create_app_disables_cors_credentials_for_explicit_wildcard():
    from server.app import create_app

    app = create_app({"cors_allowed_origins": ["*"]})
    cors_options = _cors_middleware_options(app)

    assert cors_options["allow_origins"] == ["*"]
    assert cors_options["allow_credentials"] is False


def test_create_app_serves_spa_index_for_client_routes(monkeypatch, tmp_path):
    from server import app as app_module

    _run_staticfile_threadpool_inline(monkeypatch)

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>karkinos-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    for route in ["", "portfolio", "activity", "risk", "market", "settings"]:
        response = __import__("asyncio").run(
            static.get_response(
                route,
                {
                    "type": "http",
                    "method": "GET",
                    "path": f"/{route}" if route else "/",
                    "headers": [],
                },
            )
        )

        assert response.status_code == 200
        assert response.path.endswith("index.html")


def test_create_app_does_not_fallback_reserved_backend_namespaces(
    monkeypatch, tmp_path
):
    from server import app as app_module

    _run_staticfile_threadpool_inline(monkeypatch)

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>karkinos-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    for route in ["api/missing", "ws/missing"]:
        with pytest.raises(StarletteHTTPException) as exc_info:
            __import__("asyncio").run(
                static.get_response(
                    route,
                    {
                        "type": "http",
                        "method": "GET",
                        "path": f"/{route}",
                        "headers": [],
                    },
                )
            )

        assert exc_info.value.status_code == 404


def test_create_app_keeps_missing_static_assets_as_404(monkeypatch, tmp_path):
    from server import app as app_module

    _run_staticfile_threadpool_inline(monkeypatch)

    dist_dir = tmp_path / "web" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>karkinos-spa</body></html>")

    original_path = Path

    def fake_path(value="."):
        if value == "web/dist":
            return original_path(dist_dir)
        return original_path(value)

    monkeypatch.setattr(app_module, "Path", fake_path)

    static = app_module.SPAStaticFiles(directory=str(dist_dir), html=True)
    with pytest.raises(StarletteHTTPException) as exc_info:
        __import__("asyncio").run(
            static.get_response(
                "assets/missing.js",
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/assets/missing.js",
                    "headers": [],
                },
            )
        )

    assert exc_info.value.status_code == 404


def _run_staticfile_threadpool_inline(monkeypatch):
    import starlette.staticfiles as staticfiles

    async def run_sync_inline(func, *args, **kwargs):
        return func(*args)

    monkeypatch.setattr(staticfiles.anyio.to_thread, "run_sync", run_sync_inline)
