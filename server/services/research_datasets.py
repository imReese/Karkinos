"""供项目运行时使用的持久研究数据：准备、发现及离线读取。

Backward-compatible facade for server.services.research.datasets.
"""

from __future__ import annotations

import subprocess

from data.dataset.reader import read_daily_bar_dataset
from data.providers.tdx import prepare_tdx_runtime
from server.services.research.datasets import (
    MAX_VERIFIED_DATASET_INSTRUMENTS,
    ResearchDatasetError,
    ResearchDatasetService,
    dataset_summary,
    prepare_daily_dataset,
    publish_verified_interval_dataset,
    require_supported_snapshot,
    verified_dataset_dates,
)

__all__ = [
    "MAX_VERIFIED_DATASET_INSTRUMENTS",
    "ResearchDatasetError",
    "ResearchDatasetService",
    "dataset_summary",
    "prepare_daily_dataset",
    "prepare_tdx_runtime",
    "publish_verified_interval_dataset",
    "read_daily_bar_dataset",
    "require_supported_snapshot",
    "subprocess",
    "verified_dataset_dates",
]
