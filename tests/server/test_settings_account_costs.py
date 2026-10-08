from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.config import ServerConfig
from server.contracts.http.settings_models import (
    AccountCostSettingsUpdate,
    FullSettingsUpdate,
)
from server.routes import settings as settings_routes


@pytest.fixture
def settings_client(monkeypatch, tmp_path):
    config = ServerConfig()
    config.data_source = "tushare"
    config.tushare_token = ""
    config.live_poll_interval = 120
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(config=config, db=None),
    )
    monkeypatch.setattr(
        settings_routes, "resolve_config_path", lambda: tmp_path / "config.json"
    )
    app = FastAPI()
    app.include_router(settings_routes.create_router())
    return TestClient(app), config


def test_cost_patch_preserves_other_settings_and_needs_no_provider_credential(
    settings_client,
):
    client, config = settings_client
    response = client.put(
        "/api/settings",
        json={"account_commission_rate": 0.00025, "account_min_commission": 3},
    )

    assert response.status_code == 200
    assert response.json()["account_commission_rate"] == 0.00025
    assert response.json()["account_min_commission"] == 3
    assert config.data_source == "tushare"
    assert config.live_poll_interval == 120
    assert config.host == "0.0.0.0"


def test_incomplete_cost_patch_cannot_apply_full_settings_defaults(settings_client):
    client, config = settings_client
    response = client.put("/api/settings", json={"account_commission_rate": 0.00025})
    assert response.status_code == 422
    assert config.data_source == "tushare"
    assert config.live_poll_interval == 120


@pytest.mark.parametrize(
    "payload",
    [
        {"account_commission_rate": 0.00025, "data_source": "akshare"},
        {
            "account_commission_rate": 0.00025,
            "account_min_commission": 3,
            "data_source": "akshare",
        },
    ],
)
def test_mixed_incomplete_update_cannot_replace_saved_settings(
    settings_client, payload
):
    client, config = settings_client
    before = settings_routes._settings_response(SimpleNamespace(config=config, db=None))
    response = client.put("/api/settings", json=payload)
    assert response.status_code == 422
    assert (
        settings_routes._settings_response(SimpleNamespace(config=config, db=None))
        == before
    )
    with pytest.raises(ValidationError):
        FullSettingsUpdate.model_validate(payload)


def test_complete_legacy_update_remains_supported(settings_client):
    client, config = settings_client
    legacy_payload = settings_routes._settings_response(
        SimpleNamespace(config=config, db=None)
    ).model_dump()
    legacy_payload.update(
        data_source="akshare", account_commission_rate=0.00025, account_min_commission=3
    )
    FullSettingsUpdate.model_validate(legacy_payload)
    response = client.put("/api/settings", json=legacy_payload)
    assert response.status_code == 200
    assert response.json()["account_commission_rate"] == 0.00025
    assert response.json()["account_min_commission"] == 3
    assert config.live_poll_interval == 120


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_cost_patch_rejects_negative_and_nonfinite_values(value):
    with pytest.raises(ValidationError):
        AccountCostSettingsUpdate(
            account_commission_rate=value, account_min_commission=0
        )
    with pytest.raises(ValidationError):
        AccountCostSettingsUpdate(
            account_commission_rate=0, account_min_commission=value
        )


def test_failed_cost_persistence_keeps_runtime_costs_unchanged(
    settings_client, monkeypatch
):
    client, config = settings_client
    before = settings_routes._account_cost_settings(config)

    def fail_write(_):
        raise OSError("fixture write failure")

    monkeypatch.setattr(settings_routes, "_write_persisted_config", fail_write)
    with pytest.raises(OSError, match="fixture write failure"):
        client.put(
            "/api/settings",
            json={"account_commission_rate": 0.00025, "account_min_commission": 3},
        )
    assert settings_routes._account_cost_settings(config) == before


def test_failed_data_settings_persistence_keeps_runtime_settings_unchanged(
    settings_client, monkeypatch
):
    client, config = settings_client

    def fail_write(_):
        raise OSError("fixture write failure")

    monkeypatch.setattr(settings_routes, "_write_persisted_config", fail_write)
    with pytest.raises(OSError, match="fixture write failure"):
        client.put(
            "/api/settings/data-source",
            json={"data_source": "akshare", "live_poll_interval": 60},
        )
    assert config.data_source == "tushare"
    assert config.live_poll_interval == 120
