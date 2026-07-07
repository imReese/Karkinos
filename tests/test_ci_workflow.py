from __future__ import annotations

import json
from pathlib import Path


def test_ci_runs_backend_frontend_and_profit_discipline_smoke_path() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()
    package = json.loads(Path("web/package.json").read_text())

    assert "Run backend test suite" in workflow
    assert "uv run python -m pytest" in workflow
    assert "Run deterministic Profit Discipline smoke path" in workflow
    assert "uv run python -m pytest tests/test_profit_discipline_smoke.py" in workflow
    assert "Run acceptance audit report" in workflow
    assert "uv run python scripts/export_acceptance_audit.py --audit all" in workflow

    assert "format:check" in package["scripts"]
    assert package["scripts"]["format:check"].startswith("prettier --check")
    assert "npm --prefix web run format:check" in workflow
    assert "npm --prefix web run build" in workflow
    assert "npm --prefix web run test" in workflow


def test_ci_uses_node24_compatible_github_actions() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/setup-node@v6" in workflow
    assert 'node-version: "24"' in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "actions/setup-node@v4" not in workflow


def test_ci_repository_hygiene_blocks_runtime_and_generated_artifacts() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "Check tracked private artifacts" in workflow
    assert "data/store/" in workflow
    assert "logs/" in workflow
    assert "exports/" in workflow
    assert "screenshots/" in workflow
    assert "reports/" in workflow
    assert ".*\\.(db|sqlite|duckdb)" in workflow
