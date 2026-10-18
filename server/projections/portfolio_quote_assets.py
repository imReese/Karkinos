"""Asset identity and broker cost-basis evidence for portfolio quotes."""

from __future__ import annotations

import logging

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


__all__ = (
    "broker_cost_basis_evidence_by_symbol",
    "broker_cost_basis_fields",
    "normalize_asset_class_value",
    "optional_float_attr",
    "optional_float_value",
)
