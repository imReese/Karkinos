from __future__ import annotations

from server.services.data_health import build_data_health


def test_build_data_health_preserves_quote_snapshot_structure():
    health = build_data_health(
        watchlist=[("600519", "stock")],
        latest_quotes={
            "600519": {
                "timestamp": "2026-04-18T09:30:00",
                "price": 1500.0,
            }
        },
        bar_coverage={
            "600519": {
                "start": "2020-01-01",
                "end": "2026-04-17",
                "rows": 1200,
            }
        },
    )

    assert health["quotes"] == [
        {
            "symbol": "600519",
            "asset_class": "stock",
            "timestamp": "2026-04-18T09:30:00",
            "price": 1500.0,
        }
    ]


def test_build_data_health_includes_bar_coverage_rows():
    health = build_data_health(
        watchlist=[("600519", "stock"), ("510300", "etf")],
        latest_quotes={},
        bar_coverage={
            "600519": {
                "start": "2020-01-01",
                "end": "2026-04-17",
                "rows": 1200,
            },
            "510300": {
                "start": "2021-01-01",
                "end": "2026-04-17",
                "rows": 800,
            },
        },
    )

    assert health["bars"] == [
        {
            "symbol": "600519",
            "start": "2020-01-01",
            "end": "2026-04-17",
            "rows": 1200,
        },
        {
            "symbol": "510300",
            "start": "2021-01-01",
            "end": "2026-04-17",
            "rows": 800,
        },
    ]
