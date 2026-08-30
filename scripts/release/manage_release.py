#!/usr/bin/env python3
"""Install, promote, verify, and roll back immutable Karkinos releases.

The command is deliberately local and fail-closed. It never contacts a broker
or grants trading authority. A candidate is unpacked and verified in a staging
folder, then promoted only after a disposable service health probe succeeds.
Only ``current`` and ``previous`` are active pointers; candidate directories
are never considered active releases.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import http.client
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

RELEASES_DIRNAME = "releases"
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


def _home(value: str | None) -> Path:
    """Resolve the configured root without silently following a root symlink."""
    configured = value or os.environ.get("KARKINOS_HOME")
    return (
        Path(configured or "~/Library/Application Support/Karkinos")
        .expanduser()
        .absolute()
    )


def _architecture() -> str:
    value = platform.machine().lower()
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value in {"amd64", "x86_64"}:
        return "x86_64"
    raise ValueError("macos_architecture_unsupported")


def _require_sha(value: str) -> str:
    if _FULL_SHA.fullmatch(value) is None:
        raise ValueError("release_commit_sha_invalid")
    return value


def _release_dirs(home: Path) -> tuple[Path, Path, Path]:
    releases = home / RELEASES_DIRNAME
    return releases, home / "current", home / "previous"


def _ensure_layout(home: Path) -> Path:
    releases, _current, _previous = _release_dirs(home)
    for ancestor in (home.parent, *home.parent.parents):
        if ancestor.is_symlink():
            raise ValueError("release_runtime_parent_symlink_unsupported")
        if ancestor.parent == ancestor:
            break
    for path in (home, releases, home / "data", home / "config", home / "logs"):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"release_runtime_directory_invalid:{path.name}")
        path.mkdir(parents=True, exist_ok=True)
    return releases


@contextlib.contextmanager
def _lock(home: Path) -> Iterator[None]:
    _ensure_layout(home)
    lock_path = home / ".release.lock"
    if lock_path.is_symlink():
        raise ValueError("release_lock_symlink_unsupported")
    with lock_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_explicit_false(value: object) -> bool:
    return type(value) is bool and not value


def _is_explicit_true(value: object) -> bool:
    return type(value) is bool and value


def _checksum_for_archive(archive: Path, explicit: str | None) -> str:
    value = explicit
    sidecar = archive.with_name(archive.name + ".sha256")
    if value is None:
        if sidecar.is_symlink() or not sidecar.is_file():
            raise ValueError("release_archive_checksum_missing")
        fields = sidecar.read_text(encoding="utf-8").strip().split()
        if len(fields) != 2 or fields[1] != archive.name:
            raise ValueError("release_archive_checksum_file_invalid")
        value = fields[0]
    if _HEX_DIGEST.fullmatch(value or "") is None:
        raise ValueError("release_archive_checksum_invalid")
    if _sha256(archive) != value:
        raise ValueError("release_archive_checksum_mismatch")
    return value


def _safe_member_path(root: Path, member: tarfile.TarInfo) -> Path:
    name = member.name
    relative = Path(name)
    if (
        not name
        or "\x00" in name
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
    ):
        raise ValueError("release_archive_path_unsafe")
    destination = (root / relative).resolve()
    if destination != root and root not in destination.parents:
        raise ValueError("release_archive_path_escape")
    if (
        member.issym()
        or member.islnk()
        or member.isdev()
        or not (member.isdir() or member.isreg())
    ):
        raise ValueError("release_archive_member_unsupported")
    return destination


def _extract_archive(archive: Path, destination: Path) -> Path:
    """Extract a native archive without following archive-provided links."""
    from tools.release_artifact import validate_archive

    # Validate the complete archive in an isolated directory before placing
    # anything in the managed release tree. Extraction is repeated below only
    # after the archive has passed identity, payload, and link checks.
    validate_archive(archive)
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        roots = {Path(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1:
            raise ValueError("release_archive_root_invalid")
        root_name = next(iter(roots))
        seen: set[str] = set()
        for member in members:
            target = _safe_member_path(destination, member)
            relative_name = target.relative_to(destination).as_posix()
            if relative_name in seen:
                raise ValueError("release_archive_duplicate_path")
            seen.add(relative_name)
            if member.isdir():
                if target.exists() and not target.is_dir():
                    raise ValueError("release_archive_path_conflict")
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError("release_archive_duplicate_path")
            payload = source.extractfile(member)
            if payload is None:
                raise ValueError("release_archive_payload_missing")
            with target.open("xb") as output:
                shutil.copyfileobj(payload, output)
            target.chmod(member.mode & 0o777 or 0o600)
        extracted = destination / root_name
        if not extracted.is_dir():
            raise ValueError("release_archive_root_missing")
        return extracted


def _manifest_for(path: Path, *, expected_sha: str | None = None) -> dict[str, object]:
    from tools.release_artifact import validate_manifest

    if path.parent.name == RELEASES_DIRNAME and path.name.startswith("sha-"):
        directory_sha = path.name.removeprefix("sha-")
        if _FULL_SHA.fullmatch(directory_sha) is None:
            raise ValueError("release_directory_name_invalid")
        if expected_sha is not None and expected_sha != directory_sha:
            raise ValueError("release_directory_identity_mismatch")
        expected_sha = directory_sha
    return validate_manifest(path, expected_commit_sha=expected_sha)


def _read_pointer(path: Path) -> Path | None:
    if not path.is_symlink():
        if path.exists():
            raise ValueError(f"release_pointer_not_symlink:{path.name}")
        return None
    target = os.readlink(path)
    releases = (path.parent / RELEASES_DIRNAME).resolve()
    target_path = Path(target)
    if (
        target_path.is_absolute()
        or target_path.parts[:1] != (RELEASES_DIRNAME,)
        or len(target_path.parts) != 2
        or ".." in target_path.parts
        or "\\" in target
    ):
        raise ValueError(f"release_pointer_escape:{path.name}")
    target_path = path.parent / target_path
    resolved = target_path.resolve()
    if (
        target_path.is_symlink()
        or resolved.parent != releases
        or not resolved.name.startswith("sha-")
        or _FULL_SHA.fullmatch(resolved.name.removeprefix("sha-")) is None
    ):
        raise ValueError(f"release_pointer_escape:{path.name}")
    if not resolved.is_dir():
        raise ValueError(f"release_pointer_target_missing:{path.name}")
    return resolved


def _relative_release_target(home: Path, release: Path) -> str:
    return os.path.relpath(release, home)


def _replace_pointer(home: Path, name: str, target: Path | None) -> None:
    path = home / name
    if path.exists() and not path.is_symlink():
        raise ValueError(f"release_pointer_not_symlink:{name}")
    if target is None:
        path.unlink(missing_ok=True)
        return
    releases = (home / RELEASES_DIRNAME).resolve()
    if target.is_symlink():
        raise ValueError(f"release_pointer_target_invalid:{name}")
    target = target.resolve()
    if (
        target.parent != releases
        or not target.name.startswith("sha-")
        or _FULL_SHA.fullmatch(target.name.removeprefix("sha-")) is None
        or not target.is_dir()
    ):
        raise ValueError(f"release_pointer_target_invalid:{name}")
    temporary = home / f".{name}.next-{uuid.uuid4().hex}"
    temporary.symlink_to(_relative_release_target(home, target))
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _free_port() -> int:
    try:
        with socket.socket() as stream:
            stream.bind(("127.0.0.1", 0))
            return int(stream.getsockname()[1])
    except OSError as exc:
        raise ValueError("release_probe_port_unavailable") from exc


def _restore_failed_candidate_move(final: Path, candidate: Path) -> None:
    if final.is_symlink():
        raise ValueError("release_immutable_directory_symlink_unsupported")
    if final.is_dir():
        os.replace(final, candidate)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        if path.is_symlink():
            raise ValueError(f"release_remove_symlink_unsupported:{path.name}")
        return
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"release_remove_path_invalid:{path.name}")
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise ValueError(f"release_remove_failed:{path.name}") from exc


def _required_pointer(path: Path, name: str) -> Path:
    pointer = _read_pointer(path)
    if pointer is None:
        raise ValueError(f"release_{name}_missing")
    return pointer


def _probe_json(path: str, port: int) -> object:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("release_probe_http_status_unexpected")
        return json.loads(response.read())
    finally:
        connection.close()


def _probe_release(
    home: Path, release: Path, manifest: dict[str, object], timeout: float
) -> None:
    """Start the candidate against disposable state and require its identity."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("release_health_timeout_invalid")
    entrypoint = release / "bin" / "karkinos"
    try:
        usable = entrypoint.is_file() and os.access(entrypoint, os.X_OK)
    except OSError as exc:
        raise ValueError("release_entrypoint_unusable") from exc
    if not usable:
        raise ValueError("release_entrypoint_unusable")
    with tempfile.TemporaryDirectory(prefix="karkinos-release-probe-") as temporary:
        runtime = Path(temporary)
        probe_home = runtime / "home"
        config = probe_home / "config" / "config.json"
        env_file = probe_home / "config" / ".env"
        data = probe_home / "data"
        config.parent.mkdir(parents=True)
        data.mkdir()
        config.write_text("{}\n", encoding="utf-8")
        env_file.write_text("\n", encoding="utf-8")
        port = _free_port()
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
            if key in os.environ
        }
        environment.update(
            {
                "KARKINOS_HOME": str(probe_home),
                "KARKINOS_DATA_DIR": str(data),
                "KARKINOS_CONFIG_PATH": str(config),
                "KARKINOS_ENV_FILE": str(env_file),
                "KARKINOS_HOST": "127.0.0.1",
                "KARKINOS_PORT": str(port),
                "KARKINOS_AI_ENABLED": "false",
                "KARKINOS_RELEASE_SHA": str(manifest["commit_sha"]),
                "KARKINOS_ARTIFACT_FINGERPRINT": str(manifest["payload_fingerprint"]),
            }
        )
        process = subprocess.Popen(
            [str(entrypoint), "--host", "127.0.0.1", "--port", str(port)],
            cwd=release / "app",
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        healthy = False
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    payload = _probe_json("/api/health", port)
                    live = _probe_json("/api/settings/live/status", port)
                    if not isinstance(payload, dict) or not isinstance(live, dict):
                        raise ValueError("release_probe_payload_invalid")
                    healthy = (
                        payload.get("status") == "alive"
                        and payload.get("service") == "karkinos"
                        and payload.get("version") == manifest.get("version")
                        and payload.get("release_sha") == manifest.get("commit_sha")
                        and payload.get("artifact_fingerprint")
                        == manifest.get("payload_fingerprint")
                        and _is_explicit_false(
                            payload.get("financial_readiness_claimed")
                        )
                        and _is_explicit_false(payload.get("broker_submission_enabled"))
                        and _is_explicit_false(payload.get("production_ledger_mutated"))
                        and _is_explicit_false(payload.get("capital_authority_changed"))
                        and _is_explicit_false(payload.get("authorizes_execution"))
                        and _is_explicit_true(live.get("running"))
                    )
                    if healthy:
                        break
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                time.sleep(0.2)
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if not healthy:
            raise ValueError("release_health_probe_failed")


def _stage(home: Path, archive: Path, expected_sha: str, checksum: str | None) -> Path:
    releases = _ensure_layout(home)
    _require_sha(expected_sha)
    archive = archive.expanduser().absolute()
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("release_archive_invalid")
    expected_checksum = _checksum_for_archive(archive, checksum)
    candidate = releases / f".candidate-{expected_sha}"
    if os.path.lexists(candidate) and candidate.is_symlink():
        raise ValueError("release_candidate_symlink_unsupported")
    staging = releases / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        archive_snapshot = staging / ".candidate-input.tar.gz"
        with archive.open("rb") as source, archive_snapshot.open("xb") as target:
            shutil.copyfileobj(source, target)
        if _sha256(archive_snapshot) != expected_checksum:
            raise ValueError("release_archive_checksum_mismatch")
        architecture = _architecture()
        incoming_manifest = _extract_archive_manifest(
            archive_snapshot,
            expected_sha=expected_sha,
            expected_architecture=architecture,
        )
        if candidate.exists():
            existing_manifest = _manifest_for(candidate, expected_sha=expected_sha)
            if incoming_manifest == existing_manifest:
                return candidate
            raise ValueError("release_candidate_conflict")
        extracted = _extract_archive(archive_snapshot, staging)
        manifest = _manifest_for(extracted, expected_sha=expected_sha)
        if manifest != incoming_manifest:
            raise ValueError("release_archive_validation_drift")
        os.replace(extracted, candidate)
        return candidate
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _extract_archive_manifest(
    archive: Path,
    *,
    expected_sha: str,
    expected_architecture: str,
) -> dict[str, object]:
    from tools.release_artifact import validate_archive

    return validate_archive(
        archive,
        expected_commit_sha=expected_sha,
        expected_architecture=expected_architecture,
    )


def _validate_candidate(home: Path, sha: str) -> tuple[Path, dict[str, object]]:
    candidate = _ensure_layout(home) / f".candidate-{_require_sha(sha)}"
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("release_candidate_missing")
    return candidate, _manifest_for(candidate, expected_sha=sha)


def stage(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        candidate = _stage(home, Path(args.archive), args.commit_sha, args.sha256)
        print(
            json.dumps(
                {"status": "staged", "candidate": str(candidate)}, sort_keys=True
            )
        )


def discard(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        candidate, _manifest = _validate_candidate(home, args.commit_sha)
        current = _read_pointer(home / "current")
        previous = _read_pointer(home / "previous")
        if current == candidate or previous == candidate:
            raise ValueError("release_candidate_is_active")
        _remove_tree(candidate)
        print(
            json.dumps(
                {"status": "discarded", "commit_sha": args.commit_sha}, sort_keys=True
            )
        )


def promote(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        commit_sha = _require_sha(args.commit_sha)
        releases, current_pointer, previous_pointer = _release_dirs(home)
        current = _read_pointer(current_pointer)
        previous = _read_pointer(previous_pointer)
        if current is not None and current == previous:
            raise ValueError("release_pointer_state_inconsistent")
        if current is None and previous is not None:
            raise ValueError("release_pointer_state_inconsistent")
        final = releases / f"sha-{commit_sha}"
        confirmation = f"PROMOTE {commit_sha}"
        if args.confirm != confirmation:
            raise ValueError(f"release_confirmation_required:{confirmation}")
        if current == final and final.is_dir() and not final.is_symlink():
            _manifest_for(final, expected_sha=commit_sha)
            print(
                json.dumps(
                    {
                        "status": "already_promoted",
                        "current": str(final),
                        "previous": str(previous) if previous else None,
                    },
                    sort_keys=True,
                )
            )
            return
        if final.is_symlink():
            raise ValueError("release_immutable_directory_symlink_unsupported")
        candidate_path = releases / f".candidate-{commit_sha}"
        final_exists = final.exists()
        if final_exists:
            final_manifest = _manifest_for(final, expected_sha=commit_sha)
            if candidate_path.exists():
                candidate, manifest = _validate_candidate(home, commit_sha)
                if manifest != final_manifest:
                    raise ValueError("release_immutable_directory_conflict")
            else:
                # Recover a crash after the candidate was moved but before the
                # pointer transaction completed.
                candidate, manifest = final, final_manifest
        else:
            candidate, manifest = _validate_candidate(home, commit_sha)
        try:
            _probe_release(home, candidate, manifest, args.health_timeout)
        except BaseException:
            if candidate != final:
                _remove_tree(candidate)
            raise
        installed_new_final = False
        if final_exists:
            if candidate != final:
                _remove_tree(candidate)
        else:
            os.replace(candidate, final)
            installed_new_final = True
        try:
            if current is None:
                _replace_pointer(home, "current", final)
            elif current != final:
                # Prepare the rollback pointer first. ``current`` is the only
                # activation boundary and is replaced atomically last.
                _replace_pointer(home, "previous", current)
                _replace_pointer(home, "current", final)
            # Re-promoting the already-active immutable release is idempotent
            # and must not erase the only rollback target.
        except BaseException:
            _replace_pointer(home, "current", current)
            _replace_pointer(home, "previous", previous)
            if installed_new_final:
                _restore_failed_candidate_move(final, candidate)
            raise
        print(
            json.dumps(
                {
                    "status": "promoted",
                    "current": str(final),
                    "previous": str(current) if current else None,
                },
                sort_keys=True,
            )
        )


def _rollback_locked(home: Path, args: argparse.Namespace) -> dict[str, object]:
    current = _required_pointer(home / "current", "current")
    previous = _required_pointer(home / "previous", "previous")
    if current == previous:
        raise ValueError("release_pointer_state_inconsistent")
    current_manifest = _manifest_for(current)
    previous_manifest = _manifest_for(previous)
    if args.confirm != f"ROLLBACK {previous_manifest['commit_sha']}":
        raise ValueError(
            f"release_confirmation_required:ROLLBACK {previous_manifest['commit_sha']}"
        )
    _probe_release(home, previous, previous_manifest, args.health_timeout)
    try:
        # Prepare the rollback target first; activation remains the final,
        # atomic replacement of ``current``.
        _replace_pointer(home, "previous", current)
        _replace_pointer(home, "current", previous)
    except BaseException:
        _replace_pointer(home, "current", current)
        _replace_pointer(home, "previous", previous)
        raise
    return {
        "status": "rolled_back",
        "current": previous_manifest["commit_sha"],
        "previous": current_manifest["commit_sha"],
    }


def rollback(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        print(json.dumps(_rollback_locked(home, args), sort_keys=True))


def download(_home_path: Path, args: argparse.Namespace) -> None:
    url = args.url
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "\x00" in url
    ):
        raise ValueError("release_download_url_must_use_https")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("release_download_url_must_use_https") from exc
    if port < 1 or port > 65535:
        raise ValueError("release_download_url_must_use_https")
    if _HEX_DIGEST.fullmatch(args.sha256) is None:
        raise ValueError("release_download_checksum_invalid")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("release_download_timeout_invalid")
    output = Path(args.output).expanduser().absolute()
    for ancestor in (output.parent, *output.parent.parents):
        if ancestor.is_symlink():
            raise ValueError("release_download_output_symlink_unsupported")
        if ancestor.parent == ancestor:
            break
    if os.path.lexists(output):
        raise ValueError("release_download_output_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.download-{uuid.uuid4().hex}")
    request_path = parsed.path or "/"
    if parsed.query:
        request_path += f"?{parsed.query}"
    connection = http.client.HTTPSConnection(
        parsed.hostname, port, timeout=args.timeout
    )
    try:
        connection.request(
            "GET", request_path, headers={"User-Agent": "karkinos-release-manager/1"}
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("release_download_http_status_unexpected")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise ValueError("release_download_content_length_invalid") from exc
            if declared_size < 0 or declared_size > _MAX_DOWNLOAD_BYTES:
                raise ValueError("release_download_too_large")
        else:
            declared_size = None
        total = 0
        with temporary.open("xb") as stream:
            while total <= _MAX_DOWNLOAD_BYTES:
                chunk = response.read(min(1024 * 1024, _MAX_DOWNLOAD_BYTES + 1 - total))
                if not chunk:
                    break
                stream.write(chunk)
                total += len(chunk)
        if total > _MAX_DOWNLOAD_BYTES:
            raise ValueError("release_download_too_large")
        if declared_size is not None and total != declared_size:
            raise ValueError("release_download_content_length_mismatch")
        if _sha256(temporary) != args.sha256:
            raise ValueError("release_download_checksum_mismatch")
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    print(
        json.dumps(
            {"status": "downloaded", "path": str(output), "sha256": args.sha256},
            sort_keys=True,
        )
    )


def _status_locked(home: Path, _args: argparse.Namespace) -> None:
    _ensure_layout(home)
    current = _read_pointer(home / "current")
    previous = _read_pointer(home / "previous")
    payload: dict[str, object] = {
        "schema_version": "karkinos.release_runtime_status.v1",
        "home": str(home),
        "current": None,
        "previous": None,
        "candidates": [],
        "data": str(home / "data"),
        "config": str(home / "config"),
        "logs": str(home / "logs"),
    }
    for key, path in (("current", current), ("previous", previous)):
        if path is not None:
            manifest = _manifest_for(path)
            payload[key] = {
                "path": str(path),
                "commit_sha": manifest["commit_sha"],
                "version": manifest["version"],
            }
    candidates: list[str] = []
    for path in (home / RELEASES_DIRNAME).glob(".candidate-*"):
        if path.is_symlink():
            raise ValueError("release_candidate_symlink_unsupported")
        if path.is_dir():
            candidate_sha = path.name.removeprefix(".candidate-")
            if _FULL_SHA.fullmatch(candidate_sha) is None:
                raise ValueError("release_candidate_name_invalid")
            candidates.append(candidate_sha)
    payload["candidates"] = sorted(candidates)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def status(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        _status_locked(home, args)


def start(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        current = _read_pointer(home / "current")
        if current is None:
            raise ValueError("release_current_missing")
        _manifest_for(current)
        command = [str(current / "bin" / "karkinos"), *args.server_args]
    process_result = subprocess.run(command, cwd=current / "app", check=False)
    if process_result.returncode != 0 and args.auto_rollback:
        try:
            with _lock(home):
                previous = _required_pointer(home / "previous", "previous")
                previous_manifest = _manifest_for(previous)
                rollback_result = _rollback_locked(
                    home,
                    argparse.Namespace(
                        confirm=f"ROLLBACK {previous_manifest['commit_sha']}",
                        health_timeout=args.health_timeout,
                    ),
                )
            print(json.dumps(rollback_result, sort_keys=True), file=sys.stderr)
        except (OSError, ValueError):
            print(
                "Automatic rollback was not completed; inspect previous release.",
                file=sys.stderr,
            )
    raise SystemExit(process_result.returncode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        default=None,
        help="Runtime root (default: ~/Library/Application Support/Karkinos)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    stage_parser = sub.add_parser("stage", help="verify and retain one candidate")
    stage_parser.add_argument("--archive", required=True)
    stage_parser.add_argument("--commit-sha", required=True)
    stage_parser.add_argument("--sha256")
    discard_parser = sub.add_parser("discard", help="delete one inactive candidate")
    discard_parser.add_argument("--commit-sha", required=True)
    promote_parser = sub.add_parser(
        "promote", help="health-check and atomically activate a candidate"
    )
    promote_parser.add_argument("--commit-sha", required=True)
    promote_parser.add_argument("--confirm", required=True)
    promote_parser.add_argument("--health-timeout", type=float, default=30)
    rollback_parser = sub.add_parser(
        "rollback", help="health-check and atomically swap current/previous"
    )
    rollback_parser.add_argument("--confirm", required=True)
    rollback_parser.add_argument("--health-timeout", type=float, default=30)
    download_parser = sub.add_parser(
        "download", help="download one archive over HTTPS and verify its SHA-256"
    )
    download_parser.add_argument("--url", required=True)
    download_parser.add_argument("--sha256", required=True)
    download_parser.add_argument("--output", required=True)
    download_parser.add_argument("--timeout", type=float, default=60)
    sub.add_parser("status", help="show active pointers and inactive candidates")
    start_parser = sub.add_parser(
        "start", help="start current; optionally roll back on process failure"
    )
    start_parser.add_argument("--auto-rollback", action="store_true")
    start_parser.add_argument("--health-timeout", type=float, default=30)
    start_parser.add_argument("server_args", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = _parser().parse_args()
    home = _home(args.home)
    try:
        if args.command == "stage":
            stage(home, args)
        elif args.command == "discard":
            discard(home, args)
        elif args.command == "promote":
            promote(home, args)
        elif args.command == "rollback":
            rollback(home, args)
        elif args.command == "download":
            download(home, args)
        elif args.command == "status":
            status(home, args)
        elif args.command == "start":
            start(home, args)
        return 0
    except (OSError, tarfile.TarError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
