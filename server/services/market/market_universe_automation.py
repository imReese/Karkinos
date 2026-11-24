"""Audited after-close ingestion for the full A-share research universe."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta, timezone
from time import sleep as default_sleep
from typing import Any, Callable

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.manager import build_sources_for_config
from data.source_policy import MarketDataUseCase
from data.source_routing import configured_legacy_provider_names
from data.storage.objects import ContentAddressedObjectStore
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.bootstrap import resolve_data_dir
from server.release_activation import wait_for_release_activation
from server.services.market.calendar import (
    latest_verified_closed_trading_date,
    validate_verified_market_calendar,
)
from server.services.market.history import history_session_symbols
from server.services.market.hours import get_shanghai_now
from server.services.market.market_universe_truth import (
    MarketUniversePolicy,
    market_universe_observation,
    normalize_a_share_members,
    require_complete_market_universe_snapshot,
)

logger = logging.getLogger(__name__)

MARKET_UNIVERSE_AUTOMATION_SCHEMA_PREFIX = "karkinos.market_universe_automation."
MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION = "karkinos.market_universe_automation.v7"
MARKET_UNIVERSE_AUTOMATION_RUN_TYPE = "market_universe_sync"
MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS = 60 * 60
MARKET_UNIVERSE_COVERAGE_POLICY_ID = (
    "karkinos.market_universe_coverage.strict_per_symbol.v1"
)


def check_receipts_session_coverage(
    *,
    trading_dates: Sequence[str],
    receipts: Sequence[Mapping[str, Any]],
    members: Sequence[str] | None = None,
    member_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    """Verify that receipts exist for every required trading date and cover all listed symbols."""
    if not trading_dates or not receipts:
        return False
    receipt_by_date = {str(r.get("trade_date")): r for r in receipts}
    member_symbols = [str(m) for m in members or []]
    metadata = member_metadata or []
    for session in trading_dates:
        receipt = receipt_by_date.get(session)
        if receipt is None:
            return False
        row_count = int(receipt.get("row_count") or 0)
        if row_count <= 0:
            return False
        if member_symbols:
            expected = history_session_symbols(member_symbols, metadata, session)
            receipt_symbols = set(receipt.get("symbols") or [])
            if receipt_symbols and expected and not expected.issubset(receipt_symbols):
                return False
            elif expected and row_count < len(expected):
                return False
    return True


def compute_market_coverage_evidence_fingerprint(
    *,
    snapshot_id: str | None,
    trading_dates: Sequence[str],
    receipts: Sequence[Mapping[str, Any]],
    members: Sequence[str] | None = None,
    member_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> str | None:
    """Deterministic content fingerprint binding master snapshot and daily bar receipts.

    Returns None if snapshot_id is absent, trading_dates is empty, or receipts
    do not completely cover all required trading dates and listing-aware symbols.
    """
    if not snapshot_id or not trading_dates:
        return None
    if not check_receipts_session_coverage(
        trading_dates=trading_dates,
        receipts=receipts,
        members=members,
        member_metadata=member_metadata,
    ):
        return None

    from server.ai_runtime.contracts import content_fingerprint

    receipt_cores = [
        {
            "trade_date": str(r.get("trade_date")),
            "provider_name": str(r.get("provider_name")),
            "row_count": int(r.get("row_count") or 0),
            "dataset_fingerprint": str(r.get("dataset_fingerprint") or ""),
            "receipt_fingerprint": str(r.get("receipt_fingerprint") or ""),
        }
        for r in receipts
        if str(r.get("trade_date")) in trading_dates
    ]
    return content_fingerprint(
        {
            "policy_id": MARKET_UNIVERSE_COVERAGE_POLICY_ID,
            "snapshot_id": snapshot_id,
            "trading_dates": sorted(trading_dates),
            "receipts": receipt_cores,
        }
    )


def is_qualified_market_universe_coverage_run(
    existing: Mapping[str, Any],
    *,
    expected_snapshot_id: str | None,
    expected_fingerprint: str | None,
    expected_policy_id: str | None = None,
    expected_policy_fingerprint: str | None = None,
) -> bool:
    """Validate whether an existing completed run meets strict coverage qualifications.

    Avoids blindly trusting status == 'completed' without verifying the underlying
    validation policy identity, evidence completeness, and content fingerprint.
    Both current verified snapshot identity and evidence fingerprint are strictly
    required to be non-empty; if current evidence is absent, completion cannot be reused.
    Returns False on malformed payloads, unparseable JSON, or invalid count types.
    """
    if str(existing.get("status") or "") != "completed":
        return False
    if not expected_snapshot_id or not expected_fingerprint:
        return False
    if not expected_policy_id or not expected_policy_fingerprint:
        return False
    try:
        payload = json.loads(str(existing.get("payload_json") or "{}"))
    except Exception:
        return False
    if not isinstance(payload, Mapping):
        return False

    def _strict_non_negative_int(val: Any) -> int | None:
        if isinstance(val, bool):
            return None
        if isinstance(val, int):
            return val if val >= 0 else None
        if isinstance(val, str) and val.strip().isdigit():
            try:
                parsed = int(val.strip())
                return parsed if parsed >= 0 else None
            except ValueError:
                return None
        return None

    # 1. Validation policy identity & policy fingerprint
    # Reject missing or malformed aliases: every present alias must strictly match expected_policy_id
    has_primary_policy = "validation_policy_id" in payload
    has_alias_policy = "coverage_validation_policy_id" in payload
    if not (has_primary_policy or has_alias_policy):
        return False
    if has_primary_policy and payload["validation_policy_id"] != expected_policy_id:
        return False
    if (
        has_alias_policy
        and payload["coverage_validation_policy_id"] != expected_policy_id
    ):
        return False
    if payload.get("policy_fingerprint") != expected_policy_fingerprint:
        return False

    # 2. Evidence completeness: strict list types, no blockers, frozen is True
    if payload.get("full_market_history_frozen") is not True:
        return False

    blockers = payload.get("blockers")
    if not isinstance(blockers, list) or len(blockers) != 0:
        return False

    partial_dates = payload.get("full_market_partial_receipt_dates")
    if not isinstance(partial_dates, list) or len(partial_dates) != 0:
        return False

    missing_dates = payload.get("full_market_missing_receipt_dates")
    if not isinstance(missing_dates, list) or len(missing_dates) != 0:
        return False

    uncovered_count = _strict_non_negative_int(
        payload.get("full_market_uncovered_symbol_session_count")
    )
    if uncovered_count is None or uncovered_count != 0:
        return False

    missing_date_count = _strict_non_negative_int(
        payload.get("full_market_missing_receipt_date_count")
    )
    if missing_date_count is None or missing_date_count != 0:
        return False

    if "full_market_partial_receipt_date_count" in payload:
        partial_date_count = _strict_non_negative_int(
            payload.get("full_market_partial_receipt_date_count")
        )
        if partial_date_count is None or partial_date_count != 0:
            return False

    daily_receipt_count = _strict_non_negative_int(
        payload.get("full_market_daily_receipt_count")
    )
    if daily_receipt_count is None or daily_receipt_count <= 0:
        return False

    # 3. Content identity & fingerprint: master snapshot and daily receipt evidence must match
    if payload.get("market_universe_snapshot_id") != expected_snapshot_id:
        return False

    # Reject missing or malformed evidence fingerprint aliases
    has_primary_fp = "evidence_fingerprint" in payload
    has_alias_fp = "coverage_evidence_fingerprint" in payload
    if not (has_primary_fp or has_alias_fp):
        return False
    if has_primary_fp and payload["evidence_fingerprint"] != expected_fingerprint:
        return False
    if (
        has_alias_fp
        and payload["coverage_evidence_fingerprint"] != expected_fingerprint
    ):
        return False
    return True


def find_prior_market_universe_run(
    db: Any,
    *,
    task_key: str,
    trade_date: str,
    master_provider_name: str,
    daily_provider_name: str,
    run_date: str | None = None,
) -> dict[str, Any] | None:
    """Locate the most recent prior run for this task key, paging history if necessary."""
    legacy_candidate_ids = (
        task_key,
        f"market_universe_sync:v7:{master_provider_name}:{daily_provider_name}:{trade_date}",
        f"market_universe_sync:v8:{master_provider_name}:{daily_provider_name}:{trade_date}",
    )
    lister = getattr(db, "list_automation_runs_sync", None)
    if callable(lister):
        offset = 0
        limit = 100
        while True:
            try:
                page = lister(
                    run_type=MARKET_UNIVERSE_AUTOMATION_RUN_TYPE,
                    limit=limit,
                    offset=offset,
                )
            except Exception:
                break
            if not page:
                break
            for cand in page:
                try:
                    payload = json.loads(str(cand.get("payload_json") or "{}"))
                except Exception:
                    continue
                if not isinstance(payload, Mapping):
                    continue
                cand_task_key = payload.get("task_key")
                if cand_task_key:
                    if cand_task_key == task_key:
                        return cand
                    continue
                # Only evaluate legacy fallback on keyless historical rows
                if cand.get("run_id") in legacy_candidate_ids:
                    return cand
                if (
                    payload.get("trade_date") == trade_date
                    and payload.get("security_master_provider") == master_provider_name
                    and payload.get("daily_bar_provider") == daily_provider_name
                ):
                    return cand
            if len(page) < limit:
                break
            offset += limit

    getter = getattr(db, "get_automation_run_sync", None)
    if callable(getter):
        for candidate_id in legacy_candidate_ids:
            try:
                prior = getter(candidate_id)
                if prior is not None:
                    try:
                        p = json.loads(str(prior.get("payload_json") or "{}"))
                    except Exception:
                        continue
                    if not isinstance(p, Mapping):
                        continue
                    if p.get("task_key") and p.get("task_key") != task_key:
                        continue
                    return prior
            except Exception:
                pass
    return None


def validate_market_universe_automation_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate that an automation run payload conforms to the market universe contract."""
    if not isinstance(payload, Mapping):
        raise ValueError("market_universe_automation_payload_missing")
    schema = payload.get("schema_version")
    if not schema or not str(schema).startswith(
        MARKET_UNIVERSE_AUTOMATION_SCHEMA_PREFIX
    ):
        raise ValueError(f"market_universe_automation_schema_invalid: {schema}")
    for required in (
        "trigger",
        "security_master_provider",
        "daily_bar_provider",
        "policy",
        "asset_scope",
    ):
        if required not in payload:
            raise ValueError(f"market_universe_automation_payload_missing_{required}")
    return dict(payload)


