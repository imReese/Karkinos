"""Deterministic local fixtures for the broker-neutral conformance contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_FIXTURE_KIND,
    BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION,
    BROKER_ADAPTER_CONFORMANCE_SUITE_VERSION,
    preview_broker_adapter_conformance_result,
)
from account_truth.broker_connector import (
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
    LocalJsonReadOnlyBrokerConnector,
)
from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
    preview_broker_order_lifecycle_export,
)
from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleCollectorRepository,
    preview_broker_order_lifecycle_collector_batch,
)

_FIXED_CLOCK = datetime(2026, 1, 2, 8, 0, 0, tzinfo=UTC)


def run_deterministic_broker_adapter_conformance(
    release_preview: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Execute the built-in suite in an isolated temp DB with no provider contact."""

    with TemporaryDirectory(prefix="karkinos-broker-conformance-") as directory:
        root = Path(directory)
        scenarios = [
            *_snapshot_scenarios(root),
            *_lifecycle_scenarios(root),
        ]
    return preview_broker_adapter_conformance_result(
        {
            "schema_version": BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION,
            "run_id": run_id,
            "release_evidence_ref": str(
                release_preview.get("release_evidence_ref") or ""
            ),
            "manifest_fingerprint": str(
                release_preview.get("manifest_fingerprint") or ""
            ),
            "suite_version": BROKER_ADAPTER_CONFORMANCE_SUITE_VERSION,
            "fixture_kind": BROKER_ADAPTER_CONFORMANCE_FIXTURE_KIND,
            "scenarios": scenarios,
            "provider_contacted": False,
            "adapter_registered": False,
            "broker_write_contacted": False,
        }
    )


