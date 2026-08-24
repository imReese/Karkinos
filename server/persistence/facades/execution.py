"""Execution database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.persistence.facades.base import DatabaseRepositoryAccess


class ExecutionDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- OMS Orders ----------

    def get_oms_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one OMS order by its stable order ID."""
        return self._oms.get_oms_order_sync(order_id)

    def get_oms_order_by_intent_key_sync(
        self, intent_key: str
    ) -> dict[str, Any] | None:
        """Read one OMS order by its idempotency key."""
        return self._oms.get_oms_order_by_intent_key_sync(intent_key)

    def upsert_oms_order_sync(self, order: dict[str, Any]) -> dict[str, Any]:
        """Persist or update an OMS order fact."""
        return self._oms.upsert_oms_order_sync(order)

    def update_oms_order_status_sync(
        self, *, order_id: str, status: str
    ) -> dict[str, Any]:
        """Update one OMS order status."""
        return self._oms.update_oms_order_status_sync(order_id=order_id, status=status)

    def record_oms_transition_sync(
        self,
        *,
        order_id: str,
        from_status: str,
        to_status: str,
        reason: str,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one OMS state transition."""
        return self._oms.record_oms_transition_sync(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            payload=payload,
        )

    # ---------- Controlled Broker Submit Intents ----------

    def prepare_controlled_broker_submit_intent_sync(
        self, *, intent: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist one one-shot submit intent before any external broker call."""
        return self._controlled_execution.prepare_controlled_broker_submit_intent_sync(
            intent=intent
        )

    def claim_controlled_broker_recovery_query_sync(
        self,
        *,
        submit_intent_id: str,
        recovery_fingerprint: str,
        operator_approval_id: str,
        claimed_at_epoch_ms: int,
        claimed_at: str,
        minimum_wait_seconds: int,
    ) -> dict[str, Any]:
        """Atomically admit one query-only recovery attempt and audit its identity."""
        return self._controlled_execution.claim_controlled_broker_recovery_query_sync(
            submit_intent_id=submit_intent_id,
            recovery_fingerprint=recovery_fingerprint,
            operator_approval_id=operator_approval_id,
            claimed_at_epoch_ms=claimed_at_epoch_ms,
            claimed_at=claimed_at,
            minimum_wait_seconds=minimum_wait_seconds,
        )

    def finalize_controlled_broker_submit_intent_sync(
        self,
        *,
        submit_intent_id: str,
        status: str,
        broker_order_id: str,
        broker_status: str,
        result: dict[str, Any],
        actor: str,
        finalized_at_epoch_ms: int,
        finalized_at: str,
        recovered: bool = False,
    ) -> dict[str, Any]:
        """Persist a broker result without ever retrying the external submit call."""
        return self._controlled_execution.finalize_controlled_broker_submit_intent_sync(
            submit_intent_id=submit_intent_id,
            status=status,
            broker_order_id=broker_order_id,
            broker_status=broker_status,
            result=result,
            actor=actor,
            finalized_at_epoch_ms=finalized_at_epoch_ms,
            finalized_at=finalized_at,
            recovered=recovered,
        )

    def get_controlled_broker_submit_intent_sync(
        self, submit_intent_id: str
    ) -> dict[str, Any] | None:
        return self._controlled_execution.get_controlled_broker_submit_intent_sync(
            submit_intent_id
        )

    def get_controlled_broker_submit_intent_for_order_sync(
        self, order_id: str
    ) -> dict[str, Any] | None:
        return self._controlled_execution.get_controlled_broker_submit_intent_for_order_sync(
            order_id
        )

    def list_controlled_broker_submit_intents_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._controlled_execution.list_controlled_broker_submit_intents_sync(
            limit=limit
        )

    def list_unreconciled_controlled_broker_submit_intents_sync(
        self, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        """List controlled intents that still block every different order."""
        return self._controlled_execution.list_unreconciled_controlled_broker_submit_intents_sync(
            limit=limit
        )

    def get_controlled_submission_reconciliation_clearance_sync(
        self, clearance_id: str
    ) -> dict[str, Any] | None:
        return self._controlled_execution.get_controlled_submission_reconciliation_clearance_sync(
            clearance_id
        )

    def get_controlled_submission_reconciliation_clearance_for_intent_sync(
        self, submit_intent_id: str
    ) -> dict[str, Any] | None:
        return self._controlled_execution.get_controlled_submission_reconciliation_clearance_for_intent_sync(
            submit_intent_id
        )

    def list_controlled_submission_reconciliation_clearances_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._controlled_execution.list_controlled_submission_reconciliation_clearances_sync(
            limit=limit
        )

    def get_controlled_submission_ledger_posting_sync(
        self, posting_id: str
    ) -> dict[str, Any] | None:
        """Read one immutable controlled-order ledger posting."""
        return self._controlled_execution.get_controlled_submission_ledger_posting_sync(
            posting_id
        )

    def get_account_truth_review_identity_sync(
        self, import_run_id: str
    ) -> dict[str, Any]:
        """Fingerprint current manual-review decisions for one broker import."""
        return self._controlled_execution.get_account_truth_review_identity_sync(
            import_run_id
        )

    def get_controlled_submission_ledger_posting_for_clearance_sync(
        self, clearance_id: str
    ) -> dict[str, Any] | None:
        """Read the exactly-once posting associated with one clearance."""
        return self._controlled_execution.get_controlled_submission_ledger_posting_for_clearance_sync(
            clearance_id
        )

    def list_controlled_submission_ledger_postings_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable controlled-order ledger postings, newest first."""
        return (
            self._controlled_execution.list_controlled_submission_ledger_postings_sync(
                limit=limit
            )
        )

    def get_controlled_submission_ledger_correction_sync(
        self, correction_id: str
    ) -> dict[str, Any] | None:
        """Read one immutable compensating correction."""
        return (
            self._controlled_execution.get_controlled_submission_ledger_correction_sync(
                correction_id
            )
        )

    def get_controlled_submission_ledger_correction_for_posting_sync(
        self, posting_id: str
    ) -> dict[str, Any] | None:
        """Read the exactly-once correction associated with one posting."""
        return self._controlled_execution.get_controlled_submission_ledger_correction_for_posting_sync(
            posting_id
        )

    def list_controlled_submission_ledger_corrections_sync(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List immutable compensating corrections, newest first."""
        return self._controlled_execution.list_controlled_submission_ledger_corrections_sync(
            limit=limit
        )

    def record_controlled_submission_ledger_correction_sync(
        self, *, correction: dict[str, Any]
    ) -> dict[str, Any]:
        """Re-derive and atomically append one exact correction event."""
        return self._controlled_execution.record_controlled_submission_ledger_correction_sync(
            correction=correction
        )

    def record_controlled_submission_ledger_posting_sync(
        self, *, posting: dict[str, Any]
    ) -> dict[str, Any]:
        """Verify and atomically post exact cleared fills to the ledger once."""
        return (
            self._controlled_execution.record_controlled_submission_ledger_posting_sync(
                posting=posting
            )
        )

    def record_controlled_submission_reconciliation_clearance_sync(
        self, *, clearance: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically record real fills, terminal OMS state, and clearance."""
        return self._controlled_execution.record_controlled_submission_reconciliation_clearance_sync(
            clearance=clearance
        )

    def list_oms_transitions_sync(self, order_id: str) -> list[dict[str, Any]]:
        """List OMS transitions for one order in chronological order."""
        return self._oms.list_oms_transitions_sync(order_id)

    # ---------- Broker Gateway Events ----------

    def record_broker_gateway_event_sync(
        self,
        *,
        gateway_id: str,
        event_type: str,
        order_id: str | None = None,
        status: str = "recorded",
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one broker gateway audit event."""
        return self._execution_reconciliation.record_broker_gateway_event_sync(
            gateway_id=gateway_id,
            event_type=event_type,
            order_id=order_id,
            status=status,
            actor=actor,
            payload=payload,
        )

    def list_broker_gateway_events_sync(
        self,
        *,
        order_id: str | None = None,
        gateway_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List broker gateway audit events."""
        return self._execution_reconciliation.list_broker_gateway_events_sync(
            order_id=order_id, gateway_id=gateway_id, limit=limit, offset=offset
        )

    # ---------- Execution Reconciliation ----------

    def list_oms_orders_sync(
        self, *, status: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List OMS orders for execution reconciliation."""
        return self._execution_reconciliation.list_oms_orders_sync(
            status=status, limit=limit, offset=offset
        )

    def upsert_execution_reconciliation_run_sync(
        self,
        *,
        run_id: str,
        run_date: str,
        status: str,
        item_count: int,
        open_item_count: int,
        payload: dict[str, Any] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist one execution reconciliation run and replace its items."""
        return self._execution_reconciliation.upsert_execution_reconciliation_run_sync(
            run_id=run_id,
            run_date=run_date,
            status=status,
            item_count=item_count,
            open_item_count=open_item_count,
            payload=payload,
            items=items,
        )

    def list_execution_reconciliation_runs_sync(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List recent execution reconciliation runs."""
        return self._execution_reconciliation.list_execution_reconciliation_runs_sync(
            limit=limit, offset=offset
        )

    def get_execution_reconciliation_run_sync(
        self, run_id: str
    ) -> dict[str, Any] | None:
        """Read one execution reconciliation run."""
        return self._execution_reconciliation.get_execution_reconciliation_run_sync(
            run_id
        )

    def list_execution_reconciliation_items_sync(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """List item rows for one execution reconciliation run."""
        return self._execution_reconciliation.list_execution_reconciliation_items_sync(
            run_id
        )
