"""Run an exact candidate's state replay on SQLite-consistent disposable copies."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
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

        def run(command, cwd):
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
            return result

        result = run([*candidate_command, "--replay-state"], candidate_cwd)
        report = json.loads(result.stdout)
        if (
            report.get("schema_version") != "karkinos.state_clone_replay.v1"
            or report.get("status") != "passed"
        ):
            raise ValueError("state_clone_report_invalid")
        restarted = json.loads(
            run([*candidate_command, "--replay-state"], candidate_cwd).stdout
        )
        if (
            restarted.get("schema_version") != report["schema_version"]
            or restarted.get("status") != "passed"
        ):
            raise ValueError("state_clone_restart_failed")
        report["process_restart"] = "passed"
        if rollback_command is not None:
            restored = root / "restored"
            clone_state(baseline, restored)
            environment["KARKINOS_DATA_DIR"] = str(restored)
            run([*rollback_command, "--check-state"], rollback_cwd or candidate_cwd)
            report["restored_baseline_preflight"] = "passed"
        else:
            report["restored_baseline_preflight"] = "not_checked"
        report["rollback_start_read_stop"] = "not_checked"
        report["cross_store_consistency"] = "not_checked"
        report["network_isolation"] = (
            "os_process_tree_denied" if network_isolation else "not_checked"
        )
        report["release_eligible"] = False
        return report
