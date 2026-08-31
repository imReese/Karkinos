from __future__ import annotations

import json
import re
import subprocess
import sys
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
    assert "uv run python scripts/ci/export_acceptance_audit.py --audit all" in workflow

    assert "format:check" in package["scripts"]
    assert package["scripts"]["format:check"].startswith("prettier --check")
    assert "npm --prefix web run format:check" in workflow
    assert "npm --prefix web run build" in workflow
    assert "npm --prefix web run test" in workflow
    assert "Check public shell entrypoint syntax" in workflow
    assert "scripts/release/bootstrap_installer.sh" in workflow


def test_ci_pins_release_toolchains_and_github_actions() -> None:
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
    assert set(re.findall(r'python-version:\s*"([^"]+)"', workflow)) == {"3.12.13"}
    assert set(re.findall(r'node-version:\s*"([^"]+)"', workflow)) == {"24.20.0"}
    assert dockerfile.startswith(
        "# ---- Stage 1: Build React frontend ----\n" "FROM node:24.20.0-alpine3.24"
    )
    assert "FROM python:3.12.13-slim-trixie" in dockerfile
    assert package["engines"]["node"] == ">=24.0.0 <25.0.0"
    assert nvmrc == "24.20.0"
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
    assert "actions: read" in publisher_job
    assert "python tools/download_candidate.py fetch" in publisher_job
    assert "actions/download-artifact" not in publisher_job
    assert "--json tagName,isDraft,isPrerelease" in publisher_job
    assert "gh release create" in publisher_job and "--draft" in publisher_job
    assert 'gh release edit "${RELEASE_TAG}" --draft=false' in publisher_job
    assert (
        'if [[ "${release_is_draft}" != true ]]; then\n'
        '                echo "Published release is immutable and missing expected asset: '
        '${name}" >&2' in publisher_job
    )
    assert 'cmp -s "${expected_assets_file}" "${actual_assets_file}"' in publisher_job
    assert publisher_job.index('if [[ "${release_is_draft}" != true ]]') < (
        publisher_job.index('gh release upload "${RELEASE_TAG}" "${asset}"')
    )
    assert publisher_job.index(
        'cmp -s "${expected_assets_file}" "${actual_assets_file}"'
    ) < publisher_job.index('gh release edit "${RELEASE_TAG}" --draft=false')
    assert "--json tagName,draft" not in publisher_job
    assert '--commit-sha "${GITHUB_SHA}"' not in release_workflow
    assert "org.opencontainers.image.revision=${{ github.sha }}" not in release_workflow
    assert (
        "org.opencontainers.image.revision=${{ needs.verify_main_code_ci.outputs.commit_sha }}"
        in release_workflow
    )
    publisher_steps = publisher_job.split("      - name:")
    assert all("uses: docker/build-push-action" not in step for step in publisher_steps)
    assert (
        release_workflow.index("Log in to GitHub Container Registry")
        < release_workflow.index("Compute release image plan and verify immutable tags")
        < release_workflow.index("Reverify remote tag and main ancestry")
        < release_workflow.index(
            "Promote immutable image identities by exact manifest digest"
        )
        < release_workflow.index(
            "Publish the same native candidate bytes to the GitHub release"
        )
        < release_workflow.index(
            "Advance mutable image aliases after native publication"
        )
    )

    immutable_step = release_workflow.split(
        "      - name: Promote immutable image identities by exact manifest digest\n",
        1,
    )[1].split(
        "      - name: Publish the same native candidate bytes to the GitHub release\n",
        1,
    )[
        0
    ]
    mutable_step = release_workflow.split(
        "      - name: Advance mutable image aliases after native publication\n",
        1,
    )[1].split("      - name: Summarize immutable promotion\n", 1)[0]
    assert '["immutable_image_tags"]' in immutable_step
    assert '["image_tags"]' not in immutable_step
    assert '["immutable_image_tags"]' in mutable_step
    assert '["image_tags"]' in mutable_step


def test_candidate_and_release_fetch_with_ephemeral_basic_auth() -> None:
    candidate_workflow = Path(".github/workflows/candidate.yml").read_text()
    release_workflow = Path(".github/workflows/release.yml").read_text()

    for workflow in (candidate_workflow, release_workflow):
        assert "persist-credentials: false" in workflow
        assert "AUTHORIZATION: bearer" not in workflow
        assert "printf 'x-access-token:%s'" in workflow
        assert (
            "http.https://github.com/.extraheader=AUTHORIZATION: basic "
            "${git_auth_header}" in workflow
        )


