"""Read-only broker connector contract for account-truth evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

BrokerConnectorHealthStatus = Literal[
    "healthy",
    "disconnected",
    "stale",
    "permission_limited",
    "incomplete",
]


@dataclass(frozen=True)
class BrokerConnectorCapabilities:
    """Connector capabilities; broker submission must stay explicitly disabled."""

    can_read_account: bool = True
    can_read_cash: bool = True
    can_read_positions: bool = True
    can_read_orders: bool = True
    can_read_fills: bool = True
    can_read_health: bool = True
    can_submit_orders: bool = False


@dataclass(frozen=True)
class BrokerConnectorHealth:
    """Health evidence returned by a read-only broker connector."""

    status: BrokerConnectorHealthStatus
    checked_at: str
    message: str = ""
    limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BrokerCashFact:
    """Read-only broker cash evidence."""

    currency: str
    balance: Decimal
    available: Decimal | None = None


@dataclass(frozen=True)
class BrokerPositionFact:
    """Read-only broker position evidence."""

    symbol: str
    instrument_name: str
    asset_class: str
    quantity: Decimal
    available_quantity: Decimal | None = None
    cost_basis: Decimal | None = None
    market_price: Decimal | None = None


@dataclass(frozen=True)
class BrokerOrderFact:
    """Read-only broker order evidence."""

    order_id: str
    symbol: str
    side: str
    status: str
    quantity: Decimal
    price: Decimal | None
    submitted_at: str


@dataclass(frozen=True)
class BrokerFillFact:
    """Read-only broker fill evidence."""

    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    tax: Decimal
    net_amount: Decimal
    filled_at: str


@dataclass(frozen=True)
class BrokerConnectorSnapshot:
    """One read-only account snapshot from a broker connector."""

    connector_id: str
    source_name: str
    account_id: str
    account_alias: str
    captured_at: str
    health: BrokerConnectorHealth
    cash: BrokerCashFact | None = None
    positions: list[BrokerPositionFact] = field(default_factory=list)
    orders: list[BrokerOrderFact] = field(default_factory=list)
    fills: list[BrokerFillFact] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


class ReadOnlyBrokerConnector(Protocol):
    """Capability-based broker connector contract with no submit method."""

    @property
    def capabilities(self) -> BrokerConnectorCapabilities:
        """Return read capabilities for the connector."""

    def read_account_snapshot(self) -> BrokerConnectorSnapshot:
        """Read account facts without mutating broker or Karkinos state."""


class FakeReadOnlyBrokerConnector:
    """Deterministic read-only connector for tests and local development."""

    def __init__(
        self,
        snapshot: BrokerConnectorSnapshot,
        *,
        capabilities: BrokerConnectorCapabilities | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._capabilities = capabilities or BrokerConnectorCapabilities()

    @property
    def capabilities(self) -> BrokerConnectorCapabilities:
        return self._capabilities

    def read_account_snapshot(self) -> BrokerConnectorSnapshot:
        return self._snapshot
