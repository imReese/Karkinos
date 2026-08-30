"""Correction planning and persisted exclusion resolution for fund duplicates."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from server.ledger.models import LedgerEntry
from server.persistence.database_serialization import normalize_timestamp
from server.projections.ledger_exclusion_correction import (
    build_ledger_exclusion_correction_plan,
)
from server.projections.legacy_fund_trade_duplicate_contract import (
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
    LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE,
    LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE,
    LegacyFundTradeDuplicateCorrectionError,
    LegacyFundTradeDuplicateExclusionResolution,
    legacy_fund_trade_duplicate_error,
)
from server.projections.legacy_fund_trade_duplicate_evidence import (
    as_finite_decimal,
    build_pair_evidence_item,
    decimal_identity,
    ledger_rows_by_id,
    legacy_fund_trade_duplicate_group_fingerprint,
    legacy_fund_trade_duplicate_repair_fingerprint,
    normalize_pair_entry_ids,
    require_positive_int,
    require_sha256,
    validate_exact_pair,
)
from server.projections.service import build_portfolio_projection

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_legacy_fund_trade_duplicate_correction_plan(
    *,
    ledger_rows: list[dict[str, Any]],
    pair_entry_ids: Sequence[tuple[int, int]],
    repair_fingerprint: str,
    group_fingerprint: str,
    authorization_fingerprint: str,
    authorized_preview_fingerprint: str,
    batch_group_fingerprints: Sequence[str],
    batch_pair_entry_ids: Sequence[tuple[int, int]],
    batch_pair_count: int,
) -> dict[str, Any]:
    """Derive one fund-scoped compensation from exact immutable row pairs."""

    require_sha256(repair_fingerprint, "repair_fingerprint")
    require_sha256(group_fingerprint, "group_fingerprint")
    require_sha256(authorization_fingerprint, "authorization_fingerprint")
    require_sha256(
        authorized_preview_fingerprint,
        "authorized_preview_fingerprint",
    )
    normalized_group_fingerprints = sorted(set(batch_group_fingerprints))
    if (
        not normalized_group_fingerprints
        or group_fingerprint not in normalized_group_fingerprints
    ):
        raise _error("batch_scope_invalid")
    if any(not _SHA256_RE.fullmatch(value) for value in normalized_group_fingerprints):
        raise _error("batch_scope_invalid")
    if batch_pair_count <= 0:
        raise _error("batch_scope_invalid")

    rows_by_id = ledger_rows_by_id(ledger_rows)
    normalized_pairs = normalize_pair_entry_ids(pair_entry_ids)
    normalized_batch_pairs = normalize_pair_entry_ids(batch_pair_entry_ids)
    if batch_pair_count != len(normalized_batch_pairs):
        raise _error("batch_scope_invalid")
    expected_group_fingerprint = legacy_fund_trade_duplicate_group_fingerprint(
        ledger_rows=ledger_rows,
        pair_entry_ids=normalized_pairs,
    )
    if group_fingerprint != expected_group_fingerprint:
        raise _error("group_fingerprint_drifted")
    expected_repair_fingerprint = legacy_fund_trade_duplicate_repair_fingerprint(
        ledger_rows=ledger_rows,
        batch_pair_entry_ids=normalized_batch_pairs,
        batch_group_fingerprints=normalized_group_fingerprints,
    )
    if repair_fingerprint != expected_repair_fingerprint:
        raise _error("repair_fingerprint_drifted")
    manual_ids: list[int] = []
    canonical_ids: list[int] = []
    pair_evidence: list[dict[str, Any]] = []
    symbols: set[str] = set()
    for manual_id, canonical_id in normalized_pairs:
        manual = rows_by_id.get(manual_id)
        canonical = rows_by_id.get(canonical_id)
        if manual is None or canonical is None:
            raise _error("paired_entry_missing")
        identity = validate_exact_pair(manual, canonical)
        symbols.add(identity["symbol"])
        manual_ids.append(manual_id)
        canonical_ids.append(canonical_id)
        pair_evidence.append(build_pair_evidence_item(manual, canonical, identity))
    if len(set(manual_ids)) != len(manual_ids) or len(set(canonical_ids)) != len(
        canonical_ids
    ):
        raise _error("pair_scope_invalid")
    if len(symbols) != 1:
        raise _error("symbol_scope_invalid")

    plan = build_ledger_exclusion_correction_plan(
        ledger_rows=ledger_rows,
        original_entry_ids=manual_ids,
        required_sources={LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE},
        schema_version=LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION,
        correction_identity={
            "repair_fingerprint": repair_fingerprint,
            "group_fingerprint": group_fingerprint,
        },
        blocker_prefix="legacy_fund_trade_duplicate",
        derivation=(
            "canonical_replay_excluding_exact_legacy_manual_fund_trade_duplicates"
        ),
    )
    cash_state = _batch_cash_state_by_group(
        ledger_rows=ledger_rows,
        batch_pair_entry_ids=normalized_batch_pairs,
        batch_group_fingerprints=normalized_group_fingerprints,
    )[group_fingerprint]
    plan["cash_delta"] = cash_state["cash_delta"]
    plan.update(
        {
            "cash_before": cash_state["cash_before"],
            "cash_after": cash_state["cash_after"],
            "cash_allocation": "ordered_batch_absolute_cash_state_v1",
            "repair_ledger_cutoff_id": max(rows_by_id, default=0),
            "repair_ledger_entry_count": len(rows_by_id),
            "canonical_ledger_entry_ids": canonical_ids,
            "pair_evidence": pair_evidence,
            "authorization_fingerprint": authorization_fingerprint,
            "authorized_preview_fingerprint": authorized_preview_fingerprint,
            "batch_group_fingerprints": normalized_group_fingerprints,
            "batch_group_count": len(normalized_group_fingerprints),
            "batch_pair_count": batch_pair_count,
        }
    )
    return plan


def resolve_legacy_fund_trade_duplicate_exclusions(
    ledger_rows: list[dict[str, Any]],
) -> LegacyFundTradeDuplicateExclusionResolution:
    """Validate persisted repairs and return rows safe to omit from trade sums.

    Callers MUST fail closed when ``blockers`` is non-empty and MUST only remove
    ``excluded_manual_entry_ids`` from duplicate-sensitive trade components.
    The full ledger, including correction rows, remains authoritative for the
    shared cash and position projection.
    """

    candidates = [
        dict(row)
        for row in ledger_rows
        if row.get("entry_type") == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
        or row.get("source") == LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    if not candidates:
        return LegacyFundTradeDuplicateExclusionResolution(
            excluded_manual_entry_ids=frozenset(),
            correction_entry_ids=(),
            repair_fingerprints=(),
            blockers=(),
        )

    try:
        resolution = _resolve_exclusions(ledger_rows, candidates)
    except LegacyFundTradeDuplicateCorrectionError as exc:
        return LegacyFundTradeDuplicateExclusionResolution(
            excluded_manual_entry_ids=frozenset(),
            correction_entry_ids=(),
            repair_fingerprints=(),
            blockers=(exc.blocker,),
        )
    except (InvalidOperation, TypeError, ValueError):
        return LegacyFundTradeDuplicateExclusionResolution(
            excluded_manual_entry_ids=frozenset(),
            correction_entry_ids=(),
            repair_fingerprints=(),
            blockers=("legacy_fund_trade_duplicate_correction_invalid",),
        )
    return resolution


def legacy_fund_trade_duplicate_source_ref(
    repair_fingerprint: str,
    group_fingerprint: str,
) -> str:
    require_sha256(repair_fingerprint, "repair_fingerprint")
    require_sha256(group_fingerprint, "group_fingerprint")
    return f"repair:{repair_fingerprint}:group:{group_fingerprint}"


def _resolve_exclusions(
    ledger_rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> LegacyFundTradeDuplicateExclusionResolution:
    rows_by_id = ledger_rows_by_id(ledger_rows)
    parsed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for correction in candidates:
        if (
            correction.get("entry_type")
            != LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
            or correction.get("source") != LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
        ):
            raise _error("correction_contract_mixed")
        payload = _json_object(correction.get("correction_payload_json"))
        if (
            payload.get("schema_version")
            != LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_PLAN_SCHEMA_VERSION
        ):
            raise _error("correction_schema_invalid")
        if payload.get("arbitrary_financial_input_used") is not False:
            raise _error("correction_derivation_invalid")
        parsed.append((correction, payload))

    cutoff_values = {
        require_positive_int(payload.get("repair_ledger_cutoff_id"))
        for _, payload in parsed
    }
    entry_count_values = {
        require_positive_int(payload.get("repair_ledger_entry_count"))
        for _, payload in parsed
    }
    if len(cutoff_values) != 1 or len(entry_count_values) != 1:
        raise _error("repair_cutoff_drifted")
    repair_cutoff_id = next(iter(cutoff_values))
    repair_entry_count = next(iter(entry_count_values))
    if any(
        require_positive_int(row.get("id")) <= repair_cutoff_id for row in candidates
    ):
        raise _error("repair_cutoff_invalid")
    base_rows = [
        dict(row)
        for row in ledger_rows
        if require_positive_int(row.get("id")) <= repair_cutoff_id
        and row.get("entry_type") != LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_ENTRY_TYPE
        and row.get("source") != LEGACY_FUND_TRADE_DUPLICATE_CORRECTION_SOURCE
    ]
    if len(base_rows) != repair_entry_count:
        raise _error("repair_cutoff_drifted")

    by_repair: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for item in parsed:
        repair_fingerprint = str(item[1].get("repair_fingerprint") or "")
        require_sha256(repair_fingerprint, "repair_fingerprint")
        by_repair.setdefault(repair_fingerprint, []).append(item)
    if len(by_repair) != 1:
        raise _error("multiple_repair_batches")

    excluded: set[int] = set()
    used_canonical_ids: set[int] = set()
    correction_ids: list[int] = []
    for repair_fingerprint, batch in sorted(by_repair.items()):
        declared_groups = _string_list(batch[0][1].get("batch_group_fingerprints"))
        declared_pair_count = require_positive_int(batch[0][1].get("batch_pair_count"))
        if len(declared_groups) != require_positive_int(
            batch[0][1].get("batch_group_count")
        ):
            raise _error("batch_scope_invalid")
        actual_groups = sorted(
            str(payload.get("group_fingerprint") or "") for _, payload in batch
        )
        if actual_groups != declared_groups or len(set(actual_groups)) != len(
            actual_groups
        ):
            raise _error("batch_incomplete")

        prepared: list[
            tuple[dict[str, Any], dict[str, Any], str, list[tuple[int, int]]]
        ] = []
        all_batch_pairs: list[tuple[int, int]] = []
        for correction, payload in batch:
            if (
                _string_list(payload.get("batch_group_fingerprints")) != declared_groups
                or require_positive_int(payload.get("batch_pair_count"))
                != declared_pair_count
                or require_positive_int(payload.get("batch_group_count"))
                != len(declared_groups)
            ):
                raise _error("batch_scope_invalid")
            group_fingerprint = str(payload.get("group_fingerprint") or "")
            source_ref = legacy_fund_trade_duplicate_source_ref(
                repair_fingerprint, group_fingerprint
            )
            if correction.get("source_ref") != source_ref:
                raise _error("correction_lineage_invalid")
            pair_evidence = payload.get("pair_evidence")
            if not isinstance(pair_evidence, list) or not pair_evidence:
                raise _error("pair_evidence_invalid")
            pairs: list[tuple[int, int]] = []
            for evidence in pair_evidence:
                if not isinstance(evidence, dict):
                    raise _error("pair_evidence_invalid")
                manual_id = require_positive_int(evidence.get("manual_ledger_entry_id"))
                canonical_id = require_positive_int(
                    evidence.get("canonical_ledger_entry_id")
                )
                manual = rows_by_id.get(manual_id)
                canonical = rows_by_id.get(canonical_id)
                if manual is None or canonical is None:
                    raise _error("paired_entry_missing")
                identity = validate_exact_pair(manual, canonical)
                expected_evidence = build_pair_evidence_item(
                    manual, canonical, identity
                )
                if evidence != expected_evidence:
                    raise _error("pair_evidence_drifted")
                pairs.append((manual_id, canonical_id))
            pairs = normalize_pair_entry_ids(pairs)
            manual_ids = {manual_id for manual_id, _ in pairs}
            canonical_ids = {canonical_id for _, canonical_id in pairs}
            if excluded & manual_ids:
                raise _error("original_scope_overlapped")
            if used_canonical_ids & canonical_ids:
                raise _error("canonical_scope_overlapped")
            excluded.update(manual_ids)
            used_canonical_ids.update(canonical_ids)
            all_batch_pairs.extend(pairs)
            prepared.append((correction, payload, group_fingerprint, pairs))

        all_batch_pairs = normalize_pair_entry_ids(all_batch_pairs)
        if len(all_batch_pairs) != declared_pair_count:
            raise _error("batch_incomplete")
        expected_repair_fingerprint = legacy_fund_trade_duplicate_repair_fingerprint(
            ledger_rows=base_rows,
            batch_pair_entry_ids=all_batch_pairs,
            batch_group_fingerprints=declared_groups,
        )
        if repair_fingerprint != expected_repair_fingerprint:
            raise _error("repair_fingerprint_drifted")

        for correction, payload, group_fingerprint, pairs in prepared:
            expected_plan = build_legacy_fund_trade_duplicate_correction_plan(
                ledger_rows=base_rows,
                pair_entry_ids=pairs,
                repair_fingerprint=repair_fingerprint,
                group_fingerprint=group_fingerprint,
                authorization_fingerprint=str(
                    payload.get("authorization_fingerprint") or ""
                ),
                authorized_preview_fingerprint=str(
                    payload.get("authorized_preview_fingerprint") or ""
                ),
                batch_group_fingerprints=declared_groups,
                batch_pair_entry_ids=all_batch_pairs,
                batch_pair_count=declared_pair_count,
            )
            if payload != expected_plan:
                raise _error("correction_plan_drifted")
            _validate_correction_row(correction, expected_plan)
            correction_ids.append(require_positive_int(correction.get("id")))

    return LegacyFundTradeDuplicateExclusionResolution(
        excluded_manual_entry_ids=frozenset(excluded),
        correction_entry_ids=tuple(sorted(correction_ids)),
        repair_fingerprints=tuple(sorted(by_repair)),
        blockers=(),
    )


def _batch_cash_state_by_group(
    *,
    ledger_rows: list[dict[str, Any]],
    batch_pair_entry_ids: Sequence[tuple[int, int]],
    batch_group_fingerprints: Sequence[str],
) -> dict[str, dict[str, str]]:
    """Allocate exact cash states in persisted correction order."""

    rows_by_id = ledger_rows_by_id(ledger_rows)
    normalized_pairs = normalize_pair_entry_ids(batch_pair_entry_ids)
    pairs_by_symbol: dict[str, list[tuple[int, int]]] = {}
    for manual_id, canonical_id in normalized_pairs:
        identity = validate_exact_pair(
            rows_by_id[manual_id],
            rows_by_id[canonical_id],
        )
        pairs_by_symbol.setdefault(identity["symbol"], []).append(
            (manual_id, canonical_id)
        )

    pairs_by_fingerprint = {
        legacy_fund_trade_duplicate_group_fingerprint(
            ledger_rows=ledger_rows,
            pair_entry_ids=group_pairs,
        ): tuple(sorted(group_pairs))
        for group_pairs in pairs_by_symbol.values()
    }
    ordered_fingerprints = sorted(set(batch_group_fingerprints))
    if set(pairs_by_fingerprint) != set(ordered_fingerprints):
        raise _error("batch_scope_invalid")

    current = build_portfolio_projection(
        [LedgerEntry.from_row(row) for row in ledger_rows]
    )
    all_manual_ids = {manual_id for manual_id, _ in normalized_pairs}
    target = build_portfolio_projection(
        [
            LedgerEntry.from_row(row)
            for row in ledger_rows
            if require_positive_int(row.get("id")) not in all_manual_ids
        ]
    )
    raw_deltas: dict[str, Decimal] = {}
    for fingerprint, group_pairs in pairs_by_fingerprint.items():
        group_manual_ids = {manual_id for manual_id, _ in group_pairs}
        group_target = build_portfolio_projection(
            [
                LedgerEntry.from_row(row)
                for row in ledger_rows
                if require_positive_int(row.get("id")) not in group_manual_ids
            ]
        )
        raw_deltas[fingerprint] = group_target.cash - current.cash

    result: dict[str, dict[str, str]] = {}
    running_cash = current.cash
    for index, fingerprint in enumerate(ordered_fingerprints):
        cash_before = running_cash
        cash_after = (
            target.cash
            if index == len(ordered_fingerprints) - 1
            else cash_before + raw_deltas[fingerprint]
        )
        cash_delta = cash_after - cash_before
        result[fingerprint] = {
            "cash_before": decimal_identity(cash_before),
            "cash_after": decimal_identity(cash_after),
            "cash_delta": decimal_identity(cash_delta),
        }
        running_cash = cash_after
    if running_cash != target.cash:
        raise _error("batch_cash_allocation_invalid")
    return result


def _validate_correction_row(row: dict[str, Any], plan: dict[str, Any]) -> None:
    if str(row.get("symbol") or "") != str(plan["symbol"]):
        raise _error("correction_row_drifted")
    if str(row.get("asset_class") or "").lower() != "fund":
        raise _error("correction_row_drifted")
    if normalize_timestamp(str(row.get("timestamp") or "")) != normalize_timestamp(
        str(plan["effective_at"])
    ):
        raise _error("correction_row_drifted")
    cash_delta = as_finite_decimal(plan["cash_delta"])
    before = plan["position_before"]
    after = plan["position_after"]
    quantity_delta = as_finite_decimal(after["quantity"]) - as_finite_decimal(
        before["quantity"]
    )
    if (
        as_finite_decimal(row.get("amount")) != _sqlite_real_decimal(cash_delta)
        or as_finite_decimal(row.get("quantity"))
        != _sqlite_real_decimal(quantity_delta)
        or as_finite_decimal(row.get("commission") or 0) != 0
        or row.get("direction") is not None
        or row.get("price") is not None
        or row.get("gross_amount") is not None
        or row.get("net_cash_impact") is not None
    ):
        raise _error("correction_row_drifted")


def _sqlite_real_decimal(value: Decimal) -> Decimal:
    """Return SQLite REAL's deterministic Python-float storage identity."""

    return Decimal(str(float(value)))


def _json_object(value: Any) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise _error("correction_payload_invalid")
    return parsed


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _error("batch_scope_invalid")
    values = [str(item) for item in value]
    if values != sorted(set(values)) or any(
        not _SHA256_RE.fullmatch(item) for item in values
    ):
        raise _error("batch_scope_invalid")
    return values


def _error(suffix: str) -> LegacyFundTradeDuplicateCorrectionError:
    return legacy_fund_trade_duplicate_error(suffix)


__all__ = [
    "build_legacy_fund_trade_duplicate_correction_plan",
    "legacy_fund_trade_duplicate_source_ref",
    "resolve_legacy_fund_trade_duplicate_exclusions",
]
