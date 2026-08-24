"""Explicit composition seam for the valuation projection."""

from __future__ import annotations

from typing import Any


def build_and_persist_current_valuation_snapshot(
    repository: Any,
) -> dict[str, Any]:
    """Invoke the projection at runtime without coupling repository capabilities."""

    from server.projections.valuation_snapshot import (
        build_current_valuation_snapshot,
    )

    return build_current_valuation_snapshot(repository, persist=True)


__all__ = ["build_and_persist_current_valuation_snapshot"]
