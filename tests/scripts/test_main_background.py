"""Detached startup must acknowledge readiness, retain logs, and clean cancellation."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from scripts.service import main_background as background
from scripts.service import main_control

REPO = Path(__file__).resolve().parents[2]


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail("condition did not become true")


def alive(pid):
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    )
    return result.returncode == 0 and not result.stdout.lstrip().startswith("Z")


@pytest.fixture
def source(tmp_path):
    workspace = tmp_path / "account"
    (workspace / "data/store").mkdir(parents=True)
    for name in ("config.json", ".env", "data/store/app.db", "data/store/meta.db"):
        (workspace / name).write_bytes(b"original fixture")

    root = tmp_path / "source"
    (root / "scripts/service").mkdir(parents=True)
    (root / ".venv/bin").mkdir(parents=True)
    (root / ".venv/bin/python").symlink_to(sys.executable)
    child_code = textwrap.dedent("""
        import os, sys, time, threading
        from pathlib import Path
        fd = int(os.environ['KARKINOS_SUPERVISOR_FD'])
        def watch():
            os.read(fd, 1)
            os._exit(70)
        threading.Thread(target=watch, daemon=True).start()
        role = 'research' if '--research-worker' in sys.argv else 'api'
        Path(role + '.pid').write_text(str(os.getpid()))
        print(role + ' stdout', flush=True)
        print(role + ' stderr', file=sys.stderr, flush=True)
        while True:
            time.sleep(0.05)
    """)
    driver = root / "scripts/service/run_main.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import os, sys
            from pathlib import Path
            sys.path.insert(0, {str(REPO)!r})
            from scripts.service import run_main as runtime
            runtime.ROOT = Path({str(root)!r})
            runtime.DRIVER = Path(__file__).resolve()
            runtime.check_source = lambda root: 'a' * 40
            runtime.require_runtime_idle = lambda workspace: None
            runtime.CHILD_ENTRY = {child_code!r}
            class FixtureLogs(runtime.MainLogs):
                def __enter__(self):
                    super().__enter__()
                    (runtime.ROOT / 'logger.pid').write_text(str(self.process.pid))
                    return self
            runtime.MainLogs = FixtureLogs
            runtime.startup_ready = lambda *args: os.environ.get('FIXTURE_UNREADY') != '1' and all((runtime.ROOT / (name + '.pid')).exists() for name in ('api', 'research'))
            original_prepare = runtime.run_preparation
            def prepare(command, **kwargs):
                if os.environ.get('FIXTURE_PREP_FAIL') == '1':
                    original_prepare([sys.executable, '-c', 'import sys; print("fixture build failed", flush=True); sys.exit(9)'], **kwargs)
                elif os.environ.get('FIXTURE_PREP_WAIT') == '1':
                    original_prepare([sys.executable, '-c', 'import os,time; from pathlib import Path; Path("prep.pid").write_text(str(os.getpid())); time.sleep(60)'], **kwargs)
                else:
                    print('fixture preparation', flush=True)
            runtime.run_preparation = prepare
            if '--startup-fd' in sys.argv:
                (runtime.ROOT / 'supervisor.pid').write_text(str(os.getpid()))
            raise SystemExit(runtime.main())
            """
        )
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("KARKINOS_")}
    with socket.socket() as port:
        port.bind(("127.0.0.1", 0))
        env["KARKINOS_MAIN_PORT"] = str(port.getsockname()[1])
    env["KARKINOS_WORKSPACE"] = str(workspace)
    env["KARKINOS_SOURCE_BRANCH"] = "main"
    yield root, workspace, driver, env
    main_control.request_stop(workspace / ".run/main", timeout=5)