class MarketUniverseAutomationService:
    """Refresh and freeze the stock master plus full-market bar history."""

    def __init__(
        self,
        *,
        db: Any,
        config: Any,
        data_store: DataStore | None = None,
        source: Any | None = None,
        policy: MarketUniversePolicy | None = None,
        throttle_seconds: float | None = None,
        sleep_fn: Callable[[float], None] = default_sleep,
        capture_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        inserter = getattr(db, "insert_automation_run_if_absent_sync", None)
        if not callable(inserter):
            raise TypeError(
                "market_universe_automation_requires_atomic_run_inserter: "
                "db must implement insert_automation_run_if_absent_sync"
            )
        self._config = config
        self._data_store = data_store or DataStore(resolve_data_dir())
        self._policy = policy or MarketUniversePolicy()
        self._capture_clock = capture_clock or (lambda: datetime.now(timezone.utc))

        if source is not None:
            injected_name = _injected_provider_name(config, source)
            self._security_master_source = source
            self._security_master_provider_name = injected_name
            self._daily_batch_source = (
                source
                if callable(getattr(source, "fetch_market_daily_bars", None))
                else None
            )
            self._daily_bar_provider_name = injected_name
            self._daily_source = source
        else:
            sources = build_sources_for_config(config)

            master_names = configured_legacy_provider_names(
                config,
                MarketDataUseCase.SECURITY_MASTER,
            )
            if not master_names:
                raise RuntimeError("market_universe_security_master_route_unavailable")
            self._security_master_provider_name = master_names[0]
            self._security_master_source = sources[self._security_master_provider_name]

            daily_names = configured_legacy_provider_names(
                config,
                MarketDataUseCase.DAILY_BARS,
            )
            if not daily_names:
                raise RuntimeError("market_universe_daily_bar_route_unavailable")
            batch_name = next(
                (
                    name
                    for name in daily_names
                    if name in sources
                    and callable(
                        getattr(sources[name], "fetch_market_daily_bars", None)
                    )
                ),
                None,
            )
            self._daily_bar_provider_name = batch_name or daily_names[0]
            self._daily_batch_source = (
                sources[batch_name] if batch_name is not None else None
            )
            self._daily_source = sources[self._daily_bar_provider_name]

        self._throttle_seconds = (
            _provider_request_interval_seconds(self._daily_bar_provider_name)
            if throttle_seconds is None
            else float(throttle_seconds)
        )
        if self._throttle_seconds < 0:
            raise ValueError("market_universe_throttle_seconds_invalid")
        self._sleep = sleep_fn

    def run_due(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = get_shanghai_now(now)
        trade_date = latest_verified_closed_trading_date(self._db, current)
        run_date = current.date().isoformat()
        master_provider_name = self._security_master_provider_name
        daily_provider_name = self._daily_bar_provider_name
        if trade_date is None:
            pending_id = f"market_universe_sync:pending:{run_date}"
            getter = getattr(self._db, "get_automation_run_sync", None)
            existing_pending = getter(pending_id) if callable(getter) else None
            if (
                existing_pending is not None
                and str(existing_pending.get("status")) == "blocked"
            ):
                return existing_pending
            return self._record_run(
                run_id=pending_id,
                run_date=run_date,
                status="blocked",
                now=current,
                payload={
                    **self._base_payload(
                        master_provider_name,
                        daily_provider_name,
                    ),
                    "trade_date": None,
                    "blockers": ["verified_closed_trading_date_unavailable"],
                    "retryable": True,
                },
            )
        task_key = (
            f"market_universe_sync:"
            f"{master_provider_name}:{daily_provider_name}:{trade_date}"
        )
        validation_policy_id = MARKET_UNIVERSE_COVERAGE_POLICY_ID
        policy_fingerprint = content_fingerprint(self._policy.to_dict())

        start_date = _history_start(self._config, trade_date)
        trading_dates = verified_trading_dates(
            self._db,
            start_date=start_date.isoformat(),
            end_date=trade_date,
        )

        latest_master = self._data_store.get_market_universe_snapshot(
            trade_date=trade_date, provider_name=master_provider_name
        )
        current_receipts = self._data_store.list_market_daily_ingestion_receipts(
            start_date=start_date.isoformat(),
            end_date=trade_date,
            provider_name=daily_provider_name,
        )

        prior_run = find_prior_market_universe_run(
            self._db,
            task_key=task_key,
            trade_date=trade_date,
            master_provider_name=master_provider_name,
            daily_provider_name=daily_provider_name,
            run_date=run_date,
        )

        master_members = (
            [str(m.get("symbol") or "") for m in latest_master.get("members") or []]
            if latest_master
            else []
        )
        master_metadata = (
            latest_master.get("member_metadata") or [] if latest_master else []
        )
        receipt_dates = {str(item.get("trade_date")) for item in current_receipts}
        has_complete_current_receipts = bool(
            trading_dates and receipt_dates.issuperset(trading_dates)
        )
        evidence_fingerprint = (
            compute_market_coverage_evidence_fingerprint(
                snapshot_id=str(latest_master.get("snapshot_id") or ""),
                trading_dates=trading_dates,
                receipts=current_receipts,
                members=master_members,
                member_metadata=master_metadata,
            )
            if (latest_master and has_complete_current_receipts)
            else None
        )

        if evidence_fingerprint:
            execution_fingerprint = content_fingerprint(
                {
                    "task_key": task_key,
                    "validation_policy_id": validation_policy_id,
                    "policy_fingerprint": policy_fingerprint,
                    "evidence_fingerprint": evidence_fingerprint,
                }
            )
            run_id = f"market_universe_sync:{trade_date}:{execution_fingerprint[:16]}"
        else:
            run_id = f"market_universe_sync:{trade_date}:{task_key}"

        # 1. Exact deterministic execution already recorded and completed
        existing = self._db.get_automation_run_sync(run_id)
        if existing and str(existing.get("status")) == "completed":
            if is_qualified_market_universe_coverage_run(
                existing,
                expected_snapshot_id=str(latest_master.get("snapshot_id") or "")
                if latest_master
                else None,
                expected_fingerprint=evidence_fingerprint,
                expected_policy_id=validation_policy_id,
                expected_policy_fingerprint=policy_fingerprint,
            ):
                return existing

        # 2. Check if a qualified prior run matches current evidence and policy
        if prior_run and str(prior_run.get("status")) == "completed":
            if is_qualified_market_universe_coverage_run(
                prior_run,
                expected_snapshot_id=str(latest_master.get("snapshot_id") or "")
                if latest_master
                else None,
                expected_fingerprint=evidence_fingerprint,
                expected_policy_id=validation_policy_id,
                expected_policy_fingerprint=policy_fingerprint,
            ):
                return prior_run

        # 3. Throttle / backoff check if prior run failed with identical inputs
        if prior_run and str(prior_run.get("status")) == "failed":
            prior_payload = json.loads(str(prior_run.get("payload_json") or "{}"))
            previous_master = prior_payload.get("market_universe_snapshot_id")
            repaired_master = bool(
                latest_master
                and latest_master.get("source_capture_ids")
                and latest_master.get("snapshot_id") != previous_master
            )
            evidence_changed = bool(
                evidence_fingerprint
                and (
                    prior_payload.get("evidence_fingerprint")
                    or prior_payload.get("coverage_evidence_fingerprint")
                )
                != evidence_fingerprint
            )
            within_backoff = False
            raw_finished = prior_run.get("finished_at")
            if raw_finished:
                try:
                    finished = get_shanghai_now(
                        datetime.fromisoformat(str(raw_finished))
                    )
                    if current < finished + timedelta(
                        seconds=MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS
                    ):
                        within_backoff = True
                except Exception:
                    within_backoff = False
            if (
                not repaired_master
                and not evidence_changed
                and (prior_payload.get("retryable") is False or within_backoff)
            ):
                return prior_run

        stock_master_metadata_fetched = False
        stock_master_useful_name_count = 0
        instrument_metadata_persisted_count = 0
        provider_contacted = False
        snapshot: dict[str, Any] | None = None
        try:
            (
                snapshot,
                provider_contacted,
                stock_master_metadata_fetched,
                stock_master_useful_name_count,
                instrument_metadata_persisted_count,
            ) = self._ensure_market_universe_snapshot(
                trade_date=trade_date,
                master_provider_name=master_provider_name,
            )
            snapshot = require_complete_market_universe_snapshot(
                snapshot,
                policy=self._policy,
                expected_trade_date=trade_date,
            )
            members = [str(member["symbol"]) for member in snapshot["members"]]
            start_date = _history_start(self._config, trade_date)
            trading_dates = verified_trading_dates(
                self._db,
                start_date=start_date.isoformat(),
                end_date=trade_date,
            )
            if len(trading_dates) < self._policy.minimum_history_rows:
                raise ValueError("verified_market_history_window_incomplete")

            (
                updated,
                failed,
                remote_attempted,
                receipt_skipped,
            ) = self._refresh_daily_bars(
                daily_provider_name=daily_provider_name,
                trading_dates=trading_dates,
                members=members,
            )

            coverage = self._history_coverage(
                start_date=start_date,
                trade_date=trade_date,
                daily_provider_name=daily_provider_name,
                trading_dates=trading_dates,
                members=members,
                member_metadata=snapshot.get("member_metadata") or [],
                snapshot_id=snapshot.get("snapshot_id"),
            )
            blockers = coverage["blockers"]
            final_evidence_fingerprint = (
                coverage.get("coverage_evidence_fingerprint") or evidence_fingerprint
            )
            status = (
                "completed"
                if (not blockers and final_evidence_fingerprint)
                else "failed"
            )
            if final_evidence_fingerprint:
                execution_fp = content_fingerprint(
                    {
                        "task_key": task_key,
                        "validation_policy_id": validation_policy_id,
                        "policy_fingerprint": policy_fingerprint,
                        "evidence_fingerprint": final_evidence_fingerprint,
                    }
                )
                base_run_id = f"market_universe_sync:{trade_date}:{execution_fp[:16]}"
            else:
                base_run_id = f"market_universe_sync:{trade_date}:{task_key}"

            prior_run_id = (
                str(prior_run.get("run_id") or "")
                if (prior_run and str(prior_run.get("run_id") or "") != base_run_id)
                else None
            )

            return self._record_run(
                run_id=base_run_id,
                run_date=run_date,
                status=status,
                source_ref=prior_run_id,
                now=current,
                payload={
                    **self._base_payload(master_provider_name, daily_provider_name),
                    "task_key": task_key,
                    "validation_policy_id": validation_policy_id,
                    "policy_fingerprint": policy_fingerprint,
                    "evidence_fingerprint": final_evidence_fingerprint,
                    "coverage_validation_policy_id": validation_policy_id,
                    "prior_run_id": prior_run_id,
                    "supersedes_run_id": prior_run_id,
                    "trade_date": trade_date,
                    "market_universe_snapshot_id": snapshot["snapshot_id"],
                    "market_universe_member_count": snapshot["member_count"],
                    "market_universe_observation": market_universe_observation(
                        snapshot
                    ),
                    "verified_history_start_date": start_date.isoformat(),
                    "verified_trading_date_count": len(trading_dates),
                    **coverage,
                    "persisted_receipt_skipped_count": receipt_skipped,
                    "remote_bar_refresh_attempt_count": remote_attempted,
                    "bar_refresh_success_count": updated,
                    "bar_refresh_failure_count": failed,
                    "provider_request_interval_seconds": self._throttle_seconds,
                    "provider_contacted": provider_contacted or remote_attempted > 0,
                    "stock_master_metadata_fetched": stock_master_metadata_fetched,
                    "stock_master_useful_name_count": (stock_master_useful_name_count),
                    "instrument_metadata_persisted_count": (
                        instrument_metadata_persisted_count
                    ),
                },
            )
        except Exception as exc:
            return self._handle_run_due_failure(
                exc=exc,
                current=current,
                run_date=run_date,
                trade_date=trade_date,
                task_key=task_key,
                validation_policy_id=validation_policy_id,
                policy_fingerprint=policy_fingerprint,
                evidence_fingerprint=evidence_fingerprint,
                prior_run=prior_run,
                master_provider_name=master_provider_name,
                daily_provider_name=daily_provider_name,
                snapshot=snapshot,
                stock_master_metadata_fetched=stock_master_metadata_fetched,
                stock_master_useful_name_count=stock_master_useful_name_count,
                instrument_metadata_persisted_count=instrument_metadata_persisted_count,
            )

    def _handle_run_due_failure(
        self,
        *,
        exc: Exception,
        current: datetime,
        run_date: str,
        trade_date: str,
        task_key: str,
        validation_policy_id: str,
        policy_fingerprint: str,
        evidence_fingerprint: str | None,
        prior_run: dict[str, Any] | None,
        master_provider_name: str,
        daily_provider_name: str,
        snapshot: dict[str, Any] | None,
        stock_master_metadata_fetched: bool,
        stock_master_useful_name_count: int,
        instrument_metadata_persisted_count: int,
    ) -> dict[str, Any]:
        logger.warning("Market-universe automation failed closed", exc_info=True)
        prior_run_id = str(prior_run.get("run_id") or "") if prior_run else None
        fail_evidence_fp = evidence_fingerprint or content_fingerprint(
            {"error": type(exc).__name__, "message": str(exc), "task_key": task_key}
        )
        fail_exec_fp = content_fingerprint(
            {
                "task_key": task_key,
                "validation_policy_id": validation_policy_id,
                "policy_fingerprint": policy_fingerprint,
                "evidence_fingerprint": fail_evidence_fp,
            }
        )
        base_fail_run_id = f"market_universe_sync:{trade_date}:{fail_exec_fp[:16]}"
        prior_fail_id = (
            str(prior_run.get("run_id") or "")
            if (prior_run and str(prior_run.get("run_id") or "") != base_fail_run_id)
            else None
        )

        return self._record_run(
            run_id=base_fail_run_id,
            run_date=run_date,
            status="failed",
            source_ref=prior_fail_id,
            now=current,
            payload={
                **self._base_payload(
                    master_provider_name,
                    daily_provider_name,
                ),
                "task_key": task_key,
                "validation_policy_id": validation_policy_id,
                "policy_fingerprint": policy_fingerprint,
                "evidence_fingerprint": fail_evidence_fp,
                "coverage_validation_policy_id": validation_policy_id,
                "prior_run_id": prior_fail_id,
                "supersedes_run_id": prior_fail_id,
                "trade_date": trade_date,
                "market_universe_snapshot_id": snapshot.get("snapshot_id")
                if snapshot
                else None,
                "stock_master_metadata_fetched": stock_master_metadata_fetched,
                "stock_master_useful_name_count": (stock_master_useful_name_count),
                "instrument_metadata_persisted_count": (
                    instrument_metadata_persisted_count
                ),
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "retryable": not (
                    isinstance(exc, ValueError)
                    and str(exc).startswith("stock_master_")
                    and not str(exc).endswith("unavailable")
                ),
            },
        )

    def _ensure_market_universe_snapshot(
        self,
        *,
        trade_date: str,
        master_provider_name: str,
    ) -> tuple[dict[str, Any] | None, bool, bool, int, int]:
        snapshot = self._data_store.get_market_universe_snapshot(
            trade_date=trade_date,
            provider_name=master_provider_name,
        )
        provider_contacted = False
        stock_master_metadata_fetched = False
        stock_master_useful_name_count = 0
        instrument_metadata_persisted_count = 0
        symbol_metadata: Any = None
        source_capture_ids = None

        metadata_lister = getattr(
            self._security_master_source, "list_symbol_metadata", None
        )
        capture_lister = getattr(
            self._security_master_source, "capture_symbol_metadata", None
        )
        if (
            snapshot is None
            or snapshot.get("schema_version")
            not in {
                "karkinos.market_universe_snapshot.v2",
                "karkinos.market_universe_snapshot.v3",
            }
            or (
                snapshot.get("schema_version") == "karkinos.market_universe_snapshot.v2"
                and callable(metadata_lister)
            )
            or (callable(capture_lister) and not snapshot.get("source_capture_ids"))
        ):
            capture_started_at = self._capture_clock()
            metadata_lister = getattr(
                self._security_master_source, "list_symbol_metadata", None
            )
            if callable(capture_lister):
                (
                    symbol_metadata,
                    source_capture_ids,
                    capture_started_at,
                    capture_completed_at,
                ) = capture_lister(
                    ContentAddressedObjectStore(
                        self._data_store._root / "research" / "objects"
                    ),
                    trade_date=trade_date,
                )
            elif callable(metadata_lister):
                symbol_metadata = metadata_lister()
            if symbol_metadata is None:
                symbols = self._security_master_source.list_symbols()
            else:
                stock_master_metadata_fetched = True
                symbols = [
                    item.get("symbol")
                    for item in symbol_metadata
                    if isinstance(item, Mapping)
                ]
            if source_capture_ids is None:
                capture_completed_at = self._capture_clock()
            provider_contacted = True
            normalized_members = normalize_a_share_members(symbols)
            if len(normalized_members) < self._policy.minimum_master_member_count:
                raise ValueError("market_universe_provider_result_incomplete")
            if stock_master_metadata_fetched:
                metadata_items = _useful_stock_master_metadata(
                    symbol_metadata or [],
                    members=normalized_members,
                    provider_name=master_provider_name,
                    fetched_at=capture_completed_at.isoformat(),
                    trade_date=trade_date,
                )
                stock_master_useful_name_count = len(metadata_items)
                if metadata_items:
                    batch_upsert = getattr(
                        self._db, "upsert_instrument_metadata_batch_sync", None
                    )
                    if not callable(batch_upsert):
                        raise RuntimeError(
                            "instrument_metadata_batch_persistence_unavailable"
                        )
                    instrument_metadata_persisted_count = int(
                        batch_upsert(metadata_items)
                    )
                    if instrument_metadata_persisted_count != len(metadata_items):
                        raise RuntimeError(
                            "instrument_metadata_batch_persistence_incomplete"
                        )
            snapshot = self._data_store.save_market_universe_snapshot(
                trade_date=trade_date,
                provider_name=master_provider_name,
                members=normalized_members,
                capture_started_at=capture_started_at,
                capture_completed_at=capture_completed_at,
                source_metadata=symbol_metadata,
                source_capture_ids=source_capture_ids,
            )
        return (
            snapshot,
            provider_contacted,
            stock_master_metadata_fetched,
            stock_master_useful_name_count,
            instrument_metadata_persisted_count,
        )

    def _refresh_daily_bars(
        self,
        *,
        daily_provider_name: str,
        trading_dates: Sequence[str],
        members: Sequence[str],
    ) -> tuple[int, int, int, int]:
        updated = 0
        failed = 0
        remote_attempted = 0
        receipt_skipped = 0
        batch_fetcher = (
            None
            if self._daily_batch_source is None
            else getattr(
                self._daily_batch_source,
                "fetch_market_daily_bars",
                None,
            )
        )
        if callable(batch_fetcher):
            member_set = set(members)
            for market_date in trading_dates:
                receipt = self._data_store.get_market_daily_ingestion_receipt(
                    trade_date=market_date,
                    provider_name=daily_provider_name,
                )
                if receipt is not None:
                    receipt_skipped += 1
                    continue
                if self._throttle_seconds:
                    self._sleep(self._throttle_seconds)
                remote_attempted += 1
                try:
                    frame = batch_fetcher(market_date)
                    frame = frame.loc[
                        frame["symbol"].astype(str).isin(member_set)
                    ].copy()
                    if frame.empty:
                        raise ValueError("market_daily_batch_no_active_members")
                    self._data_store.ingest_market_daily_batch(
                        trade_date=market_date,
                        provider_name=daily_provider_name,
                        bars=frame,
                    )
                    updated += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "Full-market daily batch refresh failed for %s",
                        market_date,
                        exc_info=True,
                    )
                    break
        else:
            missing_dates = [
                day
                for day in trading_dates
                if self._data_store.get_market_daily_ingestion_receipt(
                    trade_date=day, provider_name=daily_provider_name
                )
                is None
            ]
            receipt_skipped = len(trading_dates) - len(missing_dates)
            fresh_frames = {}
            for symbol_text in members if missing_dates else ():
                if self._throttle_seconds:
                    self._sleep(self._throttle_seconds)
                remote_attempted += 1
                try:
                    frame = self._daily_source.fetch_bars(
                        Symbol(symbol_text),
                        start=datetime.fromisoformat(missing_dates[0]),
                        end=datetime.combine(
                            datetime.fromisoformat(missing_dates[-1]).date(),
                            time.max,
                        ),
                        frequency=BarFrequency.DAILY,
                        asset_class=AssetClass.STOCK,
                    )
                    if (
                        frame.attrs.get("volume_unit") != "shares"
                        or frame.attrs.get("amount_unit") != "CNY"
                        or frame.attrs.get("adjustment_mode") != "none"
                    ):
                        raise ValueError("market_daily_provider_units_unverified")
                    if not frame.empty:
                        fresh_frames[symbol_text] = frame
                    updated += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "Full-market per-symbol refresh failed for %s",
                        symbol_text,
                        exc_info=True,
                    )
                    break
            if not failed and missing_dates:
                _freeze_market_dates(
                    data_store=self._data_store,
                    provider_name=daily_provider_name,
                    frames=fresh_frames,
                    trading_dates=missing_dates,
                )
        return updated, failed, remote_attempted, receipt_skipped

    def _history_coverage(
        self,
        *,
        start_date,
        trade_date,
        daily_provider_name,
        trading_dates,
        members,
        member_metadata=(),
        snapshot_id=None,
    ):
        receipts = self._data_store.list_market_daily_ingestion_receipts(
            start_date=start_date.isoformat(),
            end_date=trade_date,
            provider_name=daily_provider_name,
        )
        receipt_dates = {str(item["trade_date"]) for item in receipts}
        frames = self._data_store.load_market_bar_windows(
            symbols=members,
            start_date=start_date.isoformat(),
            end_date=trade_date,
            receipts=receipts,
        )
        ready = sum(
            1
            for frame in frames.values()
            if _frame_window_ready(
                frame,
                end_date=trade_date,
                minimum_rows=self._policy.minimum_history_rows,
            )
        )
        blockers: list[str] = []
        missing_receipt_dates = sorted(set(trading_dates) - receipt_dates)
        if missing_receipt_dates:
            blockers.append("full_market_daily_receipt_coverage_incomplete")
        partial_dates = []
        missing_symbol_sessions = 0
        for receipt in receipts:
            session = str(receipt["trade_date"])
            if session not in trading_dates:
                continue
            expected = history_session_symbols(members, member_metadata, session)
            missing = expected - set(receipt.get("symbols") or [])
            if missing:
                partial_dates.append(session)
                missing_symbol_sessions += len(missing)
        if partial_dates:
            blockers.append("full_market_daily_symbol_coverage_unverified")
        end_receipt: Mapping[str, Any] = next(
            (
                item
                for item in receipts
                if str(item.get("trade_date") or "") == trade_date
            ),
            {},
        )
        end_cross_section_count = int(end_receipt.get("row_count") or 0)
        minimum_end_cross_section_count = max(
            self._policy.panel_size,
            int(len(members) * 0.9),
        )
        minimum_ready_count = max(
            self._policy.panel_size,
            int(len(members) * 0.8),
        )
        if end_cross_section_count < minimum_end_cross_section_count:
            blockers.append("full_market_latest_cross_section_incomplete")
        if ready < minimum_ready_count:
            blockers.append("full_market_persisted_bar_coverage_incomplete")
        full_coverage = not missing_receipt_dates and not partial_dates and not blockers
        return {
            "full_market_daily_receipt_count": len(receipts),
            "full_market_missing_receipt_dates": missing_receipt_dates[:100],
            "full_market_missing_receipt_date_count": len(missing_receipt_dates),
            "full_market_partial_receipt_dates": partial_dates[:100],
            "full_market_partial_receipt_date_count": len(partial_dates),
            "full_market_uncovered_symbol_session_count": missing_symbol_sessions,
            "history_repair_entrypoint": "market_sync.full-market"
            if partial_dates
            else None,
            "persisted_bar_ready_count": ready,
            "persisted_bar_excluded_count": len(members) - ready,
            "minimum_persisted_bar_ready_count": minimum_ready_count,
            "latest_cross_section_row_count": end_cross_section_count,
            "minimum_latest_cross_section_row_count": minimum_end_cross_section_count,
            "full_market_history_frozen": not missing_receipt_dates
            and not partial_dates,
            "coverage_evidence_fingerprint": compute_market_coverage_evidence_fingerprint(
                snapshot_id=str(snapshot_id or ""),
                trading_dates=trading_dates,
                receipts=receipts,
                members=members,
                member_metadata=member_metadata,
            )
            if (snapshot_id and full_coverage)
            else None,
            "blockers": blockers,
            "retryable": bool(blockers),
        }

    def _base_payload(
        self,
        security_master_provider: str,
        daily_bar_provider: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": MARKET_UNIVERSE_AUTOMATION_SCHEMA_VERSION,
            "trigger": "server_background_market_data_ingestion",
            "security_master_provider": security_master_provider,
            "daily_bar_provider": daily_bar_provider,
            "source_policy_id": str(
                getattr(
                    self._config,
                    "market_data_source_policy",
                    "legacy_injected_source",
                )
                or "legacy_injected_source"
            ),
            "policy": self._policy.to_dict(),
            "asset_scope": ["stock"],
            "read_endpoints_contact_providers": False,
            "changes_account_truth": False,
            "changes_strategy_promotion": False,
            "creates_order": False,
            "changes_execution_authority": False,
            "changes_capital_authority": False,
        }

    def _record_run(
        self,
        *,
        run_id: str,
        run_date: str,
        status: str,
        now: datetime,
        payload: dict[str, Any],
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        inserter = self._db.insert_automation_run_if_absent_sync
        trade_scope = payload.get("trade_date") or run_date
        current_run_id = run_id
        initial_run_id = run_id
        target_predecessor = (
            source_ref
            if source_ref and str(source_ref) != run_id
            else payload.get("supersedes_run_id") or payload.get("prior_run_id")
        )
        if target_predecessor and str(target_predecessor) == run_id:
            target_predecessor = None

        max_attempts = 10
        for attempt in range(max_attempts):
            resolved_predecessor = (
                target_predecessor
                if target_predecessor and str(target_predecessor) != current_run_id
                else None
            )
            resolved_source_ref = resolved_predecessor or payload.get(
                "market_universe_snapshot_id"
            )
            payload["supersedes_run_id"] = resolved_predecessor
            payload["prior_run_id"] = resolved_predecessor

            run_dict = {
                "run_id": current_run_id,
                "run_type": MARKET_UNIVERSE_AUTOMATION_RUN_TYPE,
                "run_date": run_date,
                "status": status,
                "execution_mode": "market_data_ingestion",
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "source_ref": resolved_source_ref,
                "payload": payload,
            }

            row, inserted = inserter(run_dict)
            if inserted:
                return row
            # Collision with existing terminal run! Atomic preservation.
            existing_status = str(row.get("status") or "")
            if (
                status == "completed"
                and existing_status == "completed"
                and is_qualified_market_universe_coverage_run(
                    row,
                    expected_snapshot_id=payload.get("market_universe_snapshot_id"),
                    expected_fingerprint=payload.get("evidence_fingerprint"),
                    expected_policy_id=payload.get("validation_policy_id"),
                    expected_policy_fingerprint=payload.get("policy_fingerprint"),
                )
            ):
                return row
            if (
                status == "blocked"
                and existing_status == "blocked"
                and str(row.get("run_id") or "") == current_run_id
            ):
                return row

            colliding_id = str(row.get("run_id") or initial_run_id)
            row_task_key = None
            try:
                row_payload = json.loads(str(row.get("payload_json") or "{}"))
                if isinstance(row_payload, Mapping):
                    row_task_key = row_payload.get("task_key")
            except Exception:
                row_task_key = None

            expected_task_key = payload.get("task_key")
            is_same_task = bool(
                not row_task_key
                or not expected_task_key
                or row_task_key == expected_task_key
            )
            if is_same_task:
                if attempt == 0:
                    if (
                        not target_predecessor
                        or str(target_predecessor) == current_run_id
                    ):
                        target_predecessor = colliding_id
                else:
                    target_predecessor = colliding_id

            attempt_fp = content_fingerprint(
                {
                    "initial_run_id": initial_run_id,
                    "colliding_run_id": colliding_id,
                    "target_predecessor": target_predecessor,
                    "attempt": attempt + 1,
                    "started_at": now.isoformat(),
                }
            )
            current_run_id = f"market_universe_sync:{trade_scope}:{attempt_fp[:16]}"

        raise RuntimeError(
            f"automation_run_collision_exhaustion: unable to allocate run identity after {max_attempts} attempts"
        )


def _useful_stock_master_metadata(
    rows: Sequence[Mapping[str, Any]],
    *,
    members: Sequence[Mapping[str, Any]],
    provider_name: str,
    fetched_at: str,
    trade_date: str,
) -> list[dict[str, Any]]:
    member_by_symbol = {
        str(member.get("symbol") or "").strip(): member
        for member in members
        if str(member.get("symbol") or "").strip()
    }
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().split(".", maxsplit=1)[0]
        display_name = str(row.get("display_name") or "").strip()
        member = member_by_symbol.get(symbol)
        if (
            member is None
            or not display_name
            or display_name == symbol
            or display_name == f"{symbol} A股"
        ):
            continue
        normalized[symbol] = {
            "symbol": symbol,
            "asset_type": "stock",
            "display_name": display_name,
            "provider_symbol": str(row.get("provider_symbol") or symbol),
            "exchange": member.get("exchange"),
            "market": "cn",
            "provider_name": provider_name,
            "source": "market_universe_stock_master",
            "fetched_at": fetched_at,
            "metadata": {
                "stock_master_trade_date": trade_date,
                "listing_status": member.get("listing_status"),
                "board": member.get("board"),
            },
        }
    return [normalized[symbol] for symbol in sorted(normalized)]


async def run_market_universe_automation_loop(
    *,
    db: Any,
    config: Any,
    interval_seconds: float = MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS,
) -> None:
    """Run the idempotent universe ingestion immediately and once per hour."""
    service = MarketUniverseAutomationService(db=db, config=config)
    while True:
        await wait_for_release_activation()
        try:
            await asyncio.to_thread(service.run_due)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected market-universe automation failure")
        await asyncio.sleep(interval_seconds)


def _injected_provider_name(config: Any, source: Any) -> str:
    descriptor = getattr(source, "descriptor", None)
    provider = str(getattr(descriptor, "provider", "") or "").strip().lower()
    if provider:
        return provider
    legacy = str(getattr(config, "data_source", "") or "").strip().lower()
    if legacy:
        return legacy
    return source.__class__.__name__.strip().lower()


def _provider_request_interval_seconds(provider_name: str) -> float:
    """Leave capacity below TuShare's base 50 requests/minute ceiling."""
    return 2.0 if provider_name.strip().lower() == "tushare" else 0.0


def _history_start(config: Any, trade_date: str):
    end = datetime.fromisoformat(trade_date).date()
    start = end - timedelta(days=540)
    configured = str(getattr(config, "start_date", "") or "").strip()
    if configured:
        try:
            start = datetime.fromisoformat(configured).date()
        except ValueError:
            pass
    return start


def verified_trading_dates(
    db: Any,
    *,
    start_date: str,
    end_date: str,
) -> list[str]:
    if not start_date or not end_date:
        raise ValueError("verified_trading_dates_range_invalid")
    try:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
    except ValueError as exc:
        raise ValueError("verified_trading_dates_range_invalid") from exc
    dates: set[str] = set()
    for year in range(start.year, end.year + 1):
        row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        validation = validate_verified_market_calendar(row)
        if not validation.verified:
            raise ValueError(
                f"research_calendar_incomplete:{year}:{validation.blockers[0]}"
            )
        days = row.get("days") or json.loads(str(row.get("days_json") or "[]"))
        dates.update(
            str(day.get("date"))
            for day in days
            if isinstance(day, dict)
            and day.get("is_trading_day") is True
            and start_date <= str(day.get("date") or "") <= end_date
        )
    return sorted(dates)


def _freeze_market_dates(
    *,
    data_store: DataStore,
    provider_name: str,
    frames: Mapping[str, pd.DataFrame],
    trading_dates: list[str],
) -> None:
    rows_by_date: dict[str, list[pd.DataFrame]] = {
        market_date: [] for market_date in trading_dates
    }
    for symbol, frame in frames.items():
        dated = frame.copy()
        dated["trade_date"] = pd.to_datetime(dated["timestamp"]).dt.date.map(
            lambda value: value.isoformat()
        )
        for market_date, selected in dated.groupby("trade_date", sort=False):
            if market_date not in rows_by_date:
                continue
            batch = selected.drop(columns=["trade_date"]).copy()
            batch["symbol"] = symbol
            rows_by_date[market_date].append(batch)
    for market_date in trading_dates:
        existing = data_store.get_market_daily_ingestion_receipt(
            trade_date=market_date,
            provider_name=provider_name,
        )
        if existing is not None:
            continue
        parts = rows_by_date[market_date]
        if not parts:
            raise ValueError(f"persisted_market_date_missing:{market_date}")
        data_store.ingest_market_daily_batch(
            trade_date=market_date,
            provider_name=provider_name,
            bars=pd.concat(parts, ignore_index=True),
        )


def _frame_window_ready(
    frame: pd.DataFrame,
    *,
    end_date: str,
    minimum_rows: int,
) -> bool:
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        return False
    timestamps = pd.to_datetime(frame["timestamp"]).sort_values()
    return bool(
        len(timestamps) >= minimum_rows
        and timestamps.iloc[-1].date().isoformat() == end_date
    )
