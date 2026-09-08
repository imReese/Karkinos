from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


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

    action_refs = []
    for path in sorted(Path(".github/workflows").glob("*.yml")):
        config = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        for job in config["jobs"].values():
            for entry in (job, *job.get("steps", [])):
                if "uses" in entry:
                    action_refs.append(entry["uses"])
    assert action_refs
    for ref in action_refs:
        if ref.startswith("./"):
            assert Path(ref).is_file()
        else:
            assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref)
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
    python_versions = re.findall(r'python-version:\s*"([^"]+)"', workflow)
    assert set(python_versions) == {"3.12.10", "3.12.13"}
    assert python_versions.count("3.12.10") == 1
    candidate_workflow = Path(".github/workflows/candidate.yml").read_text()
    native_job = candidate_workflow.split("  native:\n", 1)[1].split(
        "  container:\n", 1
    )[0]
    assert 'python-version: "3.12.10"' in native_job
    assert 'python-version: "3.12.13"' not in native_job
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
    release = yaml.load(
        Path(".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader
    )
    candidate = yaml.load(
        Path(".github/workflows/candidate.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert release["on"] == {"push": {"tags": ["v*"]}}
    assert release["permissions"] == {"contents": "read"}
    verifier = release["jobs"]["verify_main_code_ci"]
    publisher = release["jobs"]["release"]
    verifier_steps = {step["name"]: step for step in verifier["steps"]}
    publisher_steps = {step["name"]: step for step in publisher["steps"]}

    assert verifier["permissions"] == {"actions": "read", "contents": "read"}
    assert verifier["steps"][0]["name"] == "Require stable SemVer tag"
    source = verifier_steps["Verify tag source and main ancestry"]["run"]
    assert 'test "${commit_sha}" = "${GITHUB_SHA}"' in source
    assert 'tag_object_sha="$(git rev-parse "${GITHUB_REF}")"' in source
    assert 'git merge-base --is-ancestor "${commit_sha}" "origin/main"' in source
    evidence = verifier_steps["Verify exact main CI evidence"]["run"]
    assert "python tools/verify_release_source_ci.py" in evidence
    assert '--required-job "Code CI gate"' in evidence
    assert '--required-job "Repository acceptance audit"' in evidence
    assert '--commit-sha "${RELEASE_COMMIT_SHA}"' in evidence
    assert publisher["needs"] == ["verify_main_code_ci"]
    assert publisher["environment"] == {"name": "stable"}
    assert publisher["concurrency"] == {
        "group": "release-image-${{ github.repository }}",
        "queue": "max",
        "cancel-in-progress": "false",
    }
    assert publisher["permissions"] == {
        "actions": "read",
        "attestations": "write",
        "contents": "write",
        "id-token": "write",
        "packages": "write",
    }
    checkout = publisher_steps["Checkout verified release commit"]
    assert checkout["with"]["ref"] == (
        "${{ needs.verify_main_code_ci.outputs.commit_sha }}"
    )
    assert checkout["with"]["persist-credentials"] == "false"
    action_names = {
        step["uses"].split("@", 1)[0] for step in publisher["steps"] if "uses" in step
    }
    assert "docker/setup-buildx-action" in action_names
    assert "docker/login-action" in action_names
    assert "docker/build-push-action" not in action_names
    assert "actions/download-artifact" not in action_names
    assert (
        publisher_steps["Log in to GitHub Container Registry"]["with"]["registry"]
        == "ghcr.io"
    )
    fetch = publisher_steps["Fetch exact candidate bundle from candidate workflow"]
    assert "python tools/download_candidate.py fetch" in fetch["run"]
    assert '--commit-sha "${RELEASE_COMMIT_SHA}"' in fetch["run"]
    plan = publisher_steps["Compute release image plan and verify immutable tags"][
        "run"
    ]
    assert "python tools/release_image_plan.py" in plan
    assert "--verify-immutable-image-tags-compatible" in plan
    assert '--expected-image-digest "${CANDIDATE_DIGEST}"' in plan
    reverify = publisher_steps["Reverify remote tag and main ancestry"]["run"]
    assert 'test "${remote_tag_object_sha}" = "${VERIFIED_TAG_OBJECT_SHA}"' in reverify
    assert 'test "${remote_tag_commit_sha}" = "${VERIFIED_COMMIT_SHA}"' in reverify
    assert 'git merge-base --is-ancestor "${VERIFIED_COMMIT_SHA}" "origin/main"' in (
        reverify
    )
    publication = publisher_steps[
        "Publish the same native candidate bytes to the GitHub release"
    ]["run"]
    assert "--json tagName,isDraft,isPrerelease" in publication
    assert "gh release create" in publication and "--draft" in publication
    assert 'gh release edit "${RELEASE_TAG}" --draft=false' in publication
    assert publication.index('if [[ "${release_is_draft}" != true ]]') < (
        publication.index('gh release upload "${RELEASE_TAG}" "${asset}"')
    )
    assert publication.index(
        'cmp -s "${expected_assets_file}" "${actual_assets_file}"'
    ) < publication.index('gh release edit "${RELEASE_TAG}" --draft=false')

    step_names = list(publisher_steps)
    ordered_steps = [
        "Log in to GitHub Container Registry",
        "Compute release image plan and verify immutable tags",
        "Reverify remote tag and main ancestry",
        "Promote immutable image identities by exact manifest digest",
        "Publish the same native candidate bytes to the GitHub release",
        "Advance mutable image aliases after native publication",
    ]
    positions = [step_names.index(name) for name in ordered_steps]
    assert positions == sorted(positions)
    immutable_step = publisher_steps[
        "Promote immutable image identities by exact manifest digest"
    ]["run"]
    mutable_step = publisher_steps[
        "Advance mutable image aliases after native publication"
    ]["run"]
    assert '["immutable_image_tags"]' in immutable_step
    assert '["image_tags"]' not in immutable_step
    assert '["immutable_image_tags"]' in mutable_step
    assert '["image_tags"]' in mutable_step

    image_build = next(
        step
        for step in candidate["jobs"]["image"]["steps"]
        if step.get("uses", "").startswith("docker/build-push-action@")
    )
    assert image_build["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert image_build["with"]["push"] == "true"
    assert (
        "org.opencontainers.image.revision=${{ needs.source.outputs.commit_sha }}"
        in image_build["with"]["labels"].splitlines()
    )


@pytest.mark.parametrize(
    ("tag", "accepted"),
    [
        ("v0.0.0", True),
        ("v12.34.567", True),
        ("v1.2.3-alpha.1", False),
        ("v1.2.3-beta.1", False),
        ("v1.2.3-rc.1", False),
        ("v1.2.3+build.1", False),
        ("v01.2.3", False),
        ("v1.2", False),
        ("1.2.3", False),
        ("v1.2.3\n", False),
    ],
)
def test_release_entry_accepts_only_stable_semver(tag: str, accepted: bool) -> None:
    release = yaml.load(
        Path(".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader
    )
    step = release["jobs"]["verify_main_code_ci"]["steps"][0]
    assert step["name"] == "Require stable SemVer tag"
    assert step["shell"] == "bash"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={"GITHUB_REF_NAME": tag},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "requires a stable SemVer tag" in result.stderr


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


def test_candidate_image_metadata_verifies_the_remote_multi_platform_index() -> None:
    candidate_workflow = Path(".github/workflows/candidate.yml").read_text()
    verification = candidate_workflow.split(
        "      - name: Verify candidate image metadata\n", 1
    )[1].split("\n  manifest:\n", 1)[0]

    assert "docker pull" not in verification
    assert "docker image inspect" not in verification
    assert "docker buildx imagetools inspect --format '{{json .}}'" in verification
    assert "tools/release_candidate.py verify-image-metadata" in verification
    assert '--image-digest "${EXPECTED_DIGEST}"' in verification
    assert '--commit-sha "${EXPECTED_REVISION}"' in verification


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
    assert smoke.count("\"${packaged_python}\" -B - <<'PY'") == 2
    assert "\"${packaged_python}\" - <<'PY'" not in smoke
    assert 'kill -TERM "${service_pid}"' in smoke
    assert 'wait "${service_pid}"' in smoke
    assert '"${service_status}" -ne 0 && "${service_status}" -ne 143' in smoke
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
