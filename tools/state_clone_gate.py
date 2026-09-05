"""Run an exact candidate's state replay on SQLite-consistent disposable copies."""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from contextlib import closing
from pathlib import Path


def _quiescent_database_copy(source: Path, destination: Path) -> None:
    """Copy a closed WAL database whose absent sidecars prevent read-only open."""
    sidecars = [Path(str(source) + suffix) for suffix in ("-wal", "-journal")]
    if any(path.exists() for path in sidecars):
        raise ValueError("state_clone_database_not_quiescent")
    before = source.stat()
    shutil.copyfile(source, destination)
    after = source.stat()
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    if identity(before) != identity(after) or any(path.exists() for path in sidecars):
        raise ValueError("state_clone_database_changed_during_copy")
    with closing(sqlite3.connect(destination)) as cloned:
        if cloned.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("state_clone_integrity_failed")
        cloned.execute("PRAGMA journal_mode=DELETE")


def _backup_database(source: Path, destination: Path, check_deadline) -> None:
    with closing(
        sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    ) as origin:
        try:
            origin.execute("PRAGMA page_count").fetchone()
        except sqlite3.OperationalError as exc:
            if str(exc) != "unable to open database file":
                raise
            # Never open production state for writing merely to create WAL sidecars.
            _quiescent_database_copy(source, destination)
        else:
            with closing(sqlite3.connect(destination)) as cloned:
                origin.backup(cloned, pages=256, progress=check_deadline, sleep=0.05)
                cloned.execute("PRAGMA journal_mode=DELETE")


