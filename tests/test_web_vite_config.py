"""Vite build contract for the frontend bundle."""

from __future__ import annotations

from pathlib import Path


def test_vite_config_splits_application_features_for_start_build():
    config = Path("web/vite.config.ts").read_text()
    chunk_config = Path("web/src/app/chunk-config.ts").read_text()

    assert "appFeatureChunk" in config
    assert "const appChunk = appFeatureChunk(id)" in config
    assert "return appChunk" in config
    assert "/src/features/backtest/" in chunk_config
    assert "/src/features/decision/" in chunk_config
    assert "/src/features/market/" in chunk_config
    assert "/src/features/portfolio/" in chunk_config
    assert "/src/features/trading/" in chunk_config
    assert "feature-account" in chunk_config
