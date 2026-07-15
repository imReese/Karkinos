from __future__ import annotations

import json

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_conformance_fixtures import (
    run_deterministic_broker_adapter_conformance,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from scripts.review_broker_adapter_release import main
from tests.account_truth.test_broker_adapter_release import (
    collector_binding,
    release_manifest,
)


def test_cli_preview_is_side_effect_free_and_acceptance_is_explicit(
    tmp_path,
    capsys,
) -> None:
    manifest_path = tmp_path / "adapter-release.json"
    manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
    db_path = tmp_path / "release-review.db"

    preview_code = main(["--file", str(manifest_path), "--db", str(db_path)])
    preview = json.loads(capsys.readouterr().out)
    database_created_by_preview = db_path.exists()
    release_preview = preview_broker_adapter_release_manifest(
        manifest_path.read_text(encoding="utf-8")
    )
    conformance = run_deterministic_broker_adapter_conformance(
        release_preview,
        run_id="cli-fixture-conformance-v1",
    )
    BrokerAdapterConformanceRepository(db_path).record_report(
        conformance,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )
    record_code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--record",
            "--review-id",
            "cli-fixture-review-v1",
            "--decision",
            "accepted",
            "--reviewer-ref",
            "cli-fixture-human-reviewer",
            "--reviewed-at",
            "2026-07-15T08:00:00+00:00",
            "--reason-ref",
            "cli-fixture-approved",
            "--acknowledgement",
            BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
        ]
    )
    recorded = json.loads(capsys.readouterr().out)
    verification = BrokerAdapterReleaseReviewRepository(
        db_path,
        ensure_schema=False,
    ).verify_collector_binding(collector_binding())

    assert preview_code == 0
    assert preview["validation_status"] == "pass"
    assert preview["provider_contacted"] is False
    assert preview["adapter_registered"] is False
    assert database_created_by_preview is False
    assert record_code == 0
    assert recorded["status"] == "accepted"
    assert recorded["authorizes_execution"] is False
    assert verification["status"] == "clear"


def test_cli_wrong_acknowledgement_fails_without_acceptance(tmp_path, capsys) -> None:
    manifest_path = tmp_path / "adapter-release.json"
    manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
    db_path = tmp_path / "release-review.db"

    code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--record",
            "--review-id",
            "cli-fixture-review-wrong-ack",
            "--decision",
            "accepted",
            "--reviewer-ref",
            "cli-fixture-human-reviewer",
            "--reviewed-at",
            "2026-07-15T08:00:00+00:00",
            "--reason-ref",
            "cli-fixture-approved",
        ]
    )
    rejected = json.loads(capsys.readouterr().out)

    assert code == 2
    assert rejected["status"] == "rejected"
    assert "broker_adapter_release_review_acknowledgement_mismatch" in (
        rejected["blockers"]
    )
    assert (
        BrokerAdapterReleaseReviewRepository(
            db_path,
            ensure_schema=False,
        ).get_status(
            "fixture-release-reviewed-v1"
        )["status"]
        == "not_found"
    )
