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
from data.research_market_data import select_replayable_scoped_receipts
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


def automation_coverage_policy_dict(policy: MarketUniversePolicy) -> dict[str, Any]:
    """Serialize MarketUniversePolicy binding explicit panel_size for automation."""
    return {
        **policy.to_dict(),
        "panel_size": policy.panel_size,
    }


def check_receipts_session_coverage(
    *,
    trading_dates: Sequence[str],
    receipts: Sequence[Mapping[str, Any]],
    members: Sequence[str] | None = None,
    member_metadata: Sequence[Mapping[str, Any]] | None = None,
    scoped_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> bool:
    """Verify that receipts exist for every required trading date and cover all listed symbols."""
    if not trading_dates or not receipts:
        return False
    scoped_receipts = select_replayable_scoped_receipts(receipts, scoped_receipts or ())
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
            halted_in_session = {
                str(row["symbol"])
                for row in metadata
                if row.get("trade_status") == "0"
                and str(row.get("status_session_date") or "") == session
            }
            scoped_in_session = {
                sym
                for sc in (scoped_receipts or [])
                if str(sc.get("trade_date") or "") == session
                for sym in (sc.get("symbols") or [])
            }
            covered = receipt_symbols | scoped_in_session | halted_in_session
            if expected:
                if receipt_symbols or scoped_in_session:
                    if not expected.issubset(covered):
                        return False
                else:
                    total_count = (
                        row_count + len(scoped_in_session) + len(halted_in_session)
                    )
                    if total_count < len(expected):
                        return False
    return True


def compute_market_coverage_evidence_fingerprint(
    *,
    snapshot_id: str | None,
    trading_dates: Sequence[str],
    receipts: Sequence[Mapping[str, Any]],
    members: Sequence[str] | None = None,
    member_metadata: Sequence[Mapping[str, Any]] | None = None,
    scoped_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> str | None:
    """Deterministic content fingerprint binding master snapshot and daily bar receipts.

    Returns None if snapshot_id is absent, trading_dates is empty, or receipts
    do not completely cover all required trading dates and listing-aware symbols.
    """
    if not snapshot_id or not trading_dates:
        return None
    scoped_receipts = select_replayable_scoped_receipts(receipts, scoped_receipts or ())
    if not check_receipts_session_coverage(
        trading_dates=trading_dates,
        receipts=receipts,
        members=members,
        member_metadata=member_metadata,
        scoped_receipts=scoped_receipts,
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
    scoped_cores = [
        {
            "trade_date": str(sc.get("trade_date")),
            "provider_name": str(sc.get("provider_name")),
            "scope_fingerprint": str(sc.get("scope_fingerprint") or ""),
            "row_count": int(sc.get("row_count") or 0),
            "dataset_fingerprint": str(sc.get("dataset_fingerprint") or ""),
            "receipt_fingerprint": str(sc.get("receipt_fingerprint") or ""),
        }
        for sc in (scoped_receipts or [])
        if str(sc.get("trade_date")) in trading_dates
    ]
    payload = {
        "policy_id": MARKET_UNIVERSE_COVERAGE_POLICY_ID,
        "snapshot_id": snapshot_id,
        "trading_dates": sorted(trading_dates),
        "receipts": receipt_cores,
    }
    if scoped_cores:
        payload["scoped_receipts"] = sorted(
            scoped_cores,
            key=lambda x: (
                x["trade_date"],
                x["provider_name"],
                x["scope_fingerprint"],
            ),
        )
    return content_fingerprint(payload)


def is_qualified_market_universe_coverage_run(
    existing: Mapping[str, Any],
    *,
    expected_snapshot_id: str | None,
    expected_fingerprint: str | None,
    expected_policy_id: str | None = None,
    expected_policy_fingerprint: str | None = None,
    expected_task_key: str | None = None,
    expected_panel_size: int | None = None,
    expected_member_count: int | None = None,
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

    if expected_task_key:
        recorded_task_key = payload.get("task_key")
        if (
            not isinstance(recorded_task_key, str)
            or recorded_task_key != expected_task_key
        ):
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

    rec_policy = payload.get("policy")
    if rec_policy is not None:
        if not isinstance(rec_policy, Mapping):
            return False
        try:
            claimed_policy_fp = content_fingerprint(dict(rec_policy))
        except Exception:
            return False
        if payload.get("policy_fingerprint") != claimed_policy_fp:
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

    member_count_raw = _strict_non_negative_int(
        payload.get("market_universe_member_count")
    )
    ready_count_raw = _strict_non_negative_int(payload.get("persisted_bar_ready_count"))
    cross_count_raw = _strict_non_negative_int(
        payload.get("latest_cross_section_row_count")
    )
    if member_count_raw is not None:
        if ready_count_raw is not None and ready_count_raw > member_count_raw:
            return False
        if cross_count_raw is not None and cross_count_raw > member_count_raw:
            return False
        excluded_count_raw = _strict_non_negative_int(
            payload.get("persisted_bar_excluded_count")
        )
        if (
            excluded_count_raw is not None
            and ready_count_raw is not None
            and ready_count_raw + excluded_count_raw != member_count_raw
        ):
            return False

    if expected_panel_size is not None:
        if not isinstance(rec_policy, Mapping):
            return False
        rec_panel = rec_policy.get("panel_size")
        if not isinstance(rec_panel, int) or isinstance(rec_panel, bool):
            return False
        if rec_panel != expected_panel_size:
            return False

        min_master = rec_policy.get("minimum_master_member_count")
        if isinstance(min_master, int) and not isinstance(min_master, bool):
            member_count_check = _strict_non_negative_int(
                payload.get("market_universe_member_count")
            )
            if member_count_check is not None and member_count_check < min_master:
                return False

        member_count = _strict_non_negative_int(
            payload.get("market_universe_member_count")
        )
        if member_count is None or member_count <= 0:
            return False
        if expected_member_count is not None and member_count != expected_member_count:
            return False

        ready_count = _strict_non_negative_int(payload.get("persisted_bar_ready_count"))
        if ready_count is None:
            return False
        min_ready_count = _strict_non_negative_int(
            payload.get("minimum_persisted_bar_ready_count")
        )
        if min_ready_count is None:
            return False

        cross_count = _strict_non_negative_int(
            payload.get("latest_cross_section_row_count")
        )
        if cross_count is None:
            return False
        min_cross_count = _strict_non_negative_int(
            payload.get("minimum_latest_cross_section_row_count")
        )
        if min_cross_count is None:
            return False

        calc_min_ready = max(expected_panel_size, (member_count * 8) // 10)
        calc_min_cross = max(expected_panel_size, (member_count * 9) // 10)

        if min_ready_count != calc_min_ready:
            return False
        if min_cross_count != calc_min_cross:
            return False
        if ready_count < calc_min_ready:
            return False
        if cross_count < calc_min_cross:
            return False
        if ready_count > member_count:
            return False
        if cross_count > member_count:
            return False

        excluded_count = _strict_non_negative_int(
            payload.get("persisted_bar_excluded_count")
        )
        if excluded_count is not None and ready_count + excluded_count != member_count:
            return False

    return True


def market_universe_legacy_candidate_ids(
    master_provider_name: str,
    daily_provider_name: str,
    trade_date: str,
    task_key: str | None = None,
) -> tuple[str, ...]:
    """Return canonical legacy candidate run IDs for historical compatibility."""
    ids = [
        f"market_universe_sync:v7:{master_provider_name}:{daily_provider_name}:{trade_date}",
        f"market_universe_sync:v8:{master_provider_name}:{daily_provider_name}:{trade_date}",
    ]
    if task_key and task_key not in ids:
        ids.append(task_key)
    return tuple(ids)


def _matches_market_universe_scope(
    payload: Mapping[str, Any],
    *,
    run_id: str | None,
    task_key: str | None,
    trade_date: str | None,
    master_provider_name: str | None,
    daily_provider_name: str | None,
    legacy_candidate_ids: Sequence[str] | None,
) -> bool:
    """Check that a payload matches task scope without explicit conflicts.

    If trade_date or providers are explicitly present in payload, they must match.
    If task_key is in payload, it must match task_key.
    If keyless, the run must either have all 3 scope fields matching or match a legacy candidate ID.
    """
    if not isinstance(payload, Mapping):
        return False

    has_scope_constraint = bool(
        task_key
        or legacy_candidate_ids
        or (trade_date and master_provider_name and daily_provider_name)
    )

    # Check explicit scope conflicts
    if trade_date and "trade_date" in payload:
        if payload["trade_date"] != trade_date:
            return False
    if master_provider_name and "security_master_provider" in payload:
        if payload["security_master_provider"] != master_provider_name:
            return False
    if daily_provider_name and "daily_bar_provider" in payload:
        if payload["daily_bar_provider"] != daily_provider_name:
            return False

    # Check task key
    if "task_key" in payload:
        anc_task = payload.get("task_key")
        if not isinstance(anc_task, str) or not anc_task.strip():
            return False
        if task_key and anc_task != task_key:
            return False
        return True

    # Truly keyless record: must either match legacy candidate ID or have full matching scope
    if legacy_candidate_ids and run_id and run_id in legacy_candidate_ids:
        return True

    if (
        trade_date
        and master_provider_name
        and daily_provider_name
        and payload.get("trade_date") == trade_date
        and payload.get("security_master_provider") == master_provider_name
        and payload.get("daily_bar_provider") == daily_provider_name
    ):
        return True

    # If no scope constraints were specified, allow
    if not has_scope_constraint:
        return True

    return False


def _row_matches_market_universe_scope(
    row: Mapping[str, Any] | None,
    *,
    run_id: str | None,
    task_key: str | None,
    trade_date: str | None,
    master_provider_name: str | None,
    daily_provider_name: str | None,
    legacy_candidate_ids: Sequence[str] | None = None,
) -> tuple[bool, Mapping[str, Any]]:
    """Verify that a row has market_universe_sync run_type and matching task scope."""
    if not isinstance(row, Mapping):
        return False, {}
    if row.get("run_type") != MARKET_UNIVERSE_AUTOMATION_RUN_TYPE:
        return False, {}
    payload = row.get("payload")
    if payload is None:
        raw_payload = row.get("payload_json")
        if raw_payload:
            try:
                payload = json.loads(str(raw_payload))
            except Exception:
                return False, {}
    if not isinstance(payload, Mapping):
        return False, {}
    matches = _matches_market_universe_scope(
        payload,
        run_id=run_id or str(row.get("run_id") or ""),
        task_key=task_key,
        trade_date=trade_date,
        master_provider_name=master_provider_name,
        daily_provider_name=daily_provider_name,
        legacy_candidate_ids=legacy_candidate_ids,
    )
    return matches, payload


def _is_matching_pending_blocked_run(
    row: Mapping[str, Any] | None,
    *,
    run_date: str,
    master_provider_name: str | None = None,
    daily_provider_name: str | None = None,
) -> bool:
    """Verify that an existing blocked run matches the pending calendar-blocked scope."""
    if not isinstance(row, Mapping):
        return False
    if row.get("run_type") != MARKET_UNIVERSE_AUTOMATION_RUN_TYPE:
        return False
    if str(row.get("status") or "") != "blocked":
        return False
    if str(row.get("run_date") or "") != run_date:
        return False
    payload = row.get("payload")
    if payload is None:
        raw_payload = row.get("payload_json")
        if raw_payload:
            try:
                payload = json.loads(str(raw_payload))
            except Exception:
                return False
    if not isinstance(payload, Mapping):
        return False
    if payload.get("trade_date") is not None:
        return False
    if (
        master_provider_name is not None
        and payload.get("security_master_provider") != master_provider_name
    ):
        return False
    if (
        daily_provider_name is not None
        and payload.get("daily_bar_provider") != daily_provider_name
    ):
        return False
    recorded_task_key = payload.get("task_key")
    if recorded_task_key is not None:
        if not isinstance(recorded_task_key, str):
            return False
        clean_task_key = recorded_task_key.strip()
        expected_pending_keys = set()
        if master_provider_name and daily_provider_name:
            expected_pending_keys.add(
                f"market_universe_sync:{master_provider_name}:{daily_provider_name}"
            )
            expected_pending_keys.add(
                f"market_universe_sync:{master_provider_name}:{daily_provider_name}:pending"
            )
        if clean_task_key not in expected_pending_keys:
            return False
    blockers = payload.get("blockers")
    if (
        not isinstance(blockers, (list, tuple))
        or "verified_closed_trading_date_unavailable" not in blockers
    ):
        return False
    return True


def validate_run_predecessor_ancestry(
    run_or_row: Mapping[str, Any] | None,
    *,
    current_run_id: str | None = None,
    db: Any = None,
    task_key: str | None = None,
    trade_date: str | None = None,
    master_provider_name: str | None = None,
    daily_provider_name: str | None = None,
    legacy_candidate_ids: Sequence[str] | None = None,
    ancestry_cache: dict[str, tuple[bool, str | None]] | None = None,
    pending_run_date: str | None = None,
) -> tuple[bool, str | None]:
    """Validate predecessor ancestry of an automation run or database row.

    Returns (is_valid, predecessor_id).
    If contradictory, malformed, or self-referential, returns (False, None).
    If valid with no predecessor, returns (True, None).
    If valid with a predecessor, returns (True, predecessor_id).
    When db is provided, resolves and validates the full ancestor chain to the root.
    """
    if not run_or_row or not isinstance(run_or_row, Mapping):
        return True, None

    if pending_run_date is not None:
        if not _is_matching_pending_blocked_run(
            run_or_row,
            run_date=pending_run_date,
            master_provider_name=master_provider_name,
            daily_provider_name=daily_provider_name,
        ):
            return False, None

    # Check for malformed or padded current_run_id
    if current_run_id is not None:
        if not isinstance(current_run_id, str) or not current_run_id.strip():
            return False, None
        if current_run_id != current_run_id.strip():
            return False, None
        target_self_id = current_run_id
    else:
        target_self_id = None

    raw_run_id = run_or_row.get("run_id")
    if raw_run_id is not None:
        if not isinstance(raw_run_id, str) or not raw_run_id.strip():
            return False, None
        if raw_run_id != raw_run_id.strip():
            return False, None
        if target_self_id is None:
            target_self_id = raw_run_id

    payload = run_or_row.get("payload")
    if payload is None:
        payload_raw = run_or_row.get("payload_json")
        if payload_raw:
            try:
                payload = json.loads(str(payload_raw))
            except Exception:
                return False, None
    if not isinstance(payload, Mapping):
        payload = {}

    snapshot_val = payload.get("market_universe_snapshot_id")
    if snapshot_val is not None and (
        not isinstance(snapshot_val, str) or snapshot_val != snapshot_val.strip()
    ):
        return False, None
    snapshot_id = snapshot_val if isinstance(snapshot_val, str) else None

    source_ref = run_or_row.get("source_ref")
    s_ref: str | None = None
    if source_ref is not None:
        if not isinstance(source_ref, str) or not source_ref.strip():
            return False, None
        if source_ref != source_ref.strip():
            return False, None
        s_ref = source_ref

    # Extract explicit payload predecessor aliases
    has_supersedes = "supersedes_run_id" in payload
    has_prior = "prior_run_id" in payload

    p_supersedes: str | None = None
    if has_supersedes:
        val = payload["supersedes_run_id"]
        if val is not None:
            if not isinstance(val, str) or not val.strip():
                return False, None
            if val != val.strip():
                return False, None
            p_supersedes = val

    p_prior: str | None = None
    if has_prior:
        val = payload["prior_run_id"]
        if val is not None:
            if not isinstance(val, str) or not val.strip():
                return False, None
            if val != val.strip():
                return False, None
            p_prior = val

    # If both keys are present in payload, their values must match exactly
    if has_supersedes and has_prior:
        if p_supersedes != p_prior:
            return False, None

    payload_predecessor = p_supersedes if has_supersedes else p_prior

    # An explicit run predecessor must never equal the row's snapshot ID
    if payload_predecessor and snapshot_id and payload_predecessor == snapshot_id:
        return False, None

    # Validate source_ref consistency
    if s_ref is not None:
        is_snapshot_ref = bool(snapshot_id and s_ref == snapshot_id)
        if is_snapshot_ref:
            if payload_predecessor is not None:
                return False, None
        else:
            if payload_predecessor is not None:
                if s_ref != payload_predecessor:
                    return False, None
            elif has_supersedes or has_prior:
                return False, None
            else:
                payload_predecessor = s_ref

    if payload_predecessor:
        if target_self_id and payload_predecessor == target_self_id:
            return False, None

    # Optional deep chain verification through db to the root
    if db is not None and payload_predecessor:
        getter = getattr(db, "get_automation_run_sync", None)
        if callable(getter):
            visited: set[str] = {target_self_id} if target_self_id else set()
            curr_pred_id = payload_predecessor
            chain_nodes: list[str] = []
            while True:
                if curr_pred_id in visited:
                    if ancestry_cache is not None:
                        for nid in chain_nodes:
                            ancestry_cache[nid] = (False, None)
                    return False, None  # Cycle detected
                visited.add(curr_pred_id)
                chain_nodes.append(curr_pred_id)

                if ancestry_cache is not None and curr_pred_id in ancestry_cache:
                    cached_valid, cached_pred = ancestry_cache[curr_pred_id]
                    if not cached_valid:
                        for nid in chain_nodes:
                            ancestry_cache[nid] = (False, None)
                        return False, None
                    # Cached valid to root
                    break

                ancestor = getter(curr_pred_id)
                if ancestor is None:
                    if ancestry_cache is not None:
                        for nid in chain_nodes:
                            ancestry_cache[nid] = (False, None)
                    return False, None  # Missing ancestor link

                if pending_run_date is not None:
                    if not _is_matching_pending_blocked_run(
                        ancestor,
                        run_date=pending_run_date,
                        master_provider_name=master_provider_name,
                        daily_provider_name=daily_provider_name,
                    ):
                        if ancestry_cache is not None:
                            for nid in chain_nodes:
                                ancestry_cache[nid] = (False, None)
                        return False, None
                else:
                    # Ancestor must be a market-universe run with object payload
                    if ancestor.get("run_type") != MARKET_UNIVERSE_AUTOMATION_RUN_TYPE:
                        if ancestry_cache is not None:
                            for nid in chain_nodes:
                                ancestry_cache[nid] = (False, None)
                        return False, None

                    anc_payload = ancestor.get("payload")
                    if anc_payload is None:
                        raw_anc_p = ancestor.get("payload_json")
                        if raw_anc_p:
                            try:
                                anc_payload = json.loads(str(raw_anc_p))
                            except Exception:
                                if ancestry_cache is not None:
                                    for nid in chain_nodes:
                                        ancestry_cache[nid] = (False, None)
                                return False, None
                    if not isinstance(anc_payload, Mapping):
                        if ancestry_cache is not None:
                            for nid in chain_nodes:
                                ancestry_cache[nid] = (False, None)
                        return False, None

                    # Validate ancestor scope and identity without explicit conflicts
                    anc_id = str(ancestor.get("run_id") or curr_pred_id)
                    if not _matches_market_universe_scope(
                        anc_payload,
                        run_id=anc_id,
                        task_key=task_key,
                        trade_date=trade_date,
                        master_provider_name=master_provider_name,
                        daily_provider_name=daily_provider_name,
                        legacy_candidate_ids=legacy_candidate_ids,
                    ):
                        if ancestry_cache is not None:
                            for nid in chain_nodes:
                                ancestry_cache[nid] = (False, None)
                        return False, None

                # Validate ancestor's own predecessor aliases
                ancestor_valid, next_pred_id = validate_run_predecessor_ancestry(
                    ancestor,
                    current_run_id=curr_pred_id,
                    pending_run_date=pending_run_date,
                    master_provider_name=master_provider_name,
                    daily_provider_name=daily_provider_name,
                )
                if not ancestor_valid:
                    if ancestry_cache is not None:
                        for nid in chain_nodes:
                            ancestry_cache[nid] = (False, None)
                    return False, None

                if not next_pred_id:
                    break
                curr_pred_id = next_pred_id

            if ancestry_cache is not None:
                for nid in chain_nodes:
                    ancestry_cache[nid] = (True, payload_predecessor)

    return True, payload_predecessor


def find_prior_market_universe_run(
    db: Any,
    *,
    task_key: str,
    trade_date: str,
    master_provider_name: str,
    daily_provider_name: str,
    run_date: str | None = None,
    legacy_candidate_ids: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Locate the most recent prior run for this task key, paging history if necessary."""
    if legacy_candidate_ids is None:
        legacy_candidate_ids = market_universe_legacy_candidate_ids(
            master_provider_name=master_provider_name,
            daily_provider_name=daily_provider_name,
            trade_date=trade_date,
            task_key=task_key,
        )
    ancestry_cache: dict[str, tuple[bool, str | None]] = {}
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
                if cand.get("run_type") != MARKET_UNIVERSE_AUTOMATION_RUN_TYPE:
                    continue
                try:
                    payload = json.loads(str(cand.get("payload_json") or "{}"))
                except Exception:
                    continue
                if not isinstance(payload, Mapping):
                    continue
                cand_id = str(cand.get("run_id") or "")
                if not _matches_market_universe_scope(
                    payload,
                    run_id=cand_id,
                    task_key=task_key,
                    trade_date=trade_date,
                    master_provider_name=master_provider_name,
                    daily_provider_name=daily_provider_name,
                    legacy_candidate_ids=legacy_candidate_ids,
                ):
                    continue
                is_valid, _ = validate_run_predecessor_ancestry(
                    cand,
                    current_run_id=cand_id,
                    db=db,
                    task_key=task_key,
                    trade_date=trade_date,
                    master_provider_name=master_provider_name,
                    daily_provider_name=daily_provider_name,
                    legacy_candidate_ids=legacy_candidate_ids,
                    ancestry_cache=ancestry_cache,
                )
                if not is_valid:
                    continue
                return cand
            if len(page) < limit:
                break
            offset += limit

    getter = getattr(db, "get_automation_run_sync", None)
    if callable(getter):
        for candidate_id in legacy_candidate_ids:
            try:
                prior = getter(candidate_id)
                if prior is None:
                    continue
                if prior.get("run_type") != MARKET_UNIVERSE_AUTOMATION_RUN_TYPE:
                    continue
                try:
                    p = json.loads(str(prior.get("payload_json") or "{}"))
                except Exception:
                    continue
                if not isinstance(p, Mapping):
                    continue
                prior_id = str(prior.get("run_id") or candidate_id)
                if not _matches_market_universe_scope(
                    p,
                    run_id=prior_id,
                    task_key=task_key,
                    trade_date=trade_date,
                    master_provider_name=master_provider_name,
                    daily_provider_name=daily_provider_name,
                    legacy_candidate_ids=legacy_candidate_ids,
                ):
                    continue
                is_valid, _ = validate_run_predecessor_ancestry(
                    prior,
                    current_run_id=prior_id,
                    db=db,
                    task_key=task_key,
                    trade_date=trade_date,
                    master_provider_name=master_provider_name,
                    daily_provider_name=daily_provider_name,
                    legacy_candidate_ids=legacy_candidate_ids,
                    ancestry_cache=ancestry_cache,
                )
                if not is_valid:
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


def _snapshot_has_empty_status_roster(
    objects: ContentAddressedObjectStore,
    snapshot: Mapping[str, Any],
    trade_date: str,
) -> bool:
    source_capture_ids = snapshot.get("source_capture_ids")
    if not source_capture_ids:
        return False
    from data.market.capture import read_provider_capture

    for cid in source_capture_ids:
        try:
            ref = objects.resolve_ref(cid)
            cap = read_provider_capture(objects, ref)
            if cap.provider == "baostock" and cap.operation in {
                "query_all_stock",
                "daily_stock_status",
            }:
                req = json.loads(cap.request_json)
                day = str(req.get("day") or req.get("trade_date") or "")
                if day == str(trade_date):
                    return (cap.record_count or 0) <= 0
        except Exception:
            continue
    return False


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
            pending_ids = (
                f"market_universe_sync:pending:{run_date}",
                f"market_universe_sync:pending:{run_date}:{master_provider_name}:{daily_provider_name}",
            )
            getter = getattr(self._db, "get_automation_run_sync", None)
            if callable(getter):
                for pid in pending_ids:
                    existing_pending = getter(pid)
                    if _is_matching_pending_blocked_run(
                        existing_pending,
                        run_date=run_date,
                        master_provider_name=master_provider_name,
                        daily_provider_name=daily_provider_name,
                    ):
                        is_valid_ancestry, _ = validate_run_predecessor_ancestry(
                            existing_pending,
                            current_run_id=pid,
                            db=self._db,
                            pending_run_date=run_date,
                            master_provider_name=master_provider_name,
                            daily_provider_name=daily_provider_name,
                        )
                        if is_valid_ancestry:
                            return existing_pending
            return self._record_run(
                run_id=pending_ids[0],
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
        policy_fingerprint = content_fingerprint(
            automation_coverage_policy_dict(self._policy)
        )

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
        scoped_receipts = []
        if hasattr(self._data_store, "list_market_daily_scoped_receipts"):
            try:
                scoped_receipts = self._data_store.list_market_daily_scoped_receipts(
                    provider_name=daily_provider_name,
                    verify=True,
                )
            except (ValueError, OSError):
                scoped_receipts = []

        evidence_fingerprint = (
            compute_market_coverage_evidence_fingerprint(
                snapshot_id=str(latest_master.get("snapshot_id") or ""),
                trading_dates=trading_dates,
                receipts=current_receipts,
                members=master_members,
                member_metadata=master_metadata,
                scoped_receipts=scoped_receipts,
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

        legacy_candidate_ids = market_universe_legacy_candidate_ids(
            master_provider_name=master_provider_name,
            daily_provider_name=daily_provider_name,
            trade_date=trade_date,
            task_key=task_key,
        )

        reusable_run = self._resolve_reusable_completed_run(
            run_id=run_id,
            prior_run=prior_run,
            task_key=task_key,
            trade_date=trade_date,
            master_provider_name=master_provider_name,
            daily_provider_name=daily_provider_name,
            legacy_candidate_ids=legacy_candidate_ids,
            latest_master=latest_master,
            master_members=master_members,
            evidence_fingerprint=evidence_fingerprint,
            validation_policy_id=validation_policy_id,
            policy_fingerprint=policy_fingerprint,
        )
        if reusable_run is not None:
            return reusable_run

        # 3. Throttle / backoff check if prior run failed with identical inputs
        if self._is_failed_run_throttled(
            prior_run=prior_run,
            validation_policy_id=validation_policy_id,
            policy_fingerprint=policy_fingerprint,
            evidence_fingerprint=evidence_fingerprint,
            latest_master=latest_master,
            current=current,
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
                snapshot=snapshot,
                trade_date=trade_date,
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

            prior_run_id = None
            if prior_run and str(prior_run.get("run_id") or "") != base_run_id:
                is_valid, _ = validate_run_predecessor_ancestry(
                    prior_run,
                    current_run_id=str(prior_run.get("run_id") or ""),
                    db=self._db,
                    task_key=task_key,
                    trade_date=trade_date,
                    master_provider_name=master_provider_name,
                    daily_provider_name=daily_provider_name,
                    legacy_candidate_ids=legacy_candidate_ids,
                )
                if is_valid:
                    prior_run_id = str(prior_run.get("run_id") or "")

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

    def _resolve_reusable_completed_run(
        self,
        *,
        run_id: str,
        prior_run: dict[str, Any] | None,
        task_key: str,
        trade_date: str,
        master_provider_name: str,
        daily_provider_name: str,
        legacy_candidate_ids: tuple[str, ...],
        latest_master: dict[str, Any] | None,
        master_members: list[str],
        evidence_fingerprint: str | None,
        validation_policy_id: str,
        policy_fingerprint: str,
    ) -> dict[str, Any] | None:
        existing = self._db.get_automation_run_sync(run_id)
        if existing and str(existing.get("status")) == "completed":
            is_valid_scope, _ = _row_matches_market_universe_scope(
                existing,
                run_id=run_id,
                task_key=task_key,
                trade_date=trade_date,
                master_provider_name=master_provider_name,
                daily_provider_name=daily_provider_name,
                legacy_candidate_ids=legacy_candidate_ids,
            )
            is_valid_existing, _ = validate_run_predecessor_ancestry(
                existing,
                current_run_id=run_id,
                db=self._db,
                task_key=task_key,
                trade_date=trade_date,
                master_provider_name=master_provider_name,
                daily_provider_name=daily_provider_name,
                legacy_candidate_ids=legacy_candidate_ids,
            )
            if (
                is_valid_scope
                and is_valid_existing
                and is_qualified_market_universe_coverage_run(
                    existing,
                    expected_snapshot_id=str(latest_master.get("snapshot_id") or "")
                    if latest_master
                    else None,
                    expected_fingerprint=evidence_fingerprint,
                    expected_policy_id=validation_policy_id,
                    expected_policy_fingerprint=policy_fingerprint,
                    expected_task_key=task_key,
                    expected_panel_size=self._policy.panel_size,
                    expected_member_count=len(master_members)
                    if latest_master
                    else None,
                )
            ):
                return existing

        if prior_run and str(prior_run.get("status")) == "completed":
            is_valid_prior, _ = validate_run_predecessor_ancestry(
                prior_run,
                current_run_id=str(prior_run.get("run_id") or ""),
                db=self._db,
                task_key=task_key,
                trade_date=trade_date,
                master_provider_name=master_provider_name,
                daily_provider_name=daily_provider_name,
                legacy_candidate_ids=legacy_candidate_ids,
            )
            if is_valid_prior and is_qualified_market_universe_coverage_run(
                prior_run,
                expected_snapshot_id=str(latest_master.get("snapshot_id") or "")
                if latest_master
                else None,
                expected_fingerprint=evidence_fingerprint,
                expected_policy_id=validation_policy_id,
                expected_policy_fingerprint=policy_fingerprint,
                expected_task_key=task_key,
                expected_panel_size=self._policy.panel_size,
                expected_member_count=len(master_members) if latest_master else None,
            ):
                return prior_run

        return None

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
        prior_fail_id = None
        if prior_run and str(prior_run.get("run_id") or "") != base_fail_run_id:
            fail_legacy_ids = market_universe_legacy_candidate_ids(
                master_provider_name=master_provider_name,
                daily_provider_name=daily_provider_name,
                trade_date=trade_date,
                task_key=task_key,
            )
            is_valid, _ = validate_run_predecessor_ancestry(
                prior_run,
                current_run_id=str(prior_run.get("run_id") or ""),
                db=self._db,
                task_key=task_key,
                trade_date=trade_date,
                master_provider_name=master_provider_name,
                daily_provider_name=daily_provider_name,
                legacy_candidate_ids=fail_legacy_ids,
            )
            if is_valid:
                prior_fail_id = str(prior_run.get("run_id") or "")

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

    def _is_failed_run_throttled(
        self,
        *,
        prior_run: Mapping[str, Any] | None,
        validation_policy_id: str,
        policy_fingerprint: str,
        evidence_fingerprint: str | None,
        latest_master: Mapping[str, Any] | None,
        current: datetime,
    ) -> bool:
        if not prior_run or str(prior_run.get("status")) != "failed":
            return False
        try:
            prior_payload = json.loads(str(prior_run.get("payload_json") or "{}"))
        except Exception:
            return False
        if not isinstance(prior_payload, Mapping):
            return False

        has_primary_policy = "validation_policy_id" in prior_payload
        has_alias_policy = "coverage_validation_policy_id" in prior_payload
        policy_present = bool(has_primary_policy or has_alias_policy)
        policy_id_matches = (
            not has_primary_policy
            or prior_payload["validation_policy_id"] == validation_policy_id
        ) and (
            not has_alias_policy
            or prior_payload["coverage_validation_policy_id"] == validation_policy_id
        )
        policy_fp_matches = bool(
            prior_payload.get("policy_fingerprint") == policy_fingerprint
        )
        same_policy = bool(policy_present and policy_id_matches and policy_fp_matches)
        if not same_policy:
            return False

        previous_master = prior_payload.get("market_universe_snapshot_id")
        repaired_master = bool(
            latest_master
            and latest_master.get("source_capture_ids")
            and latest_master.get("snapshot_id") != previous_master
        )
        if repaired_master:
            return False

        if evidence_fingerprint:
            primary_ev = prior_payload.get("evidence_fingerprint")
            coverage_ev = prior_payload.get("coverage_evidence_fingerprint")
            available_fps = [fp for fp in (primary_ev, coverage_ev) if fp is not None]
            if not available_fps:
                return False
            for fp in available_fps:
                if fp != evidence_fingerprint:
                    return False

        if prior_payload.get("retryable") is False:
            return True

        raw_finished = prior_run.get("finished_at")
        if raw_finished:
            try:
                finished = get_shanghai_now(datetime.fromisoformat(str(raw_finished)))
                if current < finished + timedelta(
                    seconds=MARKET_UNIVERSE_AUTOMATION_INTERVAL_SECONDS
                ):
                    return True
            except Exception:
                pass
        return False

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
        has_empty_status = False
        if (
            snapshot is not None
            and callable(capture_lister)
            and snapshot.get("source_capture_ids")
        ):
            try:
                objects = ContentAddressedObjectStore(
                    self._data_store._root / "research" / "objects"
                )
                has_empty_status = _snapshot_has_empty_status_roster(
                    objects, snapshot, trade_date
                )
            except Exception:
                has_empty_status = False

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
            or has_empty_status
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
        snapshot: Mapping[str, Any] | None = None,
        trade_date: str | None = None,
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
            member_metadata = (
                (snapshot.get("member_metadata") or []) if snapshot else []
            )
            current_trade_date = (
                str(trade_date)
                if trade_date
                else (
                    str(snapshot.get("trade_date") or "")
                    if snapshot
                    else (str(trading_dates[-1]) if trading_dates else "")
                )
            )
            for market_date in trading_dates:
                receipt = self._data_store.get_market_daily_ingestion_receipt(
                    trade_date=market_date,
                    provider_name=daily_provider_name,
                )
                if receipt is not None:
                    if not current_trade_date or str(market_date) != str(
                        current_trade_date
                    ):
                        receipt_skipped += 1
                        continue
                    receipt_symbols = set(receipt.get("symbols") or [])
                    expected_symbols = (
                        history_session_symbols(members, member_metadata, market_date)
                        if member_metadata
                        else member_set
                    )
                    halted_symbols = set()
                    if snapshot is not None and str(
                        snapshot.get("trade_date") or ""
                    ) == str(market_date):
                        from data.store import stock_master_nontrading_instruments

                        try:
                            halted_symbols = {
                                key.symbol
                                for key in stock_master_nontrading_instruments(
                                    snapshot, session_date=market_date
                                )
                            }
                        except Exception:
                            halted_symbols = set()
                    scoped_symbols = set()
                    if hasattr(self._data_store, "list_market_daily_scoped_receipts"):
                        try:
                            scopes = self._data_store.list_market_daily_scoped_receipts(
                                trade_date=market_date,
                                provider_name=daily_provider_name,
                                verify=True,
                            )
                            for sc in select_replayable_scoped_receipts(
                                [receipt], scopes
                            ):
                                scoped_symbols.update(sc.get("symbols") or [])
                        except (ValueError, OSError):
                            scoped_symbols = set()
                    covered = receipt_symbols | scoped_symbols | halted_symbols
                    missing_symbols = expected_symbols - covered
                    if not missing_symbols or "source_volumes" in receipt:
                        # The source-volume reader cannot replay additional scopes.
                        # Coverage stays blocked for any remaining symbols.
                        receipt_skipped += 1
                        continue

                    # Unverified missing symbols exist in this partial receipt; attempt bounded recovery
                    if self._throttle_seconds:
                        self._sleep(self._throttle_seconds)
                    remote_attempted += 1
                    try:
                        frame = batch_fetcher(market_date)
                        recovered = frame.loc[
                            frame["symbol"].astype(str).isin(missing_symbols)
                        ].copy()
                        if not recovered.empty:
                            self._data_store.ingest_scoped_market_daily_batch(
                                trade_date=market_date,
                                provider_name=daily_provider_name,
                                bars=recovered,
                                symbols=list(recovered["symbol"].astype(str).unique()),
                            )
                            updated += 1
                        else:
                            receipt_skipped += 1
                    except Exception:
                        failed += 1
                        logger.warning(
                            "Recovery refresh for missing symbols failed for %s",
                            market_date,
                            exc_info=True,
                        )
                        break
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
        blockers: list[str] = []
        missing_receipt_dates = sorted(set(trading_dates) - receipt_dates)
        if missing_receipt_dates:
            blockers.append("full_market_daily_receipt_coverage_incomplete")

        scoped_receipts: list[dict[str, Any]] = []
        if hasattr(self._data_store, "list_market_daily_scoped_receipts"):
            try:
                scoped_receipts = [
                    dict(sc)
                    for sc in self._data_store.list_market_daily_scoped_receipts(
                        provider_name=daily_provider_name,
                        verify=True,
                    )
                ]
            except (ValueError, OSError):
                blockers.append("market_daily_ingestion_receipt_drift")

        scoped_receipts = select_replayable_scoped_receipts(receipts, scoped_receipts)
        frames = self._data_store.load_market_bar_windows(
            symbols=members,
            start_date=start_date.isoformat(),
            end_date=trade_date,
            receipts=[*receipts, *scoped_receipts],
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
        scoped_by_date: dict[str, set[str]] = {}
        for sc in scoped_receipts:
            dt = str(sc.get("trade_date") or "")
            if dt:
                scoped_by_date.setdefault(dt, set()).update(sc.get("symbols") or [])

        partial_dates = []
        missing_symbol_sessions = 0
        for receipt in receipts:
            session = str(receipt["trade_date"])
            if session not in trading_dates:
                continue
            expected = history_session_symbols(members, member_metadata, session)
            receipt_symbols = set(receipt.get("symbols") or [])
            halted_in_session = {
                str(row["symbol"])
                for row in member_metadata
                if row.get("trade_status") == "0"
                and str(row.get("status_session_date") or "") == session
            }
            scoped_symbols = scoped_by_date.get(session, set())
            covered = receipt_symbols | scoped_symbols | halted_in_session
            missing = expected - covered
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
        end_symbols = set(end_receipt.get("symbols") or [])
        scoped_end_symbols = scoped_by_date.get(trade_date, set())
        end_cross_section_count = (
            len(end_symbols | scoped_end_symbols)
            if end_symbols
            else int(end_receipt.get("row_count") or 0)
        )
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
            and not partial_dates
            and ("market_daily_ingestion_receipt_drift" not in blockers),
            "coverage_evidence_fingerprint": compute_market_coverage_evidence_fingerprint(
                snapshot_id=str(snapshot_id or ""),
                trading_dates=trading_dates,
                receipts=receipts,
                members=members,
                member_metadata=member_metadata,
                scoped_receipts=scoped_receipts,
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
            "policy": automation_coverage_policy_dict(self._policy),
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
        trade_scope = payload.get("trade_date")
        if trade_scope is None and status != "blocked":
            trade_scope = run_date
        rec_master = payload.get("security_master_provider")
        rec_daily = payload.get("daily_bar_provider")
        rec_task_key = payload.get("task_key")
        rec_legacy_ids = (
            market_universe_legacy_candidate_ids(
                master_provider_name=rec_master,
                daily_provider_name=rec_daily,
                trade_date=trade_scope,
                task_key=rec_task_key,
            )
            if rec_master and rec_daily and trade_scope
            else (rec_task_key,)
            if rec_task_key
            else None
        )
        current_run_id = run_id
        initial_run_id = run_id
        if status == "blocked":
            is_valid_caller, verified_predecessor = validate_run_predecessor_ancestry(
                {
                    "payload": payload,
                    "source_ref": source_ref,
                    "run_type": MARKET_UNIVERSE_AUTOMATION_RUN_TYPE,
                    "status": "blocked",
                    "run_date": run_date,
                },
                current_run_id=run_id,
                pending_run_date=run_date,
                master_provider_name=rec_master,
                daily_provider_name=rec_daily,
            )
        else:
            is_valid_caller, verified_predecessor = validate_run_predecessor_ancestry(
                {"payload": payload, "source_ref": source_ref},
                current_run_id=run_id,
            )
        if not is_valid_caller:
            verified_predecessor = None
        target_predecessor = verified_predecessor

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
            row_matches_scope, row_payload = _row_matches_market_universe_scope(
                row,
                run_id=str(row.get("run_id") or current_run_id),
                task_key=rec_task_key,
                trade_date=trade_scope,
                master_provider_name=rec_master,
                daily_provider_name=rec_daily,
                legacy_candidate_ids=rec_legacy_ids,
            )
            if (
                status == "completed"
                and existing_status == "completed"
                and row_matches_scope
                and is_qualified_market_universe_coverage_run(
                    row,
                    expected_snapshot_id=payload.get("market_universe_snapshot_id"),
                    expected_fingerprint=payload.get("evidence_fingerprint"),
                    expected_policy_id=payload.get("validation_policy_id"),
                    expected_policy_fingerprint=payload.get("policy_fingerprint"),
                    expected_task_key=payload.get("task_key"),
                    expected_panel_size=self._policy.panel_size,
                    expected_member_count=payload.get("market_universe_member_count"),
                )
            ):
                is_valid_ancestry, _ = validate_run_predecessor_ancestry(
                    row,
                    current_run_id=str(row.get("run_id") or current_run_id),
                    db=self._db,
                    task_key=rec_task_key,
                    trade_date=trade_scope,
                    master_provider_name=rec_master,
                    daily_provider_name=rec_daily,
                    legacy_candidate_ids=rec_legacy_ids,
                )
                if is_valid_ancestry:
                    return row
            if status == "blocked" and existing_status == "blocked":
                if _is_matching_pending_blocked_run(
                    row,
                    run_date=run_date,
                    master_provider_name=rec_master,
                    daily_provider_name=rec_daily,
                ):
                    is_valid_ancestry, _ = validate_run_predecessor_ancestry(
                        row,
                        current_run_id=str(row.get("run_id") or current_run_id),
                        db=self._db,
                        pending_run_date=run_date,
                        master_provider_name=rec_master,
                        daily_provider_name=rec_daily,
                    )
                    if is_valid_ancestry:
                        return row

            colliding_id = str(row.get("run_id") or initial_run_id)
            row_task_key = row_payload.get("task_key")

            if status == "blocked":
                is_valid_ancestry, row_supersedes = validate_run_predecessor_ancestry(
                    row,
                    current_run_id=colliding_id,
                    db=self._db,
                    pending_run_date=run_date,
                    master_provider_name=rec_master,
                    daily_provider_name=rec_daily,
                )
            else:
                is_valid_ancestry, row_supersedes = validate_run_predecessor_ancestry(
                    row,
                    current_run_id=colliding_id,
                    db=self._db,
                    task_key=rec_task_key,
                    trade_date=trade_scope,
                    master_provider_name=rec_master,
                    daily_provider_name=rec_daily,
                    legacy_candidate_ids=rec_legacy_ids,
                )

            expected_task_key = payload.get("task_key")
            if expected_task_key:
                is_same_task = bool(
                    isinstance(row_task_key, str) and row_task_key == expected_task_key
                )
            else:
                is_same_task = bool(row_task_key is None)

            if status == "blocked":
                is_valid_pending_cand = _is_matching_pending_blocked_run(
                    row,
                    run_date=run_date,
                    master_provider_name=rec_master,
                    daily_provider_name=rec_daily,
                )
                if is_valid_pending_cand and is_valid_ancestry:
                    if not target_predecessor:
                        target_predecessor = colliding_id
                    elif row_supersedes and row_supersedes == target_predecessor:
                        target_predecessor = colliding_id
            else:
                if is_same_task and row_matches_scope and is_valid_ancestry:
                    if not target_predecessor:
                        target_predecessor = colliding_id
                    elif row_supersedes and row_supersedes == target_predecessor:
                        target_predecessor = colliding_id

            if status == "blocked":
                if attempt == 0:
                    current_run_id = f"market_universe_sync:pending:{run_date}:{rec_master}:{rec_daily}"
                else:
                    attempt_fp = content_fingerprint(
                        {
                            "initial_run_id": initial_run_id,
                            "run_date": run_date,
                            "master": rec_master,
                            "daily": rec_daily,
                            "attempt": attempt + 1,
                        }
                    )
                    current_run_id = (
                        f"market_universe_sync:pending:{run_date}:{attempt_fp[:16]}"
                    )
            else:
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
