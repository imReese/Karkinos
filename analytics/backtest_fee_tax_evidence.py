"""Deterministic fee and tax component evidence from canonical backtest fills."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

BACKTEST_FEE_TAX_EVIDENCE_SCHEMA_VERSION = "karkinos.backtest_fee_tax_evidence.v1"
_COMPONENT_NAMES = (
    "commission",
    "stamp_tax",
    "transfer_fee",
    "other_fees",
)


def build_backtest_fee_tax_evidence(
    *,
    fills: Iterable[Any],
    cost_model_reference: str,
    account_specific: bool = False,
    fee_schedule_source: str = "canonical_default_estimate",
    fee_schedule_fingerprint: str = "",
    broker_statement_reconciled: bool = False,
    fee_schedule_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate exact per-fill fee/tax fields without changing PnL semantics."""

    fill_list = list(fills)
    issues: list[str] = []
    components = {name: Decimal("0") for name in _COMPONENT_NAMES}
    components["slippage"] = Decimal("0")
    rule_ids: set[str] = set()
    rule_versions: set[str] = set()
    limitations: set[str] = set()

    if not fill_list:
        issues.append("fee_tax_fill_evidence_missing")
    for index, fill in enumerate(fill_list):
        breakdown = getattr(fill, "fee_breakdown", None)
        if not isinstance(breakdown, Mapping):
            issues.append(f"fill_fee_breakdown_missing:{index}")
            continue
        normalized: dict[str, Decimal] = {}
        for name in (*_COMPONENT_NAMES, "total_fee"):
            value = _decimal(breakdown.get(name))
            if value is None or value < 0:
                issues.append(f"fill_fee_component_invalid:{index}:{name}")
            else:
                normalized[name] = value
        if len(normalized) != len(_COMPONENT_NAMES) + 1:
            continue
        component_total = sum(
            (normalized[name] for name in _COMPONENT_NAMES), Decimal("0")
        )
        if component_total != normalized["total_fee"]:
            issues.append(f"fill_fee_component_total_mismatch:{index}")
        fill_commission = _decimal(getattr(fill, "commission", None))
        if fill_commission is None or fill_commission != normalized["total_fee"]:
            issues.append(f"fill_recorded_fee_total_mismatch:{index}")
        slippage = _decimal(getattr(fill, "slippage", None))
        if slippage is None or slippage < 0:
            issues.append(f"fill_slippage_invalid:{index}")
        else:
            components["slippage"] += slippage
        for name in _COMPONENT_NAMES:
            components[name] += normalized[name]

        rule_id = str(
            getattr(fill, "fee_rule_id", None) or breakdown.get("fee_rule_id") or ""
        ).strip()
        rule_version = str(getattr(fill, "fee_rule_version", None) or "").strip()
        if not rule_id:
            issues.append(f"fill_fee_rule_id_missing:{index}")
        else:
            rule_ids.add(rule_id)
        if not rule_version:
            issues.append(f"fill_fee_rule_version_missing:{index}")
        else:
            rule_versions.add(rule_version)
        raw_limitations = breakdown.get("limitations")
        if isinstance(raw_limitations, list):
            limitations.update(str(item) for item in raw_limitations if str(item))

    if not str(cost_model_reference or "").strip():
        issues.append("cost_model_reference_missing")
    issues = list(dict.fromkeys(issues))
    status = "complete" if not issues else "incomplete"
    schedule_binding = {
        str(key): value
        for key, value in dict(fee_schedule_binding or {}).items()
        if str(key)
        in {
            "fee_schedule_review_id",
            "fee_schedule_review_fingerprint",
            "fee_schedule_preview_fingerprint",
            "account_truth_import_run_id",
            "account_truth_source_fingerprint",
            "account_truth_scope_fingerprint",
            "effective_start_date",
            "effective_end_date",
            "fee_notional_envelope_enforced",
            "fee_notional_envelope_fingerprint",
            "fee_notional_covered_asset_classes",
        }
    }
    core = {
        "schema_version": BACKTEST_FEE_TAX_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "cost_model_reference": str(cost_model_reference or "").strip(),
        "fee_rule_id": str(cost_model_reference or "").strip(),
        "fee_rule_version": "|".join(sorted(rule_versions)),
        "account_specific": account_specific,
        "fee_schedule_source": str(fee_schedule_source or "").strip(),
        "fee_schedule_fingerprint": str(fee_schedule_fingerprint or "").strip(),
        "broker_statement_reconciled": broker_statement_reconciled,
        "fee_schedule_binding": schedule_binding,
        "fill_rule_ids": sorted(rule_ids),
        "fill_rule_versions": sorted(rule_versions),
        "fill_count": len(fill_list),
        "includes_taxes": status == "complete",
        "components": {name: format(value, "f") for name, value in components.items()},
        "component_reconciliation_status": (
            "pass" if status == "complete" else "blocked"
        ),
        "issues": issues,
        "model_limitations": sorted(limitations),
        "persisted_fill_evidence_only": True,
        "does_not_recalculate_backtest_pnl": True,
        "human_review_required": True,
        "authorizes_execution": False,
        "does_not_change_capital_authority": True,
        "limitations": [
            *sorted(limitations),
            *(
                []
                if account_specific and broker_statement_reconciled
                else [
                    "The canonical default model is an estimate and is not reviewed Account Truth for this account."
                ]
            ),
        ],
    }
    return {**core, "evidence_fingerprint": _fingerprint(core)}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