def test_candidate_image_preflight_reuses_fail_closed_registry_check() -> None:
    candidate_workflow = Path(".github/workflows/candidate.yml").read_text()
    preflight = candidate_workflow.split(
        "      - name: Reject a reused candidate image tag\n", 1
    )[1].split("      - name: Build and push candidate multi-architecture image\n", 1)[
        0
    ]

    assert "assert_registry_image_tag_absent" in preflight
    assert "docker buildx imagetools inspect" not in preflight


def test_candidate_reruns_bind_workflow_attempt_artifact_and_image_identity() -> None:
    candidate_workflow = Path(".github/workflows/candidate.yml").read_text()
    release_workflow = Path(".github/workflows/release.yml").read_text()

    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in candidate_workflow
    assert 'test "${GITHUB_SHA}" = "${TARGET_COMMIT_SHA}"' in candidate_workflow
    assert "candidate-sha-%s-run-%s-attempt-%s" in candidate_workflow
    assert "${GITHUB_RUN_ID}" in candidate_workflow
    assert "${GITHUB_RUN_ATTEMPT}" in candidate_workflow
    assert (
        "karkinos-candidate-${{ needs.source.outputs.commit_sha }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}" in candidate_workflow
    )
    assert "--candidate-workflow-run-id" in candidate_workflow
    assert "--candidate-workflow-run-attempt" in candidate_workflow
    assert "--image-workflow-run-id" in candidate_workflow
    assert "--image-workflow-run-attempt" in candidate_workflow

    assert "--metadata-output candidate-selection.json" in release_workflow
    assert "--candidate-selection candidate-selection.json" in release_workflow
    assert (
        "candidate-selection.json\n            candidate/candidate-manifest.json"
        in (release_workflow)
    )
    assert (
        "assets=(candidate-selection.json candidate/candidate-manifest.json "
        "candidate/candidate-artifacts/* scripts/release/bootstrap_installer.sh)"
        in release_workflow
    )


def test_native_candidates_are_signed_with_github_provenance() -> None:
    workflow = Path(".github/workflows/candidate.yml").read_text()
    native_job = workflow.split("  native:\n", 1)[1].split("  image:\n", 1)[0]

    assert "attestations: write" in native_job
    assert "id-token: write" in native_job
    assert (
        "actions/attest-build-provenance@"
        "4d101475d8b20a2381f78447822ac1eab6504dd8" in native_job
    )
    assert "subject-path: candidate/*.tar.gz" in native_job


def test_native_candidate_uses_current_ga_architecture_runners() -> None:
    workflow = Path(".github/workflows/candidate.yml").read_text()
    native_job = workflow.split("  native:\n", 1)[1].split("  image:\n", 1)[0]

    assert "- architecture: arm64\n            runner: macos-15\n" in native_job
    assert "- architecture: x86_64\n            runner: macos-15-intel\n" in native_job
    assert "runner: macos-14" not in native_job


def test_native_candidate_smokes_packaged_controller_and_service() -> None:
    workflow = Path(".github/workflows/candidate.yml").read_text()
    native_job = workflow.split("  native:\n", 1)[1].split("  image:\n", 1)[0]
    smoke = native_job.split(
        "      - name: Smoke test packaged release controller and service\n", 1
    )[1].split("      - name: Attest native candidate provenance\n", 1)[0]

    assert (
        native_job.index("Build self-contained native candidate")
        < native_job.index("Smoke test packaged release controller and service")
        < native_job.index("Attest native candidate provenance")
    )
    assert 'tar -xzf "${archive}" -C "${extract_root}"' in smoke
    assert 'controller="${release_root}/bin/karkinosctl"' in smoke
    assert 'entrypoint="${release_root}/bin/karkinos"' in smoke
    assert '"${controller}" --help' in smoke
    assert '"${controller}" status' in smoke
    assert '"${entrypoint}" --host 127.0.0.1 --port "${service_port}"' in smoke
    assert "/api/health" in smoke
    assert "/api/settings/live/status" in smoke
    assert 'health["release_sha"] == manifest["commit_sha"]' in smoke
    assert 'health["artifact_fingerprint"] == manifest["payload_fingerprint"]' in smoke
    assert 'live["running"] is True' in smoke
    assert 'live["initialized"] is True' in smoke
    assert 'kill -TERM "${service_pid}"' in smoke
    assert 'wait "${service_pid}"' in smoke
    assert 'HOME="${isolated_home}" KARKINOS_HOME="${runtime_home}"' in smoke
    assert 'test ! -e "${runtime_home}"' in smoke
    assert "launchctl " not in smoke


