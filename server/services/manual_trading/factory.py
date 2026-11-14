"""Factory creating configured ManualTradingService instances."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.services.controlled_execution.current_per_order_dossier_factory import (
    build_current_per_order_dossier_service,
)
from server.services.manual_trading.service import ManualTradingService


def build_manual_trading_service(state: Any) -> ManualTradingService:
    """Build a ManualTradingService from the application state."""
    config = getattr(state, "config", None)
    current_dossiers = build_current_per_order_dossier_service(state)

    def _broker_evidence_repo() -> Any | None:
        db = getattr(state, "db", None)
        db_path = getattr(db, "_path", None)
        if not db_path:
            return None
        from account_truth.broker_evidence import BrokerEvidenceRepository

        return BrokerEvidenceRepository(Path(str(db_path)))

    return ManualTradingService(
        db=state.db,
        trading_controls=getattr(state, "trading_controls", None),
        current_per_order_confirmation_provider=(
            current_dossiers.resolve_current_confirmation
        ),
        controlled_bridge_policy=getattr(config, "controlled_bridge_policy", None),
        broker_evidence_repository_factory=_broker_evidence_repo,
    )
