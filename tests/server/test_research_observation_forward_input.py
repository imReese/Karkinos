"""A new forward warmup never rewrites or recertifies its historical report."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from server.services.research_paper_books import ResearchPaperBookService
from tests.server.test_research_observation_inputs import (
    DAYS,
    NOW,
    dataset,
    formula_source,
    source,
)
from tests.server.test_research_observations_journey import journey  # noqa: F401

pytestmark = pytest.mark.product_smoke


def save_old_report(service, ref, *, changes=None):
    row = source(ref)
    config = {
        **json.loads(row["config_json"]),
        "dataset_id": None,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        **(changes or {}),
    }
    return asyncio.run(
        service.db.save_backtest_result(
            config_json=json.dumps(config),
            metrics_json=json.dumps({"cost_assumptions": {"slippage_bps": "12.5"}}),
            initial_cash=100_000,
            final_equity=100_000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )


def request(result_id, ref):
    return {
        "request_id": str(uuid4()),
        "source_backtest_result_id": result_id,
        "horizon_sessions": 1,
        "forward_dataset_id": ref.dataset_id,
    }


def test_old_report_starts_new_forward_book_without_rewriting_research(
    journey, tmp_path
):
    client, service, current, seed, _ = journey
    result_id = save_old_report(service, seed)
    original = asyncio.run(service.db.get_backtest_result(result_id))
    info = client.get(f"/api/research-observations/sources/{result_id}")
    assert info.status_code == 200, info.text
    assert info.json() == {
        "source_backtest_result_id": result_id,
        "strategy_kind": "dual_ma",
        "instruments": [{"symbol": "600000", "instrument_type": "stock"}],
        "minimum_bars": 4,
    }
    assert service.repository.list() == []
    command = request(result_id, seed)
    legacy = client.post(
        "/api/research-observations",
        json={
            key: value for key, value in command.items() if key != "forward_dataset_id"
        },
    )
    assert legacy.status_code == 422
    assert legacy.json()["detail"] == "observation_source_formal_dataset_required"
    response = client.post("/api/research-observations", json=command)
    assert response.status_code == 200, response.text
    started = response.json()
    identity = started["id"]
    detail = client.get(f"/api/research-observations/{identity}").json()
    assert detail["source"]["start_date"] == "2024-01-01"
    assert detail["source"]["end_date"] == "2024-12-31"
    assert detail["source"]["dataset_id"] is None
    assert detail["source"]["source_dataset_kind"] == "saved_report"
    assert detail["source"]["source_historical_pit_verified"] is False
    assert detail["source"]["source_code_verified"] is False
    assert detail["source"]["forward_input"] == {
        "dataset_id": seed.dataset_id,
        "start_date": "2026-09-14",
        "end_date": "2026-09-18",
    }
    assert detail["publications"] == detail["outcomes"] == []
    assert asyncio.run(service.db.get_backtest_result(result_id)) == original
    assert client.post("/api/research-observations", json=command).json() == started
    assert len(service.repository.list()) == 1

    books = ResearchPaperBookService(service.db, clock=lambda: current[0])
    book = books.start(
        identity,
        request_id=str(uuid4()),
        initial_cash=Decimal("100000"),
        corporate_action_mode="price_only",
    )
    assert book["evaluation_start"] == "2026-09-21"
    current[0] += timedelta(seconds=1)
    published = client.post(
        f"/api/research-observations/{identity}/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": seed.dataset_id,
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["publication_id"]
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    _, extension = dataset(tmp_path / "research", days=DAYS[:6], cutoff=current[0])
    settled = books.settle(
        identity,
        request_id=str(uuid4()),
        expected_version=0,
        dataset_id=extension.dataset_id,
    )
    assert settled["last_settled_session"] == "2026-09-21"
    assert len(settled["steps"]) == 1
    assert settled["source"]["start_date"] == "2024-01-01"
    assert settled["source"]["forward_input"]["dataset_id"] == seed.dataset_id
    assert asyncio.run(service.db.get_backtest_result(result_id)) == original


@pytest.mark.parametrize(
    "options,changes,error",
    [
        ({"verified": False}, {}, "observation_dataset_unverified"),
        ({"days": DAYS[:4]}, {}, "observation_dataset_not_latest_closed"),
        (
            {"days": (DAYS[0], DAYS[1], DAYS[3], DAYS[4])},
            {},
            "observation_dataset_prefix_incomplete",
        ),
        ({"days": DAYS[3:5]}, {}, "observation_dataset_warmup_incomplete"),
        (
            {"cutoff": NOW + timedelta(seconds=1)},
            {},
            "observation_dataset_cutoff_in_future",
        ),
        (
            {},
            {"assets": [{"symbol": "600001", "asset_class": "stock"}]},
            "observation_dataset_universe_mismatch",
        ),
    ],
)
def test_seed_requires_current_complete_verified_inputs_before_start(
    journey, tmp_path, options, changes, error
):
    client, service, _, original_seed, _ = journey
    result_id = save_old_report(service, original_seed, changes=changes)
    _, seed = dataset(tmp_path / "research", **options)
    response = client.post("/api/research-observations", json=request(result_id, seed))
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == error
    assert service.repository.list() == []


def test_forward_seed_identity_is_bound_to_retries_and_manual_publication(
    journey, tmp_path
):
    client, service, _, seed, _ = journey
    result_id = save_old_report(service, seed)
    command = request(result_id, seed)
    started = client.post("/api/research-observations", json=command)
    assert started.status_code == 200, started.text
    _, changed = dataset(tmp_path / "research", closes={DAYS[0]: "12"})
    conflict = client.post(
        "/api/research-observations",
        json={**command, "forward_dataset_id": changed.dataset_id},
    )
    assert conflict.status_code == 409
    rejected = client.post(
        f"/api/research-observations/{started.json()['id']}/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": changed.dataset_id,
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["publication_id"] is None
    assert (
        rejected.json()["last_blocker"]["code"]
        == "observation_dataset_frozen_prefix_changed"
    )


@pytest.mark.parametrize("tampered", [False, True])
def test_formula_forward_seed_keeps_original_binding_and_requires_its_integrity(
    journey, tampered
):
    client, service, _, seed, _ = journey
    row = formula_source()
    if tampered:
        row["metrics_json"]["signal_execution_evidence"]["canonical_target_weight"] = (
            0.1
        )
    result_id = asyncio.run(
        service.db.save_backtest_result(
            config_json=json.dumps(row["config_json"]),
            metrics_json=json.dumps(row["metrics_json"]),
            initial_cash=100_000,
            final_equity=100_000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    info = client.get(f"/api/research-observations/sources/{result_id}")
    response = client.post("/api/research-observations", json=request(result_id, seed))
    if tampered:
        assert info.status_code == response.status_code == 422
        assert response.json()["detail"] == "observation_formula_sizing_unbound"
        assert service.repository.list() == []
    else:
        assert info.status_code == response.status_code == 200
        assert info.json()["minimum_bars"] == 4
        detail = client.get(
            f"/api/research-observations/{response.json()['id']}"
        ).json()
        assert (
            detail["source"]["formula_binding"]
            == row["metrics_json"]["formula_binding"]
        )
        assert (
            detail["source"]["dataset_id"]
            == row["metrics_json"]["dataset_snapshot"]["snapshot_id"]
        )
        assert detail["source"]["forward_input"]["dataset_id"] == seed.dataset_id
