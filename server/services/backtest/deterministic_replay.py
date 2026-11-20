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
                    "fee_breakdown": getattr(fill, "fee_breakdown", None),
                    "fee_rule_id": getattr(fill, "fee_rule_id", None),
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
                    "fee_breakdown": fill.get("fee_breakdown"),
                    "fee_rule_id": fill.get("fee_rule_id"),
                    "metadata": metadata,
                }
            )
    return extracted


def _extract_audits(run: Any) -> list[dict[str, Any]] | None:
    if isinstance(run, BacktestResult):
        audits = []
        for fill in run.fills:
            meta = dict(fill.metadata) if fill.metadata else {}
            audits.append(
                {
                    "fill_id": str(fill.fill_id)
                    if hasattr(fill, "fill_id") and fill.fill_id is not None
                    else None,
                    "order_id": str(fill.order_id)
                    if fill.order_id is not None
                    else None,
                    "symbol": str(fill.symbol),
                    "session_date": str(meta.get("session_date"))
                    if meta.get("session_date") is not None
                    else None,
                    "bar_timestamp": str(meta.get("bar_timestamp"))
                    if meta.get("bar_timestamp") is not None
                    else None,
                    "execution_phase": meta.get("execution_phase"),
                    "execution_model": meta.get("execution_model"),
                }
            )
        return audits
    elif isinstance(run, dict):
        audits = run.get("fill_execution_audits")
        if (
            audits is None
            and "metrics_json" in run
            and isinstance(run["metrics_json"], dict)
        ):
            audits = run["metrics_json"].get("fill_execution_audits")
        if audits is None and "evidence" in run and isinstance(run["evidence"], dict):
            audits = run["evidence"].get("fill_execution_audits")
        if (
            audits is None
            and "evidence_json" in run
            and isinstance(run["evidence_json"], dict)
        ):
            audits = run["evidence_json"].get("fill_execution_audits")
        if audits is None:
            return None
        return [dict(a) for a in audits]
    return None


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


def _extract_positions(run: Any) -> dict[str, dict[str, Decimal]] | None:
    raw_pos = None
    if isinstance(run, BacktestResult):
        raw_pos = run.positions
    elif isinstance(run, dict):
        if "positions" in run:
            raw_pos = run["positions"]
        elif (
            "metrics_json" in run
            and isinstance(run["metrics_json"], dict)
            and "positions" in run["metrics_json"]
        ):
            raw_pos = run["metrics_json"]["positions"]
        elif (
            "evidence_json" in run
            and isinstance(run["evidence_json"], dict)
            and "positions" in run["evidence_json"]
        ):
            raw_pos = run["evidence_json"]["positions"]
        elif (
            "evidence" in run
            and isinstance(run["evidence"], dict)
            and "positions" in run["evidence"]
        ):
            raw_pos = run["evidence"]["positions"]
    elif hasattr(run, "positions"):
        raw_pos = getattr(run, "positions")

    if raw_pos is None:
        return None

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


def _normalize_identity_value(val: Any) -> Any:
    if val is None:
        return None
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if is_dataclass(val):
        return asdict(val)
    if isinstance(val, dict):
        return {k: _normalize_identity_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_normalize_identity_value(v) for v in val]
    return val


