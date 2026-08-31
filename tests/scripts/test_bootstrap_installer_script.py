"""Standalone bootstrap installer contracts without touching a real service."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path("scripts/release/bootstrap_installer.sh")
TAG = "v1.2.3"
VERSION = TAG.removeprefix("v")
ARCHITECTURE = "arm64"
COMMIT_SHA = "a" * 40
DRIFTED_SHA = "b" * 40


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _build_native_asset(asset_dir: Path, *, include_symlink: bool = False) -> None:
    archive_root_name = f"Karkinos-{VERSION}-macos-{ARCHITECTURE}"
    source_root = asset_dir / "source" / archive_root_name
    (source_root / "bin").mkdir(parents=True)
    (source_root / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        source_root / "bin" / "karkinosctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf "home-env=%s\\n" "${KARKINOS_HOME:-}" >"${CONTROLLER_CALLS}"\n'
        'printf "arg=%s\\n" "$@" >>"${CONTROLLER_CALLS}"\n'
        'exit "${CONTROLLER_EXIT:-0}"\n',
    )
    if include_symlink:
        (source_root / "unsafe-link").symlink_to("/private/tmp")

    archive = asset_dir / f"karkinos-{VERSION}-macos-{ARCHITECTURE}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source_root, arcname=archive_root_name, recursive=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    (asset_dir / "candidate-manifest.json").write_text(
        f'{{"commit_sha":"{COMMIT_SHA}","version":"{VERSION}"}}\n',
        encoding="utf-8",
    )


def _fixture(
    tmp_path: Path, *, include_symlink: bool = False
) -> tuple[Path, list[str], dict[str, str], Path, Path, Path]:
    asset_dir = tmp_path / "assets"
    fake_bin = tmp_path / "bin"
    temp_parent = tmp_path / "temporary"
    legacy_workdir = tmp_path / "legacy-workdir"
    legacy_plist = tmp_path / "LaunchAgents" / "com.karkinos.legacy.plist"
    karkinos_home = tmp_path / "managed-home"
    installer = tmp_path / "bootstrap_installer.sh"
    gh_calls = tmp_path / "gh-calls.log"
    controller_calls = tmp_path / "controller-calls.log"
    tag_api_calls = tmp_path / "tag-api-calls.log"
    release_view_calls = tmp_path / "release-view-calls.log"

    asset_dir.mkdir()
    fake_bin.mkdir()
    temp_parent.mkdir()
    legacy_workdir.mkdir()
    legacy_plist.parent.mkdir()
    legacy_plist.write_text("fixture\n", encoding="utf-8")
    shutil.copy2(SCRIPT, installer)
    installer.chmod(0o755)
    _build_native_asset(asset_dir, include_symlink=include_symlink)

    _write_executable(
        fake_bin / "uname",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'case "${1:-}" in\n'
        '  -s) printf "%s\\n" "${FAKE_UNAME_SYSTEM:-Darwin}" ;;\n'
        '  -m) printf "%s\\n" "${FAKE_UNAME_MACHINE:-arm64}" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    _write_executable(
        fake_bin / "gh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "{\n"
        '  printf "%s" "${1:-}"\n'
        '  for argument in "${@:2}"; do printf "\\t%s" "${argument}"; done\n'
        "  printf '\\n'\n"
        '} >>"${GH_CALLS}"\n'
        'case "${1:-}:${2:-}" in\n'
        "  auth:status)\n"
        '    [[ "${FAKE_GH_AUTH_FAIL:-0}" != "1" ]]\n'
        "    ;;\n"
        "  release:view)\n"
        "    assets_request=0\n"
        '    for argument in "$@"; do\n'
        '      [[ "${argument}" == "assets" ]] && assets_request=1\n'
        "    done\n"
        '    if [[ "${assets_request}" == "1" ]]; then\n'
        '      for asset in "${ASSET_DIR}"/*; do\n'
        '        [[ -f "${asset}" ]] || continue\n'
        '        asset_name="$(basename "${asset}")"\n'
        '        asset_size="$(wc -c <"${asset}" | tr -d "[:space:]")"\n'
        '        if [[ "${asset_name}" == *.tar.gz && '
        '-n "${FAKE_ARCHIVE_REPORTED_SIZE:-}" ]]; then\n'
        '          asset_size="${FAKE_ARCHIVE_REPORTED_SIZE}"\n'
        "        fi\n"
        '        printf "%s\\t%s\\n" "${asset_name}" "${asset_size}"\n'
        "      done\n"
        "      exit 0\n"
        "    fi\n"
        "    view_count=0\n"
        '    if [[ -f "${RELEASE_VIEW_CALLS}" ]]; then\n'
        '      view_count="$(wc -l <"${RELEASE_VIEW_CALLS}" | tr -d "[:space:]")"\n'
        "    fi\n"
        '    printf "x\\n" >>"${RELEASE_VIEW_CALLS}"\n'
        '    if [[ "${FAKE_RELEASE_DRIFT:-0}" == "1" && "${view_count}" -gt 0 ]]; then\n'
        f'      printf "%s\\t%s\\t%s\\n" "{TAG}" true false\n'
        "    else\n"
        f'      printf "%s\\t%s\\t%s\\n" "{TAG}" false false\n'
        "    fi\n"
        "    ;;\n"
        "  release:download)\n"
        '    destination=""\n'
        '    pattern=""\n'
        "    shift 2\n"
        "    while (($# > 0)); do\n"
        '      case "$1" in\n'
        '        --dir) destination="$2"; shift 2 ;;\n'
        '        --pattern) pattern="$2"; shift 2 ;;\n'
        "        *) shift ;;\n"
        "      esac\n"
        "    done\n"
        '    [[ -n "${destination}" && -n "${pattern}" ]]\n'
        '    cp "${ASSET_DIR}/${pattern}" "${destination}/${pattern}"\n'
        "    ;;\n"
        "  attestation:verify)\n"
        '    [[ "${FAKE_ATTESTATION_FAIL:-0}" != "1" ]]\n'
        "    ;;\n"
        "  api:*)\n"
        "    api_count=0\n"
        '    if [[ -f "${TAG_API_CALLS}" ]]; then\n'
        '      api_count="$(wc -l <"${TAG_API_CALLS}" | tr -d "[:space:]")"\n'
        "    fi\n"
        '    printf "x\\n" >>"${TAG_API_CALLS}"\n'
        f'    sha="{COMMIT_SHA}"\n'
        '    if [[ "${FAKE_TAG_DRIFT:-0}" == "1" && "${api_count}" -gt 0 ]]; then\n'
        f'      sha="{DRIFTED_SHA}"\n'
        "    fi\n"
        f'    printf "refs/tags/{TAG}\\tcommit\\t%s\\n" "${{sha}}"\n'
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
    )

    arguments = [
        "--tag",
        TAG,
        "--architecture",
        ARCHITECTURE,
        "--legacy-workdir",
        str(legacy_workdir),
        "--legacy-plist",
        str(legacy_plist),
        "--confirm",
        f"BOOTSTRAP {TAG}",
        "--home",
        str(karkinos_home),
    ]
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path / "user-home"),
        # macOS normally exports TMPDIR with a trailing slash.
        "TMPDIR": f"{temp_parent}/",
        "ASSET_DIR": str(asset_dir),
        "GH_CALLS": str(gh_calls),
        "CONTROLLER_CALLS": str(controller_calls),
        "TAG_API_CALLS": str(tag_api_calls),
        "RELEASE_VIEW_CALLS": str(release_view_calls),
    }
    return installer, arguments, environment, temp_parent, gh_calls, controller_calls


def _run(
    installer: Path, arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(installer), *arguments],
        cwd=installer.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _replace_argument(arguments: list[str], option: str, value: str) -> list[str]:
    changed = list(arguments)
    changed[changed.index(option) + 1] = value
    return changed


def _remove_argument(arguments: list[str], option: str) -> list[str]:
    changed = list(arguments)
    index = changed.index(option)
    del changed[index : index + 2]
    return changed


def test_installer_is_standalone_executable_and_has_no_source_checkout_dependency() -> (
    None
):
    script = SCRIPT.read_text(encoding="utf-8")

    assert SCRIPT.stat().st_mode & 0o111
    assert "git " not in script
    assert "uv " not in script
    assert "docker " not in script
    assert '"${CONTROLLER}"' in script
    assert "--signer-workflow" in script
    assert ".github/workflows/release.yml" in script
    assert '--source-ref "refs/tags/${TAG}"' in script
    assert '--source-digest "${TAG_COMMIT}"' in script


def test_installer_verifies_stable_assets_then_delegates_to_packaged_controller(
    tmp_path: Path,
) -> None:
    installer, arguments, env, temp_parent, gh_calls, controller_calls = _fixture(
        tmp_path
    )
    arguments = _remove_argument(arguments, "--architecture")

    result = _run(installer, arguments, env)

    assert result.returncode == 0, result.stderr
    home = arguments[arguments.index("--home") + 1]
    workdir = arguments[arguments.index("--legacy-workdir") + 1]
    plist = arguments[arguments.index("--legacy-plist") + 1]
    assert controller_calls.read_text(encoding="utf-8").splitlines() == [
        f"home-env={home}",
        "arg=--home",
        f"arg={home}",
        "arg=bootstrap",
        "arg=--tag",
        f"arg={TAG}",
        "arg=--legacy-workdir",
        f"arg={workdir}",
        "arg=--legacy-plist",
        f"arg={plist}",
        "arg=--confirm",
        f"arg=BOOTSTRAP {TAG}",
    ]
    calls = gh_calls.read_text(encoding="utf-8").splitlines()
    attestations = [
        line.split("\t") for line in calls if line.startswith("attestation\t")
    ]
    assert len(attestations) == 2
    assert any(
        f"karkinos-{VERSION}-macos-arm64.tar.gz" in command[2]
        for command in attestations
    )
    for command in attestations:
        assert command[:2] == ["attestation", "verify"]
        assert command[command.index("--repo") + 1] == "imReese/Karkinos"
        assert command[command.index("--signer-workflow") + 1] == (
            "imReese/Karkinos/.github/workflows/release.yml"
        )
        assert command[command.index("--source-ref") + 1] == f"refs/tags/{TAG}"
        assert command[command.index("--source-digest") + 1] == COMMIT_SHA
        assert "--deny-self-hosted-runners" in command
    assert list(temp_parent.iterdir()) == []


def test_installer_forwards_one_explicit_service_port(tmp_path: Path) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path
    )

    result = _run(installer, [*arguments, "--service-port", "8123"], env)

    assert result.returncode == 0, result.stderr
    assert controller_calls.read_text(encoding="utf-8").splitlines()[-2:] == [
        "arg=--service-port",
        "arg=8123",
    ]
    assert list(temp_parent.iterdir()) == []


@pytest.mark.parametrize("health_timeout", ("1", "120", "3600"))
def test_installer_forwards_one_explicit_health_timeout(
    tmp_path: Path, health_timeout: str
) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path
    )

    result = _run(installer, [*arguments, "--health-timeout", health_timeout], env)

    assert result.returncode == 0, result.stderr
    assert controller_calls.read_text(encoding="utf-8").splitlines()[-2:] == [
        "arg=--health-timeout",
        f"arg={health_timeout}",
    ]
    assert list(temp_parent.iterdir()) == []


@pytest.mark.parametrize("value", ("0", "65536", "08", "not-a-port"))
def test_installer_rejects_invalid_service_port_before_network(
    tmp_path: Path, value: str
) -> None:
    installer, arguments, env, temp_parent, gh_calls, controller_calls = _fixture(
        tmp_path
    )

    result = _run(installer, [*arguments, "--service-port", value], env)

    assert result.returncode != 0
    assert "--service-port must be an integer from 1 through 65535" in result.stderr
    assert not gh_calls.exists()
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


@pytest.mark.parametrize("value", ("0", "3601", "1.5", "not-a-timeout"))
def test_installer_rejects_invalid_health_timeout_before_network(
    tmp_path: Path, value: str
) -> None:
    installer, arguments, env, temp_parent, gh_calls, controller_calls = _fixture(
        tmp_path
    )

    result = _run(installer, [*arguments, "--health-timeout", value], env)

    assert result.returncode != 0
    assert "--health-timeout must be an integer from 1 through 3600" in result.stderr
    assert not gh_calls.exists()
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


@pytest.mark.parametrize(
    ("option", "value", "message"),
    (
        ("--tag", "v1.2.3-rc.1", "stable SemVer tag"),
        ("--architecture", "x86_64", "does not match this Mac"),
        ("--legacy-workdir", "relative/source", "normalized absolute path"),
        ("--legacy-workdir", "/tmp//source", "normalized absolute path"),
        ("--home", "/", "must not be the filesystem root"),
    ),
)
def test_installer_rejects_invalid_identity_and_paths_before_network(
    tmp_path: Path, option: str, value: str, message: str
) -> None:
    installer, arguments, env, temp_parent, gh_calls, controller_calls = _fixture(
        tmp_path
    )
    changed = _replace_argument(arguments, option, value)
    if option == "--tag":
        changed = _replace_argument(changed, "--confirm", f"BOOTSTRAP {value}")

    result = _run(installer, changed, env)

    assert result.returncode != 0
    assert message in result.stderr
    assert not gh_calls.exists()
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


def test_installer_requires_macos_and_authenticated_gh(tmp_path: Path) -> None:
    installer, arguments, env, temp_parent, gh_calls, controller_calls = _fixture(
        tmp_path
    )
    env["FAKE_UNAME_SYSTEM"] = "Linux"

    result = _run(installer, arguments, env)

    assert result.returncode != 0
    assert "supported only on macOS" in result.stderr
    assert not gh_calls.exists()
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []

    env["FAKE_UNAME_SYSTEM"] = "Darwin"
    env["FAKE_GH_AUTH_FAIL"] = "1"
    result = _run(installer, arguments, env)
    assert result.returncode != 0
    assert "gh must be authenticated" in result.stderr
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


def test_installer_checksum_failure_cleans_up_without_running_controller(
    tmp_path: Path,
) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path
    )
    checksum = next(Path(env["ASSET_DIR"]).glob("*.sha256"))
    checksum.write_text(f"{'0' * 64}  {checksum.name.removesuffix('.sha256')}\n")

    result = _run(installer, arguments, env)

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


def test_installer_rejects_oversized_archive_metadata_before_download(
    tmp_path: Path,
) -> None:
    installer, arguments, env, temp_parent, gh_calls, controller_calls = _fixture(
        tmp_path
    )
    env["FAKE_ARCHIVE_REPORTED_SIZE"] = "536870913"

    result = _run(installer, arguments, env)

    assert result.returncode != 0
    assert "native archive metadata size is invalid" in result.stderr
    assert "release\tdownload" not in gh_calls.read_text(encoding="utf-8")
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


def test_installer_attestation_failure_cleans_up_without_running_controller(
    tmp_path: Path,
) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path
    )
    env["FAKE_ATTESTATION_FAIL"] = "1"

    result = _run(installer, arguments, env)

    assert result.returncode != 0
    assert "attestation verification failed" in result.stderr
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


@pytest.mark.parametrize("drift_flag", ("FAKE_TAG_DRIFT", "FAKE_RELEASE_DRIFT"))
def test_installer_fails_closed_if_stable_identity_changes_during_verification(
    tmp_path: Path, drift_flag: str
) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path
    )
    env[drift_flag] = "1"

    result = _run(installer, arguments, env)

    assert result.returncode != 0
    assert "changed during verification" in result.stderr
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


def test_installer_rejects_link_entries_even_if_attestation_command_succeeds(
    tmp_path: Path,
) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path, include_symlink=True
    )

    result = _run(installer, arguments, env)

    assert result.returncode != 0
    assert "link or special entry" in result.stderr
    assert not controller_calls.exists()
    assert list(temp_parent.iterdir()) == []


def test_installer_propagates_controller_failure_and_still_cleans_up(
    tmp_path: Path,
) -> None:
    installer, arguments, env, temp_parent, _gh_calls, controller_calls = _fixture(
        tmp_path
    )
    env["CONTROLLER_EXIT"] = "42"

    result = _run(installer, arguments, env)

    assert result.returncode == 42
    assert controller_calls.exists()
    assert list(temp_parent.iterdir()) == []
