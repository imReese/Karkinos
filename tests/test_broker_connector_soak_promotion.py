from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
)
from server.services.broker_connector_soak_promotion import (
    BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE,
    BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    BrokerConnectorSoakPromotionRejected,
    BrokerConnectorSoakPromotionService,
)
from server.services.broker_connector_soak_runbook import (
    BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_DRILL_TYPES,
    BROKER_CONNECTOR_SOAK_PHASES,
    BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
)
from server.services.operator_approval import OperatorApprovalService

CONNECTOR_ID = "deterministic-fixture-readonly-promotion"
ACCOUNT_ALIAS = "deterministic-fixture-promotion-review"
ACCOUNT_REF_HASH = "a" * 64
NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


def _trading_days() -> list[str]:
    values: list[str] = []
    candidate = datetime(2026, 6, 1, tzinfo=timezone.utc)
    while len(values) < 20:
        if candidate.weekday() < 5:
            values.append(candidate.date().isoformat())
        candidate += timedelta(days=1)
    return values


def _seed_operational_evidence(
    db: AppDatabase,
    *,
    omit_phase: str = "",
    drill_connector_ids: tuple[str, ...] = (CONNECTOR_ID,),
) -> None:
    for index, trading_day in enumerate(_trading_days(), start=1):
        observation_id = f"promotion-observation-{index}"
        snapshot_fingerprint = f"{index:064x}"
        observed_at = f"{trading_day}T07:00:00+00:00"
        db.append_event_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            timestamp=observed_at,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            source_ref=CONNECTOR_ID,
            payload={
                "schema_version": "karkinos.broker_connector_soak_observation.v1",
                "observation_id": observation_id,
                "connector_id": CONNECTOR_ID,
                "account_alias": ACCOUNT_ALIAS,
                "account_ref_hash": ACCOUNT_REF_HASH,
                "trading_day": trading_day,
                "soak_status": "healthy",
                "blockers": [],
                "snapshot_fingerprint": snapshot_fingerprint,
                "qualifies_for_healthy_soak_day": True,
                "execution_reconciliation": {
                    "status": "clear",
                    "open_item_count": 0,
                    "evidence_ref": f"execution_reconciliation:{trading_day}",
                },
                "broker_submission_enabled": False,
            },
        )
        observation_ref = {
            "connector_id": CONNECTOR_ID,
            "observation_id": observation_id,
            "snapshot_fingerprint": snapshot_fingerprint,
            "trading_day": trading_day,
            "soak_status": "healthy",
            "execution_reconciliation_status": "clear",
            "execution_reconciliation_open_item_count": 0,
        }
        for phase in sorted(BROKER_CONNECTOR_SOAK_PHASES):
            if phase == omit_phase:
                continue
            run_id = f"promotion-run-{trading_day}-{phase}"
            db.append_event_sync(
                event_type=BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
                timestamp=observed_at,
                entity_type=BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
                entity_id=run_id,
                source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
                source_ref=phase,
                payload={
                    "schema_version": (
                        "karkinos.broker_connector_soak_operational_run.v1"
                    ),
                    "run_id": run_id,
                    "phase": phase,
                    "run_status": "passed",
                    "observations": [observation_ref],
                    "broker_submission_enabled": False,
                },
            )

    for drill_type in sorted(BROKER_CONNECTOR_SOAK_DRILL_TYPES):
        drill_id = f"promotion-drill-{drill_type}"
        first_observations = [
            {
                "connector_id": connector_id,
                "observation_id": f"{drill_id}-first-{connector_id}",
                "snapshot_fingerprint": "d" * 64,
                "soak_status": "blocked",
            }
            for connector_id in drill_connector_ids
        ]
        second_observations = (
            [
                {
                    "connector_id": connector_id,
                    "observation_id": f"{drill_id}-second-{connector_id}",
                    "snapshot_fingerprint": "d" * 64,
                    "soak_status": "healthy",
                }
                for connector_id in drill_connector_ids
            ]
            if drill_type in {"duplicate_evidence", "restart_recovery"}
            else []
        )
        db.append_event_sync(
            event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
            timestamp=NOW.isoformat(),
            entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
            entity_id=drill_id,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            source_ref=drill_type,
            payload={
                "schema_version": ("karkinos.broker_connector_soak_recovery_drill.v1"),
                "drill_id": drill_id,
                "drill_type": drill_type,
                "drill_status": "passed",
                "first_observations": first_observations,
                "second_observations": second_observations,
                "broker_submission_enabled": False,
            },
        )


def _clear_account_truth(source_fingerprint: str = "b" * 64) -> dict:
    return {
        "schema_version": "karkinos.account_truth.promotion_evidence.v1",
        "status": "clear",
        "source_fingerprint": source_fingerprint,
        "import_run_id": "import-promotion-1",
        "file_fingerprint": "c" * 64,
        "source_type": "canonical_broker_statement_csv",
        "captured_at": NOW.isoformat(),
        "current_age_seconds": 60,
        "max_age_seconds": 86400,
        "data_freshness_status": "fresh",
        "reconciliation_status": "pass",
        "score": 100,
        "gate_status": "pass",
        "cash_status": "pass",
        "position_status": "pass",
        "fee_status": "pass",
        "cost_basis_status": "pass",
        "unresolved_mismatch_count": 0,
        "resolved_review_count": 0,
        "blockers": [],
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
    }


