"""Paper settlements retain their input closure when discovery indexes are absent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.dataset.catalog import DatasetCatalog
from data.storage.objects import ObjectIntegrityError
from server.db import AppDatabase
from server.services.research_paper_books import ResearchPaperBookService
from tests.server.test_research_observations_journey import journey  # noqa: F401
from tests.server.test_research_paper_books import paper, prepare_trade  # noqa: F401
from tools.recovery_bundle import create_recovery_bundle, restore_recovery_bundle


@pytest.mark.parametrize("corrupt_settlement_input", [False, True])
def test_paper_input_survives_catalog_loss_and_is_verified_before_restore(
    paper, tmp_path, tmp_path_factory, corrupt_settlement_input
):
    _, settled, _, _, _, _ = prepare_trade(paper, tmp_path)
    _, service, current, observation, _ = paper
    # These real HTTP fixtures publish immutable objects without a discovery index.
    assert not DatasetCatalog(tmp_path / "research").path.exists()
    dataset_id = settled["steps"][0]["dataset_id"]
    if corrupt_settlement_input:
        digest = dataset_id.removeprefix("sha256:")
        manifest = tmp_path / "research/objects/sha256" / digest[:2] / digest[2:]
        manifest.chmod(0o600)
        manifest.write_bytes(b"corrupt-before-backup")

    configuration = tmp_path / "config.json"
    configuration.write_text(
        json.dumps({"server": {"market_calendar_auto_sync": False}}) + "\n"
    )
    destination = tmp_path_factory.mktemp("paper-recovery-destination")
    arguments = {
        "data_dir": tmp_path,
        "config_path": configuration,
        "destination_root": destination,
        "workspace_role": "development",
    }
    if corrupt_settlement_input:
        # File-level backup hashes alone would accept already damaged bytes.
        with pytest.raises(ObjectIntegrityError, match="object_integrity_mismatch"):
            create_recovery_bundle(**arguments)
        assert not list(destination.iterdir())
        assert service.get(observation["id"]) == settled
        return

    bundle = create_recovery_bundle(**arguments)
    restored = restore_recovery_bundle(
        bundle_path=bundle, candidate_dir=destination / "candidate", replay=True
    )
    assert restored["published_dataset_count"] == 3
    assert restored["replay"]["status"] == "passed"
    assert restored["replay"]["process_restart"] == "passed"
    restored_db = AppDatabase(Path(restored["candidate_dir"]) / "data/app.db")
    reopened = ResearchPaperBookService(restored_db, clock=lambda: current[0])
    assert reopened.get(observation["id"]) == settled
    assert service.get(observation["id"]) == settled
