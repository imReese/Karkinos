"""Capacity evidence projection for capital-scaling review windows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from server.services.capital_scaling_evidence_contracts import (
    MAX_SOURCE_ROWS,
    REAL_EXECUTION_MODES,
)
from server.services.capital_scaling_evidence_values import (
    average,
    decimal_string_or_none,
    decimal_value,
    fact,
    json_object,
    nearest_rank,
    parse_datetime,
)


class CapitalScalingCapacityFactMixin:
    """Project reconciled real-fill capacity without granting authority."""

    def _capacity_fact(self, *, start: datetime, end: datetime) -> dict[str, Any]:
        blockers: list[str] = []
        qualifying: list[dict[str, Any]] = []
        incomplete_count = 0
        fill_rows = self._db.list_fills_sync(limit=MAX_SOURCE_ROWS, offset=0)
        if len(fill_rows) >= MAX_SOURCE_ROWS:
            blockers.append("fill_scan_truncated")
        for row in fill_rows:
            occurred_at = parse_datetime(str(row.get("timestamp") or ""))
            if occurred_at is None or occurred_at < start or occurred_at > end:
                continue
            if str(row.get("execution_mode") or "") not in REAL_EXECUTION_MODES:
                continue
            source = str(row.get("source") or "").lower()
            if "paper" in source or "simulat" in source:
                continue
            metadata = json_object(row.get("metadata_json"))
            gross = (decimal_value(row.get("fill_price")) or Decimal("0")) * abs(
                decimal_value(row.get("fill_quantity")) or Decimal("0")
            )
            capacity_limit = decimal_value(metadata.get("capacity_limit_notional"))
            available_liquidity = decimal_value(
                metadata.get("available_liquidity_notional")
            )
            required = (
                row.get("provider_name"),
                row.get("broker_order_id"),
                metadata.get("account_truth_import_run_id"),
                metadata.get("execution_reconciliation_run_id"),
                metadata.get("capacity_model_ref"),
                metadata.get("market_data_ref"),
            )
            if (
                gross <= 0
                or capacity_limit is None
                or capacity_limit <= 0
                or available_liquidity is None
                or available_liquidity <= 0
                or not all(str(item or "").strip() for item in required)
            ):
                incomplete_count += 1
                continue
            slippage = abs(decimal_value(row.get("slippage")) or Decimal("0"))
            qualifying.append(
                {
                    "fill_id": str(row.get("fill_id") or ""),
                    "slippage_bps": slippage / gross * Decimal("10000"),
                    "capacity_utilization_pct": gross / capacity_limit,
                    "liquidity_utilization_pct": gross / available_liquidity,
                    "account_truth_import_run_id": metadata.get(
                        "account_truth_import_run_id"
                    ),
                    "execution_reconciliation_run_id": metadata.get(
                        "execution_reconciliation_run_id"
                    ),
                    "capacity_model_ref": metadata.get("capacity_model_ref"),
                    "market_data_ref": metadata.get("market_data_ref"),
                }
            )
        if not qualifying:
            blockers.append("reconciled_real_fill_capacity_evidence_missing")
        if incomplete_count:
            blockers.append("real_fill_capacity_metadata_incomplete")
        slippages = [item["slippage_bps"] for item in qualifying]
        capacities = [item["capacity_utilization_pct"] for item in qualifying]
        liquidities = [item["liquidity_utilization_pct"] for item in qualifying]
        return fact(
            kind="capacity",
            metrics={
                "fill_count": len(qualifying),
                "incomplete_fill_count": incomplete_count,
                "average_slippage_bps": decimal_string_or_none(average(slippages)),
                "p95_slippage_bps": decimal_string_or_none(
                    nearest_rank(slippages, Decimal("0.95"))
                ),
                "capacity_utilization_pct": decimal_string_or_none(
                    max(capacities) if capacities else None
                ),
                "liquidity_utilization_pct": decimal_string_or_none(
                    max(liquidities) if liquidities else None
                ),
            },
            blockers=blockers,
            source_refs=[
                ref
                for item in qualifying
                for ref in (
                    f"fill:{item['fill_id']}",
                    f"account_truth_import:{item['account_truth_import_run_id']}",
                    f"execution_reconciliation:{item['execution_reconciliation_run_id']}",
                    str(item["capacity_model_ref"]),
                    str(item["market_data_ref"]),
                )
            ],
            assumptions=[
                "Stored fill slippage is monetary impact; basis points divide it by absolute fill notional.",
                "Capacity and liquidity utilization use the explicit per-fill model limits recorded by the reviewed fill producer.",
            ],
            limitations=[
                "Paper, simulated, unlinked, or metadata-incomplete fills cannot support capital scaling.",
                "Maximum utilization is used instead of averaging away a stressed fill.",
            ],
        )
