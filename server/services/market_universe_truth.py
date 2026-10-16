"""Persisted A-share universe truth and deterministic research-panel evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

import pandas as pd

from core.types import BarFrequency, InstrumentKey, Symbol
from data.market_daily_store import is_supported_stock_receipt_identity
from data.store import DataStore, normalize_stock_master_metadata
from domain.instrument import (
    RESEARCH_STOCK_TRADING_RULES_ID,
    a_share_identity,
    make_research_stock,
)
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.ai_runtime.contracts import content_fingerprint

LEGACY_MARKET_UNIVERSE_POLICY_VERSION = "karkinos.market_universe_policy.v2"
MARKET_UNIVERSE_POLICY_VERSION = "karkinos.market_universe_policy.v3"
MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION = "karkinos.market_universe_truth.v2"
RESEARCH_PANEL_SCHEMA_VERSION = "karkinos.research_panel_snapshot.v2"
RESEARCH_POSITION_SIZING_POLICY_VERSION = "karkinos.research_position_sizing_policy.v1"
FULL_MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION = "karkinos.full_market_universe_truth.v1"


class MarketUniverseRejected(ValueError):
    """A stable fail-closed rejection for incomplete or drifting universe evidence."""


@dataclass(frozen=True)
class MarketUniversePolicy:
    """Versioned, non-authorizing policy for stock-only research inputs."""

    panel_size: int = 40
    backfill_candidate_count: int = 160
    minimum_master_member_count: int = 1_000
    minimum_history_rows: int = 60
    allocation_slots: int = 4
    lot_size: int = 100
    fee_buffer_rate: Decimal = Decimal("0.01")
    policy_version: str = MARKET_UNIVERSE_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy_version not in {
            MARKET_UNIVERSE_POLICY_VERSION,
            LEGACY_MARKET_UNIVERSE_POLICY_VERSION,
        }:
            raise MarketUniverseRejected("market_universe_policy_version_invalid")
        if (
            self.panel_size != 40
            and self.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
        ):
            raise MarketUniverseRejected("research_panel_size_must_be_40")
        if (
            self.backfill_candidate_count < self.panel_size
            and self.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
        ):
            raise MarketUniverseRejected("research_panel_backfill_pool_too_small")
        if self.minimum_master_member_count < (
            self.panel_size
            if self.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
            else 1
        ):
            raise MarketUniverseRejected("market_universe_minimum_too_small")
        if not 1 <= self.allocation_slots <= self.panel_size:
            raise MarketUniverseRejected("research_allocation_slots_invalid")
        if self.lot_size <= 0 or self.minimum_history_rows < 2:
            raise MarketUniverseRejected("market_universe_policy_invalid")
        if not Decimal("0") <= self.fee_buffer_rate <= Decimal("0.1"):
            raise MarketUniverseRejected("research_fee_buffer_invalid")

    @property
    def target_weight(self) -> Decimal:
        return Decimal("1") / Decimal(self.allocation_slots)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.policy_version,
            "asset_scope": ["stock"],
            "supported_exchanges": ["BSE", "SSE", "SZSE"],
            "panel_size": self.panel_size,
            "backfill_candidate_count": self.backfill_candidate_count,
            "minimum_master_member_count": self.minimum_master_member_count,
            "minimum_history_rows": self.minimum_history_rows,
            "allocation_slots": self.allocation_slots,
            "lot_size": self.lot_size,
            "fee_buffer_rate": str(self.fee_buffer_rate),
            "target_weight": str(self.target_weight),
            "selection_order": "board_round_robin_then_sha256_symbol_order",
            "model_controls_position_size": False,
            "authorizes_strategy_promotion": False,
            "authorizes_order_creation": False,
            "changes_capital_authority": False,
        }
        if self.policy_version == MARKET_UNIVERSE_POLICY_VERSION:
            result.pop("panel_size")
            result.pop("backfill_candidate_count")
            result["scope_kind"] = "full_declared_market"
            result["selection_order"] = "all_eligible_then_symbol_asc"
            result["trading_rules_id"] = RESEARCH_STOCK_TRADING_RULES_ID
            result["session_eligibility"] = (
                "source_observed_ordinary_name_and_verified_history"
            )
            result["minimum_history_basis"] = "verified_observed_sessions"
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MarketUniversePolicy:
        version = str(value.get("schema_version") or value.get("policy_version") or "")
        return cls(
            policy_version=version,
            panel_size=int(value.get("panel_size", 40)),
            backfill_candidate_count=int(value.get("backfill_candidate_count", 160)),
            minimum_master_member_count=int(
                value.get("minimum_master_member_count", 1000)
            ),
            minimum_history_rows=int(value.get("minimum_history_rows", 60)),
            allocation_slots=int(value.get("allocation_slots", 4)),
            lot_size=int(value.get("lot_size", 100)),
            fee_buffer_rate=Decimal(str(value.get("fee_buffer_rate", "0.01"))),
        )

    @classmethod
    def legacy(cls, **kwargs: Any) -> MarketUniversePolicy:
        return cls(policy_version=LEGACY_MARKET_UNIVERSE_POLICY_VERSION, **kwargs)


def market_deployment_scope(
    policy: MarketUniversePolicy,
    *,
    portfolio_policy_id: str = FORMULA_PORTFOLIO_POLICY_ID,
) -> dict[str, Any]:
    """Scope identity binds rules, never today's changing list of members."""
    core = {
        "universe_policy": policy.to_dict(),
        "portfolio_policy_id": portfolio_policy_id,
    }
    return {
        "scope_kind": "full_declared_market"
        if policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
        else "sampled_development",
        **core,
        "deployment_scope_fingerprint": "sha256:" + content_fingerprint(core),
    }


