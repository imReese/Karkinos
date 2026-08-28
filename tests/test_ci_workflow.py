from __future__ import annotations

import json
import re
from pathlib import Path


def test_ci_runs_backend_frontend_and_profit_discipline_smoke_path() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()
    pyproject = Path("pyproject.toml").read_text()
    package = json.loads(Path("web/package.json").read_text())

    assert "Run backend test suite" in workflow
    assert "uv run python -m pytest" in workflow
    assert "-n 4 --dist loadfile --max-worker-restart=0" in workflow
    assert '"pytest-xdist>=3.8.0"' in pyproject
    assert "Run deterministic Profit Discipline smoke path" in workflow
    assert "uv run python -m pytest tests/test_profit_discipline_smoke.py" in workflow
    assert "Run repository acceptance audit report" in workflow
    assert "uv run python scripts/export_acceptance_audit.py --audit all" in workflow

    assert "format:check" in package["scripts"]
    assert package["scripts"]["format:check"].startswith("prettier --check")
    assert "npm --prefix web run format:check" in workflow
    assert "npm --prefix web run build" in workflow
    assert "npm --prefix web run test" in workflow


def test_ci_uses_node24_compatible_github_actions() -> None:
    workflow = "\n".join(
        path.read_text() for path in sorted(Path(".github/workflows").glob("*.yml"))
    )
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


def test_release_reuses_exact_successful_main_ci_before_publishing() -> None:
    ci_workflow = Path(".github/workflows/ci.yml").read_text()
    release_workflow = Path(".github/workflows/release.yml").read_text()

    assert 'tags:\n      - "v*"' not in ci_workflow
    assert "name: Publish release image" not in ci_workflow
    assert (
        "github.event_name == 'pull_request' && github.ref || github.sha" in ci_workflow
    )
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in ci_workflow
    )

    assert 'tags:\n      - "v*"' in release_workflow
    assert "name: Verify exact main Code CI" in release_workflow
    assert "actions: read" in release_workflow
    assert "python tools/verify_release_source_ci.py" in release_workflow
    assert '--required-job "Code CI gate"' in release_workflow
    assert '--required-job "Repository acceptance audit"' in release_workflow
    assert 'test "${commit_sha}" = "${GITHUB_SHA}"' in release_workflow
    assert 'tag_object_sha="$(git rev-parse "${GITHUB_REF}")"' in release_workflow
    assert (
        'test "${remote_tag_object_sha}" = "${VERIFIED_TAG_OBJECT_SHA}"'
        in release_workflow
    )
    assert "git merge-base --is-ancestor" in release_workflow
    assert "needs: [verify_main_code_ci]" in release_workflow
    assert "name: Publish release image" in release_workflow
    assert "python tools/release_image_plan.py" in release_workflow
    assert "docker/setup-buildx-action" in release_workflow
    assert "docker/login-action" in release_workflow
    assert "docker/build-push-action" in release_workflow
    assert "registry: ghcr.io" in release_workflow
    assert "platforms: linux/amd64,linux/arm64" in release_workflow
    assert "group: release-image-${{ github.repository }}" in release_workflow
    assert "queue: max" in release_workflow
    assert "cancel-in-progress: false" in release_workflow
    assert "--verify-immutable-image-tags-absent" in release_workflow
    assert "packages: write" in release_workflow
    verifier_job, publisher_job = release_workflow.split("  release:\n", 1)
    assert "packages: write" not in verifier_job
    assert "actions: read" not in publisher_job
    assert '--commit-sha "${GITHUB_SHA}"' not in release_workflow
    assert "org.opencontainers.image.revision=${{ github.sha }}" not in release_workflow
    assert (
        "org.opencontainers.image.revision=${{ needs.verify_main_code_ci.outputs.commit_sha }}"
        in release_workflow
    )
    assert (
        release_workflow.index("Log in to GitHub Container Registry")
        < release_workflow.index("Compute release image plan and verify immutable tags")
        < release_workflow.index("Reverify remote tag and main ancestry")
        < release_workflow.index("Build and push multi-architecture image")
    )
