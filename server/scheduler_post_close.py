"""Post-close reconciliation behavior for :class:`TradingScheduler`."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from core.types import AssetClass, InstrumentType
from server.scheduler_loop import runtime_quotes_from_persisted
from server.services.fund_nav_sync import (
    is_confirmed_fund_nav_quote,
    refresh_fund_nav_quotes,
)
from server.services.market_calendar_dates import (
    resolve_latest_verified_closed_trading_date,
)
from server.services.market_hours import get_shanghai_now
from server.services.post_close_stock_quotes import publish_post_close_stock_quotes

logger = logging.getLogger(__name__)

_MORNING_OPEN = time(9, 30)
_AFTERNOON_CLOSE = time(15, 0)
_POST_CLOSE_MARKET_REFRESH_TIME = time(16, 0)
_POST_CLOSE_FUND_NAV_REFRESH_TIME = time(21, 30)
_POST_CLOSE_MARKET_RETRY_INTERVAL = timedelta(minutes=5)
_POST_CLOSE_FUND_NAV_RETRY_INTERVAL = timedelta(minutes=15)


class SchedulerPostCloseMixin:
    """Reconcile verified stock closes and canonical fund NAV facts."""

    def _historical_backfill_remote_refresh_policy(
        self,
        data_manager: Any,
        *,
        trade_date: str,
    ) -> bool | None:
        """Never let per-symbol refresh mutate a frozen market-daily batch."""

        store = getattr(data_manager, "store", None)
        receipt_reader = getattr(store, "get_market_daily_ingestion_receipt", None)
        if not callable(receipt_reader):
            return True
        try:
            receipt = receipt_reader(
                trade_date=trade_date,
                provider_name=str(getattr(self._config, "data_source", "") or ""),
                verify=True,
            )
        except Exception:
            logger.exception(
                "历史行情补齐被阻断: frozen market-daily receipt is invalid, "
                "trade_date=%s",
                trade_date,
            )
            return None
        return receipt is None

    def _publish_post_close_stock_quotes(
        self,
        *,
        data_store: Any,
        trade_date: date,
        calendar_evidence_refs: tuple[str, ...],
        captured_at: datetime,
    ) -> str | None:
        """Promote one complete exact-date stock close batch into current facts."""

        if self._db is None:
            logger.error("收盘行情发布失败: scheduler database is unavailable")
            return None
        with self._lock:
            watchlist = list(self._watchlist)
        try:
            result = publish_post_close_stock_quotes(
                self._db,
                data_store,
                watchlist,
                provider_name=str(getattr(self._config, "data_source", "") or ""),
                trade_date=trade_date,
                calendar_evidence_refs=calendar_evidence_refs,
                captured_at=captured_at,
            )
        except Exception:
            logger.exception(
                "收盘行情发布检查失败，将重试: date=%s",
                trade_date,
            )
            return None
        if not result.published:
            logger.warning(
                "收盘行情尚未满足原子发布条件: date=%s, missing=%s, error=%s",
                trade_date,
                ",".join(result.missing_symbols) or "none",
                result.error_message or "unknown",
            )
            return None
        try:
            persisted_quotes = self._db.get_latest_quotes_sync()
            self.replace_runtime_quotes(
                runtime_quotes_from_persisted(
                    persisted_quotes,
                    self.instruments,
                )
            )
        except Exception:
            logger.exception(
                "收盘行情已发布但运行时缓存恢复失败，将重试: run_id=%s",
                result.run_id,
            )
            return None
        logger.info(
            "收盘行情原子发布完成: date=%s, symbols=%d, run_id=%s, replayed=%s",
            trade_date,
            len(result.symbols),
            result.run_id or "not_required",
            result.replayed,
        )
        return result.receipt_fingerprint or "no_stock_scope"

    @staticmethod
    def _is_post_close_valuation_refresh_window(now: datetime) -> bool:
        """Return whether provider-free close reconciliation should run."""
        now = get_shanghai_now(now)
        return bool(
            now.weekday() >= 5
            or now.time() >= _AFTERNOON_CLOSE
            or now.time() < _MORNING_OPEN
        )

    def _should_refresh_post_close_market_data(
        self,
        now: datetime,
        *,
        provider_name: str,
        target_trade_date: str,
        refresh_identity: str,
    ) -> bool:
        if (
            target_trade_date == now.date().isoformat()
            and now.time() < _POST_CLOSE_MARKET_REFRESH_TIME
        ):
            return False
        completed_prefix = f"{provider_name}:{target_trade_date}:{refresh_identity}:"
        if str(self._last_post_close_market_refresh_key or "").startswith(
            completed_prefix
        ):
            return False
        last_attempt = self._last_post_close_market_refresh_attempt_at
        return not (
            last_attempt is not None
            and now - last_attempt < _POST_CLOSE_MARKET_RETRY_INTERVAL
        )

    def _post_close_market_refresh_identity(
        self,
        *,
        calendar_evidence_refs: tuple[str, ...],
    ) -> str:
        with self._lock:
            stock_symbols = sorted(
                str(symbol)
                for symbol, asset_class in self._watchlist
                if asset_class is AssetClass.STOCK
            )
        payload = json.dumps(
            {
                "calendar_evidence_refs": list(calendar_evidence_refs),
                "stock_symbols": stock_symbols,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _should_refresh_post_close_fund_nav_data(
        self,
        now: datetime,
        *,
        target_trade_date: str,
    ) -> bool:
        today = now.date().isoformat()
        if target_trade_date > today:
            return False
        if (
            target_trade_date == today
            and now.time() < _POST_CLOSE_FUND_NAV_REFRESH_TIME
        ):
            return False
        if self._last_post_close_fund_nav_refresh_date == target_trade_date:
            return False
        last_attempt = self._last_post_close_fund_nav_refresh_attempt_at
        return not (
            last_attempt is not None
            and now - last_attempt < _POST_CLOSE_FUND_NAV_RETRY_INTERVAL
        )

    def _maybe_refresh_post_close_valuation_data(
        self,
        data_manager: Any,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Refresh close-driven valuation inputs after verified market closes."""
        current = get_shanghai_now(now)
        refreshed = False
        resolved = (
            resolve_latest_verified_closed_trading_date(self._db, current)
            if self._db is not None
            else None
        )
        if resolved is None:
            return False
        target_trade_date = resolved.trade_date
        provider_name = str(getattr(self._config, "data_source", "") or "")
        market_refresh_identity = self._post_close_market_refresh_identity(
            calendar_evidence_refs=resolved.calendar_evidence_refs,
        )

        if self._should_refresh_post_close_market_data(
            current,
            provider_name=provider_name,
            target_trade_date=target_trade_date,
            refresh_identity=market_refresh_identity,
        ):
            self._last_post_close_market_refresh_attempt_at = current
            data_store = getattr(data_manager, "store", None)
            receipt_fingerprint = (
                self._publish_post_close_stock_quotes(
                    data_store=data_store,
                    trade_date=date.fromisoformat(target_trade_date),
                    calendar_evidence_refs=resolved.calendar_evidence_refs,
                    captured_at=current,
                )
                if data_store is not None
                else None
            )
            if receipt_fingerprint is not None:
                self._last_post_close_market_refresh_key = (
                    f"{provider_name}:{target_trade_date}:"
                    f"{market_refresh_identity}:{receipt_fingerprint}"
                )
                logger.info(
                    "收盘后行情对账完成: trade_date=%s, scheduled_time=%s",
                    target_trade_date,
                    _POST_CLOSE_MARKET_REFRESH_TIME.isoformat(timespec="minutes"),
                )
                refreshed = True
            elif data_store is None:
                logger.warning(
                    "收盘行情对账等待重试: verified market data store unavailable"
                )

        if self._should_refresh_post_close_fund_nav_data(
            current,
            target_trade_date=target_trade_date,
        ):
            self._last_post_close_fund_nav_refresh_attempt_at = current
            if self._sync_fund_nav_quotes(
                confirmation_only=True,
                captured_at=current,
                target_date=target_trade_date,
            ):
                self._last_post_close_fund_nav_refresh_date = target_trade_date
                logger.info(
                    "收盘后基金净值确认刷新完成: date=%s, scheduled_time=%s",
                    target_trade_date,
                    _POST_CLOSE_FUND_NAV_REFRESH_TIME.isoformat(timespec="minutes"),
                )
                refreshed = True

        return refreshed

    def _sync_fund_nav_quotes(
        self,
        *,
        confirmation_only: bool = False,
        captured_at: datetime | None = None,
        target_date: str | None = None,
    ) -> bool:
        """Refresh fund NAV/estimate quotes independently from stock polling."""
        if self._db is None:
            return False
        with self._lock:
            watchlist = list(self._watchlist)
            instruments = dict(self._instruments)
            latest_quotes = dict(self._latest_quotes)
        fund_watchlist: list[tuple[Any, InstrumentType]] = []
        for symbol, asset_class in watchlist:
            if asset_class is not AssetClass.FUND:
                continue
            instrument_type = getattr(instruments.get(symbol), "instrument_type", None)
            if not isinstance(instrument_type, InstrumentType):
                logger.error(
                    "基金净值同步被阻断: canonical instrument type missing: %s",
                    symbol,
                )
                return False
            if instrument_type is InstrumentType.OPEN_END_FUND:
                fund_watchlist.append((symbol, instrument_type))
        fund_symbols = [str(symbol) for symbol, _ in fund_watchlist]
        if not fund_symbols:
            return True

        try:
            refresh_kwargs = (
                {
                    "confirmation_only": True,
                    "now": get_shanghai_now(captured_at),
                    "target_date": target_date,
                }
                if confirmation_only
                else {}
            )
            result = refresh_fund_nav_quotes(
                self._config,
                self._db,
                fund_watchlist,
                latest_quotes,
                **refresh_kwargs,
            )
        except Exception:
            logger.warning("基金净值/估值同步失败，将保留已有快照", exc_info=True)
            return False

        if result.quotes:
            with self._lock:
                self._latest_quotes.update(result.quotes)
        if not confirmation_only:
            return "__publication__" not in result.failed

        confirmation_target_date = (
            target_date or get_shanghai_now(captured_at).date().isoformat()
        )
        try:
            completed = all(
                is_confirmed_fund_nav_quote(
                    self._db.get_latest_quote_sync(
                        symbol,
                        asset_type=InstrumentType.OPEN_END_FUND.value,
                    ),
                    target_date=confirmation_target_date,
                )
                for symbol in fund_symbols
            )
        except Exception:
            logger.warning("基金确认净值持久化验收失败，将重试", exc_info=True)
            return False
        if not completed:
            logger.warning(
                "基金确认净值尚未完整发布，将重试: target_date=%s",
                confirmation_target_date,
            )
            return False
        try:
            persisted_quotes = self._db.get_latest_quotes_sync()
            self.replace_runtime_quotes(
                runtime_quotes_from_persisted(
                    persisted_quotes,
                    self.instruments,
                )
            )
        except Exception:
            logger.warning("基金确认净值运行时缓存恢复失败，将重试", exc_info=True)
            return False
        return True


__all__ = ["SchedulerPostCloseMixin"]