def _extract_input_identity(run: Any) -> dict[str, Any]:
    ctx_id = None
    dataset_id = None
    window = None
    strat_meta = None
    cost_assumptions = None
    research_mode = None
    strict_status = None
    policy_id = None
    initial_cash = None

    if isinstance(run, dict):
        metrics = (
            run.get("metrics_json") if isinstance(run.get("metrics_json"), dict) else {}
        )
        config = run.get("config") if isinstance(run.get("config"), dict) else {}
        timing = (
            run.get("execution_timing")
            or metrics.get("execution_timing")
            or (
                run.get("evidence") if isinstance(run.get("evidence"), dict) else {}
            ).get("execution_timing")
            or (
                run.get("evidence_json")
                if isinstance(run.get("evidence_json"), dict)
                else {}
            ).get("execution_timing")
            or {}
        )
        policy_id = (
            timing.get("policy_id") or run.get("policy_id") or metrics.get("policy_id")
        )
        raw_initial_cash = (
            run.get("initial_cash")
            if "initial_cash" in run
            else (
                metrics.get("initial_cash")
                if "initial_cash" in metrics
                else config.get("initial_cash")
            )
        )
        if raw_initial_cash is not None:
            initial_cash = _to_decimal(raw_initial_cash)

        binding = run.get("dataset_binding") or metrics.get("dataset_binding")
        b_ctx_id = (
            binding.get("execution_context_id") if isinstance(binding, dict) else None
        )
        b_ds_id = binding.get("dataset_id") if isinstance(binding, dict) else None

        ctx_id = (
            run.get("execution_context_id")
            or metrics.get("execution_context_id")
            or b_ctx_id
            or config.get("execution_context_id")
        )
        dataset_id = (
            run.get("dataset_id")
            or metrics.get("dataset_id")
            or b_ds_id
            or config.get("dataset_id")
        )
        window = run.get("execution_window") or metrics.get("execution_window")
        if window is None and (config.get("start_date") or config.get("end_date")):
            window = {
                "start_date": str(config.get("start_date")),
                "end_date": str(config.get("end_date")),
            }
        strat_meta = run.get("strategy_metadata") or metrics.get("strategy_metadata")
        if strat_meta is None and config.get("strategy"):
            strat_meta = {
                "strategy": config.get("strategy"),
                "params": config.get("params"),
            }
        cost_assumptions = (
            run.get("cost_assumptions")
            or metrics.get("cost_assumptions")
            or config.get("cost_assumptions")
        )
        research_mode = (
            run.get("research_mode")
            or metrics.get("research_mode")
            or config.get("research_mode")
        )
        strict_status = (
            run.get("strict_security_status")
            if "strict_security_status" in run
            else (
                metrics.get("strict_security_status")
                if "strict_security_status" in metrics
                else config.get("strict_security_status")
            )
        )
    else:
        timing = getattr(run, "execution_timing", None) or {}
        policy_id = (
            timing.get("policy_id")
            if isinstance(timing, dict)
            else getattr(run, "policy_id", None)
        )
        raw_initial_cash = getattr(run, "initial_cash", None)
        if raw_initial_cash is not None:
            initial_cash = _to_decimal(raw_initial_cash)

        ctx_id = getattr(run, "execution_context_id", None)
        dataset_id = getattr(run, "dataset_id", None)
        snapshot = getattr(run, "dataset_snapshot", None)
        if isinstance(snapshot, dict):
            ctx_id = ctx_id or snapshot.get("execution_context_id")
            dataset_id = dataset_id or snapshot.get("dataset_id")
        window = getattr(run, "execution_window", None)
        strat_meta = getattr(run, "strategy_metadata", None)
        cost_assumptions = getattr(run, "cost_assumptions", None)
        research_mode = getattr(run, "research_mode", None)
        strict_status = getattr(run, "strict_security_status", None)

    return {
        "execution_context_id": ctx_id,
        "dataset_id": dataset_id,
        "execution_window": window,
        "strategy_metadata": strat_meta,
        "cost_assumptions": cost_assumptions,
        "research_mode": research_mode,
        "strict_security_status": strict_status,
        "policy_id": policy_id,
        "initial_cash": initial_cash,
    }


