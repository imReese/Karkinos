"""Application boundary for building or publishing valuation projections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from server.projections.valuation_snapshot import (
    VALUATION_POLICY_VERSION,
)
from server.projections.valuation_snapshot import (
    build_current_valuation_snapshot as _build_current_valuation_snapshot,
)
from server.projections.valuation_snapshot import (
    ledger_identity_from_rows,
    load_persisted_quote_rows,
    select_authoritative_quote_rows,
    validate_valuation_snapshot,
    valuation_identity_fields,
    valuation_snapshot_from_row,
)


def build_current_valuation_snapshot(
    db: Any,
    *,
    valuation_policy: str = VALUATION_POLICY_VERSION,
    persist: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a projection or atomically publish it with an explicit choice."""

    if persist:
        publisher = getattr(db, "publish_current_valuation_snapshot_sync", None)
        if not callable(publisher):
            raise RuntimeError("valuation snapshot publication is unavailable")
        if valuation_policy == VALUATION_POLICY_VERSION:
            return publisher() if now is None else publisher(now=now)
        if now is None:
            return publisher(valuation_policy=valuation_policy)
        return publisher(valuation_policy=valuation_policy, now=now)

    payload = _build_current_valuation_snapshot(
        db,
        valuation_policy=valuation_policy,
        persist=False,
        now=now,
    )
    return payload


__all__ = [
    "VALUATION_POLICY_VERSION",
    "build_current_valuation_snapshot",
    "ledger_identity_from_rows",
    "load_persisted_quote_rows",
    "select_authoritative_quote_rows",
    "validate_valuation_snapshot",
    "valuation_identity_fields",
    "valuation_snapshot_from_row",
]