def _environment(
    tmp_path,
    *,
    omit_phase: str = "",
    drill_connector_ids: tuple[str, ...] = (CONNECTOR_ID,),
) -> dict:
    db = AppDatabase(tmp_path / "broker-soak-promotion.db")
    db.init_sync()
    _seed_operational_evidence(
        db,
        omit_phase=omit_phase,
        drill_connector_ids=drill_connector_ids,
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    identity = TrustedOperatorIdentityConfig(
        operator_id="local-owner",
        key_id="owner-promotion-key-1",
        public_key_base64=base64.b64encode(public_key).decode("ascii"),
        enabled=True,
    )
    account_truth = [_clear_account_truth()]
    service = BrokerConnectorSoakPromotionService(
        db=db,
        connectors=[SimpleNamespace(connector_id=CONNECTOR_ID)],
        trusted_operator_identities=[identity],
        account_truth_evidence_provider=lambda: account_truth[0],
        clock=lambda: NOW,
    )
    return {
        "db": db,
        "private_key": private_key,
        "identity": identity,
        "account_truth": account_truth,
        "service": service,
    }


def _approval(env: dict, dossier_fingerprint: str) -> dict:
    service = OperatorApprovalService(
        db=env["db"],
        trusted_identities=[env["identity"]],
        clock=lambda: NOW,
    )
    challenge = service.create_challenge(
        operator_id="local-owner",
        key_id="owner-promotion-key-1",
        action="accept_broker_connector_soak_promotion",
        artifact_type="broker_connector_soak_promotion_dossier",
        artifact_fingerprint=dossier_fingerprint,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    return service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def test_promotion_dossier_binds_full_readonly_operating_and_account_truth_evidence(
    tmp_path,
) -> None:
    env = _environment(tmp_path)

    dossier = env["service"].preview_dossier(CONNECTOR_ID)

    assert dossier["review_status"] == "ready_for_signed_owner_acceptance"
    assert dossier["review_blockers"] == []
    assert dossier["promotion_ready"] is False
    assert dossier["promotion_blockers"] == ["signed_owner_acceptance_missing"]
    operational = dossier["operational_evidence"]
    assert operational["selected_trading_day_count"] == 20
    assert all(len(days) == 20 for days in operational["phase_coverage"].values())
    assert all(operational["drill_coverage"].values())
    assert dossier["account_truth_evidence"]["gate_status"] == "pass"
    assert dossier["runtime_execution_authority"] == "disabled"
    assert dossier["broker_submission_enabled"] is False
    assert dossier["authorizes_execution"] is False


@pytest.mark.parametrize(
    "drill_connector_ids",
    [
        (),
        ("unrelated-deterministic-fixture",),
        (CONNECTOR_ID, "unrelated-deterministic-fixture"),
    ],
)
def test_unscoped_unrelated_or_mixed_drills_cannot_promote_connector(
    tmp_path,
    drill_connector_ids: tuple[str, ...],
) -> None:
    env = _environment(
        tmp_path,
        drill_connector_ids=drill_connector_ids,
    )

    dossier = env["service"].preview_dossier(CONNECTOR_ID)

    assert dossier["review_status"] == "blocked_review"
    assert dossier["promotion_ready"] is False
    assert dossier["operational_evidence"]["drill_coverage"] == {
        drill_type: False for drill_type in sorted(BROKER_CONNECTOR_SOAK_DRILL_TYPES)
    }
    for drill_type in BROKER_CONNECTOR_SOAK_DRILL_TYPES:
        assert f"recovery_drill_missing:{drill_type}" in dossier["review_blockers"]


def test_signed_owner_acceptance_is_append_only_reused_and_still_non_executing(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    dossier = env["service"].preview_dossier(CONNECTOR_ID)
    approval = _approval(env, dossier["dossier_fingerprint"])

    first = env["service"].record_acceptance(
        connector_id=CONNECTOR_ID,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    )
    rerun = env["service"].record_acceptance(
        connector_id=CONNECTOR_ID,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    )
    status = env["service"].get_status()

    assert first["status"] == "recorded_verified_owner_acceptance"
    assert first["operator_identity_verified"] is True
    assert first["owner_assertions"] == {
        "account_truth_import_matches_reviewed_account_alias": True,
        "full_process_and_broker_terminal_restart_performed": True,
        "promotion_evidence_only_without_execution_authority": True,
    }
    assert first["authorizes_execution"] is False
    assert first["broker_submission_enabled"] is False
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert status["promotion_ready"] is True
    assert status["owner_acceptance_recorded"] is True
    assert status["account_truth_reconciliation_linked"] is True
    assert status["runtime_execution_authority"] == "disabled"
    assert (
        len(
            env["db"].list_events_sync(
                event_type=BROKER_SOAK_PROMOTION_ACCEPTANCE_EVENT_TYPE
            )
        )
        == 1
    )


def test_missing_daily_phase_and_blocked_account_truth_fail_closed(tmp_path) -> None:
    env = _environment(tmp_path, omit_phase="intraday")
    env["account_truth"][0] = {
        **_clear_account_truth(),
        "status": "blocked",
        "gate_status": "blocked",
        "blockers": ["account_truth_unresolved_mismatches"],
    }

    dossier = env["service"].preview_dossier(CONNECTOR_ID)

    assert dossier["review_status"] == "blocked_review"
    assert (
        "runbook_phase_coverage_incomplete:intraday:0/20" in dossier["review_blockers"]
    )
    assert (
        "account_truth:account_truth_unresolved_mismatches"
        in dossier["review_blockers"]
    )
    assert dossier["promotion_ready"] is False


def test_account_truth_source_drift_invalidates_recorded_acceptance(tmp_path) -> None:
    env = _environment(tmp_path)
    dossier = env["service"].preview_dossier(CONNECTOR_ID)
    approval = _approval(env, dossier["dossier_fingerprint"])
    env["service"].record_acceptance(
        connector_id=CONNECTOR_ID,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    )

    env["account_truth"][0] = _clear_account_truth("d" * 64)
    changed = env["service"].preview_dossier(CONNECTOR_ID)

    assert changed["dossier_fingerprint"] != dossier["dossier_fingerprint"]
    assert changed["acceptance"]["status"] == "missing"
    assert changed["promotion_ready"] is False


def test_newer_scoped_failed_drill_invalidates_recorded_acceptance(tmp_path) -> None:
    env = _environment(tmp_path)
    dossier = env["service"].preview_dossier(CONNECTOR_ID)
    approval = _approval(env, dossier["dossier_fingerprint"])
    env["service"].record_acceptance(
        connector_id=CONNECTOR_ID,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    )
    env["db"].append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
        timestamp=(NOW + timedelta(minutes=1)).isoformat(),
        entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
        entity_id="promotion-drill-disconnect-regression",
        source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
        source_ref="disconnect",
        payload={
            "schema_version": "karkinos.broker_connector_soak_recovery_drill.v1",
            "drill_id": "promotion-drill-disconnect-regression",
            "drill_type": "disconnect",
            "drill_status": "failed",
            "first_observations": [
                {
                    "connector_id": CONNECTOR_ID,
                    "observation_id": "promotion-drill-disconnect-regression-first",
                    "snapshot_fingerprint": "e" * 64,
                    "soak_status": "healthy",
                }
            ],
            "second_observations": [],
            "broker_submission_enabled": False,
        },
    )

    changed = env["service"].preview_dossier(CONNECTOR_ID)

    assert changed["dossier_fingerprint"] != dossier["dossier_fingerprint"]
    assert changed["operational_evidence"]["drill_coverage"]["disconnect"] is False
    assert "recovery_drill_missing:disconnect" in changed["review_blockers"]
    assert changed["acceptance"]["status"] == "missing"
    assert changed["promotion_ready"] is False


def test_newer_malformed_replay_does_not_fall_back_to_older_pass(tmp_path) -> None:
    env = _environment(tmp_path)
    env["db"].append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
        timestamp=(NOW + timedelta(minutes=1)).isoformat(),
        entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
        entity_id="promotion-drill-restart-malformed",
        source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
        source_ref="restart_recovery",
        payload={
            "schema_version": "karkinos.broker_connector_soak_recovery_drill.v1",
            "drill_id": "promotion-drill-restart-malformed",
            "drill_type": "restart_recovery",
            "drill_status": "passed",
            "first_observations": [{"connector_id": CONNECTOR_ID}],
            "second_observations": [
                {"connector_id": "unrelated-deterministic-fixture"}
            ],
            "broker_submission_enabled": False,
        },
    )

    dossier = env["service"].preview_dossier(CONNECTOR_ID)

    assert (
        dossier["operational_evidence"]["drill_coverage"]["restart_recovery"] is False
    )
    assert "recovery_drill_missing:restart_recovery" in dossier["review_blockers"]
    assert dossier["promotion_ready"] is False


def test_acceptance_rejects_approval_bound_to_another_dossier(tmp_path) -> None:
    env = _environment(tmp_path)
    dossier = env["service"].preview_dossier(CONNECTOR_ID)
    wrong_approval = _approval(env, "f" * 64)

    with pytest.raises(BrokerConnectorSoakPromotionRejected) as exc_info:
        env["service"].record_acceptance(
            connector_id=CONNECTOR_ID,
            dossier_fingerprint=dossier["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=wrong_approval["approval_id"],
            acknowledgement=BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
        )

    assert exc_info.value.evidence["rejection_reasons"] == ["operator_approval_blocked"]
    assert exc_info.value.evidence["authorizes_execution"] is False