def _extract_cost_summary(run: Any) -> dict[str, Decimal] | None:
    raw = None
    if isinstance(run, BacktestResult):
        raw = run.cost_summary
    elif isinstance(run, dict):
        raw = run.get("cost_summary_json") or run.get("cost_summary")
        if raw is None and "metrics_json" in run:
            raw = run["metrics_json"].get("cost_summary")
    else:
        raw = getattr(run, "cost_summary", None)
    if raw is None:
        return None
    if hasattr(raw, "total_commission"):
        return {
            "total_commission": _to_decimal(raw.total_commission),
            "total_slippage": _to_decimal(raw.total_slippage),
            "gross_turnover": _to_decimal(raw.gross_turnover),
            "total_trades": Decimal(str(raw.total_trades)),
        }
    elif isinstance(raw, dict):
        return {
            "total_commission": _to_decimal(raw.get("total_commission")),
            "total_slippage": _to_decimal(raw.get("total_slippage")),
            "gross_turnover": _to_decimal(raw.get("gross_turnover")),
            "total_trades": Decimal(str(raw.get("total_trades", 0))),
        }
    return None


def _extract_final_equity(run: Any) -> Decimal | None:
    if isinstance(run, BacktestResult):
        return _to_decimal(run.final_equity)
    elif isinstance(run, dict):
        val = run.get("final_equity")
        if val is None and "metrics_json" in run:
            val = run["metrics_json"].get("final_equity")
        if val is not None:
            return _to_decimal(val)
    elif hasattr(run, "final_equity"):
        return _to_decimal(run.final_equity)
    return None


def _extract_blocked_counts(run: Any) -> dict[str, int]:
    timing = None
    if isinstance(run, BacktestResult):
        timing = run.execution_timing
    elif isinstance(run, dict):
        timing = run.get("execution_timing")
        if not timing and "metrics_json" in run:
            timing = run["metrics_json"].get("execution_timing")
        if not timing and "evidence" in run:
            timing = run["evidence"].get("execution_timing")
        if not timing and "evidence_json" in run:
            timing = run["evidence_json"].get("execution_timing")
    else:
        timing = getattr(run, "execution_timing", None)
    if timing and isinstance(timing, dict):
        return {
            k: int(v)
            for k, v in timing.items()
            if k.endswith("_count")
            or k.endswith("_blocked_count")
            or k in {"cash_resized_count", "capacity_resized_count"}
        }
    return {}


class _IdBijectionChecker:
    """Normalizes UUIDs via 1-to-1 bijection to ensure isomorphic execution graphs."""

    def __init__(self) -> None:
        self.map_a_to_canon: dict[str, str] = {}
        self.map_b_to_canon: dict[str, str] = {}
        self.id_counter: int = 0

    def check(
        self, id_a: str | None, id_b: str | None, path: str
    ) -> dict[str, Any] | None:
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
        canon_a = self.map_a_to_canon.get(id_a)
        canon_b = self.map_b_to_canon.get(id_b)

        if canon_a is None and canon_b is None:
            self.id_counter += 1
            new_canon = f"id_{self.id_counter:04d}"
            self.map_a_to_canon[id_a] = new_canon
            self.map_b_to_canon[id_b] = new_canon
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


def _compare_input_identity(run_a: Any, run_b: Any) -> dict[str, Any] | None:
    id_a = _extract_input_identity(run_a)
    id_b = _extract_input_identity(run_b)

    for field in (
        "execution_context_id",
        "dataset_id",
        "execution_window",
        "strategy_metadata",
        "cost_assumptions",
        "research_mode",
        "strict_security_status",
        "policy_id",
        "initial_cash",
    ):
        va = _normalize_identity_value(id_a.get(field))
        vb = _normalize_identity_value(id_b.get(field))
        if (va is None) != (vb is None):
            return {
                "is_identical": False,
                "category": "input_identity",
                "first_difference": {
                    "category": "input_identity",
                    "field": field,
                    "path": f"input_identity.{field}",
                    "expected": va,
                    "actual": vb,
                    "detail": f"Asymmetric input qualification presence for {field}: {va!r} vs {vb!r}",
                },
                "summary": f"Input identity presence mismatch for {field}",
            }
        if va is not None and vb is not None and va != vb:
            return {
                "is_identical": False,
                "category": "input_identity",
                "first_difference": {
                    "category": "input_identity",
                    "field": field,
                    "path": f"input_identity.{field}",
                    "expected": va,
                    "actual": vb,
                    "detail": f"Input qualification mismatch for {field}: {va!r} vs {vb!r}",
                },
                "summary": f"Input identity mismatch: {field} {va!r} vs {vb!r}",
            }
    return None


