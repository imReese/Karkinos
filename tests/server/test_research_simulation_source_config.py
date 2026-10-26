"""Strict local research source selection carries references only."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from typing import Any

import pytest

from server.config import (
    BacktestConfig,
    ResearchSimulationSourceConfig,
    ServerConfig,
)


def _source() -> dict[str, Any]:
    return {
        "session_id": "fixture-session",
        "draft_id": "fixture-draft",
        "backtest_run_id": "fixture-backtest",
        "critique_id": "fixture-critique",
        "canonical_backtest_result_id": 27,
    }


def _write_config(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("payload", [{}, {"research_simulation_source": None}])
def test_research_simulation_source_defaults_to_unselected(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    assert ServerConfig().research_simulation_source is None
    assert (
        ServerConfig.from_json(
            _write_config(tmp_path, payload)
        ).research_simulation_source
        is None
    )


def test_research_simulation_source_loads_exact_immutable_references(
    tmp_path: Path,
) -> None:
    source = ServerConfig.from_json(
        _write_config(tmp_path, {"research_simulation_source": _source()})
    ).research_simulation_source

    assert isinstance(source, ResearchSimulationSourceConfig)
    assert asdict(source) == _source()
    with pytest.raises(FrozenInstanceError):
        source.session_id = "other-session"  # type: ignore[misc]


def test_research_simulation_source_belongs_only_to_server_config(
    tmp_path: Path,
) -> None:
    assert not hasattr(BacktestConfig(), "research_simulation_source")
    with pytest.raises(ValueError, match="unsupported top-level fields"):
        BacktestConfig.from_json(
            _write_config(tmp_path, {"research_simulation_source": _source()})
        )


@pytest.mark.parametrize("value", [True, 1, "fixture-source", [], [{}]])
def test_research_simulation_source_rejects_non_object_values(
    tmp_path: Path, value: object
) -> None:
    with pytest.raises(ValueError, match="must be an object or null"):
        ServerConfig.from_json(
            _write_config(tmp_path, {"research_simulation_source": value})
        )


@pytest.mark.parametrize("field_name", tuple(_source()))
def test_research_simulation_source_requires_every_exact_reference(
    tmp_path: Path, field_name: str
) -> None:
    source = _source()
    del source[field_name]
    with pytest.raises(ValueError, match=f"requires fields: {field_name}"):
        ServerConfig.from_json(
            _write_config(tmp_path, {"research_simulation_source": source})
        )


@pytest.mark.parametrize(
    "field_name", ["approved", "formula_ast", "account_cash", "authorizes_execution"]
)
def test_research_simulation_source_rejects_extra_authority_or_payload_fields(
    tmp_path: Path, field_name: str
) -> None:
    source = {**_source(), field_name: "fixture-value-must-not-be-echoed"}
    with pytest.raises(ValueError, match="contains unsupported fields") as error:
        ServerConfig.from_json(
            _write_config(tmp_path, {"research_simulation_source": source})
        )
    assert "fixture-value-must-not-be-echoed" not in str(error.value)


@pytest.mark.parametrize(
    "field_name", ["session_id", "draft_id", "backtest_run_id", "critique_id"]
)
@pytest.mark.parametrize(
    "value", [None, True, 7, 1.2, [], {}, "", " \t", " id", "id ", "id id", "id\nid"]
)
def test_research_simulation_source_rejects_invalid_string_references(
    tmp_path: Path, field_name: str, value: object
) -> None:
    source = {**_source(), field_name: value}
    with pytest.raises(ValueError, match=f"{field_name} must be a non-empty string"):
        ServerConfig.from_json(
            _write_config(tmp_path, {"research_simulation_source": source})
        )
    with pytest.raises(ValueError, match=f"{field_name} must be a non-empty string"):
        ResearchSimulationSourceConfig(**source)


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1.0, "1", "", [], {}])
def test_research_simulation_source_requires_positive_integer_result_reference(
    tmp_path: Path, value: object
) -> None:
    source = {**_source(), "canonical_backtest_result_id": value}
    with pytest.raises(
        ValueError, match="canonical_backtest_result_id.*positive integer"
    ):
        ServerConfig.from_json(
            _write_config(tmp_path, {"research_simulation_source": source})
        )
    with pytest.raises(
        ValueError, match="canonical_backtest_result_id.*positive integer"
    ):
        ResearchSimulationSourceConfig(**source)
