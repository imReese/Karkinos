"""Complete recovery-bundle creation, verification and candidate restore."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.dataset.catalog import DatasetCatalog
from data.dataset.reader import DatasetReaderError, read_daily_bar_dataset
from data.storage.objects import ContentAddressedObjectStore, ObjectIntegrityError
from data.store import DataStore
from server.contracts.portfolio_cash_flows import CashFlowWrite
from server.db import AppDatabase
from server.persistence import initializer
from server.persistence.backtest_results import insert_backtest_result
from server.persistence.database_identity import ensure_database_identity
from server.persistence.research_observations import ResearchObservationsRepository
from tests.server.test_research_datasets import (
    _DAYS,
    _backtest_request,
    _Provider,
    _publish,
)
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
    _publish(data / "research")
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
    assert restored["published_dataset_count"] == 1
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


def test_recovery_replays_current_research_datasets_after_restore(tmp_path) -> None:
    data, config = _state(tmp_path)
    ref = _publish(data / "research")
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    assert verify_recovery_bundle(bundle)["published_dataset_count"] == 1
    restored = restore_recovery_bundle(
        bundle_path=bundle, candidate_dir=tmp_path / "candidate", replay=False
    )
    research = Path(restored["candidate_dir"]) / "data/research"
    replayed = read_daily_bar_dataset(
        ContentAddressedObjectStore(research / "objects"), ref
    )
    assert replayed.ref == ref
    assert replayed.row_count == len(_DAYS)


def test_recovery_still_replays_legacy_dataset_layout(tmp_path) -> None:
    data, config = _state(tmp_path)
    source = tmp_path / "legacy-source"
    ref = _publish(source)
    shutil.copytree(source / "objects", data / "objects")
    DatasetCatalog(data / "index").register(
        ContentAddressedObjectStore(data / "objects"), ref
    )
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    assert verify_recovery_bundle(bundle)["published_dataset_count"] == 1


@pytest.mark.parametrize("checkpoint_only", [False, True])
def test_recovery_rejects_preexisting_corruption_in_research_objects(
    tmp_path, checkpoint_only
) -> None:
    data, config = _state(tmp_path)
    research = data / "research"
    if checkpoint_only:
        with pytest.raises(RuntimeError, match="controlled network failure"):
            _publish(research, _Provider(fail_day=_DAYS[2]))
        catalog = DatasetCatalog(research / "checkpoints")
        ref = catalog.list_daily_bar_datasets()[0].ref
    else:
        ref = _publish(research)
    object_path = (
        research
        / "objects/sha256"
        / ref.manifest_ref.digest[:2]
        / ref.manifest_ref.digest[2:]
    )
    object_path.chmod(0o600)
    object_path.write_bytes(b"corrupt-before-backup")
    with pytest.raises(DatasetReaderError):
        create_recovery_bundle(
            data_dir=data,
            config_path=config,
            destination_root=tmp_path / "bundles",
            workspace_role="development",
        )
    assert not list((tmp_path / "bundles").iterdir())


def test_recovery_preserves_interrupted_research_ingestion_for_resume(tmp_path) -> None:
    data, config = _state(tmp_path)
    with pytest.raises(RuntimeError, match="controlled network failure"):
        _publish(data / "research", _Provider(fail_day=_DAYS[2]))
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    assert verify_recovery_bundle(bundle)["published_dataset_count"] == 0
    restored = restore_recovery_bundle(
        bundle_path=bundle, candidate_dir=tmp_path / "candidate", replay=False
    )
    provider = _Provider()
    research = Path(restored["candidate_dir"]) / "data/research"
    ref = _publish(research, provider)
    assert provider.calls == list(_DAYS[2:])
    assert read_daily_bar_dataset(
        ContentAddressedObjectStore(research / "objects"), ref
    ).row_count == len(_DAYS)


def _save_report(data: Path, config, *, metrics=None) -> int:
    with sqlite3.connect(data / "app.db") as conn:
        return insert_backtest_result(
            conn,
            created_at="2026-09-18T08:00:00+00:00",
            config_json=json.dumps(config),
            metrics_json=json.dumps(metrics or {}),
            initial_cash=1000,
            final_equity=1000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )


def _corrupt_manifest(research: Path, ref) -> None:
    path = (
        research
        / "objects/sha256"
        / ref.manifest_ref.digest[:2]
        / ref.manifest_ref.digest[2:]
    )
    path.chmod(0o600)
    path.write_bytes(b"corrupt-before-backup")


@pytest.mark.parametrize("partial_catalog", [False, True])
def test_recovery_keeps_report_bound_dataset_when_catalog_is_incomplete(
    tmp_path, partial_catalog
) -> None:
    data, config = _state(tmp_path)
    research = data / "research"
    ref = _publish(research)
    _save_report(
        data,
        _backtest_request(ref).model_dump(mode="json"),
        metrics={"dataset_binding": {"dataset_id": ref.dataset_id}},
    )
    catalog = DatasetCatalog(research)
    catalog.path.unlink()
    if partial_catalog:
        replacement = _publish(research, _Provider(correction=True), refresh=True)
        assert replacement != ref
        assert [entry.ref for entry in catalog.list_daily_bar_datasets()] == [
            replacement
        ]

    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    assert verify_recovery_bundle(bundle)["published_dataset_count"] == (
        2 if partial_catalog else 1
    )
    restored = restore_recovery_bundle(
        bundle_path=bundle, candidate_dir=tmp_path / "candidate", replay=False
    )
    replayed = read_daily_bar_dataset(
        ContentAddressedObjectStore(
            Path(restored["candidate_dir"]) / "data/research/objects"
        ),
        ref,
    )
    assert replayed.ref == ref
    assert replayed.row_count == len(_DAYS)


def test_recovery_rejects_corrupt_report_bound_dataset_without_catalog(
    tmp_path,
) -> None:
    data, config = _state(tmp_path)
    research = data / "research"
    ref = _publish(research)
    _save_report(data, _backtest_request(ref).model_dump(mode="json"))
    DatasetCatalog(research).path.unlink()
    _corrupt_manifest(research, ref)

    # The bundle's copied-file checksums would match these already damaged bytes.
    # The saved report still requires semantic replay of its immutable Dataset.
    with pytest.raises(ObjectIntegrityError, match="object_integrity_mismatch"):
        create_recovery_bundle(
            data_dir=data,
            config_path=config,
            destination_root=tmp_path / "bundles",
            workspace_role="development",
        )
    assert not list((tmp_path / "bundles").iterdir())


@pytest.mark.parametrize("damaged_ref", ["source", "publication", "outcome"])
def test_recovery_checks_observation_datasets_after_source_report_is_deleted(
    tmp_path, damaged_ref
) -> None:
    data, config = _state(tmp_path)
    research = data / "research"
    source = _publish(research)
    report_id = _save_report(data, _backtest_request(source).model_dump(mode="json"))
    checkpoints = DatasetCatalog(research / "checkpoints")
    daily_refs = [entry.ref for entry in checkpoints.list_daily_bar_datasets()]
    refs = {"source": source, "publication": daily_refs[0], "outcome": daily_refs[-1]}
    assert len({ref.dataset_id for ref in refs.values()}) == 3
    now = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    repo = ResearchObservationsRepository(data / "app.db", clock=lambda: now)
    repo.start(
        observation_id="independent",
        request_id="start",
        request_fingerprint="start-independent",
        source_backtest_result_id=report_id,
        source={
            "strategy_kind": "dual_ma",
            "source_dataset_kind": "immutable_dataset",
            "dataset_id": source.dataset_id,
        },
        code_binding={"fingerprint": "frozen"},
        policy={"horizon_sessions": 1},
        universe=[{"symbol": "600000", "instrument_type": "stock"}],
    )
    repo.advance(
        observation_id="independent",
        request_id="advance",
        request_fingerprint="advance-independent",
        expected_version=0,
        publication={
            "id": "publication",
            "decision_session": "2026-09-21",
            "dataset_id": refs["publication"].dataset_id,
            "payload": {"targets": {"600000": "0.5"}},
        },
        outcomes=[
            {
                "publication_id": "publication",
                "horizon": 1,
                "dataset_id": refs["outcome"].dataset_id,
                "payload": {"weighted_price_response": "0.01"},
            }
        ],
        publication_deadline=now + timedelta(days=1),
    )
    with sqlite3.connect(data / "app.db") as conn:
        conn.execute("DELETE FROM backtest_results WHERE id=?", (report_id,))
    DatasetCatalog(research).path.unlink()
    checkpoints.path.unlink()
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "healthy-bundles",
        workspace_role="development",
    )
    assert verify_recovery_bundle(bundle)["published_dataset_count"] == 3

    _corrupt_manifest(research, refs[damaged_ref])
    with pytest.raises(ObjectIntegrityError, match="object_integrity_mismatch"):
        create_recovery_bundle(
            data_dir=data,
            config_path=config,
            destination_root=tmp_path / "damaged-bundles",
            workspace_role="development",
        )
    assert not list((tmp_path / "damaged-bundles").iterdir())


def test_formula_analytics_snapshot_does_not_require_immutable_object_store(
    tmp_path,
) -> None:
    data, config = _state(tmp_path)
    snapshot_id = "sha256:" + "a" * 64
    report_id = _save_report(
        data,
        {"strategy": "formula"},
        metrics={"dataset_snapshot": {"snapshot_id": snapshot_id}},
    )
    repo = ResearchObservationsRepository(
        data / "app.db", clock=lambda: datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    )
    repo.start(
        observation_id="formula",
        request_id="start",
        request_fingerprint="start-formula",
        source_backtest_result_id=report_id,
        source={
            "strategy_kind": "formula",
            "source_dataset_kind": "analytics_snapshot",
            "dataset_id": snapshot_id,
        },
        code_binding={"fingerprint": "frozen"},
        policy={"horizon_sessions": 1},
        universe=[{"symbol": "600000", "instrument_type": "stock"}],
    )
    assert not (data / "research/objects").exists()
    bundle = create_recovery_bundle(
        data_dir=data,
        config_path=config,
        destination_root=tmp_path / "bundles",
        workspace_role="development",
    )
    verified = verify_recovery_bundle(bundle)
    assert verified["verified"] is True
    assert verified["published_dataset_count"] == 0
