from __future__ import annotations

import json
from decimal import Decimal

import pytest

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerFillFact,
    BrokerOrderFact,
    BrokerPositionFact,
    FakeReadOnlyBrokerConnector,
    LocalJsonReadOnlyBrokerConnector,
    LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
)


def _local_snapshot_payload() -> dict:
    return {
        "schema_version": LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
        "connector_id": "local-fixture-export",
        "source_name": "Deterministic local readonly export",
        "account_id": "private-account-id",
        "captured_at": "2026-07-03T15:01:00+08:00",
        "health": {
            "status": "healthy",
            "checked_at": "2026-07-03T15:00:00+08:00",
            "message": "Local export parsed.",
        },
        "source_contract": {
            "deployment_identity": "synthetic-deployment-001",
            "batch_id": "synthetic-batch-001",
            "cursor": {"previous": 0, "current": 1},
            "trading_day": "2026-07-03",
            "session_phase": "end_of_day",
            "heartbeat_at": "2026-07-03T15:00:30+08:00",
            "completeness": {
                "cash": True,
                "positions": True,
                "orders": True,
                "fills": True,
            },
        },
        "cash": {
            "currency": "CNY",
            "balance": "100000.00",
            "available": "88000.00",
        },
        "positions": [
            {
                "symbol": "600519",
                "instrument_name": "贵州茅台",
                "asset_class": "stock",
                "quantity": "200",
                "available_quantity": "100",
                "cost_basis": "1600.00",
                "market_price": "1688.00",
            }
        ],
        "orders": [
            {
                "order_id": "broker-order-private",
                "symbol": "600519",
                "side": "buy",
                "status": "filled",
                "quantity": "100",
                "price": "1688.00",
                "submitted_at": "2026-07-03T09:31:10+08:00",
            }
        ],
        "fills": [
            {
                "fill_id": "fill-001",
                "order_id": "broker-order-private",
                "symbol": "600519",
                "side": "buy",
                "quantity": "100",
                "price": "1688.00",
                "fee": "5.10",
                "tax": "0",
                "net_amount": "-168805.10",
                "filled_at": "2026-07-03T09:31:20+08:00",
            }
        ],
        "limitations": ["Local export file; no broker client contacted."],
    }


def test_read_only_broker_connector_reads_account_facts_without_submit() -> None:
    snapshot = BrokerConnectorSnapshot(
        connector_id="fake_qmt_readonly",
        source_name="synthetic deterministic readonly fixture",
        account_id="synthetic-account",
        account_alias="safe-local-alias",
        captured_at="2026-06-22T15:05:00+08:00",
        health=BrokerConnectorHealth(
            status="healthy",
            checked_at="2026-06-22T15:05:00+08:00",
            message="synthetic connector is healthy",
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal("10000.00"),
            available=Decimal("8800.00"),
        ),
        positions=[
            BrokerPositionFact(
                symbol="SYN001",
                instrument_name="合成样例股票A",
                asset_class="stock",
                quantity=Decimal("100"),
                available_quantity=Decimal("0"),
                cost_basis=Decimal("10.25"),
                market_price=Decimal("10.40"),
            )
        ],
        orders=[
            BrokerOrderFact(
                order_id="synthetic-order-001",
                symbol="SYN001",
                side="buy",
                status="filled",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                submitted_at="2026-06-22T10:05:00+08:00",
            )
        ],
        fills=[
            BrokerFillFact(
                fill_id="synthetic-fill-001",
                order_id="synthetic-order-001",
                symbol="SYN001",
                side="buy",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                fee=Decimal("5.00"),
                tax=Decimal("0.00"),
                net_amount=Decimal("-1028.00"),
                filled_at="2026-06-22T10:05:05+08:00",
            )
        ],
        limitations=["Synthetic fixture; no broker client is contacted."],
    )
    connector = FakeReadOnlyBrokerConnector(snapshot)

    result = connector.read_account_snapshot()

    assert connector.capabilities == BrokerConnectorCapabilities(
        can_read_account=True,
        can_read_cash=True,
        can_read_positions=True,
        can_read_orders=True,
        can_read_fills=True,
        can_read_health=True,
        can_submit_orders=False,
    )
    assert not hasattr(connector, "submit_order")
    assert result.account_id == "synthetic-account"
    assert result.account_alias == "safe-local-alias"
    assert result.cash.balance == Decimal("10000.00")
    assert result.positions[0].symbol == "SYN001"
    assert result.orders[0].order_id == "synthetic-order-001"
    assert result.fills[0].fill_id == "synthetic-fill-001"
    assert result.health.status == "healthy"
    assert result.limitations == ["Synthetic fixture; no broker client is contacted."]