def run_driver(source, *args, overrides=None):
    _, _, driver, env = source
    return subprocess.run(
        [sys.executable, str(driver), *args],
        env={**env, **(overrides or {})},
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_default_start_returns_detached_with_logs_and_stop_allows_restart(source):
    root, workspace, _, _ = source
    before = {
        name: (workspace / name).read_bytes()
        for name in ("config.json", ".env", "data/store/app.db", "data/store/meta.db")
    }
    started = run_driver(source)
    assert started.returncode == 0, started.stderr
    assert "Main started" in started.stdout
    assert str(workspace / "logs/main.log") in started.stdout
    pids = {
        name: int((root / f"{name}.pid").read_text())
        for name in ("supervisor", "api", "research")
    }
    assert all(alive(pid) for pid in pids.values())
    assert os.getsid(pids["supervisor"]) == pids["supervisor"]
    log = workspace / "logs/main.log"
    wait_for(
        lambda: all(
            text in log.read_text()
            for text in (
                "fixture preparation",
                "api stdout",
                "research stderr",
                "Karkinos ready",
            )
        )
    )
    duplicate = run_driver(source)
    assert duplicate.returncode == 1
    assert "runtime already in use" in duplicate.stderr
    assert all(alive(pid) for pid in pids.values())
    assert run_driver(source, "--stop").returncode == 0
    wait_for(lambda: not any(alive(pid) for pid in pids.values()))
    assert not main_control._lock_held(workspace / ".run/main")
    assert not (workspace / ".run/main/control.sock").exists()
    old_log = log.read_bytes()
    assert run_driver(source).returncode == 0
    assert log.read_bytes().startswith(old_log)
    assert before == {name: (workspace / name).read_bytes() for name in before}


def test_preparation_failure_is_reported_and_logged_without_service(source):
    root, workspace, _, _ = source
    failed = run_driver(source, overrides={"FIXTURE_PREP_FAIL": "1"})
    assert failed.returncode == 1
    assert "exit status 9" in failed.stderr
    assert "fixture build failed" in (workspace / "logs/main.log").read_text()
    assert not (root / "api.pid").exists()
    assert not main_control._lock_held(workspace / ".run/main")


@pytest.mark.parametrize(
    "interrupt", ["signal", "parent_death", "supervisor_death", "stop"]
)
def test_pending_start_cancellation_cleans_preparation_and_locks(source, interrupt):
    root, workspace, driver, env = source
    caller = subprocess.Popen(
        [sys.executable, str(driver)],
        env={**env, "FIXTURE_PREP_WAIT": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for(lambda: (root / "prep.pid").exists())
        pid = int((root / "prep.pid").read_text())
        if interrupt == "signal":
            caller.send_signal(signal.SIGINT)
        elif interrupt == "parent_death":
            caller.kill()
        elif interrupt == "supervisor_death":
            os.kill(int((root / "supervisor.pid").read_text()), signal.SIGKILL)
        else:
            assert run_driver(source, "--stop").returncode == 0
        caller.communicate(timeout=15)
        assert caller.returncode != 0
        wait_for(lambda: not alive(pid))
        wait_for(lambda: not main_control._lock_held(workspace / ".run/main"))
        assert not (root / "api.pid").exists()
    finally:
        if caller.poll() is None:
            caller.kill()
            caller.communicate(timeout=5)


def test_unready_start_timeout_cleans_api_research_and_locks(source):
    root, workspace, driver, env = source
    result = background.launch_background(
        [sys.executable, str(driver)],
        {**env, "FIXTURE_UNREADY": "1"},
        workspace / "logs/main.log",
        timeout=1,
    )
    assert result == 1
    for name in ("api", "research"):
        pid = int((root / f"{name}.pid").read_text())
        wait_for(lambda: not alive(pid))
    assert not main_control._lock_held(workspace / ".run/main")


def test_preparation_cancellation_terminates_descendant_group(tmp_path):
    command = [
        sys.executable,
        "-c",
        'import subprocess,time; from pathlib import Path; p=subprocess.Popen(["sleep","60"]); Path("descendant.pid").write_text(str(p.pid)); time.sleep(60)',
    ]

    def monitor():
        if (tmp_path / "descendant.pid").exists():
            raise InterruptedError("fixture cancellation")

    with pytest.raises(InterruptedError):
        background.run_preparation(
            command, cwd=tmp_path, env=os.environ.copy(), monitor=monitor
        )
    pid = int((tmp_path / "descendant.pid").read_text())
    wait_for(lambda: not alive(pid))


@pytest.mark.parametrize("target", ["supervisor", "logger"])
def test_serving_failure_stops_children_and_releases_locks(source, target):
    root, workspace, _, _ = source
    assert run_driver(source).returncode == 0
    pids = {
        name: int((root / f"{name}.pid").read_text())
        for name in ("supervisor", "logger", "api", "research")
    }
    os.kill(pids[target], signal.SIGKILL)
    wait_for(lambda: not any(alive(pid) for pid in pids.values()), timeout=12)
    assert not main_control._lock_held(workspace / ".run/main")
