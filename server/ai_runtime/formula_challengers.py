"""Deterministic and random Formula DSL challengers for AI incremental value.

Challengers are the non-model baselines an AI champion must beat on the same
frozen data, costs, and execution semantics.  They never register a strategy,
grant authority, or contact a provider; they only produce formula candidates
and a comparison against the champion's realized sealed/OOS return.
"""

from __future__ import annotations

import hashlib
import json
import random as _random
from typing import Any, Mapping, Sequence

from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT

FORMULA_CHALLENGER_SCHEMA_VERSION = "karkinos.formula_challenger.v1"

_FIELDS = ("open", "high", "low", "close", "volume")
_WINDOW_OPS = ("rolling_mean", "rolling_std", "zscore", "ema", "rsi")
_PERIOD_OPS = ("lag", "delta", "return")
_COMPARISON_OPS = ("gt", "gte", "lt", "lte", "cross")


def _field(name: str) -> dict[str, Any]:
    return {"op": "field", "name": name}


def _constant(value: float) -> dict[str, Any]:
    return {"op": "constant", "value": value}


def _ma_crossover(window: int) -> dict[str, Any]:
    sma = {"op": "rolling_mean", "input": _field("close"), "window": window}
    return {
        "label": f"ma_crossover_{window}",
        "formula_ast": {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {"op": "cross", "left": _field("close"), "right": sma},
            "exit": {"op": "cross", "left": sma, "right": _field("close")},
            "position_size": {"op": "equal_weight"},
        },
    }


def _rsi_reversion(window: int, low: int, high: int) -> dict[str, Any]:
    rsi = {"op": "rsi", "input": _field("close"), "window": window}
    return {
        "label": f"rsi_reversion_{window}_{low}_{high}",
        "formula_ast": {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {"op": "lt", "left": rsi, "right": _constant(low)},
            "exit": {"op": "gt", "left": rsi, "right": _constant(high)},
            "position_size": {"op": "equal_weight"},
        },
    }


def _momentum(period: int) -> dict[str, Any]:
    ret = {"op": "return", "input": _field("close"), "period": period}
    return {
        "label": f"momentum_{period}",
        "formula_ast": {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {"op": "gt", "left": ret, "right": _constant(0)},
            "exit": {"op": "lt", "left": ret, "right": _constant(0)},
            "position_size": {"op": "equal_weight"},
        },
    }


def generate_deterministic_challenger_formulas() -> list[dict[str, Any]]:
    """A fixed, reviewed set of simple templates with parameter grids."""

    formulas: list[dict[str, Any]] = []
    for window in (5, 10, 20, 40, 60):
        formulas.append(_ma_crossover(window))
    for window in (7, 14, 28):
        for low, high in ((30, 70), (20, 80)):
            formulas.append(_rsi_reversion(window, low, high))
    for period in (5, 10, 20):
        formulas.append(_momentum(period))
    return formulas


def _random_value(rng: _random.Random) -> dict[str, Any]:
    kind = rng.choice(("field", "window", "period"))
    if kind == "field":
        return _field(rng.choice(_FIELDS))
    field = _field("close")
    if kind == "window":
        op = rng.choice(_WINDOW_OPS)
        window = rng.randint(2, 60)
        return {"op": op, "input": field, "window": window}
    op = rng.choice(_PERIOD_OPS)
    period = rng.randint(1, 60)
    return {"op": op, "input": field, "period": period}


def generate_random_challenger_formulas(
    seed: int,
    count: int,
) -> list[dict[str, Any]]:
    """Seeded random Formula DSL challengers, deterministic for a given seed."""

    if count < 1:
        raise ValueError("count must be at least 1")
    rng = _random.Random(seed)
    formulas: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempts = 0
    while len(formulas) < count:
        attempts += 1
        if attempts > count * 100:
            raise ValueError("unable to generate enough distinct challengers")
        entry_op = rng.choice(_COMPARISON_OPS)
        exit_op = rng.choice(_COMPARISON_OPS)
        candidate = {
            "schema_version": FORMULA_AST_CONTRACT,
            "entry": {
                "op": entry_op,
                "left": _random_value(rng),
                "right": _random_value(rng),
            },
            "exit": {
                "op": exit_op,
                "left": _random_value(rng),
                "right": _random_value(rng),
            },
            "position_size": {"op": "equal_weight"},
        }
        key = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        formulas.append(
            {
                "label": f"random_{seed}_{len(formulas)}",
                "formula_ast": candidate,
            }
        )
    return formulas


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_challenger_comparison(
    *,
    champion_return: float,
    challenger_returns: Sequence[float],
) -> dict[str, Any]:
    """Rank the champion's realized return against challenger returns."""

    if not challenger_returns:
        raise ValueError("challenger_returns must be non-empty")
    values = [float(item) for item in challenger_returns]
    if any(not _is_finite(item) for item in values):
        raise ValueError("challenger_returns must be finite")
    champion = float(champion_return)
    if not _is_finite(champion):
        raise ValueError("champion_return must be finite")
    beaten = sum(1 for value in values if value <= champion)
    rank_percentile = beaten / len(values)
    max_value = max(values)
    mean_value = sum(values) / len(values)
    core = {
        "schema_version": FORMULA_CHALLENGER_SCHEMA_VERSION,
        "method": "challenger_comparison",
        "champion_return": champion,
        "challenger_count": len(values),
        "challenger_mean_return": mean_value,
        "challenger_max_return": max_value,
        "champion_rank_percentile": rank_percentile,
        "champion_beats_all_challengers": rank_percentile >= 1.0,
        "ai_increment_over_max_challenger": champion - max_value,
    }
    return {
        **core,
        "limitations": [
            "Challenger comparison reflects the frozen challenger family only; it is not a profitability guarantee.",
            "Incremental value is only meaningful when challengers run on the same frozen data, costs, and execution semantics as the champion.",
        ],
        "evidence_fingerprint": _fingerprint(core),
    }


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


__all__ = [
    "FORMULA_CHALLENGER_SCHEMA_VERSION",
    "generate_deterministic_challenger_formulas",
    "generate_random_challenger_formulas",
    "build_challenger_comparison",
]
