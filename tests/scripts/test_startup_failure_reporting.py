"""The reloader staying alive must not turn a known failure into a timeout."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.service import run_dev
from server.__main__ import _report_startup_failure


def test_failure_report_is_token_bound_and_does_not_include_exception_text(
    tmp_path, monkeypatch
):
    path = tmp_path / "status.json"
    monkeypatch.setenv("KARKINOS_STARTUP_STATUS_FILE", str(path))
    monkeypatch.setenv("KARKINOS_STARTUP_STATUS_TOKEN", "fixture-token")
    _report_startup_failure(RuntimeError("private details must stay out of IPC"))
    assert json.loads(path.read_text()) == {
        "token": "fixture-token",
        "state": "failed",
        "error_type": "RuntimeError",
    }
    assert path.stat().st_mode & 0o777 == 0o600
    assert run_dev._startup_failed(dict(os.environ))
    monkeypatch.setenv("KARKINOS_STARTUP_STATUS_TOKEN", "other-token")
    assert not run_dev._startup_failed(dict(os.environ))


def test_failure_reporting_io_error_does_not_replace_original(tmp_path, monkeypatch):
    monkeypatch.setenv("KARKINOS_STARTUP_STATUS_FILE", str(tmp_path / "missing/status"))
    monkeypatch.setenv("KARKINOS_STARTUP_STATUS_TOKEN", "fixture-token")
    _report_startup_failure(RuntimeError("original failure"))
    assert not list(tmp_path.iterdir())


def test_live_reloader_failure_stops_owned_children_without_starting_frontend(tmp_path):
    status = tmp_path / "status.json"
    pid_file = tmp_path / "api.pid"
    frontend = tmp_path / "frontend.started"
    environment = dict(os.environ)
    environment.update(
        KARKINOS_STARTUP_STATUS_FILE=str(status),
        KARKINOS_STARTUP_STATUS_TOKEN="fixture-token",
    )
    child = (
        "import os,time; from pathlib import Path; "
        "from server.__main__ import _report_startup_failure; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "_report_startup_failure(RuntimeError('synthetic startup failure')); "
        "time.sleep(60)"
    )
    commands = [
        [sys.executable, "-c", child],
        [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(frontend)!r}).touch()",
        ],
    ]
    program = (
        "import os; from scripts.service.run_dev import supervise; "
        f"raise SystemExit(supervise({commands!r}, dict(os.environ), "
        "health_url='http://127.0.0.1:1/api/health', startup_timeout=60))"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=run_dev.ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 1, result.stderr
        assert "startup failed" in result.stderr
        assert "timed out" not in result.stderr
        assert time.monotonic() - started < 15
        assert not frontend.exists()
        assert unrelated.poll() is None
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
    finally:
        unrelated.send_signal(signal.SIGTERM)
        unrelated.wait(timeout=10)
