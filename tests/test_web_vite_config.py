"""Vite build contract for the frontend bundle."""

from __future__ import annotations

from pathlib import Path


def test_vite_config_splits_application_features_for_start_build():
    config = Path("web/vite.config.ts").read_text()
    chunk_config = Path("web/src/app/chunk-config.ts").read_text()

    assert "appFeatureChunk" in config
    assert "codeSplitting" in config
    assert "includeDependenciesRecursively: false" in config
    assert "name: (id) => appFeatureChunk(id) ?? null" in config
    assert "manualChunks" not in config
    assert "/src/features/backtest/" in chunk_config
    assert "/src/features/decision/" in chunk_config
    assert "/src/features/market/" in chunk_config
    assert "/src/features/portfolio/" in chunk_config
    assert "/src/features/trading/" in chunk_config
    assert "feature-account" in chunk_config


def test_vite_dev_proxy_targets_the_isolated_source_backend():
    config = Path("web/vite.config.ts").read_text()

    assert "process.env.KARKINOS_DEV_BACKEND_URL" in config
    assert "'http://127.0.0.1:8001'" in config
    assert ").replace(/^http/, 'ws')" in config
    assert "target: 'http://127.0.0.1:8000'" not in config
    assert "target: 'ws://127.0.0.1:8000'" not in config
