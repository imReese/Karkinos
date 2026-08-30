"""Provider-free preview/apply service for one bounded legacy ledger repair."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from domain.portfolio_accounting import total_trade_fee
from server.contracts.content_identity import content_fingerprint
from server.ledger.models import LedgerEntry
from server.persistence.database_serialization import normalize_timestamp
from server.persistence.legacy_fund_trade_duplicate_repair import (
    LegacyFundTradeDuplicateRepairBlocked,
    LegacyFundTradeDuplicateRepairPersistence,
    LegacyFundTradeDuplicateRepairUnitOfWork,
    LegacyFundTradeDuplicateTransactionDecision,
)
from server.persistence.portfolio_trade_repository import validate_trade_projection
from server.persistence.valuation_transaction import ValuationTransactionWriter
from server.projections.legacy_fund_trade_duplicate_correction import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    build_legacy_fund_trade_duplicate_correction_plan,
    legacy_fund_trade_duplicate_group_fingerprint,
    legacy_fund_trade_duplicate_repair_fingerprint,
    resolve_legacy_fund_trade_duplicate_exclusions,
)
from server.projections.service import build_portfolio_projection

LEGACY_FUND_TRADE_DUPLICATE_REPAIR_PREVIEW_SCHEMA_VERSION = (
    "karkinos.legacy_fund_trade_duplicate_repair_preview.v1"
)
LEGACY_FUND_TRADE_DUPLICATE_REPAIR_RESULT_SCHEMA_VERSION = (
    "karkinos.legacy_fund_trade_duplicate_repair_result.v1"
)
LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION = (
    "APPLY APPEND-ONLY LEGACY FUND TRADE DUPLICATE REPAIR"
)

_TRADE_REF_RE = re.compile(r"^trade:([1-9][0-9]*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_FEE_RULE = "legacy_manual_trade"
_LEGACY_COST_METHOD = "moving_average_buy_cost"
_PAIR_FINANCIAL_FIELDS = (
    "amount",
    "quantity",
    "price",
    "commission",
    "gross_amount",
    "net_cash_impact",
)
_EMPTY_EVIDENCE_FIELDS = (
    "estimated_commission",
    "estimated_net_cash_impact",
    "estimated_fee_breakdown_json",
    "estimated_fee_rule_id",
    "estimated_fee_rule_version",
    "settlement_status",
    "settled_at",
    "settlement_source",
    "settlement_source_ref",
    "settlement_note",
    "correction_payload_json",
)

FailureInjector = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class LegacyFundTradeDuplicateRepairCommand:
    command_id: str
    operator_id: str
    preview_fingerprint: str
    confirmation: str


@dataclass(frozen=True, slots=True)
class LegacyFundTradeDuplicateRepairResult:
    status: str
    repair_fingerprint: str
    correction_count: int
    pair_count: int
    valuation_snapshot_id: str
    replayed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (
                LEGACY_FUND_TRADE_DUPLICATE_REPAIR_RESULT_SCHEMA_VERSION
            ),
            "status": self.status,
            "repair_fingerprint": self.repair_fingerprint,
            "correction_count": self.correction_count,
            "pair_count": self.pair_count,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "replayed": self.replayed,
            "provider_contact_performed": False,
            "original_rows_updated_or_deleted": False,
            "authorizes_execution": False,
        }


@dataclass(frozen=True, slots=True)
class _RepairGroup:
    pair_entry_ids: tuple[tuple[int, int], ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _RepairAnalysis:
    status: str
    ledger_rows: tuple[dict[str, Any], ...]
    trade_rows: tuple[dict[str, Any], ...]
    groups: tuple[_RepairGroup, ...]
    ledger_cutoff_id: int
    ledger_fingerprint: str
    repair_fingerprint: str
    preview_fingerprint: str
    blockers: tuple[str, ...]
    existing_authorization_fingerprint: str = ""
    existing_authorized_preview_fingerprint: str = ""

    @property
    def pair_count(self) -> int:
        return sum(len(group.pair_entry_ids) for group in self.groups)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (
                LEGACY_FUND_TRADE_DUPLICATE_REPAIR_PREVIEW_SCHEMA_VERSION
            ),
            "status": self.status,
            "ledger_cutoff_id": self.ledger_cutoff_id,
            "ledger_fingerprint": self.ledger_fingerprint,
            "preview_fingerprint": self.preview_fingerprint,
            "repair_fingerprint": self.repair_fingerprint,
            "pair_count": self.pair_count,
            "affected_fund_count": len(self.groups),
            "group_pair_counts": sorted(
                (len(group.pair_entry_ids) for group in self.groups),
                reverse=True,
            ),
            "blockers": list(self.blockers),
            "required_confirmation": (LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION),
            "canonical_owner_retained": "portfolio_trade",
            "excluded_original_source": "manual",
            "provider_contact_performed": False,
            "database_writes_performed": False,
            "private_financial_values_exposed": False,
            "authorizes_execution": False,
        }


class LegacyFundTradeDuplicateRepairService:
    """Preview by default and append corrections only after exact confirmation."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        now: Callable[[], str] | None = None,
        valuation_transaction_writer: ValuationTransactionWriter | None = None,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self._persistence = LegacyFundTradeDuplicateRepairPersistence(
            database_path,
            now=now or (lambda: datetime.now(timezone.utc).isoformat()),
            valuation_transaction_writer=valuation_transaction_writer,
            failure_injector=failure_injector,
        )

    def preview(self) -> dict[str, Any]:
        """Return privacy-minimized evidence using a SQLite read-only handle."""

        ledger_rows, trade_rows = self._persistence.read_snapshot()
        return _analyze_rows(ledger_rows, trade_rows).to_public_dict()

    def apply(
        self,
        command: LegacyFundTradeDuplicateRepairCommand,
    ) -> LegacyFundTradeDuplicateRepairResult:
        """Append the complete correction batch and valuation atomically."""

        _validate_command(command)
        return self._persistence.run_immediate(
            lambda unit_of_work: _apply_in_unit_of_work(
                unit_of_work,
                command=command,
                authorization_fingerprint=_authorization_fingerprint(command),
            )
        )