def _compare_fills(
    fills_a: list[dict[str, Any]],
    fills_b: list[dict[str, Any]],
    checker: _IdBijectionChecker,
) -> dict[str, Any] | None:
    if len(fills_a) != len(fills_b):
        return {
            "is_identical": False,
            "category": "output_difference",
            "first_difference": {
                "category": "output_difference",
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
            "bar_timestamp",
            "execution_model",
            "fee_rule_id",
        ):
            va, vb = fa.get(field), fb.get(field)
            if va != vb:
                return {
                    "is_identical": False,
                    "category": "output_difference",
                    "first_difference": {
                        "category": "output_difference",
                        "field": field,
                        "path": f"{fill_path}.{field}",
                        "expected": va,
                        "actual": vb,
                        "detail": f"Fill {field} mismatch at index {i}",
                    },
                    "summary": f"Discrepancy at {fill_path}.{field}: expected {va!r}, got {vb!r}",
                }

        fb_a, fb_b = fa.get("fee_breakdown"), fb.get("fee_breakdown")
        if fb_a != fb_b:
            return {
                "is_identical": False,
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": "fee_breakdown",
                    "path": f"{fill_path}.fee_breakdown",
                    "expected": fb_a,
                    "actual": fb_b,
                    "detail": f"Fill fee_breakdown mismatch at index {i}",
                },
                "summary": f"Discrepancy at {fill_path}.fee_breakdown: expected {fb_a!r}, got {fb_b!r}",
            }

        for dec_field in ("price", "quantity", "commission", "slippage"):
            da, db = fa[dec_field], fb[dec_field]
            if da != db:
                return {
                    "is_identical": False,
                    "category": "output_difference",
                    "first_difference": {
                        "category": "output_difference",
                        "field": dec_field,
                        "path": f"{fill_path}.{dec_field}",
                        "expected": str(da),
                        "actual": str(db),
                        "detail": f"Fill {dec_field} Decimal mismatch at index {i}",
                    },
                    "summary": f"Discrepancy at {fill_path}.{dec_field}: expected {da}, got {db}",
                }

        if fa["timestamp"] != fb["timestamp"]:
            return {
                "is_identical": False,
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": "timestamp",
                    "path": f"{fill_path}.timestamp",
                    "expected": fa["timestamp"],
                    "actual": fb["timestamp"],
                    "detail": f"Fill timestamp mismatch at index {i}",
                },
                "summary": f"Discrepancy at {fill_path}.timestamp: expected {fa['timestamp']!r}, got {fb['timestamp']!r}",
            }

        for id_field in ("order_id", "fill_id"):
            diff = checker.check(
                fa.get(id_field), fb.get(id_field), f"{fill_path}.{id_field}"
            )
            if diff is not None:
                diff["category"] = "output_difference"
                return {
                    "is_identical": False,
                    "category": "output_difference",
                    "first_difference": diff,
                    "summary": f"ID linkage discrepancy at {diff['path']}",
                }
    return None


REQUIRED_AUDIT_FIELDS = (
    "symbol",
    "session_date",
    "bar_timestamp",
    "execution_phase",
    "execution_model",
)