def test_fake_broker_connector_exposes_diagnostic_health_states() -> None:
    for status in ["disconnected", "stale", "permission_limited", "incomplete"]:
        connector = FakeReadOnlyBrokerConnector(
            BrokerConnectorSnapshot(
                connector_id=f"fake_{status}",
                source_name="synthetic diagnostic fixture",
                account_id="synthetic-account",
                account_alias="safe-local-alias",
                captured_at="2026-06-22T15:05:00+08:00",
                health=BrokerConnectorHealth(
                    status=status,
                    checked_at="2026-06-22T15:05:00+08:00",
                    message=f"synthetic {status} state",
                    limitations=[f"{status} fixture limitation"],
                ),
            )
        )

        result = connector.read_account_snapshot()

        assert result.health.status == status
        assert result.health.limitations == [f"{status} fixture limitation"]
        assert connector.capabilities.can_submit_orders is False
        assert not hasattr(connector, "submit_order")


def test_local_json_readonly_connector_reads_export_without_submit(tmp_path) -> None:
    snapshot_path = tmp_path / "fixture-snapshot.json"
    snapshot_path.write_text(
        json.dumps(_local_snapshot_payload()),
        encoding="utf-8",
    )
    connector = LocalJsonReadOnlyBrokerConnector(
        connector_id="local-fixture-export",
        snapshot_path=snapshot_path,
        account_alias="local-review",
    )

    snapshot = connector.read_account_snapshot()

    assert connector.capabilities == BrokerConnectorCapabilities()
    assert not hasattr(connector, "submit_order")
    assert snapshot.connector_id == "local-fixture-export"
    assert snapshot.source_name == "Deterministic local readonly export"
    assert snapshot.account_id == "private-account-id"
    assert snapshot.account_alias == "local-review"
    assert snapshot.health.status == "healthy"
    assert snapshot.cash.balance == Decimal("100000.00")
    assert snapshot.positions[0].symbol == "600519"
    assert snapshot.orders[0].order_id == "broker-order-private"
    assert snapshot.fills[0].net_amount == Decimal("-168805.10")
    assert snapshot.source_contract is not None
    assert snapshot.source_contract.schema_version == (
        LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION
    )
    assert snapshot.source_contract.deployment_identity == ("synthetic-deployment-001")
    assert snapshot.source_contract.complete_scopes is True
    assert "Local export file; no broker client contacted." in snapshot.limitations


def test_local_json_readonly_connector_degrades_invalid_export_without_submit(
    tmp_path,
) -> None:
    snapshot_path = tmp_path / "fixture-snapshot-invalid.json"
    payload = _local_snapshot_payload()
    payload["positions"][0]["quantity"] = "not-a-number"
    snapshot_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    connector = LocalJsonReadOnlyBrokerConnector(
        connector_id="local-fixture-export",
        snapshot_path=snapshot_path,
        account_alias="local-review",
    )

    snapshot = connector.read_account_snapshot()

    assert not hasattr(connector, "submit_order")
    assert snapshot.connector_id == "local-fixture-export"
    assert snapshot.source_name == "local readonly export"
    assert snapshot.account_id == ""
    assert snapshot.account_alias == "local-review"
    assert snapshot.health.status == "incomplete"
    assert snapshot.health.message == (
        "Local JSON snapshot export is invalid; review the ignored local export file."
    )
    assert snapshot.health.limitations == [
        "parse_error:InvalidLocalJsonSnapshotContract",
        "No broker client was contacted and no broker order was submitted.",
    ]
    assert snapshot.cash is None
    assert snapshot.positions == []
    assert snapshot.orders == []
    assert snapshot.fills == []
    assert snapshot.limitations == [
        "Local JSON snapshot export could not be parsed; no broker client is contacted.",
        "Broker order submission remains disabled.",
    ]


