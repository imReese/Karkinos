"""Privacy-minimized Account Truth projection for external strategy research."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
)
from server.ai_runtime.strategy_research_values import (
    SANITIZED_ACCOUNT_EVIDENCE_CONTRACT,
)


def sanitize_account_evidence(evidence: Mapping[str, Any]) -> JsonObject:
    """Allowlist persisted portfolio-risk facts and drop private account values."""
    payload = evidence.get("payload")
    if not isinstance(payload, Mapping):
        raise ExternalResearchInvalidResponseError("account_evidence_payload_invalid")
    summary = payload.get("summary")
    snapshot = payload.get("snapshot")
    risks = payload.get("risks")
    next_step = payload.get("next_step")
    if not isinstance(summary, Mapping) or not isinstance(snapshot, Mapping):
        raise ExternalResearchInvalidResponseError("account_evidence_shape_invalid")
    if summary.get("valuation_status") != "complete":
        raise ExternalResearchInvalidResponseError(
            "account_evidence_valuation_not_complete"
        )
    if snapshot.get("valuation_status") != "complete":
        raise ExternalResearchInvalidResponseError(
            "account_snapshot_valuation_not_complete"
        )
    summary_trade_date = _account_evidence_text(
        summary.get("valuation_trade_date"), "valuation_trade_date"
    )
    snapshot_trade_date = _account_evidence_text(
        snapshot.get("valuation_trade_date"), "snapshot_valuation_trade_date"
    )
    if summary_trade_date != snapshot_trade_date:
        raise ExternalResearchInvalidResponseError(
            "account_evidence_trade_date_mismatch"
        )
    allocation = snapshot.get("allocation")
    grouped = snapshot.get("allocation_grouped")
    if not isinstance(allocation, list) or not isinstance(grouped, list):
        raise ExternalResearchInvalidResponseError(
            "account_evidence_allocation_invalid"
        )
    sanitized_allocation = []
    for item in allocation:
        if not isinstance(item, Mapping):
            raise ExternalResearchInvalidResponseError(
                "account_evidence_allocation_item_invalid"
            )
        sanitized_allocation.append(
            {
                "symbol": _account_evidence_text(item.get("symbol"), "symbol"),
                "asset_class": _account_evidence_text(
                    item.get("asset_class"), "asset_class"
                ),
                "weight": _account_evidence_number(item.get("weight"), "weight"),
            }
        )
    sanitized_groups = []
    for item in grouped:
        if not isinstance(item, Mapping):
            raise ExternalResearchInvalidResponseError(
                "account_evidence_group_item_invalid"
            )
        sanitized_groups.append(
            {
                "asset_class": _account_evidence_text(
                    item.get("asset_class"), "group_asset_class"
                ),
                "weight": _account_evidence_number(item.get("weight"), "group_weight"),
            }
        )
    if not isinstance(risks, list) or not risks:
        raise ExternalResearchInvalidResponseError("account_evidence_risks_invalid")
    sanitized_risks = []
    for item in risks:
        if not isinstance(item, Mapping):
            raise ExternalResearchInvalidResponseError(
                "account_evidence_risk_item_invalid"
            )
        sanitized_risks.append(
            {
                key: _account_evidence_text(item.get(key), f"risk_{key}")
                for key in ("kind", "level", "title", "detail")
            }
        )
    positions_count = summary.get("positions_count")
    if (
        isinstance(positions_count, bool)
        or not isinstance(positions_count, int)
        or positions_count < 0
    ):
        raise ExternalResearchInvalidResponseError(
            "account_evidence_positions_count_invalid"
        )
    using_persistent_cache = summary.get("using_persistent_cache")
    if not isinstance(using_persistent_cache, bool):
        raise ExternalResearchInvalidResponseError(
            "account_evidence_cache_flag_invalid"
        )
    sanitized: JsonObject = {
        "schema_version": SANITIZED_ACCOUNT_EVIDENCE_CONTRACT,
        "as_of": _account_evidence_text(evidence.get("as_of"), "as_of"),
        "status": "complete",
        "summary": {
            "positions_count": positions_count,
            "cash_ratio": _account_evidence_number(
                summary.get("cash_ratio"), "cash_ratio"
            ),
            "current_drawdown": _account_evidence_number(
                summary.get("current_drawdown"),
                "current_drawdown",
                allow_none=True,
            ),
            "quote_status": _account_evidence_text(
                summary.get("quote_status"), "quote_status"
            ),
            "valuation_trade_date": summary_trade_date,
            "valuation_status": "complete",
            "using_persistent_cache": using_persistent_cache,
        },
        "allocation": sanitized_allocation,
        "allocation_grouped": sanitized_groups,
        "risks": sanitized_risks,
        "next_step": _account_evidence_text(next_step, "next_step"),
        "persisted_facts_only": True,
        "authoritative": True,
        "absolute_account_values_redacted": True,
        "valuation_and_ledger_identifiers_redacted": True,
    }
    return json.loads(canonical_json(sanitized))


def _account_evidence_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExternalResearchInvalidResponseError(
            f"account_evidence_{field_name}_invalid"
        )
    return value.strip()


def _account_evidence_number(
    value: Any,
    field_name: str,
    *,
    allow_none: bool = False,
) -> int | float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExternalResearchInvalidResponseError(
            f"account_evidence_{field_name}_invalid"
        )
    if not math.isfinite(value):
        raise ExternalResearchInvalidResponseError(
            f"account_evidence_{field_name}_invalid"
        )
    return value