def _snapshot_scenarios(root: Path) -> list[dict[str, str]]:
    scenarios: list[dict[str, str]] = []
    for scenario, health_status in (
        ("healthy_snapshot", "healthy"),
        ("disconnected_snapshot", "disconnected"),
        ("stale_snapshot", "stale"),
        ("permission_limited_snapshot", "permission_limited"),
        ("incomplete_snapshot", "incomplete"),
    ):
        connector = FakeReadOnlyBrokerConnector(
            BrokerConnectorSnapshot(
                connector_id="deterministic-fixture-connector",
                source_name="deterministic local fixture",
                account_id="local-fixture-account",
                account_alias="fixture-account",
                captured_at=_FIXED_CLOCK.isoformat(),
                health=BrokerConnectorHealth(
                    status=health_status,  # type: ignore[arg-type]
                    checked_at=_FIXED_CLOCK.isoformat(),
                ),
            ),
            capabilities=BrokerConnectorCapabilities(can_submit_orders=False),
        )
        snapshot = connector.read_account_snapshot()
        observed = (
            "healthy"
            if snapshot.health.status == "healthy"
            and connector.capabilities.can_submit_orders is False
            else "blocked"
        )
        scenarios.append(
            _scenario(
                scenario,
                expected_status=(
                    "healthy" if scenario == "healthy_snapshot" else "blocked"
                ),
                observed_status=observed,
                evidence={
                    "health_status": snapshot.health.status,
                    "can_submit_orders": connector.capabilities.can_submit_orders,
                },
            )
        )

    drift_path = root / "unsupported-snapshot-schema.json"
    drift_path.write_text(
        json.dumps(
            {
                "schema_version": "unsupported.fixture.schema.v999",
                "captured_at": _FIXED_CLOCK.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    drift_connector = LocalJsonReadOnlyBrokerConnector(
        connector_id="deterministic-schema-drift-fixture",
        snapshot_path=drift_path,
        account_alias="fixture-account",
    )
    drift_snapshot = drift_connector.read_account_snapshot()
    scenarios.append(
        _scenario(
            "snapshot_schema_drift",
            expected_status="blocked",
            observed_status=(
                "blocked"
                if drift_snapshot.health.status == "incomplete"
                else "unexpected"
            ),
            evidence={
                "health_status": drift_snapshot.health.status,
                "limitations": sorted(drift_snapshot.health.limitations),
                "can_submit_orders": drift_connector.capabilities.can_submit_orders,
            },
        )
    )
    return scenarios


def _lifecycle_scenarios(root: Path) -> list[dict[str, str]]:
    main_repository = BrokerOrderLifecycleCollectorRepository(root / "main.db")
    first_preview = _collector_preview(_collector_batch(run_id="fixture-first"))
    first = _ingest(main_repository, first_preview)
    replay = _ingest(main_repository, first_preview)
    duplicate = _ingest(
        main_repository,
        _collector_preview(_collector_batch(run_id="fixture-duplicate")),
    )

    out_of_order_path = root / "out-of-order.db"
    prior_lifecycle = preview_broker_order_lifecycle_export(
        _json(_lifecycle(cursor=2)),
        source_name="deterministic prior lifecycle fixture",
        clock=lambda: _FIXED_CLOCK,
    )
    BrokerOrderLifecycleEvidenceRepository(out_of_order_path).record(
        prior_lifecycle,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )
    out_of_order_repository = BrokerOrderLifecycleCollectorRepository(out_of_order_path)
    out_of_order = _ingest(
        out_of_order_repository,
        _collector_preview(_collector_batch(run_id="fixture-out-of-order")),
    )

    disconnect_repository = BrokerOrderLifecycleCollectorRepository(
        root / "disconnect.db"
    )
    disconnected = _ingest(
        disconnect_repository,
        _collector_preview(
            _collector_batch(
                run_id="fixture-disconnect",
                connection_status="disconnected",
                batch_status="partial",
                event_count=0,
                lifecycle=None,
            )
        ),
    )

    partial_repository = BrokerOrderLifecycleCollectorRepository(root / "partial.db")
    partial = _ingest(
        partial_repository,
        _collector_preview(
            _collector_batch(
                run_id="fixture-partial",
                batch_status="partial",
                event_count=0,
                lifecycle=None,
            )
        ),
    )

    restart_path = root / "restart.db"
    restart_repository = BrokerOrderLifecycleCollectorRepository(restart_path)
    prepared = restart_repository.prepare(
        _collector_preview(_collector_batch(run_id="fixture-restart")),
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )
    restarted_repository = BrokerOrderLifecycleCollectorRepository(restart_path)
    committed = restarted_repository.commit_prepared("fixture-restart")
    committed_replay = restarted_repository.commit_prepared("fixture-restart")

    return [
        _scenario(
            "lifecycle_idempotent_replay",
            expected_status="reused",
            observed_status=(
                "reused"
                if first.get("run_status") == "recorded"
                and replay.get("reused") is True
                else "unexpected"
            ),
            evidence=_collector_evidence(first, replay),
        ),
        _scenario(
            "lifecycle_duplicate",
            expected_status="duplicate",
            observed_status=str(duplicate.get("run_status") or "unexpected"),
            evidence=_collector_evidence(duplicate),
        ),
        _scenario(
            "lifecycle_out_of_order",
            expected_status="blocked",
            observed_status=(
                "blocked"
                if "broker_order_lifecycle_collector_cursor_out_of_order"
                in (out_of_order.get("blockers") or [])
                else "unexpected"
            ),
            evidence=_collector_evidence(out_of_order),
        ),
        _scenario(
            "lifecycle_disconnect",
            expected_status="blocked",
            observed_status=(
                "blocked"
                if "broker_order_lifecycle_collector_disconnected"
                in (disconnected.get("blockers") or [])
                else "unexpected"
            ),
            evidence=_collector_evidence(disconnected),
        ),
        _scenario(
            "lifecycle_partial_batch",
            expected_status="blocked",
            observed_status=(
                "blocked"
                if "broker_order_lifecycle_collector_partial_batch"
                in (partial.get("blockers") or [])
                else "unexpected"
            ),
            evidence=_collector_evidence(partial),
        ),
        _scenario(
            "lifecycle_restart_replay",
            expected_status="recorded_and_reused",
            observed_status=(
                "recorded_and_reused"
                if prepared.get("run_status") == "prepared"
                and committed.get("run_status") == "recorded"
                and committed_replay.get("reused") is True
                else "unexpected"
            ),
            evidence=_collector_evidence(prepared, committed, committed_replay),
        ),
    ]


def _collector_batch(
    *,
    run_id: str,
    connection_status: str = "not_applicable",
    batch_status: str = "complete",
    event_count: int = 1,
    lifecycle: dict[str, Any] | None | object = ...,
) -> dict[str, Any]:
    effective_lifecycle = _lifecycle(cursor=1) if lifecycle is ... else lifecycle
    return {
        "schema_version": "karkinos.broker_order_lifecycle_collector_batch.v1",
        "run_id": run_id,
        "collector_id": "deterministic-fixture-collector",
        "deployment_id": "deterministic-fixture-deployment",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "d" * 64,
        "release_evidence_ref": "deterministic-fixture-release",
        "release_review_status": "unreviewed",
        "adapter_authorization_ref": "deterministic-fixture-authorization",
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-gateway",
        "account_id": "local-fixture-account",
        "account_alias": "fixture-account",
        "collection_mode": "fixture",
        "source_contact_status": "not_contacted",
        "connection_status": connection_status,
        "batch_status": batch_status,
        "cursor": {"previous": 0, "current": 1},
        "captured_at": _FIXED_CLOCK.isoformat(),
        "event_count": event_count,
        "callbacks_received": 0,
        "duplicate_callbacks_dropped": 0,
        "out_of_order_callbacks_dropped": 0,
        "lifecycle": effective_lifecycle,
    }


def _lifecycle(*, cursor: int) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "deterministic_fixture",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-gateway",
        "account_id": "local-fixture-account",
        "account_alias": "fixture-account",
        "captured_at": _FIXED_CLOCK.isoformat(),
        "source_sequence": cursor,
        "orders": [
            {
                "broker_order_id": "FIXTURE-ORDER-1",
                "client_order_id": "KARK-FIXTURE-CLIENT-1",
                "symbol": "600000",
                "side": "buy",
                "status": "open",
                "order_quantity": "100",
                "cumulative_filled_quantity": "0",
                "cancelled_quantity": "0",
                "average_fill_price": None,
                "submitted_at": "2026-01-02T07:59:58+00:00",
                "updated_at": "2026-01-02T07:59:59+00:00",
            }
        ],
        "fills": [],
    }


def _collector_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return preview_broker_order_lifecycle_collector_batch(
        _json(payload),
        source_name="deterministic broker conformance fixture",
        clock=lambda: _FIXED_CLOCK,
    )


def _ingest(
    repository: BrokerOrderLifecycleCollectorRepository,
    preview: dict[str, Any],
) -> dict[str, Any]:
    return repository.ingest(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )


def _scenario(
    scenario: str,
    *,
    expected_status: str,
    observed_status: str,
    evidence: dict[str, Any],
) -> dict[str, str]:
    return {
        "scenario": scenario,
        "expected_status": expected_status,
        "observed_status": observed_status,
        "evidence_fingerprint": _fingerprint(evidence),
    }


def _collector_evidence(*results: dict[str, Any]) -> dict[str, Any]:
    return {
        "results": [
            {
                "run_id": str(result.get("run_id") or ""),
                "run_status": str(result.get("run_status") or ""),
                "reused": bool(result.get("reused")),
                "blockers": sorted(str(item) for item in result.get("blockers") or []),
                "cursor_current": result.get("cursor_current"),
            }
            for result in results
        ]
    }


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = ["run_deterministic_broker_adapter_conformance"]
