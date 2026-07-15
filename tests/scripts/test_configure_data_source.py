"""Safe local data-source onboarding script behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_script_module():
    script_path = Path("scripts/configure_data_source.py")
    spec = importlib.util.spec_from_file_location("configure_data_source", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configure_akshare_keeps_existing_config_without_token(tmp_path):
    module = _load_script_module()
    config_path = tmp_path / "config.json"
    config_path.write_text('{"initial_cash": 0, "tushare_token": "old-token"}\n')

    saved = module.save_data_source_config(
        config_path=config_path,
        provider="akshare",
        token_reader=lambda: pytest.fail("akshare should not request a token"),
    )

    assert saved == {
        "initial_cash": 0,
        "data_source": {"provider": "akshare"},
    }
    assert "old-token" not in config_path.read_text()


def test_configure_tushare_prompts_for_token_without_printing_it(tmp_path, capsys):
    module = _load_script_module()
    config_path = tmp_path / "config.json"

    saved = module.save_data_source_config(
        config_path=config_path,
        provider="tushare",
        token_reader=lambda: "unit-secret-token",
    )

    captured = capsys.readouterr()
    assert saved["data_source"] == {
        "provider": "tushare",
        "tushare_token": "unit-secret-token",
    }
    assert "unit-secret-token" not in captured.out
    assert "unit-secret-token" in config_path.read_text()


def test_rejects_tushare_without_token(tmp_path):
    module = _load_script_module()

    with pytest.raises(ValueError, match="TuShare token is required"):
        module.save_data_source_config(
            config_path=tmp_path / "config.json",
            provider="tushare",
            token_reader=lambda: "",
        )


def test_migrates_legacy_data_source_fields_without_losing_poll_interval(tmp_path):
    module = _load_script_module()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"data_source": "akshare", "live_poll_interval": 90}',
        encoding="utf-8",
    )

    saved = module.save_data_source_config(
        config_path=config_path,
        provider="tushare",
        token_reader=lambda: "unit-secret-token",
    )

    assert saved == {
        "data_source": {
            "provider": "tushare",
            "live_poll_interval": 90,
            "tushare_token": "unit-secret-token",
        }
    }


def test_cli_does_not_accept_token_argument():
    module = _load_script_module()

    with pytest.raises(SystemExit):
        module.parse_args(["--provider", "tushare", "--tushare-token", "secret"])
