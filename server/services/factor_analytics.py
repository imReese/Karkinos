"""Factor evaluation and curated universe analytics service.

Backward-compatible facade for server.services.research.factors.
"""

from __future__ import annotations

from typing import Any

from server.runtime_paths import resolve_data_dir
from server.services.research.factors import (
    compute_factor_panel,
    get_curated_universe,
    list_curated_universes,
)
from server.services.research.factors import (
    run_factor_evaluation as _run_factor_evaluation,
)


def run_factor_evaluation(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Execute factor evaluation, resolving data_dir dynamically to respect test patches."""
    if "data_dir" not in kwargs or kwargs["data_dir"] is None:
        kwargs["data_dir"] = resolve_data_dir()
    return _run_factor_evaluation(*args, **kwargs)


__all__ = [
    "compute_factor_panel",
    "get_curated_universe",
    "list_curated_universes",
    "resolve_data_dir",
    "run_factor_evaluation",
]