def _apply_in_unit_of_work(
    unit_of_work: LegacyFundTradeDuplicateRepairUnitOfWork,
    *,
    command: LegacyFundTradeDuplicateRepairCommand,
    authorization_fingerprint: str,
) -> LegacyFundTradeDuplicateTransactionDecision[LegacyFundTradeDuplicateRepairResult]:
    ledger_rows, trade_rows = unit_of_work.read_snapshot()
    analysis = _analyze_rows(ledger_rows, trade_rows)
    if analysis.status == "already_applied":
        if (
            analysis.existing_authorization_fingerprint == authorization_fingerprint
            and analysis.existing_authorized_preview_fingerprint
            == command.preview_fingerprint
        ):
            return LegacyFundTradeDuplicateTransactionDecision(
                value=LegacyFundTradeDuplicateRepairResult(
                    status="already_applied",
                    repair_fingerprint=analysis.repair_fingerprint,
                    correction_count=len(analysis.groups),
                    pair_count=analysis.pair_count,
                    valuation_snapshot_id="",
                    replayed=True,
                ),
                commit=False,
            )
        raise LegacyFundTradeDuplicateRepairBlocked(
            "legacy_fund_trade_duplicate_existing_correction"
        )
    if analysis.status != "ready":
        raise LegacyFundTradeDuplicateRepairBlocked(*analysis.blockers)
    if analysis.preview_fingerprint != command.preview_fingerprint:
        raise LegacyFundTradeDuplicateRepairBlocked(
            "legacy_fund_trade_duplicate_preview_drifted"
        )

    base_rows = [dict(row) for row in analysis.ledger_rows]
    all_pairs = tuple(
        pair for group in analysis.groups for pair in group.pair_entry_ids
    )
    group_fingerprints = tuple(group.fingerprint for group in analysis.groups)
    correction_rows: list[dict[str, Any]] = []
    for index, group in enumerate(analysis.groups, start=1):
        plan = build_legacy_fund_trade_duplicate_correction_plan(
            ledger_rows=base_rows,
            pair_entry_ids=group.pair_entry_ids,
            repair_fingerprint=analysis.repair_fingerprint,
            group_fingerprint=group.fingerprint,
            authorization_fingerprint=authorization_fingerprint,
            authorized_preview_fingerprint=command.preview_fingerprint,
            batch_group_fingerprints=group_fingerprints,
            batch_pair_entry_ids=all_pairs,
            batch_pair_count=len(all_pairs),
        )
        correction_rows.append(
            unit_of_work.append_correction(
                plan=plan,
                repair_fingerprint=analysis.repair_fingerprint,
                group_fingerprint=group.fingerprint,
                correction_index=index,
            )
        )

    current_rows = unit_of_work.read_ledger_rows()
    resolution = resolve_legacy_fund_trade_duplicate_exclusions(current_rows)
    expected_exclusions = frozenset(left for left, _ in all_pairs)
    if (
        not resolution.valid
        or resolution.excluded_manual_entry_ids != expected_exclusions
        or len(resolution.correction_entry_ids) != len(analysis.groups)
    ):
        raise RuntimeError(
            "persisted legacy fund duplicate correction failed validation"
        )
    _validate_corrected_projection(
        base_rows=base_rows,
        current_rows=current_rows,
        excluded_manual_entry_ids=expected_exclusions,
    )
    unit_of_work.corrections_validated()

    valuation = unit_of_work.publish_valuation(
        candidate_ledger_rows=correction_rows,
    )
    snapshot_id = str(valuation.get("snapshot_id") or "")
    if not snapshot_id:
        raise RuntimeError("valuation snapshot identity is missing")
    return LegacyFundTradeDuplicateTransactionDecision(
        value=LegacyFundTradeDuplicateRepairResult(
            status="applied",
            repair_fingerprint=analysis.repair_fingerprint,
            correction_count=len(correction_rows),
            pair_count=analysis.pair_count,
            valuation_snapshot_id=snapshot_id,
        ),
        commit=True,
    )


