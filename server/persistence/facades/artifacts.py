"""Artifacts database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.persistence.facades.base import DatabaseRepositoryAccess


class ArtifactDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Backtest Results ----------

    async def save_backtest_result(
        self,
        config_json: str,
        initial_cash: float,
        final_equity: float,
        total_return: float,
        sharpe: float,
        max_dd: float,
        equity_curve_json: str,
        annual_return: float = 0.0,
        sortino: float = 0.0,
        win_rate: float = 0.0,
        duration_days: int = 0,
        metrics_json: str = "{}",
        cost_summary_json: str = "{}",
    ) -> int:
        """保存回测结果，返回 ID。"""
        return await self._backtest_results.save(
            config_json=config_json,
            initial_cash=initial_cash,
            final_equity=final_equity,
            total_return=total_return,
            sharpe=sharpe,
            max_dd=max_dd,
            equity_curve_json=equity_curve_json,
            annual_return=annual_return,
            sortino=sortino,
            win_rate=win_rate,
            duration_days=duration_days,
            metrics_json=metrics_json,
            cost_summary_json=cost_summary_json,
        )

    async def get_backtest_results(self) -> list[dict[str, Any]]:
        """获取所有回测结果摘要。"""
        return await self._backtest_results.list_results()

    async def get_backtest_result(self, result_id: int) -> dict[str, Any] | None:
        """获取单个回测结果详情。"""
        return await self._backtest_results.get_result(result_id)

    # ---------- Quote Fetch Runs ----------

    def save_valuation_snapshot_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one immutable, content-addressed valuation snapshot."""
        return self._financial_facts.save_valuation_snapshot_sync(payload)

    def publish_current_valuation_snapshot_sync(
        self,
        *,
        valuation_policy: str | None = None,
    ) -> dict[str, Any]:
        """Build and persist the immutable snapshot for committed facts."""
        return self._financial_facts.publish_current_valuation_snapshot_sync(
            valuation_policy=valuation_policy,
        )

    def get_valuation_snapshot_sync(self, snapshot_id: str) -> dict[str, Any] | None:
        """Read one immutable valuation snapshot by content id."""
        return self._financial_facts.get_valuation_snapshot_sync(snapshot_id)

    def create_quote_fetch_run(
        self,
        *,
        run_id: str,
        started_at: str,
        trigger: str,
        status: str,
        provider: str | None = None,
        asset_type: str | None = None,
        symbol_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> int:
        """Create one quote fetch run audit row."""
        return self._financial_facts.create_quote_fetch_run(
            run_id=run_id,
            started_at=started_at,
            trigger=trigger,
            status=status,
            provider=provider,
            asset_type=asset_type,
            symbol_count=symbol_count,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=cache_hit_count,
            error_message=error_message,
            metadata=metadata,
        )

    def finish_quote_fetch_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int = 0,
        failure_count: int = 0,
        cache_hit_count: int = 0,
        error_message: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a quote fetch run as finished and return the updated row."""
        return self._financial_facts.finish_quote_fetch_run(
            run_id=run_id,
            finished_at=finished_at,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=cache_hit_count,
            error_message=error_message,
            metadata=metadata,
        )

    def get_quote_fetch_run(self, run_id: str) -> dict[str, Any] | None:
        """Read one quote fetch run by run_id."""
        return self._financial_facts.get_quote_fetch_run(run_id)

    def list_quote_fetch_runs(
        self,
        limit: int = 50,
        trigger: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        """List quote fetch runs, newest first."""
        return self._financial_facts.list_quote_fetch_runs(
            limit, trigger, status, provider
        )

    # ---------- Event Log ----------

    def append_event_sync(
        self,
        *,
        event_type: str,
        timestamp: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        source: str = "app",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        """Append one normalized domain event to the shared event stream."""
        return self._event_log.append(
            event_type=event_type,
            timestamp=timestamp,
            entity_type=entity_type,
            entity_id=entity_id,
            source=source,
            source_ref=source_ref,
            payload=payload,
        )

    def list_events_sync(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List normalized domain events newest first."""
        return self._event_log.list_events(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            source=source,
            limit=limit,
            offset=offset,
        )
