"""Exercise bounded log output and real logger lifecycle without account state."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.service import main_logs
from scripts.service.main_logs import MainLogs, _LogWriter

ROOT = Path(__file__).resolve().parents[2]


def test_append_preserves_existing_output_and_tightens_permissions(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir(mode=0o755)
    current = directory / "main.log"
    current.write_bytes(b"previous startup\n")
    archive = directory / "main.log.1"
    archive.write_bytes(b"older startup\n")
    with MainLogs(directory) as logs:
        logs.check_running()
        logs.stream.write(b"new startup\n")
    assert current.read_bytes() == b"previous startup\nnew startup\n"
    assert archive.read_bytes() == b"older startup\n"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(current.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    logs.finish()
    assert logs.process.returncode == 0


def test_no_newline_output_rotates_while_running_and_retains_tail(tmp_path):
    directory = tmp_path / "logs"
    limit = 1024
    output = bytes(range(256)) * 2049
    with MainLogs(directory, max_bytes=limit) as logs:
        # Unbuffered pipe writes may be short; model a real subprocess producer.
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes(range(256)) * 2049)",
            ],
            stdout=logs.stream,
            stderr=logs.stream,
        )
        assert child.wait(timeout=10) == 0
        logs.check_running()
    files = [directory / f"main.log.{i}" for i in (3, 2, 1)]
    files.append(directory / "main.log")
    assert b"".join(path.read_bytes() for path in files) == output[-(3 * limit + 256) :]
    assert all(path.stat().st_size <= limit for path in files)
    assert not (directory / "main.log.4").exists()


def test_subprocess_stdout_stderr_drain_before_successful_shutdown(tmp_path):
    with MainLogs(tmp_path / "logs") as logs:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os; os.write(1, b'API output\\n'); os.write(2, b'worker error\\n')",
            ],
            stdout=logs.stream,
            stderr=logs.stream,
        )
        logs.stream.close()
        assert process.wait(timeout=3) == 0
    assert (tmp_path / "logs/main.log").read_bytes() == b"API output\nworker error\n"


def test_active_logger_excludes_concurrent_writer(tmp_path):
    with MainLogs(tmp_path / "logs") as first:
        with pytest.raises(RuntimeError, match="already running"):
            with MainLogs(tmp_path / "logs"):
                pytest.fail("concurrent logger started")
        first.stream.write(b"first owner\n")
    assert (tmp_path / "logs/main.log").read_bytes() == b"first owner\n"


@pytest.mark.parametrize("name", ["main.log", "main.log.1", ".main.log.lock"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo"])
def test_unsafe_entries_are_rejected_without_touching_target(tmp_path, name, kind):
    directory = tmp_path / "logs"
    directory.mkdir()
    target = tmp_path / "unrelated"
    target.write_bytes(b"keep this data")
    entry = directory / name
    if kind == "symlink":
        entry.symlink_to(target)
    elif kind == "hardlink":
        entry.hardlink_to(target)
    elif kind == "directory":
        entry.mkdir()
    else:
        os.mkfifo(entry)
    with pytest.raises(RuntimeError, match="unsafe main log entry"):
        with MainLogs(directory):
            pytest.fail("unsafe logger started")
    assert target.read_bytes() == b"keep this data"
    assert entry.lstat()


def test_symlink_directory_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    directory = tmp_path / "logs"
    directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="main log sink failed"):
        with MainLogs(directory):
            pytest.fail("unsafe logger started")
    assert list(target.iterdir()) == []


def test_shared_writable_directory_is_rejected_without_chmod(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    directory.chmod(0o777)
    with pytest.raises(RuntimeError, match="unsafe"):
        with MainLogs(directory):
            pytest.fail("unsafe logger started")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o777
    assert list(directory.iterdir()) == []


def test_foreign_directory_is_rejected(tmp_path, monkeypatch):
    directory = tmp_path / "logs"
    directory.mkdir()
    real_uid = os.getuid()
    monkeypatch.setattr(main_logs.os, "getuid", lambda: real_uid + 1)
    with pytest.raises(ValueError, match="unsafe"):
        with _LogWriter(directory, 1024, 3):
            pytest.fail("foreign logger started")
    assert list(directory.iterdir()) == []


def test_foreign_file_is_rejected_before_permission_changes(tmp_path, monkeypatch):
    directory = tmp_path / "logs"
    directory.mkdir()
    entry = directory / "main.log"
    entry.write_bytes(b"foreign output")
    mode = entry.stat().st_mode
    original_stat = os.stat

    def foreign_owner(path, **kwargs):
        value = original_stat(path, **kwargs)
        if path == "main.log":
            fields = list(value)
            fields[4] = value.st_uid + 1
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(main_logs.os, "stat", foreign_owner)
    with pytest.raises(ValueError, match="unsafe main log entry"):
        with _LogWriter(directory, 1024, 3):
            pytest.fail("foreign logger started")
    assert entry.read_bytes() == b"foreign output"
    assert entry.stat().st_mode == mode


@pytest.mark.parametrize("changed", ["main.log", "main.log.1", ".main.log.lock"])
def test_entry_replacement_after_start_is_observable_by_supervisor(tmp_path, changed):
    directory = tmp_path / "logs"
    logs = MainLogs(directory)
    logs.__enter__()
    target = tmp_path / "unrelated"
    target.write_bytes(b"unchanged")
    entry = directory / changed
    entry.unlink(missing_ok=True)
    entry.symlink_to(target)
    logs.stream.write(b"must not be silently discarded")
    assert logs.process.wait(timeout=3) == 1
    with pytest.raises(RuntimeError, match="unsafe main log entry"):
        logs.check_running()
    with pytest.raises(RuntimeError, match="unsafe main log entry"):
        logs.finish()
    assert target.read_bytes() == b"unchanged"


def test_archive_failure_does_not_rotate_existing_history(tmp_path):
    directory = tmp_path / "logs"
    with _LogWriter(directory, 4, 3) as writer:
        writer.write(b"keep")
        target = tmp_path / "unrelated"
        target.write_bytes(b"untouched")
        (directory / "main.log.3").symlink_to(target)
        with pytest.raises(ValueError, match="unsafe main log entry"):
            writer.write(b"overflow")
        assert (directory / "main.log").read_bytes() == b"keep"
        assert not (directory / "main.log.1").exists()
        assert target.read_bytes() == b"untouched"


def test_disk_error_exits_nonzero_and_reports_reason(tmp_path):
    code = """
