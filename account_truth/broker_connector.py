"""Read-only broker connector contract for account-truth evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

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


class LocalJsonReadOnlyBrokerConnector:
    """Read a local broker snapshot export without contacting a broker client."""

    def __init__(
        self,
        *,
        connector_id: str,
        snapshot_path: str | Path,
        account_alias: str = "",
    ) -> None:
        self.connector_id = connector_id
        self.snapshot_path = Path(snapshot_path)
        self.account_alias = account_alias

    @property
    def capabilities(self) -> BrokerConnectorCapabilities:
        return BrokerConnectorCapabilities()

    def read_account_snapshot(self) -> BrokerConnectorSnapshot:
        data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        captured_at = str(data.get("captured_at") or "")
        health_data = _dict(data.get("health"))
        health = BrokerConnectorHealth(
            status=_health_status(health_data.get("status")),
            checked_at=str(health_data.get("checked_at") or captured_at),
            message=str(health_data.get("message") or ""),
            limitations=_string_list(health_data.get("limitations")),
        )
        limitations = [
            "Local JSON snapshot export; no broker client is contacted.",
            *_string_list(data.get("limitations")),
        ]
        return BrokerConnectorSnapshot(
            connector_id=self.connector_id or str(data.get("connector_id") or ""),
            source_name=str(data.get("source_name") or "local readonly export"),
            account_id=str(data.get("account_id") or ""),
            account_alias=self.account_alias or str(data.get("account_alias") or ""),
            captured_at=captured_at,
            health=health,
            cash=_cash_fact(data.get("cash")),
            positions=[
                _position_fact(item) for item in _dict_list(data.get("positions"))
            ],
            orders=[_order_fact(item) for item in _dict_list(data.get("orders"))],
            fills=[_fill_fact(item) for item in _dict_list(data.get("fills"))],
            limitations=limitations,
        )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _decimal(value: Any, default: str = "0") -> Decimal:
    return Decimal(str(value if value is not None else default))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _health_status(value: Any) -> BrokerConnectorHealthStatus:
    status = str(value or "").strip()
    if status in {
        "healthy",
        "disconnected",
        "stale",
        "permission_limited",
        "incomplete",
    }:
        return status  # type: ignore[return-value]
    return "incomplete"


def _cash_fact(value: Any) -> BrokerCashFact | None:
    data = _dict(value)
    if not data:
        return None
    return BrokerCashFact(
        currency=str(data.get("currency") or "CNY"),
        balance=_decimal(data.get("balance")),
        available=_optional_decimal(data.get("available")),
    )


def _position_fact(data: dict[str, Any]) -> BrokerPositionFact:
    return BrokerPositionFact(
        symbol=str(data.get("symbol") or ""),
        instrument_name=str(data.get("instrument_name") or ""),
        asset_class=str(data.get("asset_class") or ""),
        quantity=_decimal(data.get("quantity")),
        available_quantity=_optional_decimal(data.get("available_quantity")),
        cost_basis=_optional_decimal(data.get("cost_basis")),
        market_price=_optional_decimal(data.get("market_price")),
    )


def _order_fact(data: dict[str, Any]) -> BrokerOrderFact:
    return BrokerOrderFact(
        order_id=str(data.get("order_id") or ""),
        symbol=str(data.get("symbol") or ""),
        side=str(data.get("side") or ""),
        status=str(data.get("status") or ""),
        quantity=_decimal(data.get("quantity")),
        price=_optional_decimal(data.get("price")),
        submitted_at=str(data.get("submitted_at") or ""),
    )


def _fill_fact(data: dict[str, Any]) -> BrokerFillFact:
    return BrokerFillFact(
        fill_id=str(data.get("fill_id") or ""),
        order_id=str(data.get("order_id") or ""),
        symbol=str(data.get("symbol") or ""),
        side=str(data.get("side") or ""),
        quantity=_decimal(data.get("quantity")),
        price=_decimal(data.get("price")),
        fee=_decimal(data.get("fee")),
        tax=_decimal(data.get("tax")),
        net_amount=_decimal(data.get("net_amount")),
        filled_at=str(data.get("filled_at") or ""),
    )
