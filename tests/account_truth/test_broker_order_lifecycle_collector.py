from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerAdapterConformanceRepository,
    preview_broker_adapter_conformance_result,
)
from account_truth.broker_adapter_conformance_fixtures import (
    run_deterministic_broker_adapter_conformance,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
    broker_order_lifecycle_clearance_blockers,
    preview_broker_order_lifecycle_export,
)
from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleCollectorRejected,
    BrokerOrderLifecycleCollectorRepository,
    preview_broker_order_lifecycle_collector_batch,
)

NOW = datetime(2026, 7, 13, 8, 0, 0, tzinfo=UTC)


def _lifecycle(
    *,
    cursor: int = 1,
    captured_at: datetime = NOW,
    status: str = "open",
    broker_order_id: str = "FIXTURE-ORDER-1",
) -> dict:
    return {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "deterministic_fixture",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "fixture-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": cursor,
        "orders": [
            {
                "broker_order_id": broker_order_id,
                "client_order_id": "KARK-fixture-client-order-1",
                "symbol": "600519",
                "side": "buy",
                "status": status,
                "order_quantity": "100",
                "cumulative_filled_quantity": "0",
                "cancelled_quantity": "0",
                "average_fill_price": None,
                "submitted_at": (captured_at - timedelta(seconds=2)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": [],
    }


def _batch(
    *,
    run_id: str = "collector-run-1",
    cursor_previous: int = 0,
    cursor_current: int = 1,
    captured_at: datetime = NOW,
    lifecycle: dict | None = None,
    deployment_fingerprint: str = "d" * 64,
    release_review_status: str = "unreviewed",
    collection_mode: str = "fixture",
    source_contact_status: str = "not_contacted",
    connection_status: str = "not_applicable",
    batch_status: str = "complete",
    event_count: int = 1,
    callbacks_received: int = 0,
    duplicate_callbacks_dropped: int = 0,
    out_of_order_callbacks_dropped: int = 0,
) -> dict:
    return {
        "schema_version": "karkinos.broker_order_lifecycle_collector_batch.v1",
        "run_id": run_id,
        "collector_id": "deterministic-fixture-collector",
        "deployment_id": "fixture-deployment-1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": deployment_fingerprint,
        "release_evidence_ref": "fixture-release-unreviewed",
        "release_review_status": release_review_status,
        "adapter_authorization_ref": "test-only-user-authorization",
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "fixture-account",
        "collection_mode": collection_mode,
        "source_contact_status": source_contact_status,
        "connection_status": connection_status,
        "batch_status": batch_status,
        "cursor": {
            "previous": cursor_previous,
            "current": cursor_current,
        },
        "captured_at": captured_at.isoformat(),
        "event_count": event_count,
        "callbacks_received": callbacks_received,
        "duplicate_callbacks_dropped": duplicate_callbacks_dropped,
        "out_of_order_callbacks_dropped": out_of_order_callbacks_dropped,
        "lifecycle": (
            lifecycle
            if lifecycle is not None
            else _lifecycle(cursor=cursor_current, captured_at=captured_at)
        ),
    }


def _preview(payload: dict) -> dict:
    return preview_broker_order_lifecycle_collector_batch(
        json.dumps(payload),
        source_name="deterministic broker collector fixture",
        clock=lambda: NOW,
    )


def _ingest(repository, preview: dict) -> dict:
    return repository.ingest(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )


def _release_preview() -> dict:
    return preview_broker_adapter_release_manifest(
        json.dumps(
            {
                "schema_version": "karkinos.broker_adapter_release_manifest.v1",
                "release_evidence_ref": "fixture-release-unreviewed",
                "collector_id": "deterministic-fixture-collector",
                "deployment_id": "fixture-deployment-1",
                "collector_version": "fixture-v1",
                "deployment_fingerprint": "d" * 64,
                "provider": "deterministic_fixture",
                "gateway_id": "fixture-gateway-1",
                "account_alias": "fixture-account",
                "adapter_authorization_ref": "test-only-user-authorization",
                "collection_modes": ["callback", "poll"],
                "capabilities": {
                    "can_read_account": False,
                    "can_read_cash": False,
                    "can_read_positions": False,
                    "can_read_orders": True,
                    "can_read_fills": True,
                    "can_read_market_session": False,
                    "can_read_heartbeat": True,
                    "can_submit_orders": False,
                    "can_cancel_orders": False,
                },
                "boundaries": {
                    "runtime_auth_material_external": True,
                    "strategy_imports_adapter": False,
                    "ai_imports_adapter": False,
                    "core_imports_provider_sdk": False,
                    "writes_oms": False,
                    "writes_production_ledger": False,
                    "writes_risk_state": False,
                    "writes_kill_switch": False,
                    "writes_capital_authority": False,
                    "default_registered": False,
                },
                "review_refs": {
                    "adapter_adr": "fixture-adr-v1",
                    "capability_matrix": "fixture-capability-matrix-v1",
                    "threat_model": "fixture-threat-model-v1",
                    "deployment_runbook": "fixture-deployment-runbook-v1",
                    "rollback_runbook": "fixture-rollback-runbook-v1",
                    "privacy_review": "fixture-privacy-review-v1",
                },
                "limitations": ["Deterministic test-only adapter release."],
            }
        ),
        source_name="deterministic adapter release fixture",
    )


def _accept_live_release(db_path) -> dict:
    preview = _release_preview()
    conformance = run_deterministic_broker_adapter_conformance(
        preview,
        run_id="fixture-live-conformance-v1",
    )
    BrokerAdapterConformanceRepository(db_path).record_report(
        conformance,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )
    return BrokerAdapterReleaseReviewRepository(db_path).record_review(
        preview,
        review_id="fixture-release-review-accepted-v1",
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=NOW.isoformat(),
        reason_ref="fixture-release-approved",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )


def test_complete_batch_records_lifecycle_and_advances_cursor(tmp_path) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    preview = _preview(_batch())

    result = _ingest(repository, preview)
    state = repository.get_state(
        provider="deterministic_fixture",
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
    )
    lifecycle = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )

    assert preview["validation_status"] == "pass"
    assert result["run_status"] == "recorded"
    assert result["provider_contacted"] is False
    assert result["default_registered"] is False
    assert result["does_not_mutate_oms"] is True
    assert result["does_not_mutate_fills"] is True
    assert result["does_not_mutate_production_ledger"] is True
    assert result["does_not_mutate_risk_state"] is True
    assert result["does_not_mutate_kill_switch"] is True
    assert result["does_not_mutate_capital_authority"] is True
    assert state["status"] == "found"
    assert state["last_cursor"] == 1
    assert lifecycle["status"] == "found"
    assert lifecycle["order"]["status"] == "open"

    database_text = db_path.read_bytes().decode("utf-8", errors="ignore")
    assert "private-fixture-account-001" not in database_text


def test_same_run_and_same_evidence_with_new_run_are_idempotent(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    first_preview = _preview(_batch())
    first = _ingest(repository, first_preview)
    same_run = _ingest(repository, first_preview)
    duplicate_payload = _batch(run_id="collector-run-duplicate")
    duplicate = _ingest(repository, _preview(duplicate_payload))

    assert first["run_status"] == "recorded"
    assert same_run["run_status"] == "recorded"
    assert same_run["reused"] is True
    assert duplicate["run_status"] == "duplicate"
    assert duplicate["lifecycle_observation_id"] == first["lifecycle_observation_id"]
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            tmp_path / "collector.db",
            ensure_schema=False,
        ).list_observations(limit=10)
        != []
    )
    assert (
        len(
            BrokerOrderLifecycleEvidenceRepository(
                tmp_path / "collector.db",
                ensure_schema=False,
            ).list_observations(limit=10)
        )
        == 1
    )


def test_same_cursor_with_different_evidence_is_blocked(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    _ingest(repository, _preview(_batch()))
    changed = _batch(
        run_id="collector-run-conflict",
        lifecycle=_lifecycle(status="rejected"),
    )

    result = _ingest(repository, _preview(changed))
    state = repository.get_state(
        provider="deterministic_fixture",
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
    )

    assert result["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_cursor_evidence_conflict" in (
        result["blockers"]
    )
    assert state["last_cursor"] == 1


def test_gap_and_out_of_order_cursor_do_not_advance_state(tmp_path) -> None:
    gap_repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "gap.db")
    gap_payload = _batch(
        run_id="collector-gap",
        cursor_previous=2,
        cursor_current=3,
        captured_at=NOW,
        lifecycle=_lifecycle(cursor=3),
    )
    gap = _ingest(gap_repository, _preview(gap_payload))

    out_of_order_db = tmp_path / "out-of-order.db"
    lifecycle_preview = preview_broker_order_lifecycle_export(
        json.dumps(_lifecycle(cursor=2)),
        source_name="deterministic preexisting lifecycle",
        clock=lambda: NOW,
    )
    BrokerOrderLifecycleEvidenceRepository(out_of_order_db).record(
        lifecycle_preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )
    out_of_order_repository = BrokerOrderLifecycleCollectorRepository(out_of_order_db)
    old_payload = _batch(
        run_id="collector-out-of-order",
        cursor_previous=0,
        cursor_current=1,
        lifecycle=_lifecycle(cursor=1),
    )
    out_of_order = _ingest(out_of_order_repository, _preview(old_payload))

    assert gap["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_cursor_gap" in gap["blockers"]
    assert (
        gap_repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_found"
    )
    assert out_of_order["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_cursor_out_of_order" in (
        out_of_order["blockers"]
    )


@pytest.mark.parametrize(
    ("collection_mode", "connection_status", "batch_status", "expected_blocker"),
    [
        (
            "callback",
            "disconnected",
            "partial",
            "broker_order_lifecycle_collector_disconnected",
        ),
        (
            "poll",
            "not_applicable",
            "partial",
            "broker_order_lifecycle_collector_partial_batch",
        ),
    ],
)
def test_disconnect_and_partial_batch_are_persisted_without_cursor_advance(
    tmp_path,
    collection_mode: str,
    connection_status: str,
    batch_status: str,
    expected_blocker: str,
) -> None:
    db_path = tmp_path / f"{connection_status}-{batch_status}.db"
    _accept_live_release(db_path)
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    payload = _batch(
        run_id=f"collector-{connection_status}-{batch_status}",
        collection_mode=collection_mode,
        source_contact_status="read_only_contact",
        release_review_status="reviewed",
        connection_status=connection_status,
        batch_status=batch_status,
        event_count=0,
    )
    payload["lifecycle"] = None

    result = _ingest(repository, _preview(payload))

    assert result["run_status"] == "blocked"
    assert expected_blocker in result["blockers"]
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_found"
    )
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path,
            ensure_schema=False,
        ).list_observations()
        == []
    )


def test_process_restart_replays_prepared_preview_without_duplicate_fact(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    first_process = BrokerOrderLifecycleCollectorRepository(db_path)
    preview = _preview(_batch(run_id="collector-restart-run"))

    prepared = first_process.prepare(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )
    assert prepared["run_status"] == "prepared"
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path,
            ensure_schema=False,
        ).list_observations()
        == []
    )

    restarted_process = BrokerOrderLifecycleCollectorRepository(db_path)
    recorded = restarted_process.commit_prepared("collector-restart-run")
    replayed = restarted_process.commit_prepared("collector-restart-run")

    assert recorded["run_status"] == "recorded"
    assert replayed["run_status"] == "recorded"
    assert replayed["reused"] is True
    assert (
        len(
            BrokerOrderLifecycleEvidenceRepository(
                db_path,
                ensure_schema=False,
            ).list_observations()
        )
        == 1
    )


