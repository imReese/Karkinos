"""Transaction-local values for controlled clearance persistence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ControlledClearanceWritePlan:
    """Revalidated inputs that may be written by the active transaction."""

    fill_rows: tuple[dict[str, Any], ...]
    terminal_status: str
    fill_quantity: Decimal
    cancelled_quantity: Decimal
    blockers: tuple[str, ...]
