"""Complete recovery-bundle creation, verification and candidate restore."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from data.store import DataStore
from server.contracts.portfolio_cash_flows import CashFlowWrite
from server.db import AppDatabase
from server.persistence import initializer
from server.persistence.database_identity import ensure_database_identity
from tools.recovery_bundle import (
    create_recovery_bundle,
    restore_recovery_bundle,
    verify_recovery_bundle,
)


def _state(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    app = AppDatabase(data / "app.db")
    app.init_sync()
    app.record_cash_flow_sync(
        CashFlowWrite(
            command_id="recovery-fixture-deposit",
            operator_id="test",
            flow_type="deposit",
            amount=1000,
            timestamp="2026-09-17T09:00:00+08:00",
            note="recovery fixture",
        )
    )
    DataStore(data)
    bars = data / "bars/1d/stock"
    bars.mkdir(parents=True)
    (bars / "600000.parquet").write_bytes(b"immutable-fixture")
    ensure_database_identity(data, workspace_role="development")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"server": {"market_calendar_auto_sync": False}}) + "\n",
        encoding="utf-8",
    )
    return data, config


def _cash_flow_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM cash_flows").fetchone()[0])


def test_bundle_is_complete_private_and_restores_to_new_candidate(tmp_path) -> None:
    data, config = _state(tmp_path)
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )

    verified = verify_recovery_bundle(bundle)
    assert verified["verified"] is True
    assert verified["workspace_role"] == "development"
    assert verified["database_state"] == "current"
    assert verified["file_count"] >= 5
    assert not (bundle / "data/backups").exists()
    assert not list((bundle / "data").rglob("*-wal"))
    assert not list((bundle / "data").rglob("*.initialize.lock"))
    assert (bundle / "config/config.json").is_file()
    assert not (bundle / "config/.env").exists()
    assert _cash_flow_count(bundle / "data/app.db") == 1

    candidate = tmp_path / "candidate"
    restored = restore_recovery_bundle(
        bundle_path=bundle,
        candidate_dir=candidate,
        replay=False,
    )
    assert restored["candidate_dir"] == str(candidate)
    assert _cash_flow_count(candidate / "data/app.db") == 1
    assert (candidate / ".recovery-restore.json").is_file()
    assert (candidate / "config/config.json").is_file()
    assert not (candidate / "config/.env").exists()


def test_bundle_verification_detects_file_tampering(tmp_path) -> None:
    data, config = _state(tmp_path)
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    (bundle / "config/config.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="recovery_bundle_file_manifest_mismatch"):
        verify_recovery_bundle(bundle)


def test_candidate_restore_replays_current_application_without_mutating_bundle(
    tmp_path,
) -> None:
    data, config = _state(tmp_path)
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    before = (bundle / "manifest.json").read_bytes()

    restored = restore_recovery_bundle(
        bundle_path=bundle,
        candidate_dir=tmp_path / "candidate",
        replay=True,
    )

    assert restored["replay"]["status"] == "passed"
    assert restored["replay"]["process_restart"] == "passed"
    assert (bundle / "manifest.json").read_bytes() == before


def test_bundle_creation_refuses_active_managed_runtime(tmp_path) -> None:
    data, config = _state(tmp_path)
    with initializer.database_runtime(data / "app.db"):
        with pytest.raises(RuntimeError, match="recovery_runtime_active"):
            create_recovery_bundle(
                data_dir=data,
                config_path=config,
                destination_root=tmp_path / "bundles",
                workspace_role="development",
            )


def test_bundle_verification_detects_manifest_tampering(tmp_path) -> None:
    data, config = _state(tmp_path)
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert "source_root" not in manifest["source"]
    manifest["database_status"]["state"] = "tampered"
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="recovery_manifest_digest_mismatch"):
        verify_recovery_bundle(bundle)


def test_bundle_creation_rejects_inline_secret_config(tmp_path) -> None:
    data, config = _state(tmp_path)
    config.write_text(
        json.dumps({"provider": {"api_key": "plaintext"}}), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="recovery_config_contains_secret_key"):
        create_recovery_bundle(
            data_dir=data,
            config_path=config,
            destination_root=tmp_path / "bundles",
            workspace_role="development",
        )


def test_bundle_allows_environment_secret_references(tmp_path) -> None:
    data, config = _state(tmp_path)
    config.write_text(
        json.dumps({"provider": {"api_key_env": "KARKINOS_PROVIDER_API_KEY"}}),
        encoding="utf-8",
    )
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )

    assert verify_recovery_bundle(bundle)["verified"] is True
