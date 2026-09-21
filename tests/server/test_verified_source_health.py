from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from server.db import AppDatabase
from server.routes import market
from server.services.verified_daily_market_data import (
    VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
    VerifiedDailySourceResolution,
)
from server.services.verified_source_health import (
    VERIFIED_SOURCE_HEALTH_SCHEMA_VERSION,
    build_verified_source_health_response,
)


def _append(
    db: AppDatabase,
    *,
    timestamp: str,
    resolution: VerifiedDailySourceResolution,
    result_ref: str | None = None,
    error_type: str | None = None,
) -> None:
    db.append_event_sync(
        event_type=VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
        timestamp=timestamp,
        entity_type="market_daily_job",
        entity_id=f"job:{timestamp}",
        source="data_worker",
        source_ref=f"job:{timestamp}",
        payload={
            **resolution.to_payload(),
            "job_id": f"job:{timestamp}",
            "attempt": 1,
            "result_ref": result_ref,
            "error_type": error_type,
        },
    )


def test_verified_source_health_aggregates_observed_routing_without_invented_rates(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    _append(
        db,
        timestamp="2026-09-21T09:00:00+00:00",
        resolution=VerifiedDailySourceResolution(
            source_policy_id="karkinos.market.source.free_cn_research.v1",
            outcome="conflict",
            attempted_pairs=(("baostock", "akshare_tencent"),),
            selected_pair=("baostock", "akshare_tencent"),
        ),
        error_type="VerifiedDailyMarketDataNotPublishable",
    )
    _append(
        db,
        timestamp="2026-09-21T10:00:00+00:00",
        resolution=VerifiedDailySourceResolution(
            source_policy_id="karkinos.market.source.free_cn_research.v1",
            outcome="matched",
            attempted_pairs=(
                ("baostock", "akshare_tencent"),
                ("akshare_tencent", "akshare"),
            ),
            unavailable_providers=("baostock",),
            selected_pair=("akshare_tencent", "akshare"),
        ),
        result_ref="dataset:sha256:" + "a" * 64,
    )
    db.append_event_sync(
        event_type=VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
        timestamp="2026-09-21T08:00:00+00:00",
        entity_type="market_daily_job",
        entity_id="invalid",
        source="data_worker",
        source_ref="invalid",
        payload={"schema_version": "unknown"},
    )

    health = build_verified_source_health_response(db, limit=100)

    assert health["schema_version"] == VERIFIED_SOURCE_HEALTH_SCHEMA_VERSION
    assert health["status"] == "observed"
    assert health["sample_count"] == 2
    assert health["invalid_event_count"] == 1
    assert health["outcome_counts"] == {
        "matched": 1,
        "conflict": 1,
        "unavailable": 0,
        "quality_blocked": 0,
    }
    assert health["failover_count"] == 1
    assert health["attempted_pair_counts"] == [
        {
            "primary": "baostock",
            "comparison": "akshare_tencent",
            "count": 2,
        },
        {
            "primary": "akshare_tencent",
            "comparison": "akshare",
            "count": 1,
        },
    ]
    assert health["selected_pair_counts"] == [
        {
            "primary": "akshare_tencent",
            "comparison": "akshare",
            "count": 1,
        },
        {
            "primary": "baostock",
            "comparison": "akshare_tencent",
            "count": 1,
        },
    ]
    assert health["unavailable_provider_counts"] == [
        {"provider": "baostock", "count": 1}
    ]
    assert health["source_policy_ids"] == ["karkinos.market.source.free_cn_research.v1"]
    assert health["latest"] == {
        "timestamp": "2026-09-21T10:00:00+00:00",
        "outcome": "matched",
        "source_policy_id": "karkinos.market.source.free_cn_research.v1",
        "selected_pair": {
            "primary": "akshare_tencent",
            "comparison": "akshare",
        },
        "unavailable_providers": ["baostock"],
        "result_ref": "dataset:sha256:" + "a" * 64,
        "error_type": None,
    }


def test_verified_source_health_is_explicit_when_no_samples(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    health = build_verified_source_health_response(db, limit=25)

    assert health["status"] == "no_samples"
    assert health["window_limit"] == 25
    assert health["sample_count"] == 0
    assert health["latest"] is None


def test_verified_source_health_endpoint_is_read_only_and_validates_limit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _append(
        db,
        timestamp="2026-09-21T10:00:00+00:00",
        resolution=VerifiedDailySourceResolution(
            source_policy_id="karkinos.market.source.free_cn_research.v1",
            outcome="matched",
            attempted_pairs=(("baostock", "akshare_tencent"),),
            selected_pair=("baostock", "akshare_tencent"),
        ),
        result_ref="dataset:sha256:" + "b" * 64,
    )
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(db=db),
    )

    router = market.create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/verified-source-health"
    )

    response = asyncio.run(endpoint(limit=20))

    assert response.schema_version == VERIFIED_SOURCE_HEALTH_SCHEMA_VERSION
    assert response.sample_count == 1
    assert response.outcome_counts["matched"] == 1
    assert response.latest is not None
    assert response.latest.selected_pair == {
        "primary": "baostock",
        "comparison": "akshare_tencent",
    }

    with pytest.raises(Exception) as caught:
        asyncio.run(endpoint(limit=0))
    assert getattr(caught.value, "status_code", None) == 422


def test_verified_source_health_ignores_non_object_or_malformed_payloads(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    # event_log JSON validity is enforced by the database; valid JSON with the
    # wrong shape still must be treated as invalid telemetry, not as a sample.
    db.append_event_sync(
        event_type=VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
        timestamp="2026-09-21T10:00:00+00:00",
        entity_type="market_daily_job",
        entity_id="list",
        source="data_worker",
        source_ref="list",
        payload=json.dumps(["not", "an", "object"]),
    )

    health = build_verified_source_health_response(db, limit=10)

    assert health["sample_count"] == 0
    assert health["invalid_event_count"] == 1
