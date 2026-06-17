"""Parameter-sweep stability and sensitivity evidence."""

from __future__ import annotations

from typing import Any


def build_sweep_robustness_evidence(
    *,
    results: list[dict[str, Any]],
    rank_by: str,
    rank_direction: str,
) -> dict[str, Any]:
    """Summarize whether a sweep winner is stable across nearby grid results."""
    if not results:
        return {
            "schema_version": "karkinos.sweep_robustness.v1",
            "rank_by": rank_by,
            "rank_direction": rank_direction,
            "tested_count": 0,
            "best_params": {},
            "local_stability": {
                "best_score": 0.0,
                "neighbor_count": 0,
                "mean_neighbor_score": 0.0,
                "stability_ratio": 0.0,
            },
            "parameter_sensitivity": [],
            "overfitting_warnings": [
                {
                    "code": "no_sweep_results",
                    "message": "No parameter sweep results were available for robustness analysis.",
                }
            ],
            "limitations": _limitations(),
        }

    sorted_results = sorted(
        results,
        key=lambda item: _score(item),
        reverse=rank_direction == "desc",
    )
    best = sorted_results[0]
    best_score = _score(best)
    best_params = dict(best.get("params") or {})
    neighbors = [
        item
        for item in results
        if item is not best
        and _is_grid_neighbor(best_params, dict(item.get("params") or {}))
    ]
    mean_neighbor_score = (
        sum((_score(item) for item in neighbors), 0.0) / len(neighbors)
        if neighbors
        else 0.0
    )
    stability_ratio = (
        mean_neighbor_score / best_score if best_score not in {0.0, -0.0} else 0.0
    )
    warnings = _overfitting_warnings(
        neighbor_count=len(neighbors),
        stability_ratio=stability_ratio,
    )
    return {
        "schema_version": "karkinos.sweep_robustness.v1",
        "rank_by": rank_by,
        "rank_direction": rank_direction,
        "tested_count": len(results),
        "best_params": best_params,
        "local_stability": {
            "best_score": best_score,
            "neighbor_count": len(neighbors),
            "mean_neighbor_score": mean_neighbor_score,
            "stability_ratio": stability_ratio,
        },
        "parameter_sensitivity": _parameter_sensitivity(results, best_params),
        "overfitting_warnings": warnings,
        "limitations": _limitations(),
    }


def _score(result: dict[str, Any]) -> float:
    try:
        return float(result.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_grid_neighbor(best_params: dict[str, Any], params: dict[str, Any]) -> bool:
    differences = [
        key for key, best_value in best_params.items() if params.get(key) != best_value
    ]
    return len(differences) == 1


def _parameter_sensitivity(
    results: list[dict[str, Any]],
    best_params: dict[str, Any],
) -> list[dict[str, Any]]:
    parameters = list(best_params)
    sensitivity: list[dict[str, Any]] = []
    scores = [_score(item) for item in results]
    global_min = min(scores) if scores else 0.0
    global_max = max(scores) if scores else 0.0
    for parameter in parameters:
        values = _sorted_unique_values(
            [dict(item.get("params") or {}).get(parameter) for item in results]
        )
        grouped_scores = [
            _score(item)
            for item in results
            if dict(item.get("params") or {}).get(parameter) in values
        ]
        score_min = min(grouped_scores) if grouped_scores else global_min
        score_max = max(grouped_scores) if grouped_scores else global_max
        score_range = score_max - score_min if len(values) > 1 else 0.0
        sensitivity.append(
            {
                "parameter": parameter,
                "tested_values": values,
                "best_value": best_params.get(parameter),
                "score_range": score_range,
                "score_span": {"min": score_min, "max": score_max},
            }
        )
    return sensitivity


def _sorted_unique_values(values: list[Any]) -> list[Any]:
    unique = list(dict.fromkeys(values))
    return sorted(unique, key=lambda item: (str(type(item)), item))


def _overfitting_warnings(
    *,
    neighbor_count: int,
    stability_ratio: float,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if neighbor_count == 0:
        warnings.append(
            {
                "code": "insufficient_neighbor_grid",
                "message": "Best parameter set has no one-parameter neighbors in the tested grid; expand the grid before promotion review.",
            }
        )
    elif stability_ratio < 0.8:
        warnings.append(
            {
                "code": "local_peak_risk",
                "message": "Best parameter set is materially stronger than nearby tested neighbors; require OOS or rolling validation before promotion.",
            }
        )
    return warnings


def _limitations() -> list[str]:
    return [
        "Parameter sweep robustness evidence is not investment advice or an execution approval.",
        "Sensitivity evidence only reflects the tested grid and must be paired with after-cost, OOS, risk, and data-quality gates before promotion.",
    ]