def test_stable_release_reverifies_native_candidate_provenance() -> None:
    workflow = Path(".github/workflows/release.yml").read_text()
    publisher = workflow.split("  release:\n", 1)[1]

    assert "attestations: write" in publisher
    assert "id-token: write" in publisher
    assert "name: Verify native candidate provenance" in publisher
    assert 'gh attestation verify "${archive}"' in publisher
    assert (
        '--signer-workflow "${GITHUB_REPOSITORY}/.github/workflows/candidate.yml"'
        in publisher
    )
    assert '--source-digest "${RELEASE_COMMIT_SHA}"' in publisher
    assert "--deny-self-hosted-runners" in publisher
    assert "name: Attest stable release authorization" in publisher
    assert (
        "actions/attest-build-provenance@"
        "4d101475d8b20a2381f78447822ac1eab6504dd8" in publisher
    )
    assert "subject-path: |" in publisher
    assert "candidate-selection.json" in publisher
    assert "candidate/candidate-manifest.json" in publisher
    assert "candidate/candidate-artifacts/*.tar.gz" in publisher
    assert (
        publisher.index("Verify candidate manifest and artifact bytes")
        < (publisher.index("Verify native candidate provenance"))
        < publisher.index("Compute release image plan and verify immutable tags")
    )


def test_stable_release_attests_and_publishes_checkout_free_bootstrap_installer() -> (
    None
):
    workflow = Path(".github/workflows/release.yml").read_text()
    publisher = workflow.split("  release:\n", 1)[1]

    installer = "scripts/release/bootstrap_installer.sh"
    attestation = publisher.split(
        "      - name: Attest stable release authorization\n", 1
    )[1].split(
        "      - name: Compute release image plan and verify immutable tags\n", 1
    )[
        0
    ]
    publication = publisher.split(
        "      - name: Publish the same native candidate bytes to the GitHub release\n",
        1,
    )[1].split(
        "      - name: Advance mutable image aliases after native publication\n", 1
    )[
        0
    ]

    assert installer in attestation
    assert installer in publication
    assert publisher.index("Attest stable release authorization") < publisher.index(
        "Publish the same native candidate bytes to the GitHub release"
    )


def test_release_publication_classifies_real_tsv_states_with_bash() -> None:
    workflow = Path(".github/workflows/release.yml").read_text()
    publisher = workflow.split("  release:\n", 1)[1]
    start = publisher.index("          release_is_draft=false\n")
    end = publisher.index("\n          fi", start) + len("\n          fi")
    block = "\n".join(
        line.removeprefix("          ") for line in publisher[start:end].splitlines()
    )
    script = (
        'set -euo pipefail\nRELEASE_TAG="$1"\nrelease_state="$2"\n'
        f"{block}\n"
        'printf "%s\\n" "${release_is_draft}"\n'
    )

    for state, expected in (
        ("v1.2.3\tfalse\tfalse", "false"),
        ("v1.2.3\ttrue\tfalse", "true"),
    ):
        result = subprocess.run(
            ["bash", "-c", script, "release-state-test", "v1.2.3", state],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected


def test_release_image_tag_extractors_emit_one_real_line_per_tag(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text()
    commands = [
        command
        for command in re.findall(r"python -c '([^']+)'", workflow)
        if 'json.load(open("release-plan.json"))' in command
    ]
    immutable_tags = [
        "ghcr.io/imreese/karkinos:v0.3.1",
        "ghcr.io/imreese/karkinos:sha-" + "a" * 40,
    ]
    image_tags = [*immutable_tags, "ghcr.io/imreese/karkinos:v0.3", "latest"]
    (tmp_path / "release-plan.json").write_text(
        json.dumps(
            {
                "immutable_image_tags": immutable_tags,
                "image_tags": image_tags,
            }
        ),
        encoding="utf-8",
    )

    assert len(commands) == 3
    for command in commands:
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        expected = immutable_tags if '"immutable_image_tags"' in command else image_tags
        assert result.stdout.splitlines() == expected
