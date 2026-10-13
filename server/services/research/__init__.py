"""Research domain services: factor analytics, forecasts, datasets, instruments, and research factories."""

from __future__ import annotations

from server.services.research.datasets import (
    ResearchDatasetError,
    ResearchDatasetService,
    dataset_summary,
    prepare_daily_dataset,
    publish_verified_interval_dataset,
    require_supported_snapshot,
    verified_dataset_dates,
)
from server.services.research.factors import (
    compute_factor_panel,
    get_curated_universe,
    list_curated_universes,
    run_factor_evaluation,
)
from server.services.research.factory import (
    DEEPSEEK_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS,
    DEFAULT_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS,
    build_strategy_research_write_service,
    database_path,
    strategy_research_model_timeout_seconds,
)
from server.services.research.forecasts import (
    FORECAST_POLICY_ID,
    build_observation_forecasts,
)
from server.services.research.instruments import (
    RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION,
    build_research_operation_instruments,
)

__all__ = [
    "DEEPSEEK_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS",
    "DEFAULT_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS",
    "FORECAST_POLICY_ID",
    "RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION",
    "ResearchDatasetError",
    "ResearchDatasetService",
    "build_observation_forecasts",
    "build_research_operation_instruments",
    "build_strategy_research_write_service",
    "compute_factor_panel",
    "database_path",
    "dataset_summary",
    "get_curated_universe",
    "list_curated_universes",
    "prepare_daily_dataset",
    "publish_verified_interval_dataset",
    "require_supported_snapshot",
    "run_factor_evaluation",
    "strategy_research_model_timeout_seconds",
    "verified_dataset_dates",
]
