"""Asset identity and broker cost-basis evidence for portfolio quotes."""

from __future__ import annotations

import logging

from core.types import AssetClass, Symbol
from server.projections.portfolio_assets import normalize_asset_class

logger = logging.getLogger(__name__)


def normalize_asset_class_value(value) -> str:
    if hasattr(value, "value"):
        return normalize_asset_class(getattr(value, "value", None))
    return normalize_asset_class(str(value) if value is not None else None)


def optional_float_attr(obj, name: str) -> float | None:
    return optional_float_value(getattr(obj, name, None))


def optional_float_value(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def broker_cost_basis_evidence_by_symbol(
    state,
    symbols: set[str],
) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        return {}

    try:
        from account_truth.broker_evidence import BrokerEvidenceRepository

        repository = BrokerEvidenceRepository(db_path)
        evidence_by_symbol: dict[str, dict[str, object]] = {}
        for import_run in repository.list_import_runs(limit=50):
            for event in reversed(repository.list_events(import_run.import_run_id)):
                symbol = str(event.symbol)
                if (
                    symbol not in symbols
                    or symbol in evidence_by_symbol
                    or event.event_type != "position_snapshot"
                    or event.is_row_duplicate
                ):
                    continue
                unit_cost = optional_float_value(event.cost_basis)
                if unit_cost is None:
                    continue
                evidence_by_symbol[symbol] = {
                    "unit_cost": unit_cost,
                    "method": event.cost_basis_method or "broker_remaining_cost",
                    "import_run_id": import_run.import_run_id,
                }
            if symbols.issubset(evidence_by_symbol):
                break
        return evidence_by_symbol
    except Exception:
        logger.debug("Unable to hydrate broker cost-basis evidence", exc_info=True)
        return {}


def broker_cost_basis_fields(
    pos,
    evidence: dict[str, object] | None,
    *,
    quantity: float,
    avg_cost: float,
) -> dict[str, object]:
    unit_cost = optional_float_attr(pos, "broker_displayed_unit_cost")
    if unit_cost is None and evidence is not None:
        unit_cost = optional_float_value(evidence.get("unit_cost"))

    displayed_cost_basis = optional_float_attr(pos, "broker_displayed_cost_basis")
    if displayed_cost_basis is None and unit_cost is not None:
        displayed_cost_basis = unit_cost * quantity

    difference = optional_float_attr(pos, "broker_cost_basis_difference")
    if difference is None and displayed_cost_basis is not None:
        difference = displayed_cost_basis - quantity * avg_cost

    method = getattr(pos, "broker_cost_basis_method", None)
    if method is None and evidence is not None:
        method = evidence.get("method")

    status = getattr(pos, "broker_cost_basis_status", None)
    if status is None and unit_cost is not None:
        status = "available"

    return {
        "broker_displayed_unit_cost": unit_cost,
        "broker_displayed_cost_basis": displayed_cost_basis,
        "broker_cost_basis_difference": difference,
        "broker_cost_basis_method": method,
        "broker_cost_basis_status": status,
    }


def asset_class_from_config(state, symbol: str) -> str | None:
    """Legacy fallback for old config assets; persisted sources remain primary."""

    for asset in getattr(state.config, "assets", []) or []:
        if not isinstance(asset, dict):
            continue
        if str(asset.get("symbol") or "").strip() != symbol:
            continue
        asset_class = asset.get("asset_class") or asset.get("asset_type")
        if asset_class not in {None, ""}:
            return str(asset_class)
    return None


def asset_class_from_watchlist(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if not callable(list_watchlist):
        return None
    try:
        rows = list_watchlist()
    except Exception:
        logger.warning("Failed to read watchlist assets for %s", symbol, exc_info=True)
        return None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip() != symbol:
            continue
        asset_class = row.get("asset_class") or row.get("asset_type")
        if asset_class not in {None, ""}:
            return str(asset_class)
    return None


def asset_class_from_metadata(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_instrument_metadata_sync"):
        return None
    try:
        metadata = db.get_instrument_metadata_sync(symbol)
    except Exception:
        logger.warning(
            "Failed to read instrument metadata for %s",
            symbol,
            exc_info=True,
        )
        return None
    if not metadata:
        return None
    asset_class = metadata.get("asset_type") or metadata.get("asset_class")
    return None if asset_class in {None, ""} else str(asset_class)


def asset_class_from_ledger(state, symbol: str) -> str | None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return None

    offset = 0
    batch_size = 500
    latest_asset_class: str | None = None
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol") or "").strip() != symbol:
                continue
            asset_class = row.get("asset_class")
            if asset_class not in {None, ""}:
                latest_asset_class = str(asset_class)
        if len(rows) < batch_size:
            break
        offset += batch_size
    return latest_asset_class


def asset_class_for_position(
    symbol: str,
    quote: dict | None,
    instruments: dict,
    state=None,
) -> AssetClass | None:
    raw_asset_class = (quote or {}).get("asset_class")
    if not raw_asset_class and instruments:
        instrument = instruments.get(Symbol(symbol)) or instruments.get(symbol)
        raw_asset_class = getattr(
            getattr(instrument, "asset_class", None),
            "value",
            None,
        )
    if not raw_asset_class and state is not None:
        raw_asset_class = (
            asset_class_from_metadata(state, symbol)
            or asset_class_from_watchlist(state, symbol)
            or asset_class_from_ledger(state, symbol)
            or asset_class_from_config(state, symbol)
        )

    normalized = normalize_asset_class_value(raw_asset_class)
    if normalized == "etf":
        normalized = AssetClass.FUND.value

    try:
        return AssetClass(normalized)
    except ValueError:
        return None


__all__ = (
    "asset_class_for_position",
    "asset_class_from_config",
    "asset_class_from_ledger",
    "asset_class_from_metadata",
    "asset_class_from_watchlist",
    "broker_cost_basis_evidence_by_symbol",
    "broker_cost_basis_fields",
    "normalize_asset_class_value",
    "optional_float_attr",
    "optional_float_value",
)
