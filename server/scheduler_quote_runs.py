"""Quote-ingestion run ownership for the background scheduler."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime

from core.events import MarketEvent
from core.types import AssetClass, InstrumentType, Symbol
from server.scheduler_contracts import SchedulerConfig, SchedulerDatabase, SchedulerFeed
from server.scheduler_values import (
    provider_status_for_quote_run,
    quote_fetch_asset_type,
    quote_fetch_metadata,
    quote_fetch_started_metadata,
    quote_fetch_status,
)

logger = logging.getLogger(__name__)


class SchedulerQuoteRunMixin:
    """Open, poll, and publish one auditable scheduler quote batch."""

    _config: SchedulerConfig
    _db: SchedulerDatabase | None
    _watchlist: list[tuple[Symbol, AssetClass]]
    _pending_valuation_publication_reason: str | None
    _scheduler_clock: Callable[[], datetime]

    def _create_scheduler_quote_fetch_run(
        self,
        *,
        run_id: str,
        started_at: str,
    ) -> bool:
        if self._db is None:
            logger.error("Scheduler database is required to create quote fetch runs")
            return False
        try:
            metadata = quote_fetch_started_metadata(self._config, self._watchlist)
            instrument_types = []
            for symbol, asset_class in self._watchlist:
                instrument = getattr(self, "_instruments", {}).get(symbol)
                kind = getattr(instrument, "instrument_type", None)
                instrument_types.append(
                    kind.value
                    if isinstance(kind, InstrumentType)
                    else (
                        asset_class.value
                        if asset_class is not AssetClass.FUND
                        else None
                    )
                )
            metadata["instrument_types"] = instrument_types
            self._db.create_quote_fetch_run(
                run_id=run_id,
                started_at=started_at,
                trigger="scheduler_poll",
                provider=self._config.data_source,
                asset_type=quote_fetch_asset_type(self._watchlist),
                symbol_count=len(self._watchlist),
                status="running",
                metadata=metadata,
            )
        except Exception:
            logger.warning("Failed to create scheduler quote fetch run", exc_info=True)
            return False
        return True

    def _finish_scheduler_quote_fetch_run(
        self,
        *,
        run_id: str,
        finished_at: str,
        status: str,
        success_count: int,
        failure_count: int,
        metadata: dict,
        error_message: str | None = None,
    ) -> bool:
        if self._db is None:
            logger.error("Scheduler database is required to finish quote fetch runs")
            return False
        try:
            finished = self._db.finish_quote_fetch_run(
                run_id=run_id,
                finished_at=finished_at,
                status=status,
                success_count=success_count,
                failure_count=failure_count,
                cache_hit_count=0,
                error_message=error_message,
                metadata=metadata,
            )
            if isinstance(finished, dict) and str(
                finished.get("error_message") or ""
            ).startswith("valuation snapshot publication failed:"):
                self._pending_valuation_publication_reason = f"quote_fetch_run:{run_id}"
                return False
        except Exception:
            logger.warning("Failed to finish scheduler quote fetch run", exc_info=True)
            return False
        if not isinstance(finished, dict) or str(finished.get("status") or "") not in {
            "success",
            "partial",
            "partial_success",
        }:
            return False
        try:
            completion_metadata = json.loads(str(finished.get("metadata_json") or "{}"))
        except (TypeError, ValueError):
            logger.error("Scheduler quote run returned invalid completion metadata")
            return False
        if completion_metadata.get("valuation_snapshot_status") != "complete":
            logger.warning(
                "Scheduler quote run published incomplete valuation evidence: %s",
                run_id,
            )
            return False
        self._pending_valuation_publication_reason = None
        return True

    def _poll_watchlist_quotes(
        self,
        feed: SchedulerFeed,
    ) -> tuple[list[MarketEvent], str]:
        """Poll once while keeping the ingestion run open for staged writes."""

        started_at = self._scheduler_clock()
        run_id = f"scheduler_poll:{started_at.isoformat()}:{uuid.uuid4().hex}"
        if not self._create_scheduler_quote_fetch_run(
            run_id=run_id,
            started_at=started_at.isoformat(),
        ):
            raise RuntimeError("scheduler quote fetch run could not be persisted")
        try:
            events = feed.poll_all(self._watchlist)
        except Exception as exc:
            failed_symbols = [str(symbol) for symbol, _ in self._watchlist]
            metadata = quote_fetch_metadata(
                self._config,
                self._watchlist,
                provider_status="failed",
                success_symbols=[],
                failed_symbols=failed_symbols,
                error_message=str(exc),
            )
            self._finish_scheduler_quote_fetch_run(
                run_id=run_id,
                finished_at=self._scheduler_clock().isoformat(),
                status="failed",
                success_count=0,
                failure_count=len(self._watchlist),
                metadata=metadata,
                error_message=str(exc),
            )
            raise
        return events, run_id

    def _finish_persisted_quote_fetch_run(
        self,
        run_id: str,
        events: list[MarketEvent],
        quote_statuses: list[str],
    ) -> bool:
        """Publish one staged quote batch and its valuation terminal state."""

        success_symbols = [str(event.symbol) for event in events]
        success_symbol_set = set(success_symbols)
        failed_symbols = [
            str(symbol)
            for symbol, _ in self._watchlist
            if str(symbol) not in success_symbol_set
        ]
        success_count = len(events)
        failure_count = len(self._watchlist) - success_count
        status = quote_fetch_status(
            len(self._watchlist),
            success_count=success_count,
            failure_count=failure_count,
        )
        provider_status = provider_status_for_quote_run(
            len(self._watchlist),
            success_count=success_count,
            failure_count=failure_count,
        )
        metadata = quote_fetch_metadata(
            self._config,
            self._watchlist,
            provider_status=provider_status,
            success_symbols=success_symbols,
            failed_symbols=failed_symbols,
            quote_statuses=quote_statuses,
        )
        return self._finish_scheduler_quote_fetch_run(
            run_id=run_id,
            finished_at=self._scheduler_clock().isoformat(),
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            metadata=metadata,
        )