def _validate_audit_completeness(
    fills: list[dict[str, Any]],
    audits: list[dict[str, Any]] | None,
    run_label: str,
) -> dict[str, Any] | None:
    if not fills:
        if audits is not None and len(audits) > 0:
            return {
                "is_identical": False,
                "category": "missing_evidence",
                "first_difference": {
                    "category": "missing_evidence",
                    "field": "fill_execution_audits",
                    "path": f"{run_label}.fill_execution_audits",
                    "expected": "0 audit entries for 0 fills",
                    "actual": f"{len(audits)} audit entries",
                    "detail": f"{run_label} has 0 fills but contains {len(audits)} execution audit entries",
                },
                "summary": f"{run_label} has unexpected audits for 0 fills",
            }
        return None

    if audits is None:
        return {
            "is_identical": False,
            "category": "missing_evidence",
            "first_difference": {
                "category": "missing_evidence",
                "field": "fill_execution_audits",
                "path": f"{run_label}.fill_execution_audits",
                "expected": f"{len(fills)} execution audits",
                "actual": "missing evidence (None)",
                "detail": f"{run_label} contains {len(fills)} fills but lacks fill_execution_audits evidence",
            },
            "summary": f"{run_label} lacks fill_execution_audits evidence",
        }

    if len(audits) != len(fills):
        return {
            "is_identical": False,
            "category": "missing_evidence",
            "first_difference": {
                "category": "missing_evidence",
                "field": "fill_execution_audits",
                "path": f"{run_label}.fill_execution_audits",
                "expected": f"{len(fills)} audit entries for {len(fills)} fills",
                "actual": f"{len(audits)} audit entries",
                "detail": f"{run_label} contains {len(fills)} fills but only {len(audits)} execution audit entries",
            },
            "summary": f"Incomplete audit coverage in {run_label}: {len(audits)} audits for {len(fills)} fills",
        }

    seen_audits: dict[Any, int] = {}
    for i, (fill, audit) in enumerate(zip(fills, audits, strict=True)):
        audit_path = f"{run_label}.fill_execution_audits[{i}]"
        for field in REQUIRED_AUDIT_FIELDS:
            val = audit.get(field)
            if val is None or str(val).strip() == "":
                return {
                    "is_identical": False,
                    "category": "missing_evidence",
                    "first_difference": {
                        "category": "missing_evidence",
                        "field": field,
                        "path": f"{audit_path}.{field}",
                        "expected": f"valid non-empty {field}",
                        "actual": repr(val),
                        "detail": f"Audit entry at index {i} in {run_label} lacks mandatory field '{field}'",
                    },
                    "summary": f"Missing mandatory field '{field}' at {audit_path}",
                }

        f_fill_id = fill.get("fill_id")
        a_fill_id = audit.get("fill_id")
        if f_fill_id is not None and a_fill_id is not None:
            if str(f_fill_id) != str(a_fill_id):
                return {
                    "is_identical": False,
                    "category": "missing_evidence",
                    "first_difference": {
                        "category": "missing_evidence",
                        "field": "fill_id",
                        "path": f"{audit_path}.fill_id",
                        "expected": str(f_fill_id),
                        "actual": str(a_fill_id),
                        "detail": f"Audit entry at index {i} fill_id does not correspond to fill at index {i}",
                    },
                    "summary": f"Audit fill_id linkage mismatch at {audit_path}",
                }

        f_order_id = fill.get("order_id")
        a_order_id = audit.get("order_id")
        if f_order_id is not None and a_order_id is not None:
            if str(f_order_id) != str(a_order_id):
                return {
                    "is_identical": False,
                    "category": "missing_evidence",
                    "first_difference": {
                        "category": "missing_evidence",
                        "field": "order_id",
                        "path": f"{audit_path}.order_id",
                        "expected": str(f_order_id),
                        "actual": str(a_order_id),
                        "detail": f"Audit entry at index {i} order_id does not correspond to fill at index {i}",
                    },
                    "summary": f"Audit order_id linkage mismatch at {audit_path}",
                }

        fill_key = (
            ("fill_id", str(a_fill_id))
            if a_fill_id is not None
            else (
                str(audit.get("symbol")),
                str(audit.get("session_date")),
                str(audit.get("bar_timestamp")),
                str(audit.get("execution_phase")),
                str(audit.get("order_id")),
            )
        )
        if fill_key in seen_audits:
            prev_idx = seen_audits[fill_key]
            return {
                "is_identical": False,
                "category": "missing_evidence",
                "first_difference": {
                    "category": "missing_evidence",
                    "field": "fill_execution_audits",
                    "path": audit_path,
                    "expected": f"unique audit entry for fill {i}",
                    "actual": f"duplicate of audit at index {prev_idx}",
                    "detail": f"Duplicate audit entry at index {i} in {run_label} does not provide complete coverage",
                },
                "summary": f"Duplicate audit entry at {audit_path}",
            }
        seen_audits[fill_key] = i

    return None