def test_deployment_drift_blocks_next_cursor(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    _ingest(repository, _preview(_batch()))
    second_payload = _batch(
        run_id="collector-run-2",
        cursor_previous=1,
        cursor_current=2,
        captured_at=NOW + timedelta(seconds=1),
        lifecycle=_lifecycle(
            cursor=2,
            captured_at=NOW + timedelta(seconds=1),
        ),
        deployment_fingerprint="e" * 64,
    )

    result = _ingest(repository, _preview(second_payload))

    assert result["run_status"] == "blocked"
    assert (
        "broker_order_lifecycle_collector_deployment_fingerprint_changed"
        in result["blockers"]
    )
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["last_cursor"]
        == 1
    )


def test_duplicate_and_out_of_order_callback_telemetry_cannot_add_facts(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    _accept_live_release(db_path)
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    payload = _batch(
        collection_mode="callback",
        source_contact_status="read_only_contact",
        connection_status="connected",
        release_review_status="reviewed",
        callbacks_received=4,
        duplicate_callbacks_dropped=2,
        out_of_order_callbacks_dropped=1,
    )

    result = _ingest(repository, _preview(payload))

    assert result["run_status"] == "recorded"
    assert result["callbacks_received"] == 4
    assert result["duplicate_callbacks_dropped"] == 2
    assert result["out_of_order_callbacks_dropped"] == 1
    assert (
        len(
            BrokerOrderLifecycleEvidenceRepository(
                db_path,
                ensure_schema=False,
            ).list_observations()
        )
        == 1
    )


def test_live_source_requires_reviewed_read_only_adapter_authorization(
    tmp_path,
) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    payload = _batch(
        collection_mode="callback",
        source_contact_status="read_only_contact",
        connection_status="connected",
        release_review_status="reviewed",
        callbacks_received=1,
    )

    result = _ingest(repository, _preview(payload))

    assert result["run_status"] == "blocked"
    assert "broker_adapter_release_review_not_found" in result["blockers"]
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_found"
    )