import errno
from scripts.service import main_logs
def full_disk(fd, data):
    raise OSError(errno.ENOSPC, 'disk full')
main_logs.os.write = full_disk
raise SystemExit(main_logs.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code, "--directory", str(tmp_path / "logs")],
        cwd=ROOT,
        input=b"unrecorded output",
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == 1
    assert result.stdout == b"ready\n"
    assert b"disk full" in result.stderr


def test_partial_writes_preserve_all_bytes(tmp_path, monkeypatch):
    original_write = os.write

    def partial_write(descriptor, data):
        return original_write(descriptor, data[:2])

    with _LogWriter(tmp_path / "logs", 10, 3) as writer:
        monkeypatch.setattr(main_logs.os, "write", partial_write)
        writer.write(b"0123456789abc")
    assert (tmp_path / "logs/main.log.1").read_bytes() == b"0123456789"
    assert (tmp_path / "logs/main.log").read_bytes() == b"abc"


def test_drain_timeout_is_a_failure_and_reaps_logger(tmp_path):
    logs = MainLogs(tmp_path / "logs")
    logs.__enter__()
    inherited_output = os.dup(logs.stream.fileno())
    try:
        with pytest.raises(TimeoutError, match="finish draining"):
            logs.finish(timeout=0.05)
    finally:
        os.close(inherited_output)
    assert logs.process.poll() is not None
    logs.finish()


@pytest.mark.parametrize("max_bytes,backups", [(0, 3), (1024, 0), (-1, 3)])
def test_invalid_bounds_fail_before_creating_logs(tmp_path, max_bytes, backups):
    with pytest.raises(RuntimeError, match="must be positive"):
        with MainLogs(tmp_path / "logs", max_bytes=max_bytes, backups=backups):
            pytest.fail("invalid logger started")
    assert not (tmp_path / "logs").exists()
