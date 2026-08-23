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
    lines = [
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

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
        "web/src/**/",
        "web/src/**/*.ts",
        "web/src/**/*.tsx",
        "web/src/**/*.css",
        "strategy/extensions/__init__.py",
        *(f"{package}/" for package in RUNTIME_PACKAGE_DIRS),
        *(f"{package}/**/" for package in RUNTIME_PACKAGE_DIRS),
        *(f"{package}/**/*.py" for package in RUNTIME_PACKAGE_DIRS),
    }
    assert allowed == expected_allowed
    assert "data/store/" in lines
    assert "strategy/extensions/**" in lines
    assert "strategy/extensions/__init__.py" in allowed
    assert not any(
        pattern.endswith("/**") for pattern in allowed if pattern != "web/src/**/"
    )
    assert "web/node_modules/" in lines
    assert "web/dist/" in lines


def test_docker_context_contract_checks_private_sentinel_files() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    absent_checks = {
        line.strip().removeprefix("&& ").removesuffix("\\").strip()
        for line in workflow.splitlines()
        if "test ! -e /build-context/" in line
    }
    expected_checks = {
        "test ! -e /build-context/config.json",
        "test ! -e /build-context/broker_statement.csv",
        "test ! -e /build-context/secret.py",
        "test ! -e /build-context/.env",
        "test ! -e /build-context/data/store/runtime.sqlite",
        "test ! -e /build-context/data/store/private_runtime.py",
        "test ! -e /build-context/logs",
        "test ! -e /build-context/reports",
        "test ! -e /build-context/exports",
        "test ! -e /build-context/screenshots",
        "test ! -e /build-context/.playwright-mcp",
        "test ! -e /build-context/strategy/extensions/private_strategy.py",
        "test ! -e /build-context/account_truth/private-export.csv",
        "test ! -e /build-context/server/account-snapshot.json",
        "test ! -e /build-context/web/src/private-account.json",
    }

    assert absent_checks == expected_checks
    assert "test ! -e /build-context/data/store" not in absent_checks


def test_docker_runtime_uses_the_python_and_uv_release_baseline() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "FROM python:3.14-slim" not in dockerfile
    assert "ARG UV_VERSION=0.11.28" in dockerfile
    assert 'pip install --no-cache-dir "uv==${UV_VERSION}"' in dockerfile


def test_deployment_examples_default_to_no_live_scheduler() -> None:
    environment_template = Path(".env.example").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "KARKINOS_LIVE_AUTO_START=false" in environment_template
    assert "KARKINOS_LIVE_AUTO_START=true" not in environment_template
    assert "KARKINOS_LIVE_AUTO_START=${KARKINOS_LIVE_AUTO_START:-false}" in compose
    assert "Start runtime with fail-closed defaults" in workflow
    assert "karkinos:ci python -m server --no-live" not in workflow
    assert '"live scheduler auto-start"' in Path(
        "scripts/verify_docker_runtime.py"
    ).read_text(encoding="utf-8")