def clone_state(source: Path, destination: Path, *, timeout: float = 30) -> None:
    """Clone files privately and use SQLite backup rather than copying live WALs."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("state_clone_source_invalid")
    destination.mkdir(mode=0o700)
    deadline = time.monotonic() + timeout

    def check_deadline(*_):
        if time.monotonic() >= deadline:
            raise TimeoutError("state_clone_backup_timeout")

    for path in sorted(source.rglob("*")):
        check_deadline()
        # Archived repair backups are not inputs to application startup or reads.
        if path.relative_to(source).parts[0] == "backups":
            continue
        if path.is_symlink():
            raise ValueError("state_clone_symlink_rejected")
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(mode=0o700, exist_ok=True)
        elif path.name.endswith(("-wal", "-shm", "-journal")):
            continue
        elif path.suffix in {".db", ".sqlite", ".sqlite3"}:
            _backup_database(path, target, check_deadline)
            target.chmod(0o600)
        elif path.is_file():
            shutil.copyfile(path, target)
            target.chmod(0o600)
        else:
            raise ValueError("state_clone_special_file_rejected")


def run_state_clone_gate(
    *,
    source_data: Path,
    candidate_command: list[str],
    candidate_cwd: Path,
    rollback_command: list[str] | None = None,
    rollback_cwd: Path | None = None,
    timeout: int = 120,
    network_isolation: bool = False,
    candidate_sha: str | None = None,
    rollback_sha: str | None = None,
):
    isolation_command = []
    if network_isolation:
        if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
            raise ValueError("state_clone_os_network_isolation_unsupported")
        isolation_command = [
            "/usr/bin/sandbox-exec",
            "-p",
            "(version 1) (allow default) (deny network*)",
        ]
    native = None
    previous_native = None
    if candidate_sha is not None:
        if not network_isolation:
            raise ValueError("state_clone_native_network_isolation_required")
        native = _native_identity(candidate_command, candidate_cwd, candidate_sha)
        if rollback_command is not None:
            if rollback_sha is None:
                raise ValueError("state_clone_rollback_identity_required")
            previous_native = _native_identity(
                rollback_command, rollback_cwd or candidate_cwd, rollback_sha
            )
    with tempfile.TemporaryDirectory(prefix="karkinos-state-clone-") as temporary:
        root = Path(temporary).resolve()
        baseline = root / "baseline"
        candidate = root / "candidate"
        clone_state(source_data, baseline)
        clone_state(baseline, candidate)
        token = uuid.uuid4().hex
        (root / ".state-clone.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "token": token,
                    "data_dir": str(candidate.resolve()),
                    "device": candidate.stat().st_dev,
                    "inode": candidate.stat().st_ino,
                }
            )
        )
        config = root / "config.json"
        config.write_text("{}\n")
        env_file = root / ".env"
        env_file.write_text("\n")
        # The existing release guard disables scheduler/provider side effects
        # throughout the candidate's real application lifespan.
        (root / ".release-transaction.json").write_text("{}\n")
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
            if key in os.environ
        }
        environment.update(
            KARKINOS_HOME=str(root),
            KARKINOS_DATA_DIR=str(candidate),
            KARKINOS_CONFIG_PATH=str(config),
            KARKINOS_ENV_FILE=str(env_file),
            KARKINOS_STATE_CLONE="1",
            KARKINOS_STATE_CLONE_TOKEN=token,
            PYTHONDONTWRITEBYTECODE="1",
        )

        def run(command, cwd, identity=None):
            if identity is not None:
                _assert_native_identity([command[0]], cwd, identity)
            process = subprocess.Popen(
                [*isolation_command, *command],
                cwd=cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            finally:
                # Reap descendants as well as a timed-out candidate process.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            result = subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
            if result.returncode != 0:
                raise ValueError(
                    "state_clone_process_failed"
                ) from subprocess.CalledProcessError(
                    result.returncode,
                    command,
                    output=result.stdout,
                    stderr=result.stderr,
                )
            if identity is not None:
                _assert_native_identity([command[0]], cwd, identity)
            return result

        result = run([*candidate_command, "--replay-state"], candidate_cwd, native)
        report = json.loads(result.stdout)
        if (
            report.get("schema_version") != "karkinos.state_clone_replay.v1"
            or report.get("status") != "passed"
        ):
            raise ValueError("state_clone_report_invalid")
        restarted = json.loads(
            run([*candidate_command, "--replay-state"], candidate_cwd, native).stdout
        )
        if (
            restarted.get("schema_version") != report["schema_version"]
            or restarted.get("status") != "passed"
        ):
            raise ValueError("state_clone_restart_failed")
        report["process_restart"] = "passed"
        if native is not None:
            first = _native_tcp_probe(
                candidate_command, candidate_cwd, environment, native, timeout=timeout
            )
            second = _native_tcp_probe(
                candidate_command, candidate_cwd, environment, native, timeout=timeout
            )
            if first["financial_read_identity"] != second["financial_read_identity"]:
                raise ValueError("state_clone_tcp_restart_identity_drift")
            report["native_tcp"] = {"candidate": first, "restart": second}
        if rollback_command is not None:
            restored = root / "restored"
            clone_state(baseline, restored)
            environment["KARKINOS_DATA_DIR"] = str(restored)
            run(
                [*rollback_command, "--check-state"],
                rollback_cwd or candidate_cwd,
                previous_native,
            )
            report["restored_baseline_preflight"] = "passed"
            if previous_native is not None:
                report["native_tcp"]["rollback"] = _native_tcp_probe(
                    rollback_command,
                    rollback_cwd or candidate_cwd,
                    environment,
                    previous_native,
                    timeout=timeout,
                )
        else:
            report["restored_baseline_preflight"] = "not_checked"
        report["rollback_start_read_stop"] = (
            "passed" if previous_native is not None else "not_checked"
        )
        report["launch_agent"] = "not_checked"
        report["promotion_evidence_binding"] = "not_checked"
        report["cross_store_consistency"] = "not_checked"
        report["network_isolation"] = (
            "os_profiles_asgi_denied_tcp_listener_only"
            if native is not None
            else "os_process_tree_denied" if network_isolation else "not_checked"
        )
        report["release_eligible"] = False
        if native is not None:
            _assert_native_identity(candidate_command, candidate_cwd, native)
            if previous_native is not None:
                _assert_native_identity(
                    rollback_command, rollback_cwd or candidate_cwd, previous_native
                )
            report["native_payload_integrity_after_run"] = "passed"
        return report


def _native_identity(command: list[str], cwd: Path, sha: str) -> dict:
    from tools.release_artifact import validate_manifest

    if len(command) != 1:
        raise ValueError("state_clone_native_entrypoint_required")
    entrypoint = Path(command[0])
    root = entrypoint.parent.parent
    if (
        not entrypoint.is_absolute()
        or entrypoint != root / "bin" / "karkinos"
        or cwd != root / "app"
    ):
        raise ValueError("state_clone_native_entrypoint_required")
    return validate_manifest(
        root,
        expected_commit_sha=sha,
        expected_architecture=platform.machine(),
        expected_control_protocol=None,
    )


def _assert_native_identity(command: list[str], cwd: Path, expected: dict) -> None:
    current = _native_identity(command, cwd, expected["commit_sha"])
    if current != expected:
        raise ValueError("state_clone_native_identity_changed")


def _tcp_port(requested: int | None = None) -> int:
    if requested is not None and (
        type(requested) is not int or not 1 <= requested <= 65535
    ):
        raise ValueError("state_clone_tcp_port_invalid")
    try:
        with socket.socket() as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reservation.bind(("127.0.0.1", requested or 0))
            return reservation.getsockname()[1]
    except OSError as exc:
        raise ValueError("state_clone_tcp_port_unavailable") from exc


def _tcp_isolation_command(port: int) -> list[str]:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("state_clone_os_network_isolation_unsupported")
    return [
        "/usr/bin/sandbox-exec",
        "-p",
        f"(version 1) (allow default) (deny network*) "
        f'(allow network-bind (local ip "localhost:{port}")) '
        f'(allow network-inbound (local ip "localhost:{port}"))',
    ]


def _tcp_json(port: int, endpoint: str):
    # Local probes must not inherit a user's HTTP proxy configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{endpoint}", timeout=2) as response:
        return json.load(response)


def _listener_owned_by(pid: int, port: int) -> bool:
    result = subprocess.run(
        [
            "/usr/sbin/lsof",
            "-nP",
            "-a",
            "-p",
            str(pid),
            "-iTCP:" + str(port),
            "-sTCP:LISTEN",
            "-Fp",
        ],
        capture_output=True,
        text=True,
        timeout=3,
    )
    processes = [line for line in result.stdout.splitlines() if line.startswith("p")]
    return result.returncode == 0 and processes == [f"p{pid}"]


def _process_group_exists(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_process_group_exit(pid: int, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while _process_group_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not _process_group_exists(pid)


def _native_worker_pid(data: Path, supervisor_pid: int) -> int | None:
    with closing(
        sqlite3.connect((data / "app.db").resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        row = conn.execute(
            "SELECT value_json FROM runtime_controls WHERE key='data_worker_heartbeat'"
        ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        kind, pid, _ = value["owner"].split(":")
        worker_pid = int(pid)
        if (
            kind == "data-worker"
            and value.get("status") == "ready"
            and worker_pid != supervisor_pid
            and os.getpgid(worker_pid) == supervisor_pid
        ):
            return worker_pid
    except (KeyError, TypeError, ValueError, ProcessLookupError):
        pass
    return None


def _verify_native_network_isolation(isolation, cwd, environment):
    denied = "import socket\nfor address in [('127.0.0.1',1),('198.51.100.1',443)]:\n try: socket.create_connection(address,timeout=1)\n except PermissionError: pass\n else: raise AssertionError('network isolation failed')"
    code = f"import subprocess,sys; subprocess.run([sys.executable,'-I','-B','-c',{denied!r}],check=True)"
    subprocess.run(
        [
            *isolation,
            str(cwd.parent / "runtime/bin/python3.12"),
            "-I",
            "-B",
            "-c",
            code,
        ],
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        timeout=10,
    )


def _tcp_financial_read_identity(data: Path, port: int) -> dict:
    with closing(
        sqlite3.connect((data / "app.db").resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        query = (
            "SELECT s.snapshot_id, s.ledger_cutoff_id FROM valuation_snapshots s "
            "JOIN runtime_controls c ON s.snapshot_id=json_extract(c.value_json,'$.snapshot_id') "
            "WHERE c.key='valuation_snapshot_publication' AND json_extract(c.value_json,'$.status')='ready'"
        )
        row = conn.execute(query).fetchone()
        if row is None:
            raise ValueError("state_clone_tcp_financial_identity_unavailable")
        identity = {"valuation_snapshot_id": row[0], "ledger_cutoff_id": row[1]}
        for endpoint in ("/api/portfolio", "/api/portfolio/overview"):
            body = _tcp_json(port, endpoint)
            if not isinstance(body, dict) or any(
                body.get(key) != value for key, value in identity.items()
            ):
                raise ValueError("state_clone_tcp_financial_identity_mismatch")
        if conn.execute(query).fetchone() != row:
            raise ValueError("state_clone_tcp_financial_identity_drift")
        return identity


def _native_tcp_probe(command, cwd, environment, manifest, *, timeout, port=None):
    from scripts.release.manage_release import _health_payload_matches

    _assert_native_identity(command, cwd, manifest)
    port = _tcp_port(port)
    isolation = _tcp_isolation_command(port)
    _verify_native_network_isolation(isolation, cwd, environment)
    _assert_native_identity(command, cwd, manifest)
    data = Path(environment["KARKINOS_DATA_DIR"])
    requires_worker = (cwd / "server/workers/supervisor.py").is_file()
    worker_pid = None
    with tempfile.TemporaryFile(mode="w+") as output:
        process = subprocess.Popen(
            [*isolation, *command, "--host", "127.0.0.1", "--port", str(port)],
            cwd=cwd,
            env={
                **environment,
                "KARKINOS_HOST": "127.0.0.1",
                "KARKINOS_PORT": str(port),
            },
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ValueError("state_clone_tcp_process_exited")
                try:
                    healthy = _health_payload_matches(
                        _tcp_json(port, "/api/health"),
                        _tcp_json(port, "/api/settings/live/status"),
                        manifest,
                        expected_activation_guarded=True,
                    ) and _listener_owned_by(process.pid, port)
                    if healthy and requires_worker:
                        worker_pid = _native_worker_pid(data, process.pid)
                        healthy = worker_pid is not None
                except (OSError, ValueError):
                    healthy = False
                if healthy and process.poll() is None:
                    break
                time.sleep(0.2)
            else:
                raise ValueError("state_clone_tcp_health_identity_failed")
            identity = _tcp_financial_read_identity(data, port)
            if process.poll() is not None:
                raise ValueError("state_clone_tcp_process_exited")
            process.terminate()
            try:
                if process.wait(timeout=15) not in (0, -signal.SIGTERM):
                    raise ValueError("state_clone_tcp_stop_failed")
            except subprocess.TimeoutExpired as exc:
                raise ValueError("state_clone_tcp_stop_timeout") from exc
            if not _wait_process_group_exit(process.pid):
                raise ValueError("state_clone_tcp_descendant_survived")
            _tcp_port(port)
            _assert_native_identity(command, cwd, manifest)
            return {
                "commit_sha": manifest["commit_sha"],
                "payload_fingerprint": manifest["payload_fingerprint"],
                "pid": process.pid,
                "calendar_worker_pid": worker_pid,
                "port": port,
                "listener_identity": "passed",
                "financial_read_identity": identity,
                "read_database_writes": "not_checked",
                "start_read_stop": "passed",
                "listener_and_process_group_exit": "passed",
                "network_isolation": "os_loopback_listener_only",
                "outbound_denial": "verified_in_artifact_runtime_descendant",
            }
        finally:
            if _process_group_exists(process.pid):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)
