"""Account-truth reconciliation report builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from account_truth.broker_evidence import StoredBrokerEvidenceEvent

RECONCILIATION_SCHEMA_VERSION = "karkinos.account_truth.reconciliation.v1"

ReconciliationStatus = Literal["pass", "warning", "mismatch", "blocked"]


@dataclass(frozen=True)
class KarkinosLedgerFact:
    event_type: str
    symbol: str = ""
    quantity: Decimal = Decimal("0")
    price: Decimal = Decimal("0")
    gross_amount: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    transfer_fee: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class KarkinosPositionFact:
    symbol: str
    quantity: Decimal
    cost_basis: Decimal | None = None


@dataclass(frozen=True)
class ReconciliationItem:
    category: str
    status: ReconciliationStatus
    broker_value: str
    karkinos_value: str
    difference: str
    suggested_review_action: str
    symbol: str = ""
    detail_code: str = ""
    detail: str = ""
    detail_context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationReport:
    schema_version: str
    import_run_id: str
    status: ReconciliationStatus
    cash_difference: Decimal
    fee_difference: Decimal
    tax_difference: Decimal
    unresolved_count: int
    suggested_review_actions: list[str]
    items: list[ReconciliationItem]


def build_reconciliation_report(
    *,
    import_run_id: str,
    broker_events: list[StoredBrokerEvidenceEvent],
    ledger_facts: list[KarkinosLedgerFact],
    cash_balance: Decimal | None,
    positions: list[KarkinosPositionFact],
) -> ReconciliationReport:
    """Compare staged broker evidence with Karkinos account facts."""

    if not broker_events:
        item = ReconciliationItem(
            category="import",
            status="blocked",
            broker_value="0",
            karkinos_value="0",
            difference="0",
            suggested_review_action="import_broker_evidence",
            detail_code="account_truth.no_broker_evidence",
            detail="No broker evidence events are available for reconciliation.",
        )
        return ReconciliationReport(
            schema_version=RECONCILIATION_SCHEMA_VERSION,
            import_run_id=import_run_id,
            status="blocked",
            cash_difference=Decimal("0.00"),
            fee_difference=Decimal("0.00"),
            tax_difference=Decimal("0.00"),
            unresolved_count=1,
            suggested_review_actions=[item.suggested_review_action],
            items=[item],
        )

    broker_cash = _latest_decimal(
        event.cash_balance for event in broker_events if event.cash_balance is not None
    )
    broker_fee = sum(_decimal(event.fee) for event in broker_events)
    broker_tax = sum(_decimal(event.tax) for event in broker_events)
    ledger_fee = sum(fact.fee for fact in ledger_facts)
    ledger_tax = sum(fact.tax for fact in ledger_facts)
    has_cash_snapshot = any(
        event.event_type == "cash_snapshot" for event in broker_events
    )
    has_position_snapshot = any(
        event.event_type == "position_snapshot" for event in broker_events
    )
    cash_difference = (
        Decimal("0.00")
        if not has_cash_snapshot
        else _difference(broker_cash, cash_balance)
    )
    fee_difference = broker_fee - ledger_fee
    tax_difference = broker_tax - ledger_tax

    items = [
        (
            _warning_item(
                category="cash",
                broker_value=None,
                karkinos_value=cash_balance,
                suggested_review_action="provide_cash_snapshot",
                detail_code="account_truth.cash_snapshot_missing",
                detail="Broker cash snapshot is missing; cash reconciliation is incomplete.",
            )
            if not has_cash_snapshot
            else _item(
                category="cash",
                broker_value=broker_cash,
                karkinos_value=cash_balance,
                difference=cash_difference,
                suggested_review_action="review_cash_difference",
                detail_code="account_truth.cash_compared",
                detail="Broker cash snapshot compared with Karkinos cash balance.",
            )
        )
    ]
    if has_position_snapshot:
        items.extend(_position_items(broker_events, positions))
    else:
        items.append(
            _warning_item(
                category="position",
                broker_value=None,
                karkinos_value=None,
                suggested_review_action="provide_position_snapshot",
                detail_code="account_truth.position_snapshot_missing",
                detail=(
                    "Broker position snapshot is missing; position reconciliation "
                    "is incomplete."
                ),
            )
        )
    items.extend(_trade_component_items(broker_events, ledger_facts))
    items.extend(
        [
            _item(
                category="fee",
                broker_value=broker_fee,
                karkinos_value=ledger_fee,
                difference=fee_difference,
                suggested_review_action="review_fee_difference",
                detail_code="account_truth.fees_compared",
                detail="Broker fees compared with Karkinos ledger fees.",
            ),
            _item(
                category="tax",
                broker_value=broker_tax,
                karkinos_value=ledger_tax,
                difference=tax_difference,
                suggested_review_action="review_tax_difference",
                detail_code="account_truth.taxes_compared",
                detail="Broker taxes compared with Karkinos ledger taxes.",
            ),
        ]
    )
    if has_position_snapshot:
        items.extend(_cost_basis_items(broker_events, positions))

    unresolved_items = [item for item in items if item.status != "pass"]
    mismatches = [item for item in unresolved_items if item.status == "mismatch"]
    warnings = [item for item in unresolved_items if item.status == "warning"]
    return ReconciliationReport(
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        import_run_id=import_run_id,
        status=_report_status(mismatches=mismatches, warnings=warnings),
        cash_difference=cash_difference,
        fee_difference=fee_difference,
        tax_difference=tax_difference,
        unresolved_count=len(unresolved_items),
        suggested_review_actions=_unique_actions(unresolved_items),
        items=items,
    )


def _position_items(
    broker_events: list[StoredBrokerEvidenceEvent],
    positions: list[KarkinosPositionFact],
) -> list[ReconciliationItem]:
    broker_positions = {
        event.symbol: _decimal(event.position_quantity)
        for event in broker_events
        if event.event_type == "position_snapshot" and event.symbol
    }
    karkinos_positions = {position.symbol: position.quantity for position in positions}
    symbols = sorted(set(broker_positions) | set(karkinos_positions))
    return [
        _item(
            category="position",
            broker_value=broker_positions.get(symbol),
            karkinos_value=karkinos_positions.get(symbol),
            difference=_difference(
                broker_positions.get(symbol), karkinos_positions.get(symbol)
            ),
            suggested_review_action="review_position_difference",
            symbol=symbol,
            detail_code="account_truth.position_quantity_compared",
            detail="Broker position quantity compared with Karkinos position quantity.",
        )
        for symbol in symbols
    ]


def _trade_component_items(
    broker_events: list[StoredBrokerEvidenceEvent],
    ledger_facts: list[KarkinosLedgerFact],
) -> list[ReconciliationItem]:
    broker_components = _broker_trade_components_by_symbol(broker_events)
    ledger_components = _ledger_trade_components_by_symbol(ledger_facts)
    symbols = sorted(set(broker_components) | set(ledger_components))
    items: list[ReconciliationItem] = []
    for symbol in symbols:
        broker_values = broker_components.get(symbol, _empty_trade_components())
        ledger_values = ledger_components.get(symbol, _empty_trade_components())
        items.extend(
            [
                _item(
                    category="trade_gross_amount",
                    broker_value=broker_values["gross_amount"],
                    karkinos_value=ledger_values["gross_amount"],
                    difference=_difference(
                        broker_values["gross_amount"],
                        ledger_values["gross_amount"],
                    ),
                    suggested_review_action="review_trade_gross_amount_difference",
                    symbol=symbol,
                    detail_code="account_truth.trade_gross_amount_compared",
                    detail=(
                        "Broker trade gross amount compared with Karkinos "
                        "trade gross amount before fees and taxes."
                    ),
                ),
                _item(
                    category="net_cash_impact",
                    broker_value=broker_values["net_amount"],
                    karkinos_value=ledger_values["net_amount"],
                    difference=_difference(
                        broker_values["net_amount"],
                        ledger_values["net_amount"],
                    ),
                    suggested_review_action="review_net_cash_impact_difference",
                    symbol=symbol,
                    detail_code="account_truth.net_cash_impact_compared",
                    detail=(
                        "Broker signed net cash impact compared with Karkinos "
                        "signed ledger cash impact after fees and taxes."
                    ),
                ),
                _item(
                    category="fee",
                    broker_value=broker_values["fee"],
                    karkinos_value=ledger_values["fee"],
                    difference=_difference(
                        broker_values["fee"],
                        ledger_values["fee"],
                    ),
                    suggested_review_action="review_fee_difference",
                    symbol=symbol,
                    detail_code="account_truth.trade_commission_compared",
                    detail=(
                        "Broker trade commission compared with Karkinos trade "
                        "commission."
                    ),
                ),
                _item(
                    category="tax",
                    broker_value=broker_values["tax"],
                    karkinos_value=ledger_values["tax"],
                    difference=_difference(
                        broker_values["tax"],
                        ledger_values["tax"],
                    ),
                    suggested_review_action="review_tax_difference",
                    symbol=symbol,
                    detail_code="account_truth.trade_tax_compared",
                    detail="Broker trade tax compared with Karkinos trade tax.",
                ),
                _item(
                    category="transfer_fee",
                    broker_value=broker_values["transfer_fee"],
                    karkinos_value=ledger_values["transfer_fee"],
                    difference=_difference(
                        broker_values["transfer_fee"],
                        ledger_values["transfer_fee"],
                    ),
                    suggested_review_action="review_transfer_fee_difference",
                    symbol=symbol,
                    detail_code="account_truth.transfer_fee_compared",
                    detail=(
                        "Broker transfer fee component compared with Karkinos "
                        "transfer fee component."
                    ),
                ),
            ]
        )
    return items


def _broker_trade_components_by_symbol(
    broker_events: list[StoredBrokerEvidenceEvent],
) -> dict[str, dict[str, Decimal]]:
    components: dict[str, dict[str, Decimal]] = {}
    for event in broker_events:
        if event.event_type not in {"trade_buy", "trade_sell"} or not event.symbol:
            continue
        symbol_components = components.setdefault(
            event.symbol,
            _empty_trade_components(),
        )
        symbol_components["gross_amount"] += _decimal(event.gross_amount)
        symbol_components["net_amount"] += _decimal(event.net_amount)
        symbol_components["fee"] += _decimal(event.fee)
        symbol_components["tax"] += _decimal(event.tax)
        symbol_components["transfer_fee"] += _decimal(
            getattr(event, "transfer_fee", "0")
        )
    return components


def _ledger_trade_components_by_symbol(
    ledger_facts: list[KarkinosLedgerFact],
) -> dict[str, dict[str, Decimal]]:
    components: dict[str, dict[str, Decimal]] = {}
    for fact in ledger_facts:
        if fact.event_type not in {"trade_buy", "trade_sell"} or not fact.symbol:
            continue
        symbol_components = components.setdefault(
            fact.symbol,
            _empty_trade_components(),
        )
        gross_amount = (
            fact.gross_amount
            if fact.gross_amount != Decimal("0")
            else fact.quantity * fact.price
        )
        symbol_components["gross_amount"] += gross_amount
        symbol_components["net_amount"] += fact.net_amount
        symbol_components["fee"] += fact.fee
        symbol_components["tax"] += fact.tax
        symbol_components["transfer_fee"] += fact.transfer_fee
    return components


def _empty_trade_components() -> dict[str, Decimal]:
    return {
        "gross_amount": Decimal("0"),
        "net_amount": Decimal("0"),
        "fee": Decimal("0"),
        "tax": Decimal("0"),
        "transfer_fee": Decimal("0"),
    }


def _cost_basis_items(
    broker_events: list[StoredBrokerEvidenceEvent],
    positions: list[KarkinosPositionFact],
) -> list[ReconciliationItem]:
    broker_cost_basis = {
        event.symbol: _optional_decimal(event.cost_basis)
        for event in broker_events
        if event.event_type == "position_snapshot" and event.symbol
    }
    broker_cost_basis_methods = {
        event.symbol: getattr(event, "cost_basis_method", "")
        for event in broker_events
        if event.event_type == "position_snapshot" and event.symbol
    }
    karkinos_cost_basis = {
        position.symbol: position.cost_basis
        for position in positions
        if position.cost_basis is not None
    }
    symbols = sorted(set(broker_cost_basis) | set(karkinos_cost_basis))
    return [
        _item(
            category="cost_basis",
            broker_value=broker_cost_basis.get(symbol),
            karkinos_value=karkinos_cost_basis.get(symbol),
            difference=_difference(
                broker_cost_basis.get(symbol), karkinos_cost_basis.get(symbol)
            ),
            suggested_review_action="review_cost_basis_difference",
            symbol=symbol,
            detail_code="account_truth.cost_basis_compared",
            detail=_cost_basis_detail(broker_cost_basis_methods.get(symbol, "")),
            detail_context=_cost_basis_context(
                broker_cost_basis_methods.get(symbol, "")
            ),
        )
        for symbol in symbols
    ]


def _cost_basis_detail(cost_basis_method: str) -> str:
    detail = "Broker cost basis compared with Karkinos cost basis."
    if cost_basis_method:
        detail += f" Broker cost-basis method: {cost_basis_method}."
    return detail


def _cost_basis_context(cost_basis_method: str) -> dict[str, str]:
    if not cost_basis_method:
        return {}
    return {"cost_basis_method": cost_basis_method}


def _item(
    *,
    category: str,
    broker_value: Decimal | None,
    karkinos_value: Decimal | None,
    difference: Decimal,
    suggested_review_action: str,
    symbol: str = "",
    detail_code: str = "",
    detail: str = "",
    detail_context: dict[str, str] | None = None,
) -> ReconciliationItem:
    status: ReconciliationStatus = "pass" if difference == Decimal("0") else "mismatch"
    return ReconciliationItem(
        category=category,
        status=status,
        broker_value=_decimal_to_text(broker_value),
        karkinos_value=_decimal_to_text(karkinos_value),
        difference=_decimal_to_text(difference),
        suggested_review_action="" if status == "pass" else suggested_review_action,
        symbol=symbol,
        detail_code=detail_code,
        detail=detail,
        detail_context=detail_context or {},
    )


def _warning_item(
    *,
    category: str,
    broker_value: Decimal | None,
    karkinos_value: Decimal | None,
    suggested_review_action: str,
    symbol: str = "",
    detail_code: str = "",
    detail: str = "",
    detail_context: dict[str, str] | None = None,
) -> ReconciliationItem:
    return ReconciliationItem(
        category=category,
        status="warning",
        broker_value=_decimal_to_text(broker_value),
        karkinos_value=_decimal_to_text(karkinos_value),
        difference="0",
        suggested_review_action=suggested_review_action,
        symbol=symbol,
        detail_code=detail_code,
        detail=detail,
        detail_context=detail_context or {},
    )


def _report_status(
    *,
    mismatches: list[ReconciliationItem],
    warnings: list[ReconciliationItem],
) -> ReconciliationStatus:
    if mismatches:
        return "mismatch"
    if warnings:
        return "warning"
    return "pass"


def _difference(
    broker_value: Decimal | None,
    karkinos_value: Decimal | None,
) -> Decimal:
    return (broker_value or Decimal("0")) - (karkinos_value or Decimal("0"))


def _decimal(value: str | Decimal | None) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _optional_decimal(value: str | Decimal | None) -> Decimal | None:
    if value is None or value == "":
        return None
    return _decimal(value)


def _latest_decimal(values: object) -> Decimal | None:
    latest: Decimal | None = None
    for value in values:
        latest = _decimal(value)
    return latest


def _decimal_to_text(value: Decimal | None) -> str:
    if value is None:
        return "0"
    return format(value, "f")


def _unique_actions(items: list[ReconciliationItem]) -> list[str]:
    actions: list[str] = []
    for item in items:
        if item.suggested_review_action and item.suggested_review_action not in actions:
            actions.append(item.suggested_review_action)
    return actions
