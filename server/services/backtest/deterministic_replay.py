"""Deterministic replay comparator for backtest runs and services.

Verifies deterministic execution across independent engine and service runs
under identical inputs, preserving Decimal financial precision, order linkage,
execution phase, session date, and execution audits.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from backtest.result import BacktestResult
from core.events import FillEvent
from core.types import ZERO


def _to_decimal(value: Any) -> Decimal:
    """Preserve exact Decimal precision for financial fields without float loss."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _extract_fills(run: Any) -> list[dict[str, Any]]:
    if isinstance(run, BacktestResult):
        raw_fills = run.fills
    elif isinstance(run, dict):
        raw_fills = run.get("fills", [])
    else:
        raw_fills = getattr(run, "fills", [])

    extracted = []
    for fill in raw_fills:
        if isinstance(fill, FillEvent):
            metadata = dict(fill.metadata) if fill.metadata else {}
            price = getattr(fill, "fill_price", getattr(fill, "price", None))
            qty = getattr(fill, "fill_quantity", getattr(fill, "quantity", None))
            extracted.append(
                {
                    "symbol": str(fill.symbol),
                    "side": fill.side.value
                    if hasattr(fill.side, "value")
                    else str(fill.side),
                    "price": _to_decimal(price),
                    "quantity": _to_decimal(qty),
                    "commission": _to_decimal(fill.commission),
                    "slippage": _to_decimal(fill.slippage),
                    "timestamp": fill.timestamp.isoformat()
                    if hasattr(fill.timestamp, "isoformat")
                    else str(fill.timestamp),
                    "order_id": str(fill.order_id)
                    if fill.order_id is not None
                    else None,
                    "fill_id": str(fill.fill_id)
                    if hasattr(fill, "fill_id") and fill.fill_id is not None
                    else None,
                    "execution_phase": metadata.get("execution_phase"),
                    "session_date": str(metadata.get("session_date"))
                    if metadata.get("session_date")
                    else None,
                    "bar_timestamp": str(metadata.get("bar_timestamp"))
                    if metadata.get("bar_timestamp")
                    else None,
                    "execution_model": metadata.get("execution_model"),
                    "metadata": metadata,
                }
            )
        elif isinstance(fill, dict):
            metadata = dict(fill.get("metadata") or {})
            price = fill.get("price") if "price" in fill else fill.get("fill_price")
            qty = (
                fill.get("quantity")
                if "quantity" in fill
                else fill.get("fill_quantity")
            )
            extracted.append(
                {
                    "symbol": str(fill.get("symbol", "")),
                    "side": str(fill.get("side", "")),
                    "price": _to_decimal(price),
                    "quantity": _to_decimal(qty),
                    "commission": _to_decimal(fill.get("commission")),
                    "slippage": _to_decimal(fill.get("slippage")),
                    "timestamp": str(fill.get("timestamp", "")),
                    "order_id": str(fill["order_id"])
                    if fill.get("order_id") is not None
                    else None,
                    "fill_id": str(fill["fill_id"])
                    if fill.get("fill_id") is not None
                    else None,
                    "execution_phase": fill.get("execution_phase")
                    or metadata.get("execution_phase"),
                    "session_date": str(
                        fill.get("session_date") or metadata.get("session_date") or ""
                    ),
                    "bar_timestamp": str(
                        fill.get("bar_timestamp") or metadata.get("bar_timestamp") or ""
                    ),
                    "execution_model": fill.get("execution_model")
                    or metadata.get("execution_model"),
                    "metadata": metadata,
                }
            )
    return extracted


def _extract_audits(run: Any) -> list[dict[str, Any]]:
    if isinstance(run, dict):
        audits = run.get("fill_execution_audits")
        if audits is None and "metrics_json" in run:
            audits = run["metrics_json"].get("fill_execution_audits")
        if audits is None and "evidence" in run:
            audits = run["evidence"].get("fill_execution_audits")
        return [dict(a) for a in (audits or [])]
    return []


def _extract_equity_curve(run: Any) -> list[tuple[str, Any]]:
    if isinstance(run, BacktestResult):
        return [
            (ts.isoformat() if hasattr(ts, "isoformat") else str(ts), eq)
            for ts, eq in run.equity_curve
        ]
    elif isinstance(run, dict):
        curve = run.get("equity_curve", [])
        extracted = []
        for item in curve:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                ts, eq = item
                extracted.append(
                    (ts.isoformat() if hasattr(ts, "isoformat") else str(ts), eq)
                )
            elif isinstance(item, dict):
                ts = str(item.get("timestamp", ""))
                eq = item.get("equity")
                extracted.append((ts, eq))
        return extracted
    return []