def normalize_a_share_members(symbols: Sequence[object]) -> list[dict[str, str]]:
    """Normalize a provider's active symbol list to supported SSE/SZSE stocks."""
    members: dict[str, dict[str, str]] = {}
    for raw in symbols:
        symbol = str(raw).strip().split(".", maxsplit=1)[0]
        identity = a_share_identity(symbol)
        if identity is None:
            continue
        members[symbol] = {
            "symbol": symbol,
            "asset_class": "stock",
            **identity,
            "listing_status": "active",
        }
    return [members[symbol] for symbol in sorted(members)]


def require_complete_market_universe_snapshot(
    snapshot: Mapping[str, Any] | None,
    *,
    policy: MarketUniversePolicy,
    expected_trade_date: str | None = None,
    available_as_of: datetime | None = None,
) -> dict[str, Any]:
    """Validate one immutable provider-ingested full-market stock snapshot."""
    if not isinstance(snapshot, Mapping):
        raise MarketUniverseRejected("market_universe_snapshot_missing")
    payload = dict(snapshot)
    version = payload.get("schema_version")
    if version not in {
        "karkinos.market_universe_snapshot.v1",
        "karkinos.market_universe_snapshot.v2",
        "karkinos.market_universe_snapshot.v3",
    }:
        raise MarketUniverseRejected("market_universe_snapshot_contract_invalid")
    if available_as_of is not None and available_as_of.utcoffset() is None:
        raise MarketUniverseRejected("market_universe_as_of_timezone_required")
    if version in {
        "karkinos.market_universe_snapshot.v2",
        "karkinos.market_universe_snapshot.v3",
    }:
        try:
            started, completed, available = (
                datetime.fromisoformat(str(payload[key]))
                for key in (
                    "capture_started_at",
                    "capture_completed_at",
                    "available_at",
                )
            )
            valid_time = (
                all(
                    value.utcoffset() == timedelta(0)
                    for value in (started, completed, available)
                )
                and started <= completed == available
            )
        except (ValueError, TypeError, KeyError):
            valid_time = False
        if not valid_time or any(
            payload.get(key) != value
            for key, value in {
                "availability_basis": "capture_completed_at",
                "observation_basis": "adapter_response",
                "membership_basis": "current_active_stock_master",
                "trade_date_role": "daily_bar_window_end",
                "historical_membership_verified": False,
            }.items()
        ):
            raise MarketUniverseRejected("market_universe_observation_invalid")
        if available_as_of is not None and available > available_as_of:
            raise MarketUniverseRejected("market_universe_observation_unavailable")
    elif available_as_of is not None:
        raise MarketUniverseRejected("market_universe_observation_time_unknown")
    if expected_trade_date and payload.get("trade_date") != expected_trade_date:
        raise MarketUniverseRejected("market_universe_snapshot_date_mismatch")
    members = payload.get("members")
    if (
        not isinstance(members, list)
        or len(members) < policy.minimum_master_member_count
    ):
        raise MarketUniverseRejected("market_universe_snapshot_incomplete")
    if int(payload.get("member_count") or 0) != len(members):
        raise MarketUniverseRejected("market_universe_member_count_mismatch")
    normalized = normalize_a_share_members(
        [member.get("symbol") for member in members if isinstance(member, Mapping)]
    )
    if normalized != members:
        raise MarketUniverseRejected("market_universe_members_not_canonical")
    if (
        version == "karkinos.market_universe_snapshot.v3"
        and normalize_stock_master_metadata(
            payload.get("member_metadata") or [], members
        )
        != payload.get("member_metadata")
    ):
        raise MarketUniverseRejected("market_universe_metadata_not_canonical")
    snapshot_id = str(payload.get("snapshot_id") or "")
    core = dict(payload)
    core.pop("snapshot_id", None)
    expected_id = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                core,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    if snapshot_id != expected_id:
        raise MarketUniverseRejected("market_universe_snapshot_fingerprint_mismatch")
    return payload