def test_preview_drift_and_wrong_acknowledgement_are_rejected(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    preview = _preview(_batch())
    drifted = deepcopy(preview)
    drifted["cursor_current"] = 2

    with pytest.raises(BrokerOrderLifecycleCollectorRejected) as wrong_ack:
        repository.prepare(preview, acknowledgement="")
    with pytest.raises(BrokerOrderLifecycleCollectorRejected) as drift:
        repository.prepare(
            drifted,
            acknowledgement=(BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT),
        )

    assert "broker_order_lifecycle_collector_acknowledgement_mismatch" in (
        wrong_ack.value.evidence["blockers"]
    )
    assert "broker_order_lifecycle_collector_preview_fingerprint_drift" in (
        drift.value.evidence["blockers"]
    )


def test_read_only_repository_does_not_create_absent_database(tmp_path) -> None:
    db_path = tmp_path / "absent.db"
    repository = BrokerOrderLifecycleCollectorRepository(
        db_path,
        ensure_schema=False,
    )

    assert repository.list_runs() == []
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_configured"
    )
    assert db_path.exists() is False


def test_only_expected_evidence_tables_are_created(tmp_path) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    _ingest(repository, _preview(_batch()))

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "oms_orders" not in tables
    assert "fills" not in tables
    assert "capital_authorizations" not in tables
    assert {
        "broker_order_lifecycle_collector_runs",
        "broker_order_lifecycle_collector_state",
        "broker_order_lifecycle_observations",
        "broker_order_lifecycle_orders",
        "broker_order_lifecycle_fills",
    }.issubset(tables)


