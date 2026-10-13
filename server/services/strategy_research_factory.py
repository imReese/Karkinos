"""Application-level factory for evidence-bound strategy research services.

Backward-compatible facade for server.services.research.factory.
"""

from __future__ import annotations

from server.services.research.factory import (
    DEEPSEEK_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS,
    DEFAULT_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS,
    build_strategy_research_write_service,
    database_path,
    strategy_research_model_timeout_seconds,
)

__all__ = [
    "DEEPSEEK_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS",
    "DEFAULT_STRATEGY_RESEARCH_MODEL_TIMEOUT_SECONDS",
    "build_strategy_research_write_service",
    "database_path",
    "strategy_research_model_timeout_seconds",
]