def _extract_positions(run: Any) -> dict[str, dict[str, Decimal]]:
    raw_pos = {}
    if isinstance(run, BacktestResult):
        raw_pos = run.positions
    elif isinstance(run, dict):
        raw_pos = run.get("positions", {})

    extracted = {}
    for sym, pos in raw_pos.items():
        sym_str = str(sym)
        if hasattr(pos, "quantity"):
            extracted[sym_str] = {
                "quantity": _to_decimal(pos.quantity),
                "available_qty": _to_decimal(getattr(pos, "available_qty", ZERO)),
                "unlisted_qty": _to_decimal(getattr(pos, "unlisted_qty", ZERO)),
                "cost_basis": _to_decimal(getattr(pos, "cost_basis", ZERO)),
            }
        elif isinstance(pos, dict):
            extracted[sym_str] = {
                "quantity": _to_decimal(pos.get("quantity")),
                "available_qty": _to_decimal(pos.get("available_qty")),
                "unlisted_qty": _to_decimal(pos.get("unlisted_qty")),
                "cost_basis": _to_decimal(pos.get("cost_basis")),
            }
    return extracted


def _extract_blocked_counts(run: Any) -> dict[str, int]:
    timing = None
    if isinstance(run, BacktestResult):
        timing = run.execution_timing
    elif isinstance(run, dict):
        timing = run.get("execution_timing")
        if not timing and "evidence" in run:
            timing = run["evidence"].get("execution_timing")
    if timing and isinstance(timing, dict):
        return {
            k: int(v)
            for k, v in timing.items()
            if k.endswith("_blocked_count")
            or k in {"cash_resized_count", "capacity_resized_count"}
        }
    return {}