def test_recorded_collector_observation_resolves_as_healthy_binding(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    recorded = _ingest(repository, _preview(_batch()))

    resolved = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )

    collector = resolved["collector_evidence"]
    assert recorded["run_status"] == "recorded"
    assert collector["status"] == "healthy"
    assert collector["required"] is True
    assert collector["observation_bound"] is True
    assert collector["matching_run_id"] == "collector-run-1"
    assert collector["latest_run_id"] == "collector-run-1"
    assert collector["blockers"] == []
    assert collector["provider_contacted_by_karkinos"] is False
    assert collector["broker_submission_enabled"] is False


def test_prepared_restart_recovery_reblocks_until_cursor_commit(tmp_path) -> None:
    db_path = tmp_path / "collector.db"
    first_process = BrokerOrderLifecycleCollectorRepository(db_path)
    _ingest(first_process, _preview(_batch()))
    captured_at = NOW + timedelta(seconds=1)
    second_payload = _batch(
        run_id="collector-restart-pending",
        cursor_previous=1,
        cursor_current=2,
        captured_at=captured_at,
        lifecycle=_lifecycle(cursor=2, captured_at=captured_at),
    )
    prepared = first_process.prepare(
        _preview(second_payload),
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )

    before_recovery = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )
    before_collector = before_recovery["collector_evidence"]

    restarted_process = BrokerOrderLifecycleCollectorRepository(db_path)
    recovered = restarted_process.commit_prepared("collector-restart-pending")
    after_recovery = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )

    assert prepared["run_status"] == "prepared"
    assert before_collector["status"] == "recovery_pending"
    assert "broker_order_lifecycle_collector_recovery_pending" in (
        before_collector["blockers"]
    )
    assert recovered["run_status"] == "recorded"
    assert after_recovery["collector_evidence"]["status"] == "healthy"
    assert after_recovery["collector_evidence"]["state_cursor"] == 2


def test_direct_import_cannot_bypass_existing_collector_scope(tmp_path) -> None:
    db_path = tmp_path / "collector.db"
    collector_repository = BrokerOrderLifecycleCollectorRepository(db_path)
    _ingest(collector_repository, _preview(_batch()))
    captured_at = NOW + timedelta(seconds=1)
    direct_preview = preview_broker_order_lifecycle_export(
        json.dumps(_lifecycle(cursor=2, captured_at=captured_at)),
        source_name="explicit direct fixture import",
        clock=lambda: captured_at,
    )
    BrokerOrderLifecycleEvidenceRepository(db_path).record(
        direct_preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )

    resolved = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )
    blockers = broker_order_lifecycle_clearance_blockers(
        {
            "symbol": "600519",
            "side": "buy",
            "quantity": "100",
        },
        resolved,
    )

    assert resolved["collector_evidence"]["status"] == "unbound"
    assert "broker_order_lifecycle_collector_observation_not_bound" in (
        resolved["collector_evidence"]["blockers"]
    )
    assert blockers == ["controlled_submission_clearance_lifecycle_collector_unhealthy"]


