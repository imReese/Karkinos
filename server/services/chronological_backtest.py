"""Ordinary strategy selection on a prefix, followed by one independent test book."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from server.contracts.content_identity import content_fingerprint
from server.contracts.http.strategy_models import BacktestRequest, BacktestSweepRequest
from server.services.backtest_views.execution import (
    prepare_dataset_backtest_inputs,
    run_single_backtest,
)
from server.services.backtest_views.strategy_inputs import backtest_metrics_from_payload
from server.services.research_datasets import ResearchDatasetError


def run_chronological_sweep(
    request: BacktestSweepRequest,
    candidates: list[BacktestRequest],
    config: Any,
    db: Any,
    *,
    rank_direction: str,
) -> dict[str, Any]:
    """Candidates must have passed the ordinary strategy parameter validator.

    The complete immutable source remains bound for replay. Only its historical
    prefix reaches training engines. No test result exists when the winner is
    selected, and only that winner receives a new test book.
    """
    split = request.test_start_date
    if not request.dataset_id or request.strategy != "dual_ma":
        raise ResearchDatasetError("chronological_sweep_requires_dual_ma_dataset")
    try:
        start = date.fromisoformat(request.start_date)
        end = date.fromisoformat(request.end_date)
    except ValueError:
        raise ResearchDatasetError("chronological_sweep_window_invalid") from None
    if (
        split is None
        or not start < split <= end
        or not candidates
        or rank_direction not in {"asc", "desc"}
        or not math.isfinite(request.initial_cash)
        or request.initial_cash <= 0
    ):
        raise ResearchDatasetError("chronological_sweep_window_invalid")

    # Parameter normalization precedes identity and ties. Duplicate grid values
    # do not count as distinct experiments or change the selected parameters.
    by_params = {
        json.dumps(item.params, sort_keys=True, separators=(",", ":")): item
        for item in candidates
    }
    normalized = [by_params[key] for key in sorted(by_params)]
    prepared = prepare_dataset_backtest_inputs(normalized[0], db)
    _, handlers, _, snapshot = prepared
    longest = max(item.long_period for item in normalized)
    for handler in handlers.values():
        sessions = [
            event.timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
            for event in handler
        ]
        if (
            split not in sessions
            or sum(day < split for day in sessions) < longest + 1
            or sum(day >= split for day in sessions) < 2
        ):
            raise ResearchDatasetError("chronological_sweep_insufficient_sessions")

    training = [
        run_single_backtest(
            candidate,
            config,
            db,
            history_end=split - timedelta(days=1),
            preloaded_dataset_inputs=prepared,
        )
        for candidate in normalized
    ]
    scores = [
        float(getattr(backtest_metrics_from_payload(result), request.rank_by))
        for result in training
    ]
    if any(not math.isfinite(score) for score in scores):
        raise ResearchDatasetError("chronological_sweep_score_unavailable")
    order = sorted(
        range(len(training)),
        key=lambda index: (
            -scores[index] if rank_direction == "desc" else scores[index],
            index,
        ),
    )
    winner = order[0]
    selection = {
        "schema_version": "karkinos.chronological_sweep.v1",
        "experiment_id": str(uuid4()),
        "source_dataset_id": request.dataset_id,
        "source_snapshot_id": snapshot["snapshot_id"],
        "test_start_date": split.isoformat(),
        "rank_by": request.rank_by,
        "rank_direction": rank_direction,
        "selection_basis": "training_only",
        "tie_break": "normalized_parameters_in_canonical_json_order",
        "selected_params": dict(normalized[winner].params or {}),
        "tested_count": len(training),
        "training_trials": [
            {"params": dict(candidate.params or {}), "score": score}
            for candidate, score in zip(normalized, scores, strict=True)
        ],
        "exploratory": True,
        "independent_final": False,
        "limitations": [
            "The test uses a fresh book; training positions and cash are not carried forward.",
            "Warmup preserves crossover history but discards all prior orders and signals.",
            "Viewing or reusing test outcomes makes them iterative validation, not an untouched final holdout.",
            "A fixed source universe and data availability do not establish historical PIT eligibility.",
        ],
    }
    selection["fingerprint"] = content_fingerprint(selection)
    for result in training:
        result["metrics_json"]["chronological_validation"] = {
            **selection,
            "role": "training",
        }
    # The parameter choice above is final before the test engine reads any bars.
    tested = run_single_backtest(
        normalized[winner],
        config,
        db,
        evaluation_start=split,
        preloaded_dataset_inputs=prepared,
    )
    tested["metrics_json"]["chronological_validation"] = {
        **selection,
        "role": "test",
    }
    return {
        "requests": normalized,
        "training": training,
        "ranked_indices": order,
        "winner_index": winner,
        "test": tested,
        "selection": selection,
    }