def test_local_json_readonly_connector_degrades_unsupported_schema_without_submit(
    tmp_path,
) -> None:
    snapshot_path = tmp_path / "fixture-snapshot-wrong-schema.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "other.app.account_snapshot.v1",
                "source_name": "Deterministic local readonly export",
                "account_id": "private-account-id",
                "captured_at": "2026-07-03T15:01:00+08:00",
                "health": {
                    "status": "healthy",
                    "checked_at": "2026-07-03T15:00:00+08:00",
                    "message": "Wrong local export parsed.",
                },
                "cash": {
                    "currency": "CNY",
                    "balance": "100000.00",
                    "available": "88000.00",
                },
            }
        ),
        encoding="utf-8",
    )
    connector = LocalJsonReadOnlyBrokerConnector(
        connector_id="local-fixture-export",
        snapshot_path=snapshot_path,
        account_alias="local-review",
    )

    snapshot = connector.read_account_snapshot()

    assert not hasattr(connector, "submit_order")
    assert snapshot.connector_id == "local-fixture-export"
    assert snapshot.account_id == ""
    assert snapshot.account_alias == "local-review"
    assert snapshot.health.status == "incomplete"
    assert snapshot.health.limitations == [
        "parse_error:UnsupportedLocalJsonSnapshotSchema",
        "No broker client was contacted and no broker order was submitted.",
    ]
    assert snapshot.cash is None
    assert snapshot.positions == []
    assert snapshot.orders == []
    assert snapshot.fills == []


def test_local_json_readonly_connector_rejects_legacy_v1_and_identity_drift(
    tmp_path,
) -> None:
    for name, mutate in (
        (
            "legacy-v1",
            lambda payload: payload.update(
                {"schema_version": "karkinos.readonly_broker_snapshot_export.v1"}
            ),
        ),
        (
            "connector-mismatch",
            lambda payload: payload.update({"connector_id": "other-connector"}),
        ),
    ):
        payload = _local_snapshot_payload()
        mutate(payload)
        snapshot_path = tmp_path / f"{name}.json"
        snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
        connector = LocalJsonReadOnlyBrokerConnector(
            connector_id="local-fixture-export",
            snapshot_path=snapshot_path,
            account_alias="local-review",
        )

        snapshot = connector.read_account_snapshot()

        assert snapshot.health.status == "incomplete"
        assert snapshot.source_contract is None
        assert snapshot.account_id == ""
        assert snapshot.cash is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda payload: payload["source_contract"]["completeness"].update(
                {"orders": False}
            ),
            "incomplete-scope",
        ),
        (
            lambda payload: payload.update({"access_token": "must-not-be-read"}),
            "unknown-sensitive-field",
        ),
        (
            lambda payload: payload["fills"].append("not-an-object"),
            "partial-list-shape",
        ),
        (
            lambda payload: payload["fills"][0].update({"fee": "NaN"}),
            "non-finite-fee",
        ),
        (
            lambda payload: payload["source_contract"].update(
                {"cursor": "opaque-provider-cursor"}
            ),
            "cursor-shape",
        ),
        (
            lambda payload: payload["source_contract"].update(
                {"cursor": {"previous": 0, "current": 2}}
            ),
            "cursor-not-consecutive",
        ),
    ],
)
def test_local_json_readonly_connector_fails_closed_on_partial_or_unsafe_contract(
    tmp_path,
    mutation,
    reason,
) -> None:
    payload = _local_snapshot_payload()
    mutation(payload)
    snapshot_path = tmp_path / f"{reason}.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    connector = LocalJsonReadOnlyBrokerConnector(
        connector_id="local-fixture-export",
        snapshot_path=snapshot_path,
        account_alias="local-review",
    )

    snapshot = connector.read_account_snapshot()

    assert snapshot.health.status == "incomplete"
    assert snapshot.account_id == (
        "private-account-id" if reason == "incomplete-scope" else ""
    )
    if reason == "incomplete-scope":
        assert snapshot.source_contract is not None
        assert snapshot.source_contract.orders_complete is False
        assert "source_contract_declares_incomplete_scope" in (
            snapshot.health.limitations
        )
    else:
        assert snapshot.source_contract is None
        assert snapshot.cash is None
