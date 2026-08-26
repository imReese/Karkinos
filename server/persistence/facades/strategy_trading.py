"""Strategy Trading database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.contracts.order_state import (
    ManualOrderStateCommand,
    ManualOrderTicketCommand,
)
from server.contracts.paper_shadow import PaperShadowRunCommand
from server.persistence.facades.base import DatabaseRepositoryAccess


class StrategyTradingDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Strategy Promotion Pipeline ----------

    def upsert_strategy_promotion_state_sync(
        self,
        *,
        strategy_id: str,
        stage: str,
        gate_status: str,
        live_like_enabled: bool,
        missing_requirements: list[str] | None = None,
        backtest_result_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one strategy promotion state."""
        return self._strategy_promotion.upsert_strategy_promotion_state_sync(
            strategy_id=strategy_id,
            stage=stage,
            gate_status=gate_status,
            live_like_enabled=live_like_enabled,
            missing_requirements=missing_requirements,
            backtest_result_id=backtest_result_id,
            payload=payload,
        )

    def get_strategy_promotion_state_sync(
        self, strategy_id: str
    ) -> dict[str, Any] | None:
        """Read one strategy promotion state."""
        return self._strategy_promotion.get_strategy_promotion_state_sync(strategy_id)

    def get_ai_shadow_strategy_promotion_binding_sync(
        self, candidate_id: str
    ) -> dict[str, Any] | None:
        """Read the candidate and human approval that back one reserved strategy."""
        return self._strategy_promotion.get_ai_shadow_strategy_promotion_binding_sync(
            candidate_id
        )

    def list_strategy_promotion_states_sync(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List strategy promotion states."""
        return self._strategy_promotion.list_strategy_promotion_states_sync(
            limit=limit, offset=offset
        )

    def record_strategy_promotion_event_sync(
        self,
        *,
        strategy_id: str,
        event_type: str,
        from_stage: str | None = None,
        to_stage: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one strategy promotion audit event."""
        return self._strategy_promotion.record_strategy_promotion_event_sync(
            strategy_id=strategy_id,
            event_type=event_type,
            from_stage=from_stage,
            to_stage=to_stage,
            actor=actor,
            payload=payload,
        )

    def list_strategy_promotion_events_sync(
        self, strategy_id: str
    ) -> list[dict[str, Any]]:
        """List strategy promotion audit events for one strategy."""
        return self._strategy_promotion.list_strategy_promotion_events_sync(strategy_id)

    # ---------- Automation Alerts ----------

    def upsert_automation_alert_sync(
        self,
        *,
        alert_key: str,
        severity: str,
        category: str,
        title: str,
        detail: str,
        source: str,
        source_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist an idempotent automation alert by alert key."""
        return self._automation_alerts.upsert_alert(
            alert_key=alert_key,
            severity=severity,
            category=category,
            title=title,
            detail=detail,
            source=source,
            source_ref=source_ref,
            payload=payload,
        )

    def list_automation_alerts_sync(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List persisted automation alerts."""
        return self._automation_alerts.list_alerts(
            status=status,
            limit=limit,
            offset=offset,
        )

    def acknowledge_automation_alert_sync(
        self,
        *,
        alert_id: int,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Mark one automation alert acknowledged."""
        return self._automation_alerts.acknowledge_alert(
            alert_id=alert_id,
            actor=actor,
        )

    def list_execution_reconciliation_open_items_sync(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List execution reconciliation items that still require action."""
        return self._execution_reconciliation.list_execution_reconciliation_open_items_sync(
            limit=limit, offset=offset
        )

    def get_latest_execution_reconciliation_item_for_order_sync(
        self, order_id: str
    ) -> dict[str, Any] | None:
        """Return the latest persisted reconciliation fact for one OMS order."""
        return self._execution_reconciliation.get_latest_execution_reconciliation_item_for_order_sync(
            order_id
        )

    # ---------- Paper/Shadow Runs ----------

    def record_paper_shadow_run_sync(
        self,
        command: PaperShadowRunCommand,
    ) -> dict[str, Any]:
        """Atomically record one immutable paper-shadow simulation aggregate."""
        return self._paper_trading.record_paper_shadow_run_sync(command)

    def get_paper_shadow_run_sync(self, run_id: str) -> dict[str, Any] | None:
        """Read one persisted paper/shadow run by ID."""
        return self._paper_trading.get_paper_shadow_run_sync(run_id)

    def latest_paper_shadow_run_sync(
        self, *, plan_date: str | None = None
    ) -> dict[str, Any] | None:
        """Read the latest paper/shadow run, optionally scoped to a plan date."""
        return self._paper_trading.latest_paper_shadow_run_sync(plan_date=plan_date)

    def record_paper_shadow_run_review_sync(
        self,
        *,
        run_id: str,
        reviewed_at: str,
        review_status: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach an operator review outcome to a paper/shadow run."""
        return self._paper_trading.record_paper_shadow_run_review_sync(
            run_id=run_id,
            reviewed_at=reviewed_at,
            review_status=review_status,
            review_notes=review_notes,
            reviewer=reviewer,
        )

    # ---------- Orders ----------

    def record_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        asset_class: str = "stock",
        intent_id: str | None = None,
        risk_decision_id: str | None = None,
        execution_mode: str = "paper",
        status: str = "submitted",
        source: str = "execution",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        """Persist a shared order fact for manual, paper, and live execution."""
        return self._paper_trading.record_order_sync(
            order_id=order_id,
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            asset_class=asset_class,
            intent_id=intent_id,
            risk_decision_id=risk_decision_id,
            execution_mode=execution_mode,
            status=status,
            source=source,
            source_ref=source_ref,
            payload=payload,
        )

    def get_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one shared order fact by ID."""
        return self._paper_trading.get_order_sync(order_id)

    def record_shadow_divergence_review_sync(
        self,
        *,
        order_id: str,
        reviewed_at: str,
        divergence_status: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach an operator divergence review to a paper/shadow order fact."""
        return self._paper_trading.record_shadow_divergence_review_sync(
            order_id=order_id,
            reviewed_at=reviewed_at,
            divergence_status=divergence_status,
            review_notes=review_notes,
            reviewer=reviewer,
        )

    def list_orders_sync(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List shared order facts newest first."""
        return self._paper_trading.list_orders_sync(
            status=status, symbol=symbol, limit=limit, offset=offset
        )

    def update_order_status_sync(
        self, *, order_id: str, status: str, note: str = ""
    ) -> dict[str, Any] | None:
        """Update shared order status and append an order status event."""
        return self._paper_trading.update_order_status_sync(
            order_id=order_id, status=status, note=note
        )

    # ---------- Manual Orders ----------

    def create_manual_order_ticket_sync(
        self,
        command: ManualOrderTicketCommand,
    ) -> dict[str, Any]:
        """Atomically create both order projections and claim the action task."""
        return self._paper_trading.create_manual_order_ticket_sync(command)

    def transition_manual_order_sync(
        self,
        command: ManualOrderStateCommand,
    ) -> dict[str, Any]:
        """Atomically transition both order projections and their action task."""
        return self._paper_trading.transition_manual_order_sync(command)

    def get_manual_order_sync(self, order_id: str) -> dict[str, Any] | None:
        """Read one manual order by ID."""
        return self._paper_trading.get_manual_order_sync(order_id)

    def list_manual_orders_sync(
        self, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List manual orders, latest first."""
        return self._paper_trading.list_manual_orders_sync(status, limit, offset)

    # ---------- Fills ----------

    def record_fill_sync(
        self,
        *,
        fill_id: str,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        fill_price: float,
        fill_quantity: float,
        commission: float = 0.0,
        slippage: float = 0.0,
        asset_class: str = "stock",
        execution_mode: str = "paper",
        provider_name: str | None = None,
        broker_order_id: str | None = None,
        source: str = "execution",
        source_ref: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Persist a fill from paper/live execution and append an event."""
        return self._paper_trading.record_fill_sync(
            fill_id=fill_id,
            order_id=order_id,
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            fill_price=fill_price,
            fill_quantity=fill_quantity,
            commission=commission,
            slippage=slippage,
            asset_class=asset_class,
            execution_mode=execution_mode,
            provider_name=provider_name,
            broker_order_id=broker_order_id,
            source=source,
            source_ref=source_ref,
            metadata=metadata,
        )

    def get_fill_sync(self, fill_id: str) -> dict[str, Any] | None:
        """Read one persisted execution fill by ID."""
        return self._paper_trading.get_fill_sync(fill_id)

    def list_fills_sync(
        self,
        *,
        order_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List persisted execution fills newest first."""
        return self._paper_trading.list_fills_sync(
            order_id=order_id, symbol=symbol, limit=limit, offset=offset
        )
