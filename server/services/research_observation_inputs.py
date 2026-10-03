"""Offline source and information-time boundaries for forward target observations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from analytics.dataset_snapshot import backtest_dataset_snapshot_content_id
from core.types import InstrumentKey, InstrumentType
from data.dataset.model import DatasetRef
from data.dataset.reader import DailyBarDatasetReadResult, read_daily_bar_dataset
from data.market.capture import read_provider_capture
from data.market.quality_evidence import read_market_quality_evidence
from data.market.revision import read_market_revision_materialization
from data.market.verification_evidence import read_market_verification_evidence
from data.storage.objects import ContentAddressedObjectStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import FORMULA_BINDING_CONTRACT, FormulaBinding
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.research_datasets import require_supported_snapshot
from strategy.schema import STRATEGY_PARAMETER_SCHEMAS, validate_strategy_params

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class ResearchObservationInputError(ValueError):
    """Stable public rejection; provider or filesystem details never escape."""


def load_research_observation_source(
    row: Mapping[str, Any], objects: ContentAddressedObjectStore
) -> dict[str, Any]:
    """Freeze a saved strategy definition without upgrading its historical proof."""
    config = _object(row.get("config_json"))
    metrics = _object(row.get("metrics_json"))
    try:
        result_id = row["id"]
        if type(result_id) is not int or result_id <= 0:
            raise ValueError
        start, end = (
            date.fromisoformat(config["start_date"]),
            date.fromisoformat(config["end_date"]),
        )
        if start > end:
            raise ValueError
        if config.get("strategy") == "dual_ma":
            detail = _dual_ma_source(config, metrics, objects, start, end)
        elif config.get("strategy") == "ai_formula_research":
            detail = _formula_source(config, metrics, start, end)
        else:
            raise ResearchObservationInputError("observation_strategy_unsupported")
    except ResearchObservationInputError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ResearchObservationInputError("observation_source_invalid") from None
    return {
        "source_result_id": result_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "source_code_verified": False,
        "source_historical_pit_verified": False,
        "cost_assumptions": metrics.get("cost_assumptions"),
        "cost_model_reference": detail.get("formula_binding", {}).get(
            "cost_model_reference"
        ),
        **detail,
    }


def read_research_observation_dataset(
    objects: ContentAddressedObjectStore,
    dataset_id: str,
    *,
    instruments: tuple[InstrumentKey, ...],
    start_date: date,
    now: datetime,
    calendar_rows: Sequence[dict[str, Any]],
    minimum_bars: int,
) -> DailyBarDatasetReadResult:
    """Read a complete fixed-start history ending at the latest closed session."""
    now = _instant(now)
    calendars = _calendars(calendar_rows, now=now)
    end = latest_closed_session(calendar_rows, now=now)
    result = _read(objects, dataset_id)
    snapshot = result.snapshot
    if not snapshot.verification_bound:
        raise ResearchObservationInputError("observation_dataset_unverified")
    if snapshot.instruments != tuple(
        sorted(instruments, key=lambda item: (item.instrument_type.value, item.symbol))
    ):
        raise ResearchObservationInputError("observation_dataset_universe_mismatch")
    if snapshot.start_date != start_date:
        raise ResearchObservationInputError("observation_dataset_start_mismatch")
    if snapshot.end_date != end:
        raise ResearchObservationInputError("observation_dataset_not_latest_closed")
    if snapshot.cutoff > now:
        raise ResearchObservationInputError("observation_dataset_cutoff_in_future")
    expected = _sessions_between(calendars, start_date, end)
    if tuple(p.partition_date for p in snapshot.partitions) != expected:
        raise ResearchObservationInputError("observation_dataset_prefix_incomplete")
    if type(minimum_bars) is not int or minimum_bars < 1:
        raise ResearchObservationInputError("observation_minimum_bars_invalid")
    if len(expected) < minimum_bars:
        raise ResearchObservationInputError("observation_dataset_warmup_incomplete")
    if any(
        max(bar.event_time, bar.available_at, bar.captured_at) > now
        or bar.event_time < _session_time(bar.session_date, time(15))
        for bar in result.bars
    ):
        raise ResearchObservationInputError("observation_bar_not_available")
    try:
        for partition in snapshot.partitions:
            verification = read_market_verification_evidence(
                objects, objects.resolve_ref(partition.verification_id)
            )
            if verification.checked_at > now:
                raise ResearchObservationInputError(
                    "observation_verification_not_available"
                )
            for materialization_id, quality_id in (
                (
                    verification.primary_materialization_id,
                    verification.primary_quality_id,
                ),
                (
                    verification.comparison_materialization_id,
                    verification.comparison_quality_id,
                ),
            ):
                materialization = read_market_revision_materialization(
                    objects, objects.resolve_ref(materialization_id)
                )
                capture = read_provider_capture(objects, materialization.capture_ref)
                quality = read_market_quality_evidence(
                    objects, objects.resolve_ref(quality_id)
                )
                if (
                    max(
                        capture.started_at,
                        capture.completed_at,
                        quality.report.checked_at,
                    )
                    > now
                ):
                    raise ResearchObservationInputError(
                        "observation_bound_evidence_not_available"
                    )
        if result.corporate_action_evidence:
            for field in ("captured_at", "available_at"):
                if _instant(result.corporate_action_evidence[field]) > now:
                    raise ResearchObservationInputError(
                        "observation_corporate_actions_not_available"
                    )
    except ResearchObservationInputError:
        raise
    except Exception:
        raise ResearchObservationInputError(
            "observation_bound_evidence_unreadable"
        ) from None
    return result


def latest_closed_session(
    calendar_rows: Sequence[dict[str, Any]], *, now: datetime
) -> date:
    now = _instant(now)
    calendars = _calendars(calendar_rows, now=now)
    today = now.astimezone(_SHANGHAI).date()
    if today.year not in calendars:
        raise ResearchObservationInputError("observation_calendar_current_year_missing")
    candidates = [
        day
        for dates in calendars.values()
        for day in dates
        if _session_time(day, time(15)) <= now
    ]
    if not candidates:
        raise ResearchObservationInputError(
            "observation_calendar_closed_session_missing"
        )
    latest = max(candidates)
    _require_years(calendars, latest.year, today.year)
    return latest


def observation_outcome_sessions(
    calendar_rows: Sequence[dict[str, Any]],
    *,
    published_at: datetime,
    horizon_sessions: int,
    now: datetime,
) -> tuple[date, date]:
    """Bind the first unopened session and an exact later session at publication."""
    now, published_at = _instant(now), _instant(published_at)
    if published_at > now:
        raise ResearchObservationInputError("observation_publication_in_future")
    if type(horizon_sessions) is not int or horizon_sessions < 1:
        raise ResearchObservationInputError("observation_horizon_invalid")
    calendars = _calendars(calendar_rows, now=now)
    future = sorted(
        day
        for dates in calendars.values()
        for day in dates
        if _session_time(day, time(9, 30)) > published_at
    )
    if len(future) <= horizon_sessions:
        raise ResearchObservationInputError("observation_calendar_horizon_missing")
    reference, end = future[0], future[horizon_sessions]
    _require_years(calendars, published_at.astimezone(_SHANGHAI).year, end.year)
    return reference, end


def _dual_ma_source(config, metrics, objects, start, end):
    dataset_id = config.get("dataset_id")
    if not dataset_id:
        raise ResearchObservationInputError(
            "observation_source_formal_dataset_required"
        )
    result = _read(objects, dataset_id)
    snapshot = result.snapshot
    if (snapshot.start_date, snapshot.end_date) != (start, end):
        raise ResearchObservationInputError("observation_source_dataset_mismatch")
    binding_id = (metrics.get("dataset_binding") or {}).get("dataset_id")
    if binding_id != dataset_id:
        raise ResearchObservationInputError("observation_source_dataset_mismatch")
    instruments = snapshot.instruments
    if (
        config.get("assets") is not None
        and _instruments(config["assets"]) != instruments
    ):
        raise ResearchObservationInputError("observation_source_universe_mismatch")
    params = config.get("params")
    if params is None:
        params = {key: config[key] for key in ("short_period", "long_period")}
    validated = validate_strategy_params(
        "dual_ma", STRATEGY_PARAMETER_SCHEMAS["dual_ma"], params
    )
    if validated != params or any(type(v) is not int for v in params.values()):
        raise ResearchObservationInputError(
            "observation_source_parameters_not_normalized"
        )
    return {
        "strategy_kind": "dual_ma",
        "parameters": validated,
        "dataset_id": dataset_id,
        "source_dataset_kind": "immutable_dataset",
        "instruments": _instrument_payload(instruments),
        "minimum_bars": validated["long_period"] + 1,
        "entry_target_weight": "1",
    }


def _formula_source(config, metrics, start, end):
    raw = _object(metrics.get("formula_binding"))
    if raw.get("schema_version") != FORMULA_BINDING_CONTRACT:
        raise ResearchObservationInputError("observation_formula_binding_invalid")
    binding = FormulaBinding(
        **{
            **raw,
            "universe": tuple(raw["universe"]),
            "anti_lookahead_assumptions": tuple(raw["anti_lookahead_assumptions"]),
        }
    )
    if (
        binding.to_dict() != raw
        or metrics.get("formula_fingerprint") != binding.fingerprint
    ):
        raise ResearchObservationInputError("observation_formula_fingerprint_mismatch")
    snapshot = _object(metrics.get("dataset_snapshot"))
    core = {k: v for k, v in snapshot.items() if k != "snapshot_id"}
    if snapshot.get("schema_version") != "karkinos.dataset_snapshot.v1" or snapshot.get(
        "snapshot_id"
    ) != backtest_dataset_snapshot_content_id(core):
        raise ResearchObservationInputError("observation_source_snapshot_invalid")
    if (
        binding.dataset_snapshot_id != snapshot["snapshot_id"]
        or binding.start_date != start.isoformat()
        or binding.end_date != end.isoformat()
        or snapshot.get("date_range")
        != {"start": start.isoformat(), "end": end.isoformat()}
        or config.get("params", {}).get("formula_fingerprint") != binding.fingerprint
    ):
        raise ResearchObservationInputError("observation_formula_source_mismatch")
    instruments = _instruments(snapshot.get("symbol_universe"))
    if (
        set(binding.universe) != {item.symbol for item in instruments}
        or _instruments(config.get("assets")) != instruments
    ):
        raise ResearchObservationInputError("observation_source_universe_mismatch")
    if any(item.get("frequency") != "1d" for item in snapshot["symbol_universe"]):
        raise ResearchObservationInputError("observation_source_frequency_unsupported")
    execution = _object(metrics.get("signal_execution_evidence"))
    expected_weight = 1.0 / min(4, len(instruments))
    if (
        execution.get("schema_version") != "karkinos.ai.formula_signal_execution.v1"
        or execution.get("model_position_size_ignored") is not True
        or execution.get("allocation_slots") != min(4, len(instruments))
        or execution.get("canonical_target_weight") != expected_weight
        or execution.get("evidence_fingerprint")
        != content_fingerprint(
            {
                key: value
                for key, value in execution.items()
                if key != "evidence_fingerprint"
            }
        )
    ):
        raise ResearchObservationInputError("observation_formula_sizing_unbound")
    return {
        "strategy_kind": "formula",
        "formula_binding": raw,
        "parameters": binding.parameter_values,
        "dataset_id": binding.dataset_snapshot_id,
        "source_dataset_kind": "analytics_snapshot",
        "instruments": _instrument_payload(instruments),
        "minimum_bars": max(_warmup(binding.formula_ast[k]) for k in ("entry", "exit")),
        "entry_target_weight": str(Decimal(1) / Decimal(min(4, len(instruments)))),
        "signal_execution_evidence": execution,
    }


def _warmup(node: Mapping[str, Any]) -> int:
    op = node["op"]
    if op in {"field", "constant"}:
        return 1
    if op == "atr":
        return node["window"]
    if "left" in node:
        return max(_warmup(node["left"]), _warmup(node["right"])) + (op == "cross")
    child = _warmup(node["input"])
    if "period" in node:
        return child + node["period"]
    if "window" in node and op != "ema":
        return child + node["window"] - 1
    return child


def _read(objects, dataset_id):
    try:
        result = read_daily_bar_dataset(
            objects, DatasetRef(objects.resolve_ref(dataset_id))
        )
        require_supported_snapshot(result.snapshot)
        _instruments(_instrument_payload(result.snapshot.instruments))
        return result
    except ResearchObservationInputError:
        raise
    except Exception:
        raise ResearchObservationInputError("observation_dataset_unreadable") from None


def _instruments(values):
    if not isinstance(values, list) or not values:
        raise ResearchObservationInputError("observation_source_universe_invalid")
    items = tuple(
        sorted(
            (
                InstrumentKey(
                    item["symbol"],
                    InstrumentType(item.get("instrument_type") or item["asset_class"]),
                )
                for item in values
            ),
            key=lambda item: (item.instrument_type.value, item.symbol),
        )
    )
    if len({i.symbol for i in items}) != len(items) or any(
        i.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
        for i in items
    ):
        raise ResearchObservationInputError("observation_source_universe_invalid")
    return items


def _instrument_payload(instruments):
    return [
        {"symbol": item.symbol, "instrument_type": item.instrument_type.value}
        for item in instruments
    ]


def _object(value):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ResearchObservationInputError("observation_source_json_invalid") from None


def _instant(value):
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if (
            not isinstance(result, datetime)
            or result.tzinfo is None
            or result.utcoffset() is None
        ):
            raise ValueError
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ResearchObservationInputError("observation_timestamp_invalid") from None


def _session_time(day, at):
    return datetime.combine(day, at, tzinfo=_SHANGHAI)


def _calendars(rows, *, now):
    calendars = {}
    for row in rows:
        try:
            verified = (
                isinstance(row, dict)
                and validate_verified_market_calendar(row).verified
            )
        except (TypeError, ValueError, OverflowError):
            verified = False
        if not verified or row.get("exchange") != "SSE":
            raise ResearchObservationInputError("observation_calendar_unverified")
        if (
            max(
                _instant(row.get("fetched_at")),
                _instant(row.get("official_verified_at")),
            )
            > now
        ):
            raise ResearchObservationInputError("observation_calendar_not_available")
        year = int(row["year"])
        if year in calendars:
            raise ResearchObservationInputError("observation_calendar_ambiguous")
        days = row.get("days", row.get("days_json"))
        days = json.loads(days) if isinstance(days, str) else days
        calendars[year] = tuple(
            date.fromisoformat(item["date"]) for item in days if item["is_trading_day"]
        )
    return calendars


def _require_years(calendars, start, end):
    if any(year not in calendars for year in range(start, end + 1)):
        raise ResearchObservationInputError("observation_calendar_year_missing")


def _sessions_between(calendars, start, end):
    _require_years(calendars, start.year, end.year)
    return tuple(
        sorted(
            day for dates in calendars.values() for day in dates if start <= day <= end
        )
    )
