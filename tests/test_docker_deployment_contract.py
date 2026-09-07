from __future__ import annotations

import shlex
from pathlib import Path

RUNTIME_PACKAGE_DIRS = {
    "account_truth",
    "analytics",
    "backtest",
    "core",
    "data",
    "domain",
    "execution",
    "notification",
    "risk",
    "server",
    "strategy",
}


def _copy_sources(dockerfile: str) -> set[str]:
    sources: set[str] = set()
    for raw_line in dockerfile.splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY ") or line.startswith("COPY --from="):
            continue
        fields = shlex.split(line)
        sources.update(fields[1:-1])
    return sources


def _dockerignore_rules() -> list[str]:
    return [
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_docker_build_inputs_are_explicitly_allowlisted() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    sources = _copy_sources(dockerfile)

    expected_sources = {
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "LICENSE",
        "web/package.json",
        "web/package-lock.json",
        "web/index.html",
        "web/tsconfig.json",
        "web/vite.config.ts",
        "web/src/",
        *(f"{package}/" for package in RUNTIME_PACKAGE_DIRS),
    }
    assert sources == expected_sources
    assert "COPY . ." not in dockerfile
    assert "COPY ./ ./" not in dockerfile


def test_docker_context_is_deny_by_default_and_matches_copy_allowlist() -> None:
    lines = _dockerignore_rules()

    assert lines[0] == "**"
    allowed = {line[1:] for line in lines if line.startswith("!")}
    expected_allowed = {
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "LICENSE",
        "web/",
        "web/package.json",
        "web/package-lock.json",
        "web/index.html",
        "web/tsconfig.json",
        "web/vite.config.ts",
        "web/src/",
        "web/src/**/*.ts",
        "web/src/**/*.tsx",
        "web/src/**/*.css",
        "strategy/extensions/__init__.py",
        *(f"{package}/" for package in RUNTIME_PACKAGE_DIRS),
        *(f"{package}/**/*.py" for package in RUNTIME_PACKAGE_DIRS),
    }
    assert allowed == expected_allowed
    assert "data/store/**" in lines
    assert "strategy/extensions/**" in lines
    assert "strategy/extensions/__init__.py" in allowed
    assert not any(pattern.endswith("/**/") for pattern in allowed)
    assert "web/node_modules/" in lines
    assert "web/dist/" in lines


def test_docker_context_denies_private_runtime_artifacts() -> None:
    rules = set(_dockerignore_rules())
    required_denies = {
        "**/.env",
        "**/.env.*",
        "**/config.json",
        "**/secret.py",
        "**/broker_statement.csv",
        "**/*.db",
        "**/*.sqlite",
        "**/*.sqlite3",
        "**/*.duckdb",
        "**/logs/",
        "**/reports/",
        "**/exports/",
        "**/screenshots/",
        "data/store/**",
        "strategy/extensions/**",
        "web/node_modules/",
        "web/dist/",
    }

    assert required_denies <= rules
    assert "!strategy/extensions/__init__.py" in rules


def test_docker_runtime_uses_the_python_and_uv_release_baseline() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM node:24.20.0-alpine3.24" in dockerfile
    assert "FROM python:3.12.13-slim-trixie" in dockerfile
    assert "FROM node:24-alpine" not in dockerfile
    assert "FROM python:3.12-slim" not in dockerfile
    assert "FROM python:3.14-slim" not in dockerfile
    assert "ARG UV_VERSION=0.11.28" in dockerfile
    assert 'pip install --no-cache-dir "uv==${UV_VERSION}"' in dockerfile


def test_deployment_examples_keep_scheduler_always_on_and_authority_fail_closed() -> (
    None
):
    environment_template = Path(".env.example").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "KARKINOS_LIVE_AUTO_START" not in environment_template
    assert "KARKINOS_LIVE_AUTO_START" not in compose
    assert "/api/settings/live/status" in compose
    assert "['running'] is True" in compose
    assert "Start runtime with fail-closed defaults" in workflow
    assert "karkinos:ci python -m server --no-live" not in workflow
    assert '"live scheduler running"' in Path(
        "scripts/ci/verify_docker_runtime.py"
    ).read_text(encoding="utf-8")
    assert '"automatic trading disabled"' in Path(
        "scripts/ci/verify_docker_runtime.py"
    ).read_text(encoding="utf-8")