def _analyze_rows(
    ledger_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
) -> _RepairAnalysis:
    ledger_identity = _ledger_identity(ledger_rows)
    ledger_cutoff_id = int(ledger_identity["ledger_cutoff_id"])
    ledger_fingerprint = str(ledger_identity["ledger_fingerprint"])
    correction_resolution = resolve_legacy_fund_trade_duplicate_exclusions(ledger_rows)
    correction_rows = [
        row
        for row in ledger_rows
        if row.get("entry_type") == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
        or row.get("source") == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    if correction_rows:
        if not correction_resolution.valid:
            return _analysis_without_groups(
                status="blocked",
                ledger_rows=ledger_rows,
                trade_rows=trade_rows,
                ledger_cutoff_id=ledger_cutoff_id,
                ledger_fingerprint=ledger_fingerprint,
                blockers=correction_resolution.blockers,
            )
        return _already_applied_analysis(
            ledger_rows=ledger_rows,
            trade_rows=trade_rows,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            correction_rows=correction_rows,
            excluded_ids=correction_resolution.excluded_manual_entry_ids,
            repair_fingerprint=correction_resolution.repair_fingerprints[0],
        )

    blockers: list[str] = []
    manual_by_key: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    legacy_by_key: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    manual_by_anchor: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    legacy_by_anchor: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in ledger_rows:
        source = str(row.get("source") or "")
        if source == "manual" and str(row.get("entry_type") or "").startswith("trade_"):
            try:
                identity = _general_trade_identity(row)
            except ValueError:
                continue
            manual_by_key.setdefault(identity, []).append(row)
            manual_by_anchor.setdefault(_trade_anchor(row), []).append(row)
        elif source == "portfolio_trade" and _is_legacy_canonical(row):
            try:
                identity = _general_trade_identity(row)
                anchor = _trade_anchor(row)
            except ValueError:
                blockers.append(
                    "legacy_fund_trade_duplicate_canonical_economics_invalid"
                )
                continue
            legacy_by_key.setdefault(identity, []).append(row)
            legacy_by_anchor.setdefault(anchor, []).append(row)

    pairs: list[tuple[int, int]] = []
    for anchor in sorted(set(manual_by_anchor) & set(legacy_by_anchor)):
        manual_keys = {_general_trade_identity(row) for row in manual_by_anchor[anchor]}
        canonical_keys = {
            _general_trade_identity(row) for row in legacy_by_anchor[anchor]
        }
        if manual_keys != canonical_keys:
            blockers.append("legacy_fund_trade_duplicate_economic_pair_drifted")

    trades_by_id = {int(row["id"]): row for row in trade_rows}
    for identity in sorted(set(manual_by_key) & set(legacy_by_key)):
        manuals = manual_by_key[identity]
        canonicals = legacy_by_key[identity]
        if len(manuals) != 1 or len(canonicals) != 1:
            blockers.append("legacy_fund_trade_duplicate_pair_ambiguous")
            continue
        manual = manuals[0]
        canonical = canonicals[0]
        if identity[-1] != "fund":
            blockers.append("legacy_fund_trade_duplicate_stock_pair_detected")
            continue
        if identity[0] != "trade_buy" or identity[3] != "buy":
            blockers.append("legacy_fund_trade_duplicate_non_buy_pair_detected")
            continue
        try:
            _validate_pair_against_trade(manual, canonical, trades_by_id)
        except (InvalidOperation, RuntimeError, TypeError, ValueError):
            blockers.append("legacy_fund_trade_duplicate_pair_lineage_invalid")
            continue
        pairs.append((int(manual["id"]), int(canonical["id"])))

    if blockers:
        return _analysis_without_groups(
            status="blocked",
            ledger_rows=ledger_rows,
            trade_rows=trade_rows,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            blockers=tuple(sorted(set(blockers))),
        )
    if not pairs:
        return _analysis_without_groups(
            status="no_duplicates",
            ledger_rows=ledger_rows,
            trade_rows=trade_rows,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            blockers=("legacy_fund_trade_duplicate_no_exact_pairs",),
        )

    rows_by_id = {int(row["id"]): row for row in ledger_rows}
    pairs_by_symbol: dict[str, list[tuple[int, int]]] = {}
    for manual_id, canonical_id in pairs:
        symbol = str(rows_by_id[manual_id]["symbol"])
        pairs_by_symbol.setdefault(symbol, []).append((manual_id, canonical_id))
    groups = tuple(
        sorted(
            (
                _RepairGroup(
                    pair_entry_ids=tuple(sorted(group_pairs)),
                    fingerprint=legacy_fund_trade_duplicate_group_fingerprint(
                        ledger_rows=ledger_rows,
                        pair_entry_ids=group_pairs,
                    ),
                )
                for group_pairs in pairs_by_symbol.values()
            ),
            key=lambda group: group.fingerprint,
        )
    )
    all_pairs = tuple(pair for group in groups for pair in group.pair_entry_ids)
    group_fingerprints = tuple(group.fingerprint for group in groups)
    repair_fingerprint = legacy_fund_trade_duplicate_repair_fingerprint(
        ledger_rows=ledger_rows,
        batch_pair_entry_ids=all_pairs,
        batch_group_fingerprints=group_fingerprints,
    )
    preview_fingerprint = _preview_fingerprint(
        status="ready",
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        repair_fingerprint=repair_fingerprint,
        groups=groups,
        trade_rows=trade_rows,
        blockers=(),
    )
    return _RepairAnalysis(
        status="ready",
        ledger_rows=tuple(ledger_rows),
        trade_rows=tuple(trade_rows),
        groups=groups,
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        repair_fingerprint=repair_fingerprint,
        preview_fingerprint=preview_fingerprint,
        blockers=(),
    )


def _already_applied_analysis(
    *,
    ledger_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    ledger_cutoff_id: int,
    ledger_fingerprint: str,
    correction_rows: list[dict[str, Any]],
    excluded_ids: frozenset[int],
    repair_fingerprint: str,
) -> _RepairAnalysis:
    groups: list[_RepairGroup] = []
    authorization_values: set[str] = set()
    preview_values: set[str] = set()
    for row in correction_rows:
        payload = json.loads(str(row["correction_payload_json"]))
        pairs = tuple(
            sorted(
                (
                    int(item["manual_ledger_entry_id"]),
                    int(item["canonical_ledger_entry_id"]),
                )
                for item in payload["pair_evidence"]
            )
        )
        groups.append(
            _RepairGroup(
                pair_entry_ids=pairs,
                fingerprint=str(payload["group_fingerprint"]),
            )
        )
        authorization_values.add(str(payload["authorization_fingerprint"]))
        preview_values.add(str(payload["authorized_preview_fingerprint"]))
    if len(authorization_values) != 1 or len(preview_values) != 1:
        return _analysis_without_groups(
            status="blocked",
            ledger_rows=ledger_rows,
            trade_rows=trade_rows,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            blockers=("legacy_fund_trade_duplicate_authorization_drifted",),
        )
    normalized_groups = tuple(sorted(groups, key=lambda group: group.fingerprint))
    if len(excluded_ids) != sum(len(group.pair_entry_ids) for group in groups):
        raise RuntimeError("validated exclusion cardinality drifted")
    preview_fingerprint = _preview_fingerprint(
        status="already_applied",
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        repair_fingerprint=repair_fingerprint,
        groups=normalized_groups,
        trade_rows=trade_rows,
        blockers=(),
    )
    return _RepairAnalysis(
        status="already_applied",
        ledger_rows=tuple(ledger_rows),
        trade_rows=tuple(trade_rows),
        groups=normalized_groups,
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        repair_fingerprint=repair_fingerprint,
        preview_fingerprint=preview_fingerprint,
        blockers=(),
        existing_authorization_fingerprint=next(iter(authorization_values)),
        existing_authorized_preview_fingerprint=next(iter(preview_values)),
    )


def _analysis_without_groups(
    *,
    status: str,
    ledger_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    ledger_cutoff_id: int,
    ledger_fingerprint: str,
    blockers: tuple[str, ...],
) -> _RepairAnalysis:
    normalized_blockers = tuple(sorted(set(blockers)))
    preview_fingerprint = _preview_fingerprint(
        status=status,
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        repair_fingerprint="",
        groups=(),
        trade_rows=trade_rows,
        blockers=normalized_blockers,
    )
    return _RepairAnalysis(
        status=status,
        ledger_rows=tuple(ledger_rows),
        trade_rows=tuple(trade_rows),
        groups=(),
        ledger_cutoff_id=ledger_cutoff_id,
        ledger_fingerprint=ledger_fingerprint,
        repair_fingerprint="",
        preview_fingerprint=preview_fingerprint,
        blockers=normalized_blockers,
    )


def _preview_fingerprint(
    *,
    status: str,
    ledger_cutoff_id: int,
    ledger_fingerprint: str,
    repair_fingerprint: str,
    groups: tuple[_RepairGroup, ...],
    trade_rows: list[dict[str, Any]],
    blockers: tuple[str, ...],
) -> str:
    return content_fingerprint(
        {
            "schema_version": (
                LEGACY_FUND_TRADE_DUPLICATE_REPAIR_PREVIEW_SCHEMA_VERSION
            ),
            "status": status,
            "ledger_cutoff_id": ledger_cutoff_id,
            "ledger_fingerprint": ledger_fingerprint,
            "repair_fingerprint": repair_fingerprint,
            "group_fingerprints": [group.fingerprint for group in groups],
            "pair_count": sum(len(group.pair_entry_ids) for group in groups),
            "trade_projection_fingerprint": content_fingerprint(
                sorted(trade_rows, key=lambda row: int(row["id"]))
            ),
            "blockers": list(blockers),
        }
    )


def _ledger_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = sorted(
        (dict(row) for row in rows),
        key=lambda row: (int(row.get("id") or 0), str(row.get("timestamp") or "")),
    )
    ids = [int(row["id"]) for row in normalized if row.get("id") is not None]
    return {
        "ledger_cutoff_id": max(ids, default=0),
        "ledger_fingerprint": content_fingerprint(normalized),
    }


def _validate_pair_against_trade(
    manual: dict[str, Any],
    canonical: dict[str, Any],
    trades_by_id: dict[int, dict[str, Any]],
) -> None:
    match = _TRADE_REF_RE.fullmatch(str(canonical.get("source_ref") or ""))
    if match is None:
        raise ValueError("canonical source_ref is invalid")
    trade = trades_by_id.get(int(match.group(1)))
    if trade is None:
        raise ValueError("canonical trade projection is missing")
    validate_trade_projection(trade, canonical)
    if (
        normalize_timestamp(str(canonical.get("created_at") or ""))
        != normalize_timestamp(str(trade.get("created_at") or ""))
        or normalize_timestamp(str(manual.get("created_at") or ""))
        != normalize_timestamp(str(canonical.get("created_at") or ""))
        or str(manual.get("note") or "") != str(canonical.get("note") or "")
    ):
        raise ValueError("legacy lineage timestamps drifted")
    if any(canonical.get(field) not in {None, ""} for field in _EMPTY_EVIDENCE_FIELDS):
        raise ValueError("canonical row has post-migration evidence")
    if any(manual.get(field) not in {None, ""} for field in _EMPTY_EVIDENCE_FIELDS):
        raise ValueError("manual row has post-migration evidence")
    entry = LedgerEntry.from_row(manual)
    recorded_fee = total_trade_fee(
        commission=Decimal(str(entry.commission)),
        fee_breakdown=entry.fee_breakdown,
    )
    if recorded_fee != Decimal(str(manual.get("commission") or 0)):
        raise ValueError("manual fee evidence changes trade economics")


def _is_legacy_canonical(row: dict[str, Any]) -> bool:
    return (
        str(row.get("fee_rule_id") or "") == _LEGACY_FEE_RULE
        and str(row.get("fee_rule_version") or "") == _LEGACY_FEE_RULE
        and str(row.get("cost_basis_method") or "") == _LEGACY_COST_METHOD
        and row.get("fee_breakdown_json") in {None, ""}
    )


def _general_trade_identity(row: dict[str, Any]) -> tuple[str, ...]:
    values = []
    for field in _PAIR_FINANCIAL_FIELDS:
        value = row.get(field)
        if value is None:
            raise ValueError(f"missing {field}")
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError(f"invalid {field}")
        values.append("0" if number == 0 else format(number.normalize(), "f"))
    return (
        str(row.get("entry_type") or "").strip().lower(),
        normalize_timestamp(str(row.get("timestamp") or "")),
        str(row.get("symbol") or "").strip(),
        str(row.get("direction") or "").strip().lower(),
        *values,
        str(row.get("asset_class") or "stock").strip().lower(),
    )


def _trade_anchor(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        normalize_timestamp(str(row.get("timestamp") or "")),
        str(row.get("symbol") or "").strip(),
        str(row.get("entry_type") or "").strip().lower(),
        str(row.get("direction") or "").strip().lower(),
        str(row.get("asset_class") or "stock").strip().lower(),
    )


def _validate_corrected_projection(
    *,
    base_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    excluded_manual_entry_ids: frozenset[int],
) -> None:
    expected = build_portfolio_projection(
        [
            LedgerEntry.from_row(row)
            for row in base_rows
            if int(row["id"]) not in excluded_manual_entry_ids
        ]
    )
    actual = build_portfolio_projection(
        [LedgerEntry.from_row(row) for row in current_rows]
    )
    if _projection_signature(actual) != _projection_signature(expected):
        raise RuntimeError("corrected projection does not equal exclusion replay")


def _projection_signature(projection: Any) -> dict[str, Any]:
    return {
        "cash": _decimal_identity(projection.cash),
        "total_deposits": _decimal_identity(projection.total_deposits),
        "positions": {
            symbol: {
                "quantity": _decimal_identity(position.quantity),
                "available_qty": _decimal_identity(position.available_qty),
                "frozen_qty": _decimal_identity(position.frozen_qty),
                "avg_cost": _decimal_identity(position.avg_cost),
                "realized_pnl": _decimal_identity(position.realized_pnl),
                "commission_paid": _decimal_identity(position.commission_paid),
                "broker_displayed_cost_basis": _decimal_identity(
                    position.broker_displayed_cost_basis
                ),
                "broker_displayed_unit_cost": _decimal_identity(
                    position.broker_displayed_unit_cost
                ),
                "broker_cost_basis_difference": _decimal_identity(
                    position.broker_cost_basis_difference
                ),
                "broker_cost_basis_method": position.broker_cost_basis_method,
                "broker_cost_basis_status": position.broker_cost_basis_status,
            }
            for symbol, position in sorted(projection.positions.items())
        },
    }


def _decimal_identity(value: Any) -> str:
    number = Decimal(str(value))
    return "0" if number == 0 else format(number.normalize(), "f")


def _validate_command(command: LegacyFundTradeDuplicateRepairCommand) -> None:
    if not command.command_id.strip():
        raise ValueError("command_id is required")
    if not command.operator_id.strip():
        raise ValueError("operator_id is required")
    if not _SHA256_RE.fullmatch(command.preview_fingerprint):
        raise ValueError("preview_fingerprint must be a SHA-256 digest")
    if command.confirmation != LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION:
        raise ValueError("exact repair confirmation is required")


def _authorization_fingerprint(
    command: LegacyFundTradeDuplicateRepairCommand,
) -> str:
    return content_fingerprint(
        {
            "command_id": command.command_id,
            "operator_id": command.operator_id,
            "preview_fingerprint": command.preview_fingerprint,
            "confirmation": command.confirmation,
        }
    )


__all__ = [
    "LEGACY_FUND_TRADE_DUPLICATE_REPAIR_CONFIRMATION",
    "LEGACY_FUND_TRADE_DUPLICATE_REPAIR_PREVIEW_SCHEMA_VERSION",
    "LEGACY_FUND_TRADE_DUPLICATE_REPAIR_RESULT_SCHEMA_VERSION",
    "LegacyFundTradeDuplicateRepairBlocked",
    "LegacyFundTradeDuplicateRepairCommand",
    "LegacyFundTradeDuplicateRepairResult",
    "LegacyFundTradeDuplicateRepairService",
]