def market_universe_observation(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Describe observation timing without turning an active list into historical PIT."""
    fields = (
        "capture_started_at",
        "capture_completed_at",
        "available_at",
        "availability_basis",
        "observation_basis",
        "membership_basis",
        "trade_date_role",
    )
    return {
        **{key: snapshot.get(key) for key in fields},
        "historical_membership_verified": False,
    }


def _member_session_exclusion(snapshot: Mapping[str, Any], symbol: str) -> str | None:
    metadata: Mapping[str, Any] = next(
        (
            row
            for row in snapshot.get("member_metadata", [])
            if row.get("symbol") == symbol
        ),
        {},
    )
    session = str(snapshot.get("trade_date") or "")
    delisted = metadata.get("delist_date")
    status = metadata.get("list_status")
    if (delisted and str(delisted) <= session) or (
        status in {"P", "G", "UN"} or (status == "D" and not delisted)
    ):
        return "inactive_listing_excluded"
    if status is not None and status not in {"L", "D", "P", "G", "UN"}:
        return "trading_state_unverified"
    listed = metadata.get("list_date")
    if listed and str(listed) > session:
        return "not_yet_listed_excluded"
    if "trade_status" in metadata:
        if metadata.get("status_session_date") != session or metadata.get(
            "status_capture_id"
        ) not in snapshot.get("source_capture_ids", []):
            return "trading_state_unverified"
        if metadata["trade_status"] == "0":
            return "nontrading_session_excluded"
    name = str(metadata.get("display_name") or "").strip()
    if not name or name == symbol or name == f"{symbol} A股":
        return "trading_state_unverified"
    if "ST" in name.upper():
        return "special_treatment_excluded"
    if "退" in name:
        return "delisting_period_excluded"
    if name.startswith(("N", "C")) and len(name) > 1 and not name[1].isascii():
        return "special_listing_period_excluded"
    return None


def market_master_buy_instruments(
    snapshot: Mapping[str, Any],
    policy: MarketUniversePolicy,
    *,
    require_status: bool = True,
) -> tuple[InstrumentKey, ...]:
    """Apply named ordinary-session scope before planning provider requests."""
    eligible = []
    unknown = 0
    for member in snapshot["members"]:
        symbol = str(member["symbol"])
        reason = (
            _member_session_exclusion(snapshot, symbol)
            if policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
            else None
        )
        if reason == "trading_state_unverified":
            unknown += 1
        if reason is None:
            eligible.append(InstrumentKey.from_values(symbol, "stock"))
    if unknown and require_status:
        raise MarketUniverseRejected("market_universe_trading_state_unverified")
    if not eligible:
        raise MarketUniverseRejected("market_universe_eligible_members_missing")
    return tuple(
        sorted(eligible, key=lambda key: (key.instrument_type.value, key.symbol))
    )


def preliminary_research_panel_symbols(
    snapshot: Mapping[str, Any],
    *,
    policy: MarketUniversePolicy,
) -> tuple[str, ...]:
    """Select a deterministic overcomplete backfill pool from the full market."""
    verified = require_complete_market_universe_snapshot(snapshot, policy=policy)
    members = [dict(member) for member in verified["members"]]
    return tuple(
        member["symbol"]
        for member in _round_robin_ranked_members(
            members,
            limit=policy.backfill_candidate_count,
            policy_version=policy.policy_version,
        )
    )


def build_market_universe_truth(
    *,
    data_store: DataStore,
    snapshot: Mapping[str, Any],
    start_date: str,
    end_date: str,
    initial_cash: float,
    receipt_fingerprints: Sequence[str] = (),
    required_trading_date_count: int = 0,
    policy: MarketUniversePolicy | None = None,
    frames: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Build the declared scope, retaining explicit legacy 40-stock selection."""
    active_policy = policy or MarketUniversePolicy()
    verified = require_complete_market_universe_snapshot(
        snapshot,
        policy=active_policy,
        expected_trade_date=end_date,
    )
    cash = Decimal(str(initial_cash))
    if not cash.is_finite() or cash <= 0:
        raise MarketUniverseRejected("research_initial_cash_invalid")
    try:
        if date.fromisoformat(start_date) > date.fromisoformat(end_date):
            raise MarketUniverseRejected("research_window_invalid")
    except ValueError as exc:
        raise MarketUniverseRejected("research_window_invalid") from exc
    normalized_receipt_fingerprints = tuple(
        str(item) for item in receipt_fingerprints if str(item)
    )
    if (
        required_trading_date_count < 0
        or bool(normalized_receipt_fingerprints) != bool(required_trading_date_count)
        or len(normalized_receipt_fingerprints) != required_trading_date_count
    ):
        raise MarketUniverseRejected("research_daily_receipt_binding_invalid")

    member_by_symbol = {
        str(member["symbol"]): dict(member) for member in verified["members"]
    }
    if frames is None:
        frames = data_store.load_market_bar_windows(
            symbols=sorted(member_by_symbol),
            start_date=start_date,
            end_date=end_date,
        )
    eligible: list[dict[str, Any]] = []
    excluded_reason_counts: dict[str, int] = {}
    for symbol_text, member in sorted(member_by_symbol.items()):
        state_reason = (
            _member_session_exclusion(verified, symbol_text)
            if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
            else None
        )
        if state_reason:
            excluded_reason_counts[state_reason] = (
                excluded_reason_counts.get(state_reason, 0) + 1
            )
            continue
        assessment = _assess_member_frame(
            frame=frames.get(symbol_text),
            member=member_by_symbol[symbol_text],
            start_date=start_date,
            end_date=end_date,
            minimum_history_rows=active_policy.minimum_history_rows,
            lot_size=int(make_research_stock(symbol_text, symbol_text).lot_size)
            if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
            else active_policy.lot_size,
            fee_buffer_rate=active_policy.fee_buffer_rate,
            per_name_budget=cash * active_policy.target_weight,
            enforce_lot_feasibility=True,
        )
        if assessment["status"] == "eligible":
            eligible.append(assessment)
            continue
        reason = str(assessment["reason"])
        excluded_reason_counts[reason] = excluded_reason_counts.get(reason, 0) + 1

    selected = (
        _round_robin_ranked_members(
            eligible,
            limit=active_policy.panel_size,
            policy_version=active_policy.policy_version,
        )
        if active_policy.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
        else sorted(eligible, key=lambda member: str(member["symbol"]))
    )
    if not selected or (
        active_policy.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
        and len(selected) != active_policy.panel_size
    ):
        raise MarketUniverseRejected(
            "research_panel_incomplete:"
            f"eligible={len(eligible)}:required={active_policy.panel_size}"
        )

    capital_binding_fingerprint = "sha256:" + content_fingerprint(
        {
            "initial_cash": str(cash),
            "position_sizing_policy": active_policy.to_dict(),
        }
    )
    panel_core = {
        "schema_version": RESEARCH_PANEL_SCHEMA_VERSION
        if active_policy.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
        else "karkinos.research_panel_snapshot.v3",
        "market_universe_snapshot_id": verified["snapshot_id"],
        "trade_date": end_date,
        "start_date": start_date,
        "symbols": [member["symbol"] for member in selected],
        "asset_classes": ["stock"] * len(selected),
        "member_count": len(selected),
        "selection_policy_version": active_policy.policy_version,
        "selection_order": active_policy.to_dict()["selection_order"],
        "capital_binding_fingerprint": capital_binding_fingerprint,
        "contains_account_identifier": False,
        "contains_absolute_balance": False,
        "contains_holding_quantity": False,
        "provider_contacted_during_build": False,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "changes_capital_authority": False,
    }
    panel_fingerprint = "sha256:" + content_fingerprint(panel_core)
    panel = {**panel_core, "panel_fingerprint": panel_fingerprint}
    truth_core = {
        "schema_version": MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION,
        "status": "complete",
        "market_universe_snapshot_id": verified["snapshot_id"],
        "market_universe_trade_date": verified["trade_date"],
        "active_stock_member_count": len(verified["members"]),
        "research_backfill_pool_count": len(member_by_symbol),
        "research_screened_stock_count": len(member_by_symbol),
        "research_eligible_count": len(eligible),
        "excluded_reason_counts": dict(sorted(excluded_reason_counts.items())),
        "required_trading_date_count": required_trading_date_count,
        "daily_receipt_fingerprints": list(normalized_receipt_fingerprints),
        "receipt_bound_history": bool(normalized_receipt_fingerprints),
        "research_panel": panel,
        "position_sizing_policy": {
            "schema_version": RESEARCH_POSITION_SIZING_POLICY_VERSION,
            "allocation_slots": active_policy.allocation_slots,
            "target_weight": str(active_policy.target_weight),
            "lot_size": active_policy.lot_size,
            "fee_buffer_rate": str(active_policy.fee_buffer_rate),
            "model_controls_position_size": False,
            "capital_binding_fingerprint": capital_binding_fingerprint,
        },
        "stock_only": True,
        "etf_or_fund_candidate_count": 0,
        "provider_contacted_during_build": False,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "changes_capital_authority": False,
    }
    if verified["schema_version"] in {
        "karkinos.market_universe_snapshot.v2",
        "karkinos.market_universe_snapshot.v3",
    }:
        truth_core["market_universe_observation"] = market_universe_observation(
            verified
        )
    if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION:
        unresolved_reasons = {
            "trading_state_unverified",
            "persisted_bars_missing",
            "market_date_missing",
            "ohlcv_incomplete",
            "ohlcv_invalid",
        }
        unresolved = sum(
            count
            for reason, count in excluded_reason_counts.items()
            if reason in unresolved_reasons
        )
        truth_core.update(
            schema_version="karkinos.market_universe_truth.v3",
            universe_policy=active_policy.to_dict(),
            deployment_scope=market_deployment_scope(active_policy),
            coverage={
                "expected": len(member_by_symbol),
                "evaluated": len(eligible),
                "excluded": len(member_by_symbol) - len(eligible) - unresolved,
                "unresolved": unresolved,
                "as_of": verified.get("available_at"),
            },
            status="complete" if unresolved == 0 else "incomplete",
        )
    return {
        **truth_core,
        "evidence_fingerprint": "sha256:" + content_fingerprint(truth_core),
    }


def build_full_market_universe_truth(
    *,
    snapshot: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    receipts: Sequence[Mapping[str, Any]],
    required_trading_dates: Sequence[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    target_weight: float,
    held_symbols: Sequence[str],
    minimum_history_rows: int,
    policy: MarketUniversePolicy | None = None,
) -> dict[str, Any]:
    """Build a deterministic full-stock buy pool plus held-stock exit lane."""

    active_policy = policy or MarketUniversePolicy()
    verified = require_complete_market_universe_snapshot(
        snapshot,
        policy=active_policy,
        expected_trade_date=end_date,
    )
    cash = Decimal(str(initial_cash))
    weight = Decimal(str(target_weight))
    if (
        not cash.is_finite()
        or cash <= 0
        or not weight.is_finite()
        or weight <= 0
        or weight > 1
        or minimum_history_rows < 2
    ):
        raise MarketUniverseRejected("full_market_capital_policy_invalid")
    required_dates = tuple(
        sorted(dict.fromkeys(str(item) for item in required_trading_dates))
    )
    if not required_dates or required_dates[-1] != end_date:
        raise MarketUniverseRejected("full_market_trading_date_evidence_incomplete")
    receipt_by_date = {
        str(receipt.get("trade_date") or ""): dict(receipt) for receipt in receipts
    }
    if set(required_dates) - set(receipt_by_date):
        raise MarketUniverseRejected("full_market_daily_receipt_coverage_incomplete")
    provider_name = str(verified.get("provider_name") or "")
    receipt_fingerprints: list[str] = []
    for market_date in required_dates:
        receipt = receipt_by_date[market_date]
        fingerprint = str(receipt.get("receipt_fingerprint") or "")
        if not is_supported_stock_receipt_identity(
            receipt
        ) or not fingerprint.startswith("sha256:"):
            raise MarketUniverseRejected("full_market_daily_receipt_invalid")
        receipt_fingerprints.append(fingerprint)

    member_by_symbol = {
        str(member["symbol"]): dict(member) for member in verified["members"]
    }
    held = tuple(sorted(dict.fromkeys(str(symbol) for symbol in held_symbols)))
    missing_holdings = sorted(set(held) - set(member_by_symbol))
    blockers = [
        f"holding_outside_active_stock_universe:{symbol}" for symbol in missing_holdings
    ]
    eligible_symbols: list[str] = []
    maintenance_symbols: list[str] = []
    excluded_reason_counts: dict[str, int] = {}
    per_name_budget = cash * weight
    for symbol, member in member_by_symbol.items():
        state_reason = (
            _member_session_exclusion(verified, symbol)
            if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
            else None
        )
        assessment = (
            {"status": "excluded", "reason": state_reason}
            if state_reason
            else _assess_member_frame(
                frame=frames.get(symbol),
                member=member,
                start_date=start_date,
                end_date=end_date,
                minimum_history_rows=minimum_history_rows,
                lot_size=int(make_research_stock(symbol, symbol).lot_size)
                if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
                else active_policy.lot_size,
                fee_buffer_rate=active_policy.fee_buffer_rate,
                per_name_budget=per_name_budget,
                enforce_lot_feasibility=True,
            )
        )
        if assessment["status"] == "eligible":
            eligible_symbols.append(symbol)
        else:
            reason = str(assessment["reason"])
            excluded_reason_counts[reason] = excluded_reason_counts.get(reason, 0) + 1
        if symbol not in held:
            continue
        maintenance = _assess_member_frame(
            frame=frames.get(symbol),
            member=member,
            start_date=start_date,
            end_date=end_date,
            minimum_history_rows=minimum_history_rows,
            lot_size=int(make_research_stock(symbol, symbol).lot_size)
            if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION
            else active_policy.lot_size,
            fee_buffer_rate=active_policy.fee_buffer_rate,
            per_name_budget=per_name_budget,
            enforce_lot_feasibility=False,
        )
        if maintenance["status"] == "eligible":
            maintenance_symbols.append(symbol)
        else:
            blockers.append(
                f"holding_exit_evidence_incomplete:{symbol}:{maintenance['reason']}"
            )
    if len(eligible_symbols) < (
        active_policy.panel_size
        if active_policy.policy_version == LEGACY_MARKET_UNIVERSE_POLICY_VERSION
        else 1
    ):
        blockers.append("full_market_eligible_stock_pool_too_small")
    blockers = list(dict.fromkeys(blockers))
    unresolved = 0
    if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION:
        unresolved = sum(
            count
            for reason, count in excluded_reason_counts.items()
            if reason
            in {
                "persisted_bars_missing",
                "market_date_missing",
                "ohlcv_incomplete",
                "ohlcv_invalid",
                "trading_state_unverified",
            }
        )
        if unresolved:
            blockers.append("full_market_evidence_incomplete")
    capital_binding_fingerprint = "sha256:" + content_fingerprint(
        {
            "initial_cash": str(cash),
            "target_weight": str(weight),
            "lot_size": active_policy.lot_size,
            "fee_buffer_rate": str(active_policy.fee_buffer_rate),
        }
    )
    core = {
        "schema_version": FULL_MARKET_UNIVERSE_TRUTH_SCHEMA_VERSION,
        "status": "complete" if not blockers else "blocked",
        "trade_date": end_date,
        "start_date": start_date,
        "market_universe_snapshot_id": verified["snapshot_id"],
        "provider_name": provider_name,
        "active_stock_member_count": len(member_by_symbol),
        "eligible_stock_count": len(eligible_symbols),
        "eligible_symbols": eligible_symbols,
        "maintenance_symbols": maintenance_symbols,
        "excluded_reason_counts": dict(sorted(excluded_reason_counts.items())),
        "minimum_history_rows": minimum_history_rows,
        "required_trading_date_count": len(required_dates),
        "daily_receipt_fingerprints": receipt_fingerprints,
        "capital_binding_fingerprint": capital_binding_fingerprint,
        "selection_order": "formula_signal_then_liquidity_desc_then_symbol_asc",
        "blockers": blockers,
        "stock_only": True,
        "etf_or_fund_candidate_count": 0,
        "provider_contacted_during_build": False,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "changes_capital_authority": False,
    }
    if verified["schema_version"] in {
        "karkinos.market_universe_snapshot.v2",
        "karkinos.market_universe_snapshot.v3",
    }:
        core["market_universe_observation"] = market_universe_observation(verified)
    if active_policy.policy_version == MARKET_UNIVERSE_POLICY_VERSION:
        core["deployment_scope"] = market_deployment_scope(active_policy)
        core["coverage"] = {
            "expected": len(member_by_symbol),
            "evaluated": len(eligible_symbols),
            "excluded": len(member_by_symbol) - len(eligible_symbols) - unresolved,
            "unresolved": unresolved,
            "as_of": verified.get("available_at"),
        }
    return {**core, "evidence_fingerprint": "sha256:" + content_fingerprint(core)}


def _assess_member_frame(
    *,
    frame: pd.DataFrame | None,
    member: dict[str, Any],
    start_date: str,
    end_date: str,
    minimum_history_rows: int,
    lot_size: int,
    fee_buffer_rate: Decimal,
    per_name_budget: Decimal,
    enforce_lot_feasibility: bool,
) -> dict[str, Any]:
    if frame is None or frame.empty or "timestamp" not in frame.columns:
        return {**member, "status": "excluded", "reason": "persisted_bars_missing"}
    window = frame.copy()
    window["timestamp"] = pd.to_datetime(window["timestamp"])
    window = window.loc[
        (window["timestamp"] >= pd.Timestamp(start_date))
        & (
            window["timestamp"]
            <= pd.Timestamp(end_date)
            + pd.Timedelta(days=1)
            - pd.Timedelta(microseconds=1)
        )
    ].sort_values("timestamp")
    if len(window) < minimum_history_rows:
        return {**member, "status": "excluded", "reason": "history_too_short"}
    if window["timestamp"].iloc[-1].date().isoformat() != end_date:
        return {**member, "status": "excluded", "reason": "market_date_missing"}
    required_columns = ("open", "high", "low", "close", "volume")
    if any(column not in window.columns for column in required_columns):
        return {**member, "status": "excluded", "reason": "ohlcv_incomplete"}
    numeric = window.loc[:, required_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not numeric.map(math.isfinite).all().all():
        return {**member, "status": "excluded", "reason": "ohlcv_invalid"}
    latest_close = Decimal(str(numeric["close"].iloc[-1]))
    if latest_close <= 0 or Decimal(str(numeric["volume"].tail(20).median())) <= 0:
        return {**member, "status": "excluded", "reason": "not_tradable"}
    buffered_lot_cost = (
        latest_close * Decimal(lot_size) * (Decimal("1") + fee_buffer_rate)
    )
    if enforce_lot_feasibility and buffered_lot_cost > per_name_budget:
        return {
            **member,
            "status": "excluded",
            "reason": "one_lot_not_feasible_under_local_policy",
        }
    return {
        **member,
        "status": "eligible",
        "reason": None,
        "history_row_count": len(window),
        "market_date_present": True,
        "one_lot_feasible": True,
    }


def _round_robin_ranked_members(
    members: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    policy_version: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for raw in members:
        member = dict(raw)
        board = str(member.get("board") or "unknown")
        buckets.setdefault(board, []).append(member)
    for bucket in buckets.values():
        bucket.sort(
            key=lambda member: (
                hashlib.sha256(
                    f"{policy_version}:{member['symbol']}".encode("utf-8")
                ).hexdigest(),
                str(member["symbol"]),
            )
        )
    ordered_buckets = [buckets[name] for name in sorted(buckets)]
    selected: list[dict[str, Any]] = []
    offset = 0
    while len(selected) < limit:
        added = False
        for bucket in ordered_buckets:
            if offset < len(bucket):
                selected.append(bucket[offset])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        offset += 1
    return selected
