from __future__ import annotations

import json
import re
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
    dockerfile = Path("Dockerfile").read_text()
    package = json.loads(Path("web/package.json").read_text())
    nvmrc = Path(".nvmrc").read_text().strip()
    npmrc = Path("web/.npmrc").read_text().strip()

    action_refs = re.findall(r"uses:\s+([^\s#]+)", workflow)
    assert action_refs
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref) for ref in action_refs)
    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1" in workflow
    )
    assert (
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
        in workflow
    )
    assert (
        "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0"
        in workflow
    )
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
        in workflow
    )
    assert (
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1"
        in workflow
    )
    assert set(re.findall(r'node-version:\s*"([^"]+)"', workflow)) == {"24"}
    assert dockerfile.startswith(
        "# ---- Stage 1: Build React frontend ----\nFROM node:24-alpine"
    )
    assert package["engines"]["node"] == ">=24.0.0 <25.0.0"
    assert nvmrc == "24"
    assert npmrc == "engine-strict=true"


def test_ci_repository_hygiene_blocks_runtime_and_generated_artifacts() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "Check tracked private artifacts" in workflow
    assert "data/store/" in workflow
    assert "logs/" in workflow
    assert "exports/" in workflow
    assert "screenshots/" in workflow
    assert "reports/" in workflow
    assert ".*\\.(db|sqlite|duckdb)" in workflow