def _compare_audits(
    audits_a: list[dict[str, Any]] | None,
    audits_b: list[dict[str, Any]] | None,
    fills_a: list[dict[str, Any]],
    fills_b: list[dict[str, Any]],
    checker: _IdBijectionChecker,
) -> dict[str, Any] | None:
    err_a = _validate_audit_completeness(fills_a, audits_a, "run_a")
    if err_a:
        return err_a
    err_b = _validate_audit_completeness(fills_b, audits_b, "run_b")
    if err_b:
        return err_b

    if len(fills_a) == 0 and len(fills_b) == 0:
        return None

    assert audits_a is not None and audits_b is not None
    if len(audits_a) != len(audits_b):
        return {
            "is_identical": False,
            "category": "output_difference",
            "first_difference": {
                "category": "output_difference",
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
        for field in REQUIRED_AUDIT_FIELDS:
            va, vb = aa.get(field), ab.get(field)
            if va != vb:
                return {
                    "is_identical": False,
                    "category": "output_difference",
                    "first_difference": {
                        "category": "output_difference",
                        "field": field,
                        "path": f"{audit_path}.{field}",
                        "expected": va,
                        "actual": vb,
                        "detail": f"Audit field {field} mismatch at index {i}",
                    },
                    "summary": f"Audit discrepancy at {audit_path}.{field}: expected {va!r}, got {vb!r}",
                }
        for id_field in ("order_id", "fill_id"):
            diff = checker.check(
                aa.get(id_field), ab.get(id_field), f"{audit_path}.{id_field}"
            )
            if diff is not None:
                diff["category"] = "output_difference"
                return {
                    "is_identical": False,
                    "category": "output_difference",
                    "first_difference": diff,
                    "summary": f"Audit ID linkage discrepancy at {diff['path']}",
                }
    return None


def _compare_equity_curve(
    curve_a: list[tuple[str, Any]],
    curve_b: list[tuple[str, Any]],
    float_tolerance: float,
) -> dict[str, Any] | None:
    if len(curve_a) != len(curve_b):
        return {
            "is_identical": False,
            "category": "output_difference",
            "first_difference": {
                "category": "output_difference",
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
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": "timestamp",
                    "path": f"equity_curve[{i}].timestamp",
                    "expected": ts_a,
                    "actual": ts_b,
                    "detail": f"Equity curve timestamp mismatch at index {i}",
                },
                "summary": f"Equity curve timestamp mismatch at index {i}: expected {ts_a}, got {ts_b}",
            }
        if isinstance(eq_a, Decimal) and isinstance(eq_b, Decimal):
            if eq_a != eq_b:
                return {
                    "is_identical": False,
                    "category": "output_difference",
                    "first_difference": {
                        "category": "output_difference",
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
                    "category": "output_difference",
                    "first_difference": {
                        "category": "output_difference",
                        "field": "equity",
                        "path": f"equity_curve[{i}].equity",
                        "expected": float(eq_a),
                        "actual": float(eq_b),
                        "detail": f"Equity curve float discrepancy exceeds tolerance {float_tolerance}",
                    },
                    "summary": f"Equity float discrepancy at index {i}: diff={diff_num} > {float_tolerance}",
                }
    return None


def _compare_final_equity(
    run_a: Any, run_b: Any, float_tolerance: float
) -> dict[str, Any] | None:
    fe_a = _extract_final_equity(run_a)
    fe_b = _extract_final_equity(run_b)
    if fe_a is None or fe_b is None:
        return {
            "is_identical": False,
            "category": "missing_evidence",
            "first_difference": {
                "category": "missing_evidence",
                "field": "final_equity",
                "path": "final_equity",
                "expected": "present" if fe_a is not None else "missing",
                "actual": "present" if fe_b is not None else "missing",
                "detail": "Final equity evidence is missing on one or both runs",
            },
            "summary": "Missing required final equity evidence",
        }
    if isinstance(fe_a, Decimal) and isinstance(fe_b, Decimal):
        if fe_a != fe_b:
            return {
                "is_identical": False,
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": "final_equity",
                    "path": "final_equity",
                    "expected": str(fe_a),
                    "actual": str(fe_b),
                    "detail": f"Final equity Decimal mismatch: {fe_a} vs {fe_b}",
                },
                "summary": f"Discrepancy at final_equity: expected {fe_a}, got {fe_b}",
            }
    else:
        diff_fe = abs(float(fe_a) - float(fe_b))
        if diff_fe > float_tolerance:
            return {
                "is_identical": False,
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": "final_equity",
                    "path": "final_equity",
                    "expected": float(fe_a),
                    "actual": float(fe_b),
                    "detail": f"Final equity float discrepancy exceeds tolerance: diff={diff_fe}",
                },
                "summary": f"Discrepancy at final_equity: expected {fe_a}, got {fe_b}",
            }
    return None


def _compare_cost_summary(run_a: Any, run_b: Any) -> dict[str, Any] | None:
    cs_a = _extract_cost_summary(run_a)
    cs_b = _extract_cost_summary(run_b)
    if cs_a is None or cs_b is None:
        return {
            "is_identical": False,
            "category": "missing_evidence",
            "first_difference": {
                "category": "missing_evidence",
                "field": "cost_summary",
                "path": "cost_summary",
                "expected": "present" if cs_a is not None else "missing",
                "actual": "present" if cs_b is not None else "missing",
                "detail": "Cost summary evidence is missing on one or both runs",
            },
            "summary": "Missing required cost summary evidence",
        }
    for cost_field in (
        "total_commission",
        "total_slippage",
        "gross_turnover",
        "total_trades",
    ):
        ca = cs_a.get(cost_field)
        cb = cs_b.get(cost_field)
        if ca != cb:
            return {
                "is_identical": False,
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": cost_field,
                    "path": f"cost_summary.{cost_field}",
                    "expected": str(ca),
                    "actual": str(cb),
                    "detail": f"Cost summary {cost_field} mismatch",
                },
                "summary": f"Discrepancy at cost_summary.{cost_field}: expected {ca}, got {cb}",
            }
    return None


