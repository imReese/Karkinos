"""Read-only broker connector contract for account-truth evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

BrokerConnectorHealthStatus = Literal[
    "healthy",
    "disconnected",
    "stale",
    "permission_limited",
    "incomplete",
]
LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION = "karkinos.readonly_broker_snapshot_export.v2"

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TRADING_DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_SOURCE_SESSION_PHASES = frozenset({"startup", "intraday", "end_of_day"})
_ORDER_SIDES = frozenset({"buy", "sell"})
_ORDER_STATUSES = frozenset(
    {"submitted", "open", "partially_filled", "filled", "cancelled", "rejected"}
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "connector_id",
        "source_name",
        "account_id",
        "captured_at",
        "health",
        "source_contract",
        "cash",
        "positions",
        "orders",
        "fills",
        "limitations",
    }
)
_TOP_LEVEL_REQUIRED_FIELDS = _TOP_LEVEL_FIELDS - {"limitations"}
_HEALTH_FIELDS = frozenset({"status", "checked_at", "message", "limitations"})
_HEALTH_REQUIRED_FIELDS = frozenset({"status", "checked_at"})
_SOURCE_CONTRACT_FIELDS = frozenset(
    {
        "deployment_identity",
        "batch_id",
        "cursor",
        "trading_day",
        "session_phase",
        "heartbeat_at",
        "completeness",
    }
)
_CURSOR_FIELDS = frozenset({"previous", "current"})
_COMPLETENESS_FIELDS = frozenset({"cash", "positions", "orders", "fills"})
_CASH_FIELDS = frozenset({"currency", "balance", "available"})
_CASH_REQUIRED_FIELDS = frozenset({"currency", "balance"})
_POSITION_FIELDS = frozenset(
    {
        "symbol",
        "instrument_name",
        "asset_class",
        "quantity",
        "available_quantity",
        "cost_basis",
        "market_price",
    }
)
_POSITION_REQUIRED_FIELDS = frozenset(
    {"symbol", "instrument_name", "asset_class", "quantity"}
)
_ORDER_FIELDS = frozenset(
    {"order_id", "symbol", "side", "status", "quantity", "price", "submitted_at"}
)
_ORDER_REQUIRED_FIELDS = _ORDER_FIELDS
_FILL_FIELDS = frozenset(
    {
        "fill_id",
        "order_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "fee",
        "tax",
        "net_amount",
        "filled_at",
    }
)
_FILL_REQUIRED_FIELDS = _FILL_FIELDS


class UnsupportedLocalJsonSnapshotSchema(ValueError):
    """Raised when a local read-only snapshot is not the supported schema."""


class InvalidLocalJsonSnapshotContract(ValueError):
    """Raised when a local snapshot violates the reviewed v2 source contract."""


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
class BrokerConnectorSourceContract:
    """Versioned provenance and completeness bound to one connector snapshot."""

    schema_version: str
    connector_id: str
    deployment_identity: str
    batch_id: str
    cursor_previous: int
    cursor_current: int
    trading_day: str
    session_phase: str
    heartbeat_at: str
    cash_complete: bool
    positions_complete: bool
    orders_complete: bool
    fills_complete: bool

    @property
    def complete_scopes(self) -> bool:
        return all(
            (
                self.cash_complete,
                self.positions_complete,
                self.orders_complete,
                self.fills_complete,
            )
        )


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
    source_contract: BrokerConnectorSourceContract | None = None


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

    requires_source_contract = True

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
        try:
            data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            _validate_local_json_snapshot_schema(
                data,
                expected_connector_id=self.connector_id,
            )
            source_contract = _source_contract(data)
            captured_at = str(data.get("captured_at") or "")
            health_data = _dict(data.get("health"))
            declared_health_status = _health_status(health_data.get("status"))
            health = BrokerConnectorHealth(
                status=(
                    "incomplete"
                    if declared_health_status == "healthy"
                    and not source_contract.complete_scopes
                    else declared_health_status
                ),
                checked_at=str(health_data.get("checked_at") or captured_at),
                message=str(health_data.get("message") or ""),
                limitations=[
                    *_string_list(health_data.get("limitations")),
                    *(
                        ["source_contract_declares_incomplete_scope"]
                        if not source_contract.complete_scopes
                        else []
                    ),
                ],
            )
            limitations = [
                "Local JSON snapshot export; no broker client is contacted.",
                *_string_list(data.get("limitations")),
            ]
            return BrokerConnectorSnapshot(
                connector_id=self.connector_id or str(data.get("connector_id") or ""),
                source_name=str(data.get("source_name") or "local readonly export"),
                account_id=str(data.get("account_id") or ""),
                account_alias=self.account_alias
                or str(data.get("account_alias") or ""),
                captured_at=captured_at,
                health=health,
                cash=_cash_fact(data.get("cash")),
                positions=[
                    _position_fact(item) for item in _dict_list(data.get("positions"))
                ],
                orders=[_order_fact(item) for item in _dict_list(data.get("orders"))],
                fills=[_fill_fact(item) for item in _dict_list(data.get("fills"))],
                limitations=limitations,
                source_contract=source_contract,
            )
        except (
            OSError,
            json.JSONDecodeError,
            InvalidOperation,
            UnsupportedLocalJsonSnapshotSchema,
            InvalidLocalJsonSnapshotContract,
            TypeError,
            ValueError,
        ) as exc:
            return _invalid_local_json_snapshot(
                connector_id=self.connector_id,
                account_alias=self.account_alias,
                reason_code=type(exc).__name__,
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


def _validate_local_json_snapshot_schema(
    data: Any,
    *,
    expected_connector_id: str,
) -> None:
    if not isinstance(data, dict):
        raise UnsupportedLocalJsonSnapshotSchema
    if str(data.get("schema_version") or "") != LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION:
        raise UnsupportedLocalJsonSnapshotSchema
    _validate_fields(
        data,
        allowed=_TOP_LEVEL_FIELDS,
        required=_TOP_LEVEL_REQUIRED_FIELDS,
        context="snapshot",
    )
    connector_id = _required_string(data, "connector_id", "snapshot")
    if not expected_connector_id or connector_id != expected_connector_id:
        raise InvalidLocalJsonSnapshotContract("connector identity mismatch")
    _required_string(data, "source_name", "snapshot")
    _required_string(data, "account_id", "snapshot")
    captured_at = _required_aware_timestamp(data, "captured_at", "snapshot")

    health = _required_dict(data, "health", "snapshot")
    _validate_fields(
        health,
        allowed=_HEALTH_FIELDS,
        required=_HEALTH_REQUIRED_FIELDS,
        context="health",
    )
    if _required_string(health, "status", "health") not in {
        "healthy",
        "disconnected",
        "stale",
        "permission_limited",
        "incomplete",
    }:
        raise InvalidLocalJsonSnapshotContract("health status invalid")
    _required_aware_timestamp(health, "checked_at", "health")
    _optional_string_list(health.get("limitations"), "health limitations")

    source = _required_dict(data, "source_contract", "snapshot")
    _validate_fields(
        source,
        allowed=_SOURCE_CONTRACT_FIELDS,
        required=_SOURCE_CONTRACT_FIELDS,
        context="source contract",
    )
    for key in ("deployment_identity", "batch_id"):
        _required_string(source, key, "source contract")
    cursor = _required_dict(source, "cursor", "source contract")
    _validate_fields(
        cursor,
        allowed=_CURSOR_FIELDS,
        required=_CURSOR_FIELDS,
        context="source cursor",
    )
    cursor_previous = _required_nonnegative_int(
        cursor,
        "previous",
        "source cursor",
    )
    cursor_current = _required_nonnegative_int(
        cursor,
        "current",
        "source cursor",
    )
    if cursor_current <= 0 or cursor_current != cursor_previous + 1:
        raise InvalidLocalJsonSnapshotContract("source cursor is not consecutive")
    trading_day = _required_string(source, "trading_day", "source contract")
    if not _TRADING_DAY_PATTERN.fullmatch(trading_day):
        raise InvalidLocalJsonSnapshotContract("trading day invalid")
    try:
        parsed_trading_day = datetime.fromisoformat(trading_day).date()
    except ValueError as exc:
        raise InvalidLocalJsonSnapshotContract("trading day invalid") from exc
    if captured_at.astimezone(_SHANGHAI).date() != parsed_trading_day:
        raise InvalidLocalJsonSnapshotContract("trading day mismatch")
    if _required_string(source, "session_phase", "source contract") not in (
        _SOURCE_SESSION_PHASES
    ):
        raise InvalidLocalJsonSnapshotContract("session phase invalid")
    _required_aware_timestamp(source, "heartbeat_at", "source contract")
    completeness = _required_dict(source, "completeness", "source contract")
    _validate_fields(
        completeness,
        allowed=_COMPLETENESS_FIELDS,
        required=_COMPLETENESS_FIELDS,
        context="source completeness",
    )
    for key in _COMPLETENESS_FIELDS:
        if not isinstance(completeness.get(key), bool):
            raise InvalidLocalJsonSnapshotContract(
                f"source completeness {key} must be boolean"
            )

    cash = data.get("cash")
    if cash is None:
        if completeness["cash"]:
            raise InvalidLocalJsonSnapshotContract("complete cash scope is missing")
    elif not isinstance(cash, dict):
        raise InvalidLocalJsonSnapshotContract("cash must be an object or null")
    else:
        _validate_fields(
            cash,
            allowed=_CASH_FIELDS,
            required=_CASH_REQUIRED_FIELDS,
            context="cash",
        )
        if not _CURRENCY_PATTERN.fullmatch(_required_string(cash, "currency", "cash")):
            raise InvalidLocalJsonSnapshotContract("cash currency invalid")
        _validated_decimal(cash.get("balance"), "cash balance")
        if cash.get("available") is not None:
            _validated_decimal(cash.get("available"), "cash available")

    positions = _required_dict_list(data, "positions", "snapshot")
    orders = _required_dict_list(data, "orders", "snapshot")
    fills = _required_dict_list(data, "fills", "snapshot")
    _validate_positions(positions)
    _validate_orders(orders)
    _validate_fills(fills)
    _optional_string_list(data.get("limitations"), "snapshot limitations")


def _source_contract(data: dict[str, Any]) -> BrokerConnectorSourceContract:
    source = _required_dict(data, "source_contract", "snapshot")
    cursor = _required_dict(source, "cursor", "source contract")
    completeness = _required_dict(source, "completeness", "source contract")
    return BrokerConnectorSourceContract(
        schema_version=str(data["schema_version"]),
        connector_id=str(data["connector_id"]),
        deployment_identity=str(source["deployment_identity"]),
        batch_id=str(source["batch_id"]),
        cursor_previous=int(cursor["previous"]),
        cursor_current=int(cursor["current"]),
        trading_day=str(source["trading_day"]),
        session_phase=str(source["session_phase"]),
        heartbeat_at=str(source["heartbeat_at"]),
        cash_complete=bool(completeness["cash"]),
        positions_complete=bool(completeness["positions"]),
        orders_complete=bool(completeness["orders"]),
        fills_complete=bool(completeness["fills"]),
    )


def _validate_fields(
    data: dict[str, Any],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    context: str,
) -> None:
    unknown = sorted(set(data) - allowed)
    missing = sorted(required - set(data))
    if unknown:
        raise InvalidLocalJsonSnapshotContract(f"{context} contains unsupported fields")
    if missing:
        raise InvalidLocalJsonSnapshotContract(f"{context} is missing fields")


def _required_dict(
    data: dict[str, Any],
    key: str,
    context: str,
) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise InvalidLocalJsonSnapshotContract(f"{context} {key} must be an object")
    return value


def _required_dict_list(
    data: dict[str, Any],
    key: str,
    context: str,
) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise InvalidLocalJsonSnapshotContract(
            f"{context} {key} must be an array of objects"
        )
    return value


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InvalidLocalJsonSnapshotContract(f"{context} {key} is invalid")
    return value.strip()


def _required_nonnegative_int(
    data: dict[str, Any],
    key: str,
    context: str,
) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidLocalJsonSnapshotContract(f"{context} {key} is invalid")
    return value


def _required_aware_timestamp(
    data: dict[str, Any],
    key: str,
    context: str,
) -> datetime:
    value = _required_string(data, key, context)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidLocalJsonSnapshotContract(f"{context} {key} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidLocalJsonSnapshotContract(f"{context} {key} needs timezone")
    return parsed


def _optional_string_list(value: Any, context: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise InvalidLocalJsonSnapshotContract(f"{context} must be strings")


def _validated_decimal(
    value: Any,
    context: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidLocalJsonSnapshotContract(f"{context} is invalid") from exc
    if not parsed.is_finite():
        raise InvalidLocalJsonSnapshotContract(f"{context} is not finite")
    if positive and parsed <= 0:
        raise InvalidLocalJsonSnapshotContract(f"{context} must be positive")
    if nonnegative and parsed < 0:
        raise InvalidLocalJsonSnapshotContract(f"{context} must be nonnegative")
    return parsed


def _validate_positions(items: list[dict[str, Any]]) -> None:
    identities: set[tuple[str, str]] = set()
    for item in items:
        _validate_fields(
            item,
            allowed=_POSITION_FIELDS,
            required=_POSITION_REQUIRED_FIELDS,
            context="position",
        )
        symbol = _required_string(item, "symbol", "position")
        asset_class = _required_string(item, "asset_class", "position")
        _required_string(item, "instrument_name", "position")
        identity = (symbol, asset_class)
        if identity in identities:
            raise InvalidLocalJsonSnapshotContract("duplicate position identity")
        identities.add(identity)
        _validated_decimal(item.get("quantity"), "position quantity")
        for key in ("available_quantity", "cost_basis", "market_price"):
            if item.get(key) is not None:
                _validated_decimal(
                    item.get(key),
                    f"position {key}",
                    nonnegative=key in {"cost_basis", "market_price"},
                )


def _validate_orders(items: list[dict[str, Any]]) -> None:
    order_ids: set[str] = set()
    for item in items:
        _validate_fields(
            item,
            allowed=_ORDER_FIELDS,
            required=_ORDER_REQUIRED_FIELDS,
            context="order",
        )
        order_id = _required_string(item, "order_id", "order")
        if order_id in order_ids:
            raise InvalidLocalJsonSnapshotContract("duplicate order id")
        order_ids.add(order_id)
        _required_string(item, "symbol", "order")
        if _required_string(item, "side", "order").lower() not in _ORDER_SIDES:
            raise InvalidLocalJsonSnapshotContract("order side invalid")
        if _required_string(item, "status", "order").lower() not in _ORDER_STATUSES:
            raise InvalidLocalJsonSnapshotContract("order status invalid")
        _validated_decimal(item.get("quantity"), "order quantity", positive=True)
        if item.get("price") is not None:
            _validated_decimal(item.get("price"), "order price", positive=True)
        _required_aware_timestamp(item, "submitted_at", "order")


def _validate_fills(items: list[dict[str, Any]]) -> None:
    fill_ids: set[str] = set()
    for item in items:
        _validate_fields(
            item,
            allowed=_FILL_FIELDS,
            required=_FILL_REQUIRED_FIELDS,
            context="fill",
        )
        fill_id = _required_string(item, "fill_id", "fill")
        if fill_id in fill_ids:
            raise InvalidLocalJsonSnapshotContract("duplicate fill id")
        fill_ids.add(fill_id)
        _required_string(item, "order_id", "fill")
        _required_string(item, "symbol", "fill")
        if _required_string(item, "side", "fill").lower() not in _ORDER_SIDES:
            raise InvalidLocalJsonSnapshotContract("fill side invalid")
        _validated_decimal(item.get("quantity"), "fill quantity", positive=True)
        _validated_decimal(item.get("price"), "fill price", positive=True)
        _validated_decimal(item.get("fee"), "fill fee", nonnegative=True)
        _validated_decimal(item.get("tax"), "fill tax", nonnegative=True)
        _validated_decimal(item.get("net_amount"), "fill net amount")
        _required_aware_timestamp(item, "filled_at", "fill")


def _invalid_local_json_snapshot(
    *,
    connector_id: str,
    account_alias: str,
    reason_code: str,
) -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id=connector_id,
        source_name="local readonly export",
        account_id="",
        account_alias=account_alias,
        captured_at="",
        health=BrokerConnectorHealth(
            status="incomplete",
            checked_at="",
            message=(
                "Local JSON snapshot export is invalid; review the ignored local export file."
            ),
            limitations=[
                f"parse_error:{reason_code}",
                "No broker client was contacted and no broker order was submitted.",
            ],
        ),
        limitations=[
            "Local JSON snapshot export could not be parsed; no broker client is contacted.",
            "Broker order submission remains disabled.",
        ],
    )


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
