"""Audited decision-window quote refresh for selected stock signals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from core.types import AssetClass
from server.ai_runtime.contracts import content_fingerprint

DAILY_CANDIDATE_QUOTE_FREEZE_SCHEMA_VERSION = "karkinos.daily_candidate_quote_freeze.v1"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
QuoteRefresher = Callable[..., Awaitable[Any]]


class DailyCandidateQuoteFreezeService:
    """Refresh only selected buy symbols and persist an exact fetch-run audit."""

    def __init__(
        self,
        *,
        db: Any,
        state: Any,
        quote_refresher: QuoteRefresher,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._state = state
        self._quote_refresher = quote_refresher
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def run_once(self, prepared_scan: Mapping[str, Any]) -> dict[str, Any]:
        decision_date = str(prepared_scan.get("decision_date") or "")
        symbols = sorted(
            {
                str(signal.get("symbol") or "")
                for signal in prepared_scan.get("selected_signals") or []
                if isinstance(signal, Mapping)
                and signal.get("direction") == "buy"
                and str(signal.get("symbol") or "")
            }
        )
        base = {
            "schema_version": DAILY_CANDIDATE_QUOTE_FREEZE_SCHEMA_VERSION,
            "decision_date": decision_date,
            "prepared_scan_input_fingerprint": prepared_scan.get("input_fingerprint"),
            "signal_selection_fingerprint": prepared_scan.get(
                "signal_selection_fingerprint"
            ),
            "symbols": symbols,
            "provider_contact_performed": False,
            "creates_oms_order": False,
            "submits_broker_order": False,
            "mutates_account_ledger": False,
            "changes_capital_authority": False,
        }
        if prepared_scan.get("status") == "blocked":
            return {
                **base,
                "status": "not_run",
                "blockers": ["prepared_strategy_scan_blocked"],
                "quote_results": [],
            }
        if not symbols:
            return {
                **base,
                "status": "not_required",
                "blockers": [],
                "quote_results": [],
            }

        run_fingerprint = content_fingerprint(base)
        run_id = f"daily_candidate_quote_freeze:{decision_date}:{run_fingerprint[:16]}"
        existing = self._db.get_quote_fetch_run(run_id)
        if existing is not None and str(existing.get("status") or "") == "success":
            verification = self._verify_persisted_quotes(
                symbols=symbols,
                decision_date=decision_date,
                expected_run_id=run_id,
            )
            if not verification["blockers"]:
                return {
                    **base,
                    "run_id": run_id,
                    "status": "complete",
                    "blockers": [],
                    "quote_results": verification["quote_results"],
                    "reused": True,
                }

        started_at = self._clock().isoformat()
        if existing is None:
            runtime_config = getattr(self._state, "config", None)
            self._db.create_quote_fetch_run(
                run_id=run_id,
                started_at=started_at,
                trigger="daily_candidate_signal_quote_freeze",
                provider=str(getattr(runtime_config, "data_source", "") or ""),
                asset_type=AssetClass.STOCK.value,
                symbol_count=len(symbols),
                status="running",
                metadata={
                    **base,
                    "run_id": run_id,
                    "requested_symbols": symbols,
                    "instrument_types": ["stock"] * len(symbols),
                },
            )

        raw_results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                raw = await self._quote_refresher(
                    self._state,
                    symbol,
                    AssetClass.STOCK,
                    fetch_run_id=run_id,
                )
                raw_results.append(_result_dict(raw, symbol=symbol))
            except Exception as exc:
                raw_results.append(
                    {
                        "symbol": symbol,
                        "status": "failed",
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                )

        failed_symbols = sorted(
            {
                str(item.get("symbol") or "")
                for item in raw_results
                if item.get("status") != "refreshed"
            }
        )
        blockers = _refresh_result_blockers(
            raw_results=raw_results,
            decision_date=decision_date,
        )
        blockers = list(dict.fromkeys(blockers))
        status = "success" if not blockers else "failed"
        finished_at = self._clock().isoformat()
        finished = self._db.finish_quote_fetch_run(
            run_id=run_id,
            finished_at=finished_at,
            status=status,
            success_count=len(symbols) - len(failed_symbols),
            failure_count=len(failed_symbols),
            cache_hit_count=0,
            error_message=None if not blockers else ";".join(blockers),
            metadata={
                **base,
                "run_id": run_id,
                "raw_results": raw_results,
                "prepublication_blockers": blockers,
            },
        )
        if not isinstance(finished, Mapping) or finished.get("status") != "success":
            blockers.append("selected_quote_fetch_run_not_successful")
        verification = self._verify_persisted_quotes(
            symbols=symbols,
            decision_date=decision_date,
            expected_run_id=run_id,
        )
        blockers.extend(verification["blockers"])
        blockers = list(dict.fromkeys(blockers))
        return {
            **base,
            "run_id": run_id,
            "status": "complete" if not blockers else "blocked",
            "blockers": blockers,
            "quote_results": verification["quote_results"],
            "provider_contact_performed": True,
            "reused": False,
        }

    def _verify_persisted_quotes(
        self,
        *,
        symbols: list[str],
        decision_date: str,
        expected_run_id: str,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        quote_results: list[dict[str, Any]] = []
        for symbol in symbols:
            row = self._db.get_latest_quote_sync(symbol, AssetClass.STOCK.value)
            if not isinstance(row, Mapping):
                blockers.append(f"selected_quote_missing:{symbol}")
                continue
            timestamp = _quote_timestamp(row)
            status = str(row.get("quote_status") or "")
            if timestamp is None or timestamp.date().isoformat() != decision_date:
                blockers.append(f"selected_quote_date_mismatch:{symbol}")
            if status not in {"live", "confirmed"}:
                blockers.append(f"selected_quote_not_trusted:{symbol}")
            if str(row.get("fetch_run_id") or "") != expected_run_id:
                blockers.append(f"selected_quote_run_mismatch:{symbol}")
            quote_results.append(
                {
                    "symbol": symbol,
                    "quote_timestamp": (
                        None if timestamp is None else timestamp.isoformat()
                    ),
                    "quote_status": status,
                    "provider_name": row.get("provider_name"),
                    "fetch_run_id": row.get("fetch_run_id"),
                }
            )
        return {
            "blockers": list(dict.fromkeys(blockers)),
            "quote_results": quote_results,
        }


def _result_dict(value: Any, *, symbol: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return dict(dumper())
    return {"symbol": symbol, "status": "failed", "error": "invalid_result"}


def _refresh_result_blockers(
    *,
    raw_results: list[dict[str, Any]],
    decision_date: str,
) -> list[str]:
    blockers: list[str] = []
    for item in raw_results:
        symbol = str(item.get("symbol") or "")
        if item.get("status") != "refreshed":
            blockers.append(f"selected_quote_refresh_failed:{symbol}")
            continue
        timestamp = _quote_timestamp(item)
        if timestamp is None or timestamp.date().isoformat() != decision_date:
            blockers.append(f"selected_quote_date_mismatch:{symbol}")
    return list(dict.fromkeys(blockers))


def _quote_timestamp(row: Mapping[str, Any]) -> datetime | None:
    value = str(row.get("quote_timestamp") or row.get("timestamp") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ)
