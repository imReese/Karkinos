"""Post-close reconciliation behavior for :class:`TradingScheduler`."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.source_policy import MarketDataUseCase
from data.source_routing import (
    configured_data_provider_names,
    preferred_legacy_provider,
)
from server.scheduler.quote_restore import runtime_quotes_from_persisted
from server.services.market.calendar import (
    resolve_latest_verified_closed_trading_date,
)
from server.services.market.fund_nav import (
    is_confirmed_fund_nav_quote,
    refresh_fund_nav_quotes,
)
from server.services.market.hours import get_shanghai_now
from server.services.market.post_close import publish_post_close_stock_quotes

logger = logging.getLogger(__name__)

_MORNING_OPEN = time(9, 30)
_AFTERNOON_CLOSE = time(15, 0)
_POST_CLOSE_MARKET_REFRESH_TIME = time(16, 0)
_POST_CLOSE_FUND_NAV_REFRESH_TIME = time(21, 30)
_POST_CLOSE_MARKET_RETRY_INTERVAL = timedelta(minutes=5)
_POST_CLOSE_FUND_NAV_RETRY_INTERVAL = timedelta(minutes=15)


class SchedulerPostCloseMixin:
    """Reconcile verified stock closes and canonical fund NAV facts."""

    def _candidate_daily_providers(
        self,
        preferred_provider: str | None = None,
    ) -> tuple[str, ...]:
        """Return candidate providers in priority order for daily market bars."""
        ordered: list[str] = []
        if preferred_provider:
            ordered.append(preferred_provider)
        for name in configured_data_provider_names(
            self._config,
            MarketDataUseCase.DAILY_BARS,
        ):
            if name not in ordered:
                ordered.append(name)
        if not ordered:
            for fallback in ("akshare_tencent", "akshare", "tushare"):
                if fallback not in ordered:
                    ordered.append(fallback)
        return tuple(ordered)

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
        candidates = self._candidate_daily_providers()
        for candidate in candidates:
            try:
                receipt = receipt_reader(
                    trade_date=trade_date,
                    provider_name=candidate,
                    verify=True,
                )
            except Exception:
                logger.exception(
                    "历史行情补齐被阻断: frozen market-daily receipt is invalid, "
                    "trade_date=%s, provider=%s",
                    trade_date,
                    candidate,
                )
                return None
            if receipt is not None:
                return False
        return True

    def _ensure_post_close_market_daily_receipt(
        self,
        data_manager: Any,
        *,
        provider_name: str | None = None,
        target_trade_date: str,
        candidate_providers: tuple[str, ...] | None = None,
    ) -> str | None:
        """Recover a missing exact-date daily receipt using provider failover.

        Existing receipts remain immutable and are never replaced here. This
        recovery path checks existing receipts across candidate providers first,
        then attempts whole-market daily batch recovery, and finally falls back
        to a scoped daily receipt for watchlist stocks via individual bar fetches.
        Returns the effective provider name whose receipt was verified, or None.
        """

        data_store = getattr(data_manager, "store", None)
        if data_store is None:
            return None
        receipt_reader = getattr(data_store, "get_market_daily_ingestion_receipt", None)
        receipt_writer = getattr(data_store, "ingest_market_daily_batch", None)
        scoped_writer = getattr(data_store, "ingest_scoped_market_daily_batch", None)
        if not callable(receipt_reader) or (
            not callable(receipt_writer) and not callable(scoped_writer)
        ):
            return None

        candidates = candidate_providers or self._candidate_daily_providers(
            provider_name
        )
        if not candidates and provider_name:
            candidates = (provider_name,)

        with self._lock:
            stock_symbols = [
                str(symbol)
                for symbol, asset_class in self._watchlist
                if asset_class is AssetClass.STOCK
            ]

        # Stage 1: Check existing verified receipts across candidates
        for candidate in candidates:
            try:
                try:
                    existing = receipt_reader(
                        trade_date=target_trade_date,
                        provider_name=candidate,
                        symbols=stock_symbols if stock_symbols else None,
                        verify=True,
                    )
                except TypeError:
                    existing = receipt_reader(
                        trade_date=target_trade_date,
                        provider_name=candidate,
                        verify=True,
                    )
            except Exception:
                logger.exception(
                    "收盘行情凭证校验失败，跳过已有凭证: date=%s provider=%s",
                    target_trade_date,
                    candidate,
                )
                continue
            if existing is not None:
                receipt_symbols = {str(s) for s in existing.get("symbols", [])}
                if not stock_symbols or all(
                    s in receipt_symbols for s in stock_symbols
                ):
                    return candidate

        # Stage 2: Whole-market batch recovery across candidates
        sources = getattr(data_manager, "sources", None)
        for candidate in candidates:
            source = sources.get(candidate) if isinstance(sources, dict) else None
            batch_fetcher = getattr(source, "fetch_market_daily_bars", None)
            if not callable(batch_fetcher):
                continue
            try:
                frame = batch_fetcher(target_trade_date)
                if frame is None or getattr(frame, "empty", True):
                    logger.warning(
                        "收盘行情全市场日批次恢复为空，尝试下一个候选数据源: date=%s provider=%s",
                        target_trade_date,
                        candidate,
                    )
                    continue
                receipt_writer(
                    trade_date=target_trade_date,
                    provider_name=candidate,
                    bars=frame,
                )
                verified = receipt_reader(
                    trade_date=target_trade_date,
                    provider_name=candidate,
                    verify=True,
                )
                if verified is not None:
                    receipt_symbols = {str(s) for s in verified.get("symbols", [])}
                    if not stock_symbols or all(
                        s in receipt_symbols for s in stock_symbols
                    ):
                        logger.info(
                            "收盘行情全市场日批次凭证自动恢复完成: date=%s provider=%s rows=%s",
                            target_trade_date,
                            candidate,
                            verified.get("row_count", "unknown"),
                        )
                        return candidate
            except Exception:
                logger.exception(
                    "收盘行情全市场日批次恢复异常，尝试下一个候选数据源: date=%s provider=%s",
                    target_trade_date,
                    candidate,
                )
                continue

        # Stage 3: Scoped fallback for watchlist stocks
        if not stock_symbols:
            logger.warning(
                "收盘行情日批次凭证缺失，且当前无股票关注列表无需作用域恢复: date=%s",
                target_trade_date,
            )
            return None

        start_dt = datetime.combine(
            date.fromisoformat(target_trade_date), time(0, 0, 0)
        )
        end_dt = datetime.combine(
            date.fromisoformat(target_trade_date), time(23, 59, 59)
        )
        target_date_obj = date.fromisoformat(target_trade_date)

        for candidate in candidates:
            source = sources.get(candidate) if isinstance(sources, dict) else None
            bar_fetcher = getattr(source, "fetch_bars", None)
            if not callable(bar_fetcher):
                continue
            collected_bars: list[pd.DataFrame] = []
            candidate_failed = False
            for sym_str in stock_symbols:
                try:
                    df = bar_fetcher(
                        Symbol(sym_str),
                        start=start_dt,
                        end=end_dt,
                        frequency=BarFrequency.DAILY,
                        asset_class=AssetClass.STOCK,
                    )
                    if df is None or getattr(df, "empty", True):
                        candidate_failed = True
                        break
                    df = df.copy()
                    if "symbol" not in df.columns:
                        df["symbol"] = sym_str
                    df["_bar_date"] = pd.to_datetime(df["timestamp"]).dt.date
                    df = df[df["_bar_date"] == target_date_obj].drop(
                        columns=["_bar_date"]
                    )
                    if df.empty:
                        candidate_failed = True
                        break
                    if len(df) > 1:
                        df = df.iloc[[-1]]
                    collected_bars.append(df)
                except Exception:
                    logger.warning(
                        "收盘行情单标的补齐失败: date=%s provider=%s symbol=%s",
                        target_trade_date,
                        candidate,
                        sym_str,
                        exc_info=True,
                    )
                    candidate_failed = True
                    break
            if candidate_failed or not collected_bars:
                continue

            try:
                combined = pd.concat(collected_bars, ignore_index=True)
                if callable(scoped_writer):
                    scoped_writer(
                        trade_date=target_trade_date,
                        provider_name=candidate,
                        bars=combined,
                        symbols=stock_symbols,
                    )
                else:
                    receipt_writer(
                        trade_date=target_trade_date,
                        provider_name=candidate,
                        bars=combined,
                    )
                try:
                    verified = receipt_reader(
                        trade_date=target_trade_date,
                        provider_name=candidate,
                        symbols=stock_symbols if stock_symbols else None,
                        verify=True,
                    )
                except TypeError:
                    verified = receipt_reader(
                        trade_date=target_trade_date,
                        provider_name=candidate,
                        verify=True,
                    )
                if verified is not None:
                    logger.info(
                        "收盘行情针对持仓标的的作用域凭证恢复完成: date=%s provider=%s symbols=%s",
                        target_trade_date,
                        candidate,
                        stock_symbols,
                    )
                    return candidate
            except Exception:
                logger.exception(
                    "收盘行情作用域凭证写入失败，尝试下一个候选数据源: date=%s provider=%s",
                    target_trade_date,
                    candidate,
                )
                continue

        logger.warning(
            "收盘行情凭证恢复在所有候选数据源上均失败: date=%s candidates=%s",
            target_trade_date,
            candidates,
        )
        return None

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
        hinted_provider = getattr(self, "_effective_post_close_provider", None)
        candidates = self._candidate_daily_providers(hinted_provider)
        result = None
        for candidate in candidates:
            try:
                result = publish_post_close_stock_quotes(
                    self._db,
                    data_store,
                    watchlist,
                    provider_name=candidate,
                    trade_date=trade_date,
                    calendar_evidence_refs=calendar_evidence_refs,
                    captured_at=captured_at,
                )
                if result.published:
                    self._effective_post_close_provider = candidate
                    break
            except Exception:
                logger.exception(
                    "收盘行情发布检查失败: date=%s candidate=%s",
                    trade_date,
                    candidate,
                )
                continue
        if result is None or not result.published:
            missing_syms = ",".join(result.missing_symbols) if result else "none"
            err_msg = result.error_message if result else "no_candidate_succeeded"
            logger.warning(
                "收盘行情尚未满足原子发布条件: date=%s, missing=%s, error=%s",
                trade_date,
                missing_syms,
                err_msg,
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
        try:
            from server.services.market.etf_rotation_automation import (
                EtfRotationAutomationService,
            )

            EtfRotationAutomationService().evaluate_rebalance()
        except Exception:
            logger.debug(
                "Automated ETF rotation evaluation skipped or failed",
                exc_info=True,
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
        last_key = str(self._last_post_close_market_refresh_key or "")
        completed_token = f":{target_trade_date}:{refresh_identity}:"
        if completed_token in last_key or last_key.startswith(
            f"{provider_name}:{target_trade_date}:{refresh_identity}:"
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
        provider_name = preferred_legacy_provider(
            self._config,
            MarketDataUseCase.DAILY_BARS,
        )
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
            receipt_ready = self._ensure_post_close_market_daily_receipt(
                data_manager,
                provider_name=provider_name,
                target_trade_date=target_trade_date,
            )
            effective_provider = (
                receipt_ready if isinstance(receipt_ready, str) else provider_name
            )
            self._effective_post_close_provider = effective_provider
            receipt_fingerprint = (
                self._publish_post_close_stock_quotes(
                    data_store=data_store,
                    trade_date=date.fromisoformat(target_trade_date),
                    calendar_evidence_refs=resolved.calendar_evidence_refs,
                    captured_at=current,
                )
                if data_store is not None and receipt_ready
                else None
            )
            if receipt_fingerprint is not None:
                self._last_post_close_market_refresh_key = (
                    f"{effective_provider}:{target_trade_date}:"
                    f"{market_refresh_identity}:{receipt_fingerprint}"
                )
                logger.info(
                    "收盘后行情对账完成: trade_date=%s, scheduled_time=%s, provider=%s",
                    target_trade_date,
                    _POST_CLOSE_MARKET_REFRESH_TIME.isoformat(timespec="minutes"),
                    effective_provider,
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


__all__ = [
    "SchedulerPostCloseMixin",
    "is_confirmed_fund_nav_quote",
    "refresh_fund_nav_quotes",
]