def test_partial_poll_batch_reblocks_previously_healthy_collector_scope(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    _ingest(repository, _preview(_batch()))
    _accept_live_release(db_path)
    captured_at = NOW + timedelta(seconds=1)
    partial_payload = _batch(
        run_id="collector-partial-poll-2",
        cursor_previous=1,
        cursor_current=2,
        captured_at=captured_at,
        collection_mode="poll",
        source_contact_status="read_only_contact",
        connection_status="connected",
        release_review_status="reviewed",
        batch_status="partial",
        event_count=0,
    )
    partial_payload["lifecycle"] = None

    partial = _ingest(repository, _preview(partial_payload))
    resolved = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )

    assert partial["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_partial_batch" in partial["blockers"]
    assert resolved["collector_evidence"]["status"] == "blocked"
    assert "broker_order_lifecycle_collector_latest_run_blocked" in (
        resolved["collector_evidence"]["blockers"]
    )


def test_release_revocation_between_prepare_and_commit_blocks_restart_replay(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    _accept_live_release(db_path)
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    payload = _batch(
        run_id="collector-release-revoked-during-prepare",
        collection_mode="callback",
        source_contact_status="read_only_contact",
        connection_status="connected",
        release_review_status="reviewed",
        callbacks_received=1,
    )
    prepared = repository.prepare(
        _preview(payload),
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )
    BrokerAdapterReleaseReviewRepository(db_path).record_review(
        _release_preview(),
        review_id="fixture-release-review-revoked-v1",
        decision="revoked",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=(NOW + timedelta(seconds=1)).isoformat(),
        reason_ref="fixture-release-disabled",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )

    restarted = BrokerOrderLifecycleCollectorRepository(db_path)
    result = restarted.commit_prepared("collector-release-revoked-during-prepare")

    assert prepared["run_status"] == "prepared"
    assert result["run_status"] == "blocked"
    assert (
        "broker_order_lifecycle_collector_adapter_release_review_blocked"
        in result["blockers"]
    )
    assert "broker_adapter_release_review_not_accepted" in result["blockers"]
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path,
            ensure_schema=False,
        ).list_observations()
        == []
    )


def test_newer_failed_conformance_between_prepare_and_commit_blocks_replay(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector-conformance-drift.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    _accept_live_release(db_path)
    live_payload = _batch(
        run_id="collector-conformance-failed-during-prepare",
        collection_mode="callback",
        source_contact_status="read_only_contact",
        connection_status="connected",
        release_review_status="reviewed",
        callbacks_received=1,
    )
    prepared = repository.prepare(
        _preview(live_payload),
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )

    release_preview = _release_preview()
    failed_result = run_deterministic_broker_adapter_conformance(
        release_preview,
        run_id="fixture-live-conformance-v2-failed",
    )
    failed_payload = {
        key: deepcopy(failed_result[key])
        for key in (
            "run_id",
            "release_evidence_ref",
            "manifest_fingerprint",
            "suite_version",
            "fixture_kind",
            "scenarios",
            "provider_contacted",
            "adapter_registered",
            "broker_write_contacted",
        )
    }
    failed_payload["schema_version"] = "karkinos.broker_adapter_conformance_result.v1"
    failed_payload["scenarios"][0]["observed_status"] = "unexpected"
    failed_preview = preview_broker_adapter_conformance_result(failed_payload)
    BrokerAdapterConformanceRepository(db_path).record_report(
        failed_preview,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )

    restarted = BrokerOrderLifecycleCollectorRepository(db_path)
    result = restarted.commit_prepared("collector-conformance-failed-during-prepare")

    assert prepared["run_status"] == "prepared"
    assert result["run_status"] == "blocked"
    assert "broker_adapter_conformance_latest_report_not_passed" in (result["blockers"])
    assert "broker_adapter_release_conformance_review_drift" in result["blockers"]
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path,
            ensure_schema=False,
        ).list_observations()
        == []
    )


def test_direct_import_without_collector_history_preserves_optional_boundary(
    tmp_path,
) -> None:
    db_path = tmp_path / "direct.db"
    preview = preview_broker_order_lifecycle_export(
        json.dumps(_lifecycle()),
        source_name="explicit direct fixture import",
        clock=lambda: NOW,
    )
    BrokerOrderLifecycleEvidenceRepository(db_path).record(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )

    resolved = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )

    assert resolved["collector_evidence"]["status"] == "not_configured"
    assert resolved["collector_evidence"]["required"] is False
