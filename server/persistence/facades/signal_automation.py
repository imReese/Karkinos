"""Signal Automation database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.persistence.facades.base import DatabaseRepositoryAccess


class SignalAutomationDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Signals ----------

    def save_signal_sync(
        self,
        timestamp: str,
        strategy_id: str,
        symbol: str,
        direction: str,
        target_weight: float,
        price: float | None,
        asset_class: str,
    ) -> int:
        """同步写入信号（后台线程调用）。"""
        return self._signal_journal.save_signal_sync(
            timestamp, strategy_id, symbol, direction, target_weight, price, asset_class
        )

    async def get_signals(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """异步读取信号历史。"""
        return await self._signal_journal.get_signals(limit, offset)

    async def get_latest_signals(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最新信号。"""
        return await self._signal_journal.get_latest_signals(limit)

    async def list_signal_journal(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Async wrapper for the signal journal audit view."""
        return await self._signal_journal.list_signal_journal(limit, offset)

    def list_signal_journal_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List signal → action task → risk decision journal entries."""
        return self._signal_journal.list_signal_journal_sync(limit, offset)

    # ---------- Action Tasks ----------

    def upsert_action_task_sync(
        self,
        *,
        source_signal_id: int,
        symbol: str,
        title: str,
        detail: str,
        direction: str,
        urgency: str,
        target_weight: float,
        price: float | None,
        strategy_id: str,
        timestamp: str,
        asset_class: str,
    ) -> None:
        """同步写入或更新待执行任务，避免重复生成。"""
        return self._signal_journal.upsert_action_task_sync(
            source_signal_id=source_signal_id,
            symbol=symbol,
            title=title,
            detail=detail,
            direction=direction,
            urgency=urgency,
            target_weight=target_weight,
            price=price,
            strategy_id=strategy_id,
            timestamp=timestamp,
            asset_class=asset_class,
        )

    async def get_action_tasks(
        self, statuses: list[str] | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """列出待执行任务。"""
        return await self._signal_journal.get_action_tasks(statuses, limit, offset)

    def get_action_tasks_sync(
        self, statuses: list[str] | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步版本，避免事件循环中 sqlite 读取挂住。"""
        return self._signal_journal.get_action_tasks_sync(statuses, limit, offset)

    def get_action_task_sync(self, task_id: int) -> dict[str, Any] | None:
        """Read one action task with its latest risk and manual-confirm state."""
        return self._signal_journal.get_action_task_sync(task_id)

    async def update_action_task_status(
        self, task_id: int, status: str
    ) -> dict[str, Any] | None:
        """更新任务状态并返回新值。"""
        return await self._signal_journal.update_action_task_status(task_id, status)

    def update_action_task_status_sync(
        self, task_id: int, status: str
    ) -> dict[str, Any] | None:
        """同步版本，供线程池包装。"""
        return self._signal_journal.update_action_task_status_sync(task_id, status)

    async def record_signal_review(
        self,
        *,
        signal_id: int,
        reviewed_at: str,
        user_decision: str,
        outcome: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Async wrapper for a signal review/outcome audit event."""
        return await self._signal_journal.record_signal_review(
            signal_id=signal_id,
            reviewed_at=reviewed_at,
            user_decision=user_decision,
            outcome=outcome,
            review_notes=review_notes,
            reviewer=reviewer,
        )

    def record_signal_review_sync(
        self,
        *,
        signal_id: int,
        reviewed_at: str,
        user_decision: str,
        outcome: str,
        review_notes: str,
        reviewer: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist a post-decision signal review as an immutable audit event."""
        return self._signal_journal.record_signal_review_sync(
            signal_id=signal_id,
            reviewed_at=reviewed_at,
            user_decision=user_decision,
            outcome=outcome,
            review_notes=review_notes,
            reviewer=reviewer,
        )

    # ---------- Risk Decisions ----------

    def save_risk_decision_sync(self, *, intent, decision) -> int:
        """同步写入风控决策审计记录。"""
        return self._signal_journal.save_risk_decision_sync(
            intent=intent, decision=decision
        )

    def get_risk_decisions_sync(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """同步读取风控决策审计记录，最新优先。"""
        return self._signal_journal.get_risk_decisions_sync(limit, offset)

    # ---------- Runtime Controls ----------

    def set_runtime_control_sync(self, key: str, value: dict[str, Any]) -> None:
        """Persist runtime control state such as kill switch."""
        self._runtime_controls.set_value(key, value)

    def get_runtime_control_sync(self, key: str) -> dict[str, Any] | None:
        """Read persisted runtime control state."""
        return self._runtime_controls.get_value(key)

    # ---------- Automation Control ----------

    def get_automation_policy_sync(self, policy_id: str) -> dict[str, Any] | None:
        """Read one persisted automation policy by ID."""
        return self._automation_runs.get_automation_policy_sync(policy_id)

    def upsert_automation_policy_sync(
        self, *, policy_id: str, payload: dict[str, Any], updated_by: str | None = None
    ) -> dict[str, Any]:
        """Persist an automation policy snapshot."""
        return self._automation_runs.upsert_automation_policy_sync(
            policy_id=policy_id, payload=payload, updated_by=updated_by
        )

    def upsert_automation_run_sync(self, run: dict[str, Any]) -> dict[str, Any]:
        """Persist or update an automation run audit record."""
        return self._automation_runs.upsert_automation_run_sync(run)

    def get_automation_run_sync(self, run_id: str) -> dict[str, Any] | None:
        """Read one automation run audit record."""
        return self._automation_runs.get_automation_run_sync(run_id)

    def claim_daily_candidate_background_attempt_sync(
        self, *, run_date: str, claimed_at: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically claim one fail-closed background attempt per market date."""
        return self._automation_runs.claim_daily_candidate_background_attempt_sync(
            run_date=run_date, claimed_at=claimed_at, payload=payload
        )

    def claim_automation_run_once_sync(
        self,
        *,
        run_id: str,
        run_type: str,
        run_date: str,
        claimed_at: str,
        execution_mode: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically claim one exact automation run identity."""
        return self._automation_runs.claim_automation_run_once_sync(
            run_id=run_id,
            run_type=run_type,
            run_date=run_date,
            claimed_at=claimed_at,
            execution_mode=execution_mode,
            payload=payload,
        )

    def list_automation_runs_sync(
        self,
        *,
        run_type: str | None = None,
        run_date: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent automation run audit records."""
        return self._automation_runs.list_automation_runs_sync(
            run_type=run_type, run_date=run_date, limit=limit, offset=offset
        )

    def list_all_automation_runs_for_type_sync(
        self, *, run_type: str
    ) -> list[dict[str, Any]]:
        """Read a complete run-type history from one database snapshot.

        This is intentionally separate from the bounded operational listing:
        evidence-window consumers must not silently turn an old, valid trial
        into a truncated one when the installation passes a UI page limit.
        """
        return self._automation_runs.list_all_automation_runs_for_type_sync(
            run_type=run_type
        )
