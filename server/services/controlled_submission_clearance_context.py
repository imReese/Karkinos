"""Typed collaboration surface shared by clearance service mixins."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class ControlledSubmissionClearanceContext:
    """Declare façade-owned state and sibling operations for static checking."""

    _db: Any
    _account_truth_provider: Callable[[], dict[str, Any]] | None
    _trusted_operator_identities: tuple[Any, ...]
    _clock: Callable[[], datetime]

    def preview(
        self,
        *,
        submit_intent_id: str,
        reconciliation_run_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _build_order_fingerprint(self, order: dict[str, Any]) -> str:
        raise NotImplementedError

    def _resolve_operator_approval_with_proof(
        self,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        raise NotImplementedError

    def _broker_evidence_repository(self, path: Path) -> Any:
        raise NotImplementedError

    def _broker_order_lifecycle_repository(
        self,
        path: Path,
        *,
        ensure_schema: bool,
    ) -> Any:
        raise NotImplementedError

    def _broker_order_lifecycle_terminal_outcome(
        self,
        order: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _resolve_broker_source(
        self,
        broker_evidence: list[dict[str, Any]],
        *,
        account_truth: dict[str, Any],
        evidence_required: bool,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _resolve_terminal_lifecycle(
        self,
        *,
        intent: dict[str, Any],
        order: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _resolve_account_truth(
        self,
        *,
        now: datetime,
        broker_evidence: list[dict[str, Any]],
        order: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _clearance_rejection(
        self,
        message: str,
        *,
        evidence: dict[str, Any],
    ) -> Exception:
        raise NotImplementedError