def _compare_positions(
    run_a: Any,
    run_b: Any,
) -> dict[str, Any] | None:
    pos_a = _extract_positions(run_a)
    pos_b = _extract_positions(run_b)
    if pos_a is None or pos_b is None:
        return {
            "is_identical": False,
            "category": "missing_evidence",
            "first_difference": {
                "category": "missing_evidence",
                "field": "positions",
                "path": "positions",
                "expected": "present" if pos_a is not None else "missing",
                "actual": "present" if pos_b is not None else "missing",
                "detail": "Positions evidence is missing; cannot verify ending portfolio state",
            },
            "summary": "Missing required positions evidence",
        }

    symbols_a = sorted(pos_a.keys())
    symbols_b = sorted(pos_b.keys())
    if symbols_a != symbols_b:
        return {
            "is_identical": False,
            "category": "output_difference",
            "first_difference": {
                "category": "output_difference",
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
                    "category": "output_difference",
                    "first_difference": {
                        "category": "output_difference",
                        "field": field,
                        "path": f"positions['{sym}'].{field}",
                        "expected": str(pa[field]),
                        "actual": str(pb[field]),
                        "detail": f"Position {sym}.{field} mismatch",
                    },
                    "summary": f"Position discrepancy for {sym}.{field}: expected {pa[field]}, got {pb[field]}",
                }
    return None


def _compare_blocked_counts(run_a: Any, run_b: Any) -> dict[str, Any] | None:
    blocked_a = _extract_blocked_counts(run_a)
    blocked_b = _extract_blocked_counts(run_b)
    all_blocked_keys = sorted(set(blocked_a.keys()) | set(blocked_b.keys()))
    for key in all_blocked_keys:
        ca = blocked_a.get(key, 0)
        cb = blocked_b.get(key, 0)
        if ca != cb:
            return {
                "is_identical": False,
                "category": "output_difference",
                "first_difference": {
                    "category": "output_difference",
                    "field": key,
                    "path": f"execution_timing.{key}",
                    "expected": ca,
                    "actual": cb,
                    "detail": f"Blocked count mismatch for {key}",
                },
                "summary": f"Blocked count discrepancy for {key}: expected {ca}, got {cb}",
            }
    return None


def compare_backtest_runs(
    run_a: dict[str, Any] | BacktestResult,
    run_b: dict[str, Any] | BacktestResult,
    *,
    float_tolerance: float = 1e-7,
) -> dict[str, Any]:
    """Compare two backtest runs for exact deterministic equivalence."""
    if (isinstance(run_a, dict) and not run_a) or (
        isinstance(run_b, dict) and not run_b
    ):
        return {
            "is_identical": False,
            "category": "missing_evidence",
            "first_difference": {
                "category": "missing_evidence",
                "field": "run_payload",
                "path": "run",
                "expected": "valid backtest result",
                "actual": "empty payload",
                "detail": "Empty backtest run payload; cannot verify deterministic replay",
            },
            "summary": "Missing required backtest run evidence in empty payload",
        }

    # 0. Input Identity
    diff = _compare_input_identity(run_a, run_b)
    if diff:
        return diff

    # 1. Fills
    fills_a = _extract_fills(run_a)
    fills_b = _extract_fills(run_b)
    checker = _IdBijectionChecker()
    diff = _compare_fills(fills_a, fills_b, checker)
    if diff:
        return diff

    # 2. Audits
    audits_a = _extract_audits(run_a)
    audits_b = _extract_audits(run_b)
    diff = _compare_audits(audits_a, audits_b, fills_a, fills_b, checker)
    if diff:
        return diff

    # 3. Equity Curve
    curve_a = _extract_equity_curve(run_a)
    curve_b = _extract_equity_curve(run_b)
    diff = _compare_equity_curve(curve_a, curve_b, float_tolerance)
    if diff:
        return diff

    # 4. Final Equity
    diff = _compare_final_equity(run_a, run_b, float_tolerance)
    if diff:
        return diff

    # 5. Cost Summary
    diff = _compare_cost_summary(run_a, run_b)
    if diff:
        return diff

    # 6. Positions
    diff = _compare_positions(run_a, run_b)
    if diff:
        return diff

    # 7. Blocked Counts
    diff = _compare_blocked_counts(run_a, run_b)
    if diff:
        return diff

    pos_a = _extract_positions(run_a) or {}

    # All checks passed cleanly
    return {
        "is_identical": True,
        "category": "identical",
        "first_difference": None,
        "summary": (
            f"Runs are deterministically identical: {len(fills_a)} fills, "
            f"{len(curve_a)} equity points, {len(pos_a)} positions."
        ),
        "details": {
            "fill_count": len(fills_a),
            "equity_points": len(curve_a),
            "audit_count": len(audits_a or []),
            "position_count": len(pos_a),
            "canonical_ids_mapped": len(checker.map_a_to_canon),
            "comparison_scope": "full_replay",
        },
    }