def compare_backtest_runs(
    run_a: dict[str, Any] | BacktestResult,
    run_b: dict[str, Any] | BacktestResult,
    *,
    float_tolerance: float = 1e-7,
) -> dict[str, Any]:
    """Compare two backtest runs for exact deterministic equivalence.

    Normalizes UUIDs via 1-to-1 bijection while strictly comparing:
    - Fill sequence, symbol, side, price (Decimal), quantity (Decimal),
      commission (Decimal), slippage (Decimal), execution_phase, session_date.
    - Fill execution audits and internal order linkage integrity.
    - Equity curve length, timestamps, and equity values.
    - Final holdings and available quantity per symbol.
    - Execution blocked and resized counts.
    """
    map_a_to_canon: dict[str, str] = {}
    map_b_to_canon: dict[str, str] = {}
    id_counter = 0

    def check_id_bijection(
        id_a: str | None, id_b: str | None, path: str
    ) -> dict[str, Any] | None:
        nonlocal id_counter
        if id_a is None and id_b is None:
            return None
        if (id_a is None) != (id_b is None):
            return {
                "field": "id_presence",
                "path": path,
                "expected": id_a,
                "actual": id_b,
                "detail": f"ID presence mismatch at {path}",
            }
        assert id_a is not None and id_b is not None
        canon_a = map_a_to_canon.get(id_a)
        canon_b = map_b_to_canon.get(id_b)

        if canon_a is None and canon_b is None:
            id_counter += 1
            new_canon = f"id_{id_counter:04d}"
            map_a_to_canon[id_a] = new_canon
            map_b_to_canon[id_b] = new_canon
        elif canon_a is not None and canon_b is not None:
            if canon_a != canon_b:
                return {
                    "field": "id_linkage",
                    "path": path,
                    "expected": f"{id_a} (mapped to {canon_a})",
                    "actual": f"{id_b} (mapped to {canon_b})",
                    "detail": f"ID cross-reference linkage mismatch at {path}",
                }
        else:
            return {
                "field": "id_isomorphism",
                "path": path,
                "expected": f"A mapped: {canon_a is not None}",
                "actual": f"B mapped: {canon_b is not None}",
                "detail": f"Asymmetric ID reuse between runs at {path}",
            }
        return None

    # 1. Compare Fills
    fills_a = _extract_fills(run_a)
    fills_b = _extract_fills(run_b)

    if len(fills_a) != len(fills_b):
        return {
            "is_identical": False,
            "first_difference": {
                "field": "fill_count",
                "path": "fills",
                "expected": len(fills_a),
                "actual": len(fills_b),
                "detail": f"Fill counts differ: {len(fills_a)} vs {len(fills_b)}",
            },
            "summary": f"Fill counts differ: expected {len(fills_a)}, got {len(fills_b)}",
        }

    for i, (fa, fb) in enumerate(zip(fills_a, fills_b, strict=True)):
        fill_path = f"fills[{i}]"
        for field in (
            "symbol",
            "side",
            "execution_phase",
            "session_date",
            "execution_model",
        ):
            va, vb = fa.get(field), fb.get(field)
            if va != vb:
                return {
                    "is_identical": False,
                    "first_difference": {
                        "field": field,
                        "path": f"{fill_path}.{field}",
                        "expected": va,
                        "actual": vb,
                        "detail": f"Fill {field} mismatch at index {i}",
                    },
                    "summary": f"Discrepancy at {fill_path}.{field}: expected {va!r}, got {vb!r}",
                }

        # Compare financial fields with exact Decimal precision
        for dec_field in ("price", "quantity", "commission", "slippage"):
            da, db = fa[dec_field], fb[dec_field]
            if da != db:
                return {
                    "is_identical": False,
                    "first_difference": {
                        "field": dec_field,
                        "path": f"{fill_path}.{dec_field}",
                        "expected": str(da),
                        "actual": str(db),
                        "detail": f"Fill {dec_field} Decimal mismatch at index {i}",
                    },
                    "summary": f"Discrepancy at {fill_path}.{dec_field}: expected {da}, got {db}",
                }

        # Check timestamp
        if fa["timestamp"] != fb["timestamp"]:
            return {
                "is_identical": False,
                "first_difference": {
                    "field": "timestamp",
                    "path": f"{fill_path}.timestamp",
                    "expected": fa["timestamp"],
                    "actual": fb["timestamp"],
                    "detail": f"Fill timestamp mismatch at index {i}",
                },
                "summary": f"Discrepancy at {fill_path}.timestamp: expected {fa['timestamp']!r}, got {fb['timestamp']!r}",
            }

        # ID bijection check (order_id and fill_id)
        for id_field in ("order_id", "fill_id"):
            diff = check_id_bijection(
                fa.get(id_field), fb.get(id_field), f"{fill_path}.{id_field}"
            )
            if diff is not None:
                return {
                    "is_identical": False,
                    "first_difference": diff,
                    "summary": f"ID linkage discrepancy at {diff['path']}",
                }

    # 2. Compare Fill Execution Audits (if present)
    audits_a = _extract_audits(run_a)
    audits_b = _extract_audits(run_b)
    if audits_a or audits_b:
        if len(audits_a) != len(audits_b):
            return {
                "is_identical": False,
                "first_difference": {
                    "field": "audit_count",
                    "path": "fill_execution_audits",
                    "expected": len(audits_a),
                    "actual": len(audits_b),
                    "detail": f"Audit entry counts differ: {len(audits_a)} vs {len(audits_b)}",
                },
                "summary": f"Audit count mismatch: expected {len(audits_a)}, got {len(audits_b)}",
            }
        for i, (aa, ab) in enumerate(zip(audits_a, audits_b, strict=True)):
            audit_path = f"fill_execution_audits[{i}]"
            for field in (
                "symbol",
                "session_date",
                "bar_timestamp",
                "execution_phase",
                "execution_model",
            ):
                va, vb = aa.get(field), ab.get(field)
                if va != vb:
                    return {
                        "is_identical": False,
                        "first_difference": {
                            "field": field,
                            "path": f"{audit_path}.{field}",
                            "expected": va,
                            "actual": vb,
                            "detail": f"Audit field {field} mismatch at index {i}",
                        },
                        "summary": f"Audit discrepancy at {audit_path}.{field}: expected {va!r}, got {vb!r}",
                    }
            for id_field in ("order_id", "fill_id"):
                diff = check_id_bijection(
                    aa.get(id_field), ab.get(id_field), f"{audit_path}.{id_field}"
                )
                if diff is not None:
                    return {
                        "is_identical": False,
                        "first_difference": diff,
                        "summary": f"Audit ID linkage discrepancy at {diff['path']}",
                    }

    # 3. Compare Equity Curve
    curve_a = _extract_equity_curve(run_a)
    curve_b = _extract_equity_curve(run_b)
    if len(curve_a) != len(curve_b):
        return {
            "is_identical": False,
            "first_difference": {
                "field": "equity_curve_length",
                "path": "equity_curve",
                "expected": len(curve_a),
                "actual": len(curve_b),
                "detail": f"Equity curve point counts differ: {len(curve_a)} vs {len(curve_b)}",
            },
            "summary": f"Equity curve length mismatch: expected {len(curve_a)}, got {len(curve_b)}",
        }

    for i, ((ts_a, eq_a), (ts_b, eq_b)) in enumerate(
        zip(curve_a, curve_b, strict=True)
    ):
        if ts_a != ts_b:
            return {
                "is_identical": False,
                "first_difference": {
                    "field": "timestamp",
                    "path": f"equity_curve[{i}].timestamp",
                    "expected": ts_a,
                    "actual": ts_b,
                    "detail": f"Equity curve timestamp mismatch at index {i}",
                },
                "summary": f"Equity curve timestamp mismatch at index {i}: expected {ts_a}, got {ts_b}",
            }
        # Numeric comparison
        if isinstance(eq_a, Decimal) and isinstance(eq_b, Decimal):
            if eq_a != eq_b:
                return {
                    "is_identical": False,
                    "first_difference": {
                        "field": "equity",
                        "path": f"equity_curve[{i}].equity",
                        "expected": str(eq_a),
                        "actual": str(eq_b),
                        "detail": f"Equity curve Decimal mismatch at index {i}",
                    },
                    "summary": f"Equity value discrepancy at index {i}: expected {eq_a}, got {eq_b}",
                }
        else:
            diff_num = abs(float(eq_a) - float(eq_b))
            if diff_num > float_tolerance:
                return {
                    "is_identical": False,
                    "first_difference": {
                        "field": "equity",
                        "path": f"equity_curve[{i}].equity",
                        "expected": float(eq_a),
                        "actual": float(eq_b),
                        "detail": f"Equity curve float discrepancy exceeds tolerance {float_tolerance}",
                    },
                    "summary": f"Equity float discrepancy at index {i}: diff={diff_num} > {float_tolerance}",
                }

    # 4. Compare Positions (Holdings and Available Quantity)
    pos_a = _extract_positions(run_a)
    pos_b = _extract_positions(run_b)
    symbols_a = sorted(pos_a.keys())
    symbols_b = sorted(pos_b.keys())
    if symbols_a != symbols_b:
        return {
            "is_identical": False,
            "first_difference": {
                "field": "positions_symbols",
                "path": "positions",
                "expected": symbols_a,
                "actual": symbols_b,
                "detail": f"Position symbols differ: {symbols_a} vs {symbols_b}",
            },
            "summary": f"Position symbols differ: {symbols_a} vs {symbols_b}",
        }

    for sym in symbols_a:
        pa, pb = pos_a[sym], pos_b[sym]
        for field in ("quantity", "available_qty", "unlisted_qty", "cost_basis"):
            if pa[field] != pb[field]:
                return {
                    "is_identical": False,
                    "first_difference": {
                        "field": field,
                        "path": f"positions['{sym}'].{field}",
                        "expected": str(pa[field]),
                        "actual": str(pb[field]),
                        "detail": f"Position {sym}.{field} mismatch",
                    },
                    "summary": f"Position discrepancy for {sym}.{field}: expected {pa[field]}, got {pb[field]}",
                }

    # 5. Compare Blocked Counts
    blocked_a = _extract_blocked_counts(run_a)
    blocked_b = _extract_blocked_counts(run_b)
    all_blocked_keys = sorted(set(blocked_a.keys()) | set(blocked_b.keys()))
    for key in all_blocked_keys:
        ca = blocked_a.get(key, 0)
        cb = blocked_b.get(key, 0)
        if ca != cb:
            return {
                "is_identical": False,
                "first_difference": {
                    "field": key,
                    "path": f"execution_timing.{key}",
                    "expected": ca,
                    "actual": cb,
                    "detail": f"Blocked count mismatch for {key}",
                },
                "summary": f"Blocked count discrepancy for {key}: expected {ca}, got {cb}",
            }

    # All checks passed cleanly
    return {
        "is_identical": True,
        "first_difference": None,
        "summary": (
            f"Runs are deterministically identical: {len(fills_a)} fills, "
            f"{len(curve_a)} equity points, {len(symbols_a)} positions."
        ),
        "details": {
            "fill_count": len(fills_a),
            "equity_points": len(curve_a),
            "audit_count": len(audits_a),
            "position_count": len(symbols_a),
            "canonical_ids_mapped": len(map_a_to_canon),
        },
    }
