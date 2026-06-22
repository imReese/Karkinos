from __future__ import annotations

from decimal import Decimal

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorCapabilities,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerFillFact,
    BrokerOrderFact,
    BrokerPositionFact,
    FakeReadOnlyBrokerConnector,
)


def test_read_only_broker_connector_reads_account_facts_without_submit() -> None:
    snapshot = BrokerConnectorSnapshot(
        connector_id="fake_qmt_readonly",
        source_name="synthetic qmt readonly fixture",
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
