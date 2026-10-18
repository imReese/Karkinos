"""Executable verification for server.services.research domain package."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import server.services.research_datasets as legacy_datasets
import server.services.research_observation_forecasts as legacy_forecasts
from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation
from server.services import research
from server.services.research import (
    FORECAST_POLICY_ID,
    RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION,
    ResearchDatasetError,
    ResearchDatasetService,
    build_observation_forecasts,
    build_research_operation_instruments,
    dataset_summary,
    get_curated_universe,
    list_curated_universes,
    prepare_daily_dataset,
    publish_verified_interval_dataset,
    require_supported_snapshot,
    run_factor_evaluation,
    verified_dataset_dates,
)


def test_research_domain_exports_canonical_symbols() -> None:
    assert FORECAST_POLICY_ID == legacy_forecasts.FORECAST_POLICY_ID


def test_research_facades_maintain_symbol_identity() -> None:
    assert build_observation_forecasts is legacy_forecasts.build_observation_forecasts
    assert ResearchDatasetService is legacy_datasets.ResearchDatasetService
    assert ResearchDatasetError is legacy_datasets.ResearchDatasetError
    assert prepare_daily_dataset is legacy_datasets.prepare_daily_dataset
    assert dataset_summary is legacy_datasets.dataset_summary
    assert (
        publish_verified_interval_dataset
        is legacy_datasets.publish_verified_interval_dataset
    )
    assert require_supported_snapshot is legacy_datasets.require_supported_snapshot
    assert verified_dataset_dates is legacy_datasets.verified_dataset_dates


def test_curated_universes_via_domain() -> None:
    universes = list_curated_universes()
    assert len(universes) >= 3
    ids = {u["universe_id"] for u in universes}
    assert "core_etf_universe" in ids

    core = get_curated_universe("core_etf_universe")
    assert core is not None
    assert core["universe_id"] == "core_etf_universe"
    assert len(core["members"]) >= 5


def test_research_operation_instruments_via_domain() -> None:
    db = SimpleNamespace(
        get_instrument_metadata_batch_sync=lambda symbols, asset_type: [
            {"symbol": "600000", "display_name": "浦发银行", "source": "test"}
        ]
    )
    preview = {
        "status": "available",
        "operations": [{"symbol": "600000", "operation": "buy_candidate"}],
    }
    result = build_research_operation_instruments(db, preview)
    assert result["resolved_count"] == 1
    assert result["items"][0]["display_name"] == "浦发银行"
    assert result["schema_version"] == RESEARCH_OPERATION_INSTRUMENTS_SCHEMA_VERSION
