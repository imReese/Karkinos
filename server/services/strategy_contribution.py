"""Evidence-bound strategy contribution from posted ledger facts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from server.models import (
    AccountStrategyAssignment,
    AccountStrategyContributionReport,
)
from server.services.valuation_snapshot import (
    build_current_valuation_snapshot,
    valuation_snapshot_from_row,
)

STRATEGY_CONTRIBUTION_SCHEMA_VERSION = "karkinos.account_strategy_contribution.v2"
STRATEGY_CONTRIBUTION_READY_STATUS = "evidence_bound_from_posted_fills"

_VALUATION_PUBLICATION_KEY = "valuation_snapshot_publication"
_QUOTE_READY_STATUSES = {
    "available",
    "complete",
    "confirmed",
    "fresh",
    "healthy",
    "live",
    "ok",
    "passed",
}
_QUANTITY_TOLERANCE = Decimal("0.00000001")
_MONEY_TOLERANCE = Decimal("0.000001")


def build_strategy_contribution_report(
    *,
    db: Any,
    assignment: AccountStrategyAssignment,
    evidence: dict[str, Any],
) -> AccountStrategyContributionReport:
    """Project contribution only from posted fills and one persisted snapshot."""

    linked_fills = sorted(
        (dict(row) for row in evidence.get("linked_fills") or []),
        key=_fill_sort_key,
    )
    unattributed_fill_count = int(evidence.get("unattributed_fill_count") or 0)
    base = {
        "schema_version": STRATEGY_CONTRIBUTION_SCHEMA_VERSION,
        "strategy_id": assignment.strategy_id,
        "linked_fill_count": len(linked_fills),
        "unattributed_fill_count": unattributed_fill_count,
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "limitations": [
            "Only strategy-linked fills posted to the production ledger are eligible for contribution.",
            "Open inventory is marked only with the exact persisted valuation snapshot named by this report.",
            "Actual fill price already contains execution slippage; slippage is disclosed but is not subtracted a second time.",
            "Manual trades, cash flows, simulation fills, and unattributed movements are excluded rather than estimated into strategy P/L.",
        ],
    }
    if not linked_fills:
        blockers = (
            ["unattributed_strategy_fills_require_lineage_review"]
            if unattributed_fill_count > 0
            else []
        )
        return _blocked_or_empty_report(
            assignment=assignment,
            base=base,
            contribution_status="no_linked_fills",
            evidence_binding_status=("blocked" if blockers else "not_applicable"),
            next_manual_action=(
                "review_unattributed_strategy_fill_lineage"
                if blockers
                else "no_action_until_strategy_linked_fill_exists"
            ),
            blockers=blockers,
            linked_fill_ids=[],
        )

    ledger_rows = _load_ledger_rows(db)
    ledger_by_fill = _ledger_rows_by_fill_id(ledger_rows)
    posted_entries: list[dict[str, Any]] = []
    ledger_blockers: list[str] = []
    unposted_fill_ids: list[str] = []
    for fill in linked_fills:
        fill_id = str(fill.get("fill_id") or "")
        candidates = ledger_by_fill.get(fill_id, [])
        if not fill_id or not candidates:
            unposted_fill_ids.append(fill_id or "missing-fill-id")
            continue
        if len(candidates) != 1:
            ledger_blockers.append(
                f"strategy_contribution_ledger_entry_ambiguous:{fill_id}"
            )
            continue
        entry = candidates[0]
        entry_blockers = _ledger_fill_binding_blockers(entry=entry, fill=fill)
        if entry_blockers:
            ledger_blockers.extend(entry_blockers)
            continue
        posted_entries.append(entry)

    if ledger_blockers:
        return _blocked_or_empty_report(
            assignment=assignment,
            base=base,
            contribution_status="ledger_evidence_drift",
            evidence_binding_status="blocked",
            next_manual_action="review_strategy_fill_and_ledger_identity",
            blockers=ledger_blockers,
            linked_fill_ids=[str(fill.get("fill_id") or "") for fill in linked_fills],
            ledger_posted_fill_count=len(posted_entries),
            unposted_linked_fill_count=len(unposted_fill_ids),
        )
    if unposted_fill_ids:
        return _blocked_or_empty_report(
            assignment=assignment,
            base=base,
            contribution_status="ledger_posting_pending",
            evidence_binding_status="blocked",
            next_manual_action=(
                "complete_execution_reconciliation_and_explicit_ledger_posting"
            ),
            blockers=[
                f"strategy_contribution_fill_not_posted:{fill_id}"
                for fill_id in unposted_fill_ids
            ],
            linked_fill_ids=[str(fill.get("fill_id") or "") for fill in linked_fills],
            ledger_posted_fill_count=len(posted_entries),
            unposted_linked_fill_count=len(unposted_fill_ids),
        )

    valuation, valuation_blockers = _load_exact_valuation_binding(db)
    if valuation_blockers:
        status = _valuation_failure_status(valuation_blockers)
        return _blocked_or_empty_report(
            assignment=assignment,
            base=base,
            contribution_status=status,
            evidence_binding_status="blocked",
            next_manual_action=_valuation_next_action(status),
            blockers=valuation_blockers,
            linked_fill_ids=[str(fill.get("fill_id") or "") for fill in linked_fills],
            ledger_posted_fill_count=len(posted_entries),
            valuation=valuation,
        )

    ledger_cutoff_id = int(valuation.get("ledger_cutoff_id") or 0)
    post_cutoff_entries = [
        entry
        for entry in posted_entries
        if int(entry.get("id") or 0) > ledger_cutoff_id
    ]
    if post_cutoff_entries:
        return _blocked_or_empty_report(
            assignment=assignment,
            base=base,
            contribution_status="valuation_identity_drift",
            evidence_binding_status="blocked",
            next_manual_action="publish_or_repair_persisted_valuation_snapshot",
            blockers=["strategy_contribution_ledger_entry_after_snapshot_cutoff"],
            linked_fill_ids=[str(fill.get("fill_id") or "") for fill in linked_fills],
            ledger_posted_fill_count=len(posted_entries),
            valuation=valuation,
        )

    components = _contribution_components(
        entries=posted_entries,
        fills=linked_fills,
        valuation=valuation,
    )
    component_blockers = list(components.pop("blockers"))
    if component_blockers:
        status = (
            "inventory_lineage_incomplete"
            if any("inventory" in item for item in component_blockers)
            else "valuation_missing"
        )
        return _blocked_or_empty_report(
            assignment=assignment,
            base=base,
            contribution_status=status,
            evidence_binding_status="blocked",
            next_manual_action=(
                "review_strategy_inventory_lineage"
                if status == "inventory_lineage_incomplete"
                else "sync_confirmed_market_or_nav_evidence"
            ),
            blockers=component_blockers,
            linked_fill_ids=[str(fill.get("fill_id") or "") for fill in linked_fills],
            ledger_posted_fill_count=len(posted_entries),
            valuation=valuation,
            missing_valuation_symbols=list(
                components.get("missing_valuation_symbols") or []
            ),
        )

    evidence_refs = [
        *(f"fill:{fill['fill_id']}" for fill in linked_fills),
        *(f"ledger_entry:{entry['id']}" for entry in posted_entries),
        f"valuation_snapshot:{valuation['snapshot_id']}",
        f"ledger_cutoff:{ledger_cutoff_id}",
    ]
    fingerprint_payload = {
        "schema_version": STRATEGY_CONTRIBUTION_SCHEMA_VERSION,
        "strategy_id": assignment.strategy_id,
        "evidence_refs": evidence_refs,
        "valuation_snapshot_id": valuation["snapshot_id"],
        "ledger_cutoff_id": ledger_cutoff_id,
        "ledger_fingerprint": valuation["ledger_fingerprint"],
        "quote_set_fingerprint": valuation["quote_set_fingerprint"],
        "components": {
            key: components[key]
            for key in (
                "gross_realized_pnl",
                "gross_unrealized_pnl",
                "total_commission",
                "total_slippage",
                "total_tax",
                "net_contribution",
            )
        },
    }
    health_status, health_reasons = _strategy_health(
        assignment=assignment,
        contribution_status=STRATEGY_CONTRIBUTION_READY_STATUS,
        unattributed_fill_count=unattributed_fill_count,
    )
    return AccountStrategyContributionReport(
        **base,
        contribution_status=STRATEGY_CONTRIBUTION_READY_STATUS,
        evidence_binding_status="bound",
        next_manual_action="review_evidence_bound_strategy_contribution",
        blockers=[],
        strategy_health_status=health_status,
        strategy_health_reasons=health_reasons,
        ledger_posted_fill_count=len(posted_entries),
        unposted_linked_fill_count=0,
        gross_realized_pnl=_as_float(components["gross_realized_pnl"]),
        gross_unrealized_pnl=_as_float(components["gross_unrealized_pnl"]),
        total_commission=_as_float(components["total_commission"]),
        total_slippage=_as_float(components["total_slippage"]),
        total_tax=_as_float(components["total_tax"]),
        net_contribution=_as_float(components["net_contribution"]),
        unattributed_account_pnl=None,
        manual_unattributed_pnl=None,
        cash_flow_pnl=None,
        missing_valuation_symbols=[],
        valuation_snapshot_id=str(valuation["snapshot_id"]),
        valuation_as_of=str(valuation["as_of"]),
        valuation_status=str(valuation["status"]),
        valuation_scope_status="complete",
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=str(valuation["ledger_fingerprint"]),
        quote_set_fingerprint=str(valuation["quote_set_fingerprint"]),
        contribution_fingerprint=_fingerprint(fingerprint_payload),
        evidence_refs=evidence_refs,
    )


def _blocked_or_empty_report(
    *,
    assignment: AccountStrategyAssignment,
    base: dict[str, Any],
    contribution_status: str,
    evidence_binding_status: str,
    next_manual_action: str,
    blockers: list[str],
    linked_fill_ids: list[str],
    ledger_posted_fill_count: int = 0,
    unposted_linked_fill_count: int = 0,
    valuation: dict[str, Any] | None = None,
    missing_valuation_symbols: list[str] | None = None,
) -> AccountStrategyContributionReport:
    valuation = valuation or {}
    health_status, health_reasons = _strategy_health(
        assignment=assignment,
        contribution_status=contribution_status,
        unattributed_fill_count=int(base.get("unattributed_fill_count") or 0),
    )
    return AccountStrategyContributionReport(
        **base,
        contribution_status=contribution_status,
        evidence_binding_status=evidence_binding_status,
        next_manual_action=next_manual_action,
        blockers=list(dict.fromkeys(blockers)),
        strategy_health_status=health_status,
        strategy_health_reasons=health_reasons,
        ledger_posted_fill_count=ledger_posted_fill_count,
        unposted_linked_fill_count=unposted_linked_fill_count,
        gross_realized_pnl=None,
        gross_unrealized_pnl=None,
        total_commission=None,
        total_slippage=None,
        total_tax=None,
        net_contribution=None,
        unattributed_account_pnl=None,
        manual_unattributed_pnl=None,
        cash_flow_pnl=None,
        missing_valuation_symbols=missing_valuation_symbols or [],
        valuation_snapshot_id=(
            str(valuation.get("snapshot_id")) if valuation.get("snapshot_id") else None
        ),
        valuation_as_of=(
            str(valuation.get("as_of")) if valuation.get("as_of") else None
        ),
        valuation_status=str(valuation.get("status") or "unavailable"),
        valuation_scope_status="blocked",
        ledger_cutoff_id=int(valuation.get("ledger_cutoff_id") or 0),
        ledger_fingerprint=(
            str(valuation.get("ledger_fingerprint"))
            if valuation.get("ledger_fingerprint")
            else None
        ),
        quote_set_fingerprint=(
            str(valuation.get("quote_set_fingerprint"))
            if valuation.get("quote_set_fingerprint")
            else None
        ),
        contribution_fingerprint=None,
        evidence_refs=[
            *(f"fill:{fill_id}" for fill_id in linked_fill_ids),
            *(
                [f"valuation_snapshot:{valuation['snapshot_id']}"]
                if valuation.get("snapshot_id")
                else []
            ),
        ],
    )


def _load_exact_valuation_binding(db: Any) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    reader = getattr(db, "get_runtime_control_sync", None)
    publication = reader(_VALUATION_PUBLICATION_KEY) if callable(reader) else None
    if not isinstance(publication, dict) or publication.get("status") != "ready":
        return {}, ["strategy_contribution_valuation_publication_missing"]
    snapshot_id = str(publication.get("snapshot_id") or "")
    snapshot_reader = getattr(db, "get_valuation_snapshot_sync", None)
    if not snapshot_id or not callable(snapshot_reader):
        return {}, ["strategy_contribution_valuation_snapshot_missing"]
    row = snapshot_reader(snapshot_id)
    if not isinstance(row, dict):
        return {}, ["strategy_contribution_valuation_snapshot_missing"]
    try:
        valuation = valuation_snapshot_from_row(row)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}, ["strategy_contribution_valuation_snapshot_invalid"]
    if str(valuation.get("snapshot_id") or "") != snapshot_id:
        blockers.append("strategy_contribution_valuation_snapshot_identity_mismatch")
    try:
        current = build_current_valuation_snapshot(db, persist=False)
    except Exception:
        blockers.append("strategy_contribution_current_valuation_replay_failed")
    else:
        for field in (
            "snapshot_id",
            "ledger_cutoff_id",
            "ledger_fingerprint",
            "quote_set_fingerprint",
        ):
            if str(current.get(field) or "") != str(valuation.get(field) or ""):
                blockers.append(f"strategy_contribution_{field}_drift")
    return valuation, list(dict.fromkeys(blockers))


def _load_ledger_rows(db: Any, *, batch_size: int = 500) -> list[dict[str, Any]]:
    reader = getattr(db, "get_ledger_entries_sync", None)
    if not callable(reader):
        return []
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = [dict(row) for row in (reader(limit=batch_size, offset=offset) or [])]
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return rows


def _ledger_rows_by_fill_id(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source_ref = str(row.get("source_ref") or "")
        if not source_ref or not str(row.get("entry_type") or "").startswith("trade_"):
            continue
        grouped.setdefault(source_ref, []).append(row)
    return grouped


def _ledger_fill_binding_blockers(
    *,
    entry: dict[str, Any],
    fill: dict[str, Any],
) -> list[str]:
    fill_id = str(fill.get("fill_id") or "")
    blockers: list[str] = []
    expectations = {
        "symbol": str(fill.get("symbol") or ""),
        "direction": str(fill.get("side") or "").lower(),
        "asset_class": str(fill.get("asset_class") or "stock"),
    }
    for field, expected in expectations.items():
        actual = str(entry.get(field) or ("stock" if field == "asset_class" else ""))
        if actual.lower() != expected.lower():
            blockers.append(f"strategy_contribution_{field}_mismatch:{fill_id}")
    numeric_expectations = {
        "quantity": _decimal(fill.get("fill_quantity")),
        "price": _decimal(fill.get("fill_price")),
        "commission": _decimal(fill.get("commission")),
    }
    for field, expected in numeric_expectations.items():
        tolerance = _QUANTITY_TOLERANCE if field == "quantity" else _MONEY_TOLERANCE
        if abs(_decimal(entry.get(field)) - expected) > tolerance:
            blockers.append(f"strategy_contribution_{field}_mismatch:{fill_id}")
    return blockers


def _contribution_components(
    *,
    entries: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    valuation: dict[str, Any],
) -> dict[str, Any]:
    positions: dict[tuple[str, str], dict[str, Decimal]] = {}
    realized = Decimal("0")
    total_commission = Decimal("0")
    total_tax = Decimal("0")
    blockers: list[str] = []
    fill_by_id = {str(fill.get("fill_id") or ""): fill for fill in fills}
    total_slippage = sum(
        (_decimal(fill.get("slippage")) for fill in fills),
        Decimal("0"),
    )
    for entry in sorted(entries, key=_ledger_sort_key):
        source_ref = str(entry.get("source_ref") or "")
        fill = fill_by_id.get(source_ref, {})
        symbol = str(entry.get("symbol") or "")
        asset_class = str(entry.get("asset_class") or "stock")
        direction = str(entry.get("direction") or "").lower()
        quantity = abs(_decimal(entry.get("quantity")))
        price = abs(_decimal(entry.get("price")))
        fees, taxes = _ledger_fee_components(entry)
        total_commission += fees
        total_tax += taxes
        position = positions.setdefault(
            (symbol, asset_class),
            {"quantity": Decimal("0"), "cost": Decimal("0")},
        )
        if direction == "buy":
            position["quantity"] += quantity
            position["cost"] += quantity * price
            continue
        if direction != "sell" or quantity <= 0:
            blockers.append(
                f"strategy_contribution_trade_direction_invalid:{source_ref}"
            )
            continue
        if quantity - position["quantity"] > _QUANTITY_TOLERANCE:
            blockers.append(
                f"strategy_contribution_inventory_origin_incomplete:{source_ref}"
            )
            continue
        average_cost = (
            position["cost"] / position["quantity"]
            if position["quantity"] > 0
            else Decimal("0")
        )
        realized += (price - average_cost) * quantity
        position["quantity"] -= quantity
        position["cost"] -= average_cost * quantity
        if abs(position["quantity"]) <= _QUANTITY_TOLERANCE:
            position["quantity"] = Decimal("0")
            position["cost"] = Decimal("0")
        if str(fill.get("side") or "").lower() != "sell":
            blockers.append(f"strategy_contribution_fill_direction_drift:{source_ref}")

    quotes = _valuation_quotes(valuation)
    unrealized = Decimal("0")
    missing_symbols: list[str] = []
    for (symbol, asset_class), position in positions.items():
        quantity = position["quantity"]
        if quantity <= _QUANTITY_TOLERANCE:
            continue
        quote = quotes.get((symbol, asset_class)) or quotes.get((symbol, ""))
        status = str((quote or {}).get("quote_status") or "").strip().lower()
        price = _decimal((quote or {}).get("price"))
        if not quote or status not in _QUOTE_READY_STATUSES or price <= 0:
            missing_symbols.append(symbol)
            blockers.append(f"strategy_contribution_valuation_not_confirmed:{symbol}")
            continue
        average_cost = position["cost"] / quantity
        unrealized += (price - average_cost) * quantity
    net = realized + unrealized - total_commission - total_tax
    return {
        "gross_realized_pnl": _decimal_string(realized),
        "gross_unrealized_pnl": _decimal_string(unrealized),
        "total_commission": _decimal_string(total_commission),
        "total_slippage": _decimal_string(total_slippage),
        "total_tax": _decimal_string(total_tax),
        "net_contribution": _decimal_string(net),
        "missing_valuation_symbols": sorted(set(missing_symbols)),
        "blockers": list(dict.fromkeys(blockers)),
    }


def _valuation_quotes(
    valuation: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    quotes: dict[tuple[str, str], dict[str, Any]] = {}
    symbol_counts: dict[str, int] = {}
    for raw in valuation.get("quotes") or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        symbol = str(row.get("symbol") or "")
        asset_class = str(row.get("asset_type") or row.get("asset_class") or "stock")
        if not symbol:
            continue
        quotes[(symbol, asset_class)] = row
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    for (symbol, _asset_class), row in list(quotes.items()):
        if symbol_counts.get(symbol) == 1:
            quotes[(symbol, "")] = row
    return quotes


def _ledger_fee_components(row: dict[str, Any]) -> tuple[Decimal, Decimal]:
    breakdown = _json_object(row.get("fee_breakdown_json"))
    if breakdown:
        fee_keys = (
            "commission",
            "transfer_fee",
            "other_fees",
            "regulatory_fee",
            "exchange_fee",
            "handling_fee",
        )
        fees = (
            sum(
                (_decimal(breakdown.get(key)) for key in fee_keys),
                Decimal("0"),
            )
            if any(key in breakdown for key in fee_keys)
            else _decimal(row.get("commission"))
        )
        taxes = sum(
            (_decimal(breakdown.get(key)) for key in ("stamp_tax", "tax")),
            Decimal("0"),
        )
        if fees or taxes or any(key in breakdown for key in fee_keys):
            return fees, taxes
    return _decimal(row.get("commission")), Decimal("0")


def _strategy_health(
    *,
    assignment: AccountStrategyAssignment,
    contribution_status: str,
    unattributed_fill_count: int,
) -> tuple[str, list[str]]:
    if str(assignment.status or "").lower() in {
        "disabled",
        "inactive",
        "paused",
        "retired",
    }:
        return "paused", ["assignment_paused"]
    if unattributed_fill_count > 0:
        return "degraded", ["unattributed_strategy_movement"]
    if contribution_status == STRATEGY_CONTRIBUTION_READY_STATUS:
        return "healthy", ["posted_fill_and_valuation_evidence_bound"]
    if contribution_status == "no_linked_fills":
        return "not_applicable", ["no_strategy_linked_fills_yet"]
    if contribution_status.startswith("valuation_"):
        return "stale", [contribution_status]
    return "needs_review", [contribution_status]


def _valuation_failure_status(blockers: list[str]) -> str:
    if any("drift" in item or "mismatch" in item for item in blockers):
        return "valuation_identity_drift"
    if any("invalid" in item for item in blockers):
        return "valuation_snapshot_invalid"
    return "valuation_snapshot_missing"


def _valuation_next_action(status: str) -> str:
    if status == "valuation_identity_drift":
        return "publish_or_repair_persisted_valuation_snapshot"
    if status == "valuation_snapshot_invalid":
        return "repair_persisted_valuation_snapshot"
    return "publish_persisted_valuation_snapshot"


def _fill_sort_key(fill: dict[str, Any]) -> tuple[str, str]:
    return (str(fill.get("timestamp") or ""), str(fill.get("fill_id") or ""))


def _ledger_sort_key(entry: dict[str, Any]) -> tuple[str, int]:
    return (str(entry.get("timestamp") or ""), int(entry.get("id") or 0))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def _decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _as_float(value: Any) -> float:
    return float(_decimal(value))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
