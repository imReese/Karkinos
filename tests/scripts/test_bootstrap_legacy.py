from __future__ import annotations

import json
import os
import platform
import plistlib
import shutil
import stat
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from scripts.release import bootstrap_legacy, manage_release

_SHA = "d" * 40
_FINGERPRINT = "e" * 64
_LIVE_ENV = b"LIVE_TOKEN=live-private-sentinel\n"
_LIVE_CONFIG = b'{"source":"live-private-sentinel"}\n'
_LIVE_DATA = b"live-sqlite-private-sentinel"
_STALE_ENV = b"STALE_TOKEN=stale-private-sentinel\n"


class _Crash(BaseException):
    pass


@dataclass
class _ServiceState:
    plist: Path
    loaded: str | None = "legacy"
    managed_healthy: bool = True
    legacy_healthy: bool = True
    fail_legacy_stop: bool = False
    fail_managed_start: bool = False
    events: list[object] = field(default_factory=list)
    managed_start_timeouts: list[int] = field(default_factory=list)

    def managed_hooks(self) -> bootstrap_legacy.ManagedServiceHooks:
        def stop() -> None:
            self.events.append("managed-stop")
            self.loaded = None
            self.plist.unlink(missing_ok=True)

        def start(health_timeout: int) -> None:
            self.managed_start_timeouts.append(health_timeout)
            self.events.append("managed-start")
            if self.fail_managed_start:
                raise ValueError("injected-managed-start-failure")
            self.plist.write_bytes(b"new immutable plist")
            self.plist.chmod(0o600)
            self.loaded = "managed"

        def health(release: Path, manifest: dict[str, object], timeout: float) -> bool:
            self.events.append(
                ("managed-health", release.name, manifest["commit_sha"], timeout)
            )
            return self.loaded == "managed" and self.managed_healthy

        return bootstrap_legacy.ManagedServiceHooks(
            stop=stop,
            start=start,
            health=health,
        )

    def legacy_hooks(self) -> bootstrap_legacy.LegacyServiceHooks:
        def preflight() -> None:
            self.events.append("legacy-preflight")
            if self.loaded != "legacy":
                raise ValueError("legacy-not-loaded")

        def stop() -> None:
            self.events.append("legacy-stop")
            if self.fail_legacy_stop:
                raise ValueError("injected-legacy-stop-failure")
            self.loaded = None

        def restore(backup: Path) -> None:
            self.events.append("legacy-restore-plist")
            shutil.copy2(backup, self.plist)
            self.plist.chmod(0o600)

        def start() -> None:
            self.events.append("legacy-start")
            self.loaded = "legacy"

        def health(timeout: float) -> bool:
            self.events.append(("legacy-health", timeout))
            return self.loaded == "legacy" and self.legacy_healthy

        return bootstrap_legacy.LegacyServiceHooks(
            preflight=preflight,
            stop=stop,
            start=start,
            health=health,
            restore_plist=restore,
        )


@dataclass
class _CallbackState:
    probe_release_failure: bool = False
    probe_state_failure: bool = False
    events: list[str] = field(default_factory=list)


def _clone_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    for path in (destination, *destination.rglob("*")):
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)


def _clone_file(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    destination.chmod(0o600)


def _remove_private_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _pointer_state(home: Path) -> tuple[Path | None, Path | None]:
    def read(name: str) -> Path | None:
        pointer = home / name
        return pointer.resolve() if pointer.is_symlink() else None

    return read("current"), read("previous")


def _replace_pointer(home: Path, name: str, target: Path | None) -> None:
    pointer = home / name
    pointer.unlink(missing_ok=True)
    if target is not None:
        pointer.symlink_to(os.path.relpath(target, home))


def _manifest_for(path: Path) -> dict[str, object]:
    return {
        "commit_sha": path.name.removeprefix("sha-"),
        "payload_fingerprint": _FINGERPRINT,
        "version": "0.3.1",
    }


def _callbacks(state: _CallbackState) -> bootstrap_legacy.BootstrapCallbacks:
    def validate_candidate(home: Path, sha: str) -> tuple[Path, dict[str, object]]:
        candidate = home / "releases" / f".candidate-{sha}"
        if not candidate.is_dir():
            raise ValueError("candidate-missing")
        return candidate, {
            "commit_sha": sha,
            "payload_fingerprint": _FINGERPRINT,
            "version": "0.3.1",
        }

    def probe_release(
        _home: Path,
        _release: Path,
        _manifest: dict[str, object],
        _timeout: float,
    ) -> None:
        state.events.append("probe-release")
        if state.probe_release_failure:
            raise ValueError("injected-probe-release-failure")

    def probe_state(
        _release: Path,
        _manifest: dict[str, object],
        snapshot: Path,
        _timeout: float,
    ) -> None:
        state.events.append("probe-state")
        assert (snapshot / "config" / ".env").read_bytes() == _LIVE_ENV
        assert (snapshot / "config" / "config.json").read_bytes() == _LIVE_CONFIG
        assert (snapshot / "data" / "app.db").read_bytes() == _LIVE_DATA
        if state.probe_state_failure:
            raise ValueError("injected-probe-state-failure")

    return bootstrap_legacy.BootstrapCallbacks(
        pointer_state=_pointer_state,
        validate_candidate=validate_candidate,
        probe_release=probe_release,
        probe_state=probe_state,
        clone_tree=_clone_tree,
        clone_file=_clone_file,
        fsync_tree=lambda _path: None,
        remove_private_tree=_remove_private_tree,
        seal_release=lambda _path, _sha: None,
        replace_pointer=_replace_pointer,
        manifest_for=_manifest_for,
        fsync_directory=lambda _path, _error: None,
        remove_quarantine=_remove_private_tree,
    )


def _legacy_plist_payload(workdir: Path) -> dict[str, object]:
    return {
        "Label": "com.karkinos.daily-candidate",
        "ProgramArguments": bootstrap_legacy._expected_program_arguments(),
        "WorkingDirectory": str(workdir),
        "EnvironmentVariables": {
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "UV_CACHE_DIR": "/private/tmp/karkinos-uv-cache",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(workdir / "logs" / "server.log"),
        "StandardErrorPath": str(workdir / "logs" / "server.log"),
    }


@dataclass(frozen=True)
class _Topology:
    home: Path
    workdir: Path
    plist: Path


def _topology(tmp_path: Path) -> _Topology:
    home = tmp_path / "custom-runtime-home"
    for path in (
        home,
        home / "releases",
        home / "data",
        home / "config",
        home / "logs",
    ):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidate = home / "releases" / f".candidate-{_SHA}"
    candidate.mkdir()
    (candidate / "candidate.txt").write_text("immutable", encoding="utf-8")
    prod = home / "releases" / "prod"
    prod.mkdir()
    shared = home / "shared"
    shared.mkdir(mode=0o700)
    (shared / ".env").write_bytes(_STALE_ENV)
    (shared / "config.json").write_bytes(b'{"source":"stale"}\n')
    (prod / ".env").symlink_to(shared / ".env")

    workdir = tmp_path / "legacy-source-workdir"
    (workdir / "data" / "store").mkdir(parents=True)
    (workdir / "logs").mkdir()
    (workdir / ".env").write_bytes(_LIVE_ENV)
    (workdir / "config.json").write_bytes(_LIVE_CONFIG)
    (workdir / "data" / "store" / "app.db").write_bytes(_LIVE_DATA)
    for path in (workdir / ".env", workdir / "config.json"):
        path.chmod(0o600)

    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    plist = launch_agents / "com.karkinos.daily-candidate.plist"
    with plist.open("wb") as stream:
        plistlib.dump(_legacy_plist_payload(workdir), stream)
    plist.chmod(0o600)
    return _Topology(home=home, workdir=workdir, plist=plist)


def _run(
    topology: _Topology,
    services: _ServiceState,
    callback_state: _CallbackState,
    *,
    fault=None,
) -> dict[str, object]:
    return bootstrap_legacy.bootstrap_legacy_locked(
        topology.home,
        commit_sha=_SHA,
        legacy_workdir=topology.workdir,
        legacy_plist=topology.plist,
        confirmation=f"BOOTSTRAP {_SHA}",
        health_timeout=7,
        managed_service=services.managed_hooks(),
        legacy_service=services.legacy_hooks(),
        callbacks=_callbacks(callback_state),
        fault=fault,
    )


def _assert_legacy_restored_except_transaction(
    topology: _Topology,
    services: _ServiceState,
) -> None:
    assert services.loaded == "legacy"
    assert topology.plist.is_file()
    assert plistlib.loads(topology.plist.read_bytes())["WorkingDirectory"] == str(
        topology.workdir
    )
    assert (topology.workdir / ".env").read_bytes() == _LIVE_ENV
    assert (topology.workdir / "config.json").read_bytes() == _LIVE_CONFIG
    assert (topology.workdir / "data" / "store" / "app.db").read_bytes() == _LIVE_DATA
    assert (topology.home / "releases" / "prod").is_dir()
    assert (topology.home / "releases" / f".candidate-{_SHA}").is_dir()
    assert not (topology.home / "current").exists()
    assert not (topology.home / "previous").exists()


@pytest.mark.parametrize("health_timeout", (True, 0, 3601, 1.5))
def test_bootstrap_health_timeout_contract_rejects_invalid_values(
    health_timeout: object,
) -> None:
    with pytest.raises(ValueError, match="legacy_bootstrap_health_timeout_invalid"):
        bootstrap_legacy._require_timeout(health_timeout)


@pytest.mark.parametrize("health_timeout", (1, 3600))
def test_bootstrap_health_timeout_contract_accepts_inclusive_boundaries(
    health_timeout: int,
) -> None:
    assert bootstrap_legacy._require_timeout(health_timeout) == health_timeout


def _assert_legacy_restored(topology: _Topology, services: _ServiceState) -> None:
    _assert_legacy_restored_except_transaction(topology, services)
    assert not (topology.home / "legacy-bootstrap-quarantine").exists()
    assert not (topology.home / ".legacy-bootstrap-transaction.json").exists()


def test_legacy_source_preflight_accepts_only_prod_before_candidate_staging(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    shutil.rmtree(topology.home / "releases" / f".candidate-{_SHA}")

    bootstrap_legacy.preflight_legacy_sources(
        topology.home,
        legacy_workdir=topology.workdir,
        legacy_plist=topology.plist,
    )

    assert {path.name for path in (topology.home / "releases").iterdir()} == {"prod"}
    assert (topology.workdir / ".env").read_bytes() == _LIVE_ENV
    assert (topology.workdir / "config.json").read_bytes() == _LIVE_CONFIG
    assert (topology.workdir / "data" / "store" / "app.db").read_bytes() == _LIVE_DATA


def test_legacy_source_preflight_rejects_extra_release_before_mutation(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)

    with pytest.raises(ValueError, match="legacy_bootstrap_release_inventory_invalid"):
        bootstrap_legacy.preflight_legacy_sources(
            topology.home,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
        )

    assert (topology.home / "releases" / "prod").is_dir()
    assert (topology.home / "releases" / f".candidate-{_SHA}").is_dir()
    assert (topology.workdir / "data" / "store" / "app.db").read_bytes() == _LIVE_DATA


def test_legacy_source_preflight_rejects_unknown_plist_contract(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    shutil.rmtree(topology.home / "releases" / f".candidate-{_SHA}")
    payload = _legacy_plist_payload(topology.workdir)
    payload["ProgramArguments"] = ["/usr/bin/unknown-service"]
    with topology.plist.open("wb") as stream:
        plistlib.dump(payload, stream)

    with pytest.raises(ValueError, match="legacy_bootstrap_plist_contract_invalid"):
        bootstrap_legacy.preflight_legacy_sources(
            topology.home,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
        )

    assert (topology.workdir / ".env").read_bytes() == _LIVE_ENV
    assert (topology.workdir / "config.json").read_bytes() == _LIVE_CONFIG
    assert (topology.workdir / "data" / "store" / "app.db").read_bytes() == _LIVE_DATA


def test_bootstrap_uses_authoritative_live_state_and_retains_quarantine(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    callback_state = _CallbackState()

    result = _run(topology, services, callback_state)

    current = topology.home / "releases" / f"sha-{_SHA}"
    quarantine = topology.home / "legacy-bootstrap-quarantine"
    assert result == {
        "status": "legacy_bootstrap_complete",
        "current": _SHA,
        "previous": None,
        "quarantine_retained": True,
    }
    assert services.loaded == "managed"
    assert (topology.home / "current").resolve() == current
    assert not (topology.home / "previous").exists()
    assert {entry.name for entry in (topology.home / "releases").iterdir()} == {
        f"sha-{_SHA}"
    }
    assert (topology.home / "config" / ".env").read_bytes() == _LIVE_ENV
    assert (topology.home / "config" / "config.json").read_bytes() == _LIVE_CONFIG
    assert (topology.home / "data" / "app.db").read_bytes() == _LIVE_DATA
    assert not (topology.workdir / ".env").exists()
    assert not (topology.workdir / "config.json").exists()
    assert not (topology.workdir / "data" / "store").exists()
    assert (topology.home / "shared" / ".env").read_bytes() == _STALE_ENV
    assert (quarantine / "prod").is_dir()
    assert (quarantine / "state" / "data" / "app.db").read_bytes() == _LIVE_DATA
    assert stat.S_IMODE((quarantine / "legacy.plist").stat().st_mode) == 0o600
    assert stat.S_IMODE(quarantine.stat().st_mode) == 0o700
    assert stat.S_IMODE((topology.home / "config" / ".env").stat().st_mode) == 0o600
    serialized = json.dumps(result, sort_keys=True)
    assert "live-private-sentinel" not in serialized
    assert "stale-private-sentinel" not in serialized
    assert callback_state.events == ["probe-release", "probe-state"]
    assert services.managed_start_timeouts == [7]


@pytest.mark.parametrize("phase", sorted(bootstrap_legacy._PHASES))
def test_every_fault_checkpoint_restores_the_exact_legacy_service(
    tmp_path: Path, phase: str
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)

    def fail(current: str) -> None:
        if current == phase:
            raise RuntimeError(f"fault:{phase}")

    with pytest.raises(ValueError, match="legacy_bootstrap_failed_rolled_back"):
        _run(topology, services, _CallbackState(), fault=fail)

    _assert_legacy_restored(topology, services)


@pytest.mark.parametrize(
    "phase", ("prepared", "state_moved", "new_started", "committed")
)
def test_supported_crash_phases_recover_on_the_next_identical_command(
    tmp_path: Path, phase: str
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)

    def crash(current: str) -> None:
        if current == phase:
            raise _Crash()

    with pytest.raises(_Crash):
        _run(topology, services, _CallbackState(), fault=crash)
    assert (topology.home / ".legacy-bootstrap-transaction.json").is_file()

    with pytest.raises(ValueError, match="legacy_bootstrap_recovered_retry_required"):
        _run(topology, services, _CallbackState())

    _assert_legacy_restored(topology, services)


def test_preparing_journal_without_work_recovers_without_service_touch(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)

    def crash_before_work(current: str) -> None:
        if current == "preparing":
            raise _Crash()

    with pytest.raises(_Crash):
        _run(topology, services, _CallbackState(), fault=crash_before_work)

    journal_path = topology.home / ".legacy-bootstrap-transaction.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == "preparing"
    assert not (topology.home / str(journal["work_name"])).exists()
    services.events.clear()

    with pytest.raises(ValueError, match="legacy_bootstrap_recovered_retry_required"):
        _run(topology, services, _CallbackState())

    assert services.events == []
    _assert_legacy_restored(topology, services)


def test_preparing_journal_with_partial_work_recovers_without_service_touch(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    base = _callbacks(_CallbackState())

    def crash_during_backup(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"partial-private-plist")
        raise _Crash()

    with pytest.raises(_Crash):
        bootstrap_legacy.bootstrap_legacy_locked(
            topology.home,
            commit_sha=_SHA,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
            confirmation=f"BOOTSTRAP {_SHA}",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            legacy_service=services.legacy_hooks(),
            callbacks=replace(base, clone_file=crash_during_backup),
        )

    journal_path = topology.home / ".legacy-bootstrap-transaction.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    work = topology.home / str(journal["work_name"])
    assert journal["phase"] == "preparing"
    assert (work / "legacy.plist").read_bytes() == b"partial-private-plist"
    services.events.clear()

    with pytest.raises(ValueError, match="legacy_bootstrap_recovered_retry_required"):
        _run(topology, services, _CallbackState())

    assert services.events == []
    assert not work.exists()
    _assert_legacy_restored(topology, services)


@pytest.mark.parametrize("failure", ("stop", "state", "start", "health"))
def test_operational_failures_restore_legacy_without_disclosing_state(
    tmp_path: Path, failure: str
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    callbacks = _CallbackState()
    services.fail_legacy_stop = failure == "stop"
    services.fail_managed_start = failure == "start"
    services.managed_healthy = failure != "health"
    callbacks.probe_state_failure = failure == "state"

    with pytest.raises(
        ValueError, match="legacy_bootstrap_failed_rolled_back"
    ) as error:
        _run(topology, services, callbacks)

    assert "private-sentinel" not in str(error.value)
    _assert_legacy_restored(topology, services)


def test_post_guard_scheduler_failure_rolls_back_legacy_before_commit(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    base = services.managed_hooks()
    observed_phases: list[str] = []

    def health(
        release: Path,
        manifest: dict[str, object],
        timeout: float,
    ) -> bool:
        journal = bootstrap_legacy._read_journal(topology.home)
        assert journal is not None
        phase = str(journal["phase"])
        observed_phases.append(phase)
        base.health(release, manifest, timeout)
        return phase != "readiness"

    with pytest.raises(ValueError, match="legacy_bootstrap_failed_rolled_back"):
        bootstrap_legacy.bootstrap_legacy_locked(
            topology.home,
            commit_sha=_SHA,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
            confirmation=f"BOOTSTRAP {_SHA}",
            health_timeout=7,
            managed_service=replace(base, health=health),
            legacy_service=services.legacy_hooks(),
            callbacks=_callbacks(_CallbackState()),
        )

    assert observed_phases == ["new_started", "readiness"]
    _assert_legacy_restored(topology, services)


def test_disposable_candidate_failure_happens_before_journal_or_stop(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    callback_state = _CallbackState(probe_release_failure=True)

    with pytest.raises(ValueError, match="injected-probe-release-failure"):
        _run(topology, services, callback_state)

    assert services.events == []
    assert not (topology.home / ".legacy-bootstrap-transaction.json").exists()
    assert (topology.workdir / "data" / "store" / "app.db").read_bytes() == _LIVE_DATA


def test_partial_snapshot_failure_is_removed_before_legacy_restart(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    callback_state = _CallbackState()
    base = _callbacks(callback_state)
    clone_calls = 0

    def fail_first_tree_clone(source: Path, destination: Path) -> None:
        nonlocal clone_calls
        clone_calls += 1
        if clone_calls == 1:
            destination.mkdir()
            (destination / "partial").write_bytes(b"partial-private-state")
            raise ValueError("injected-snapshot-clone-failure")
        _clone_tree(source, destination)

    with pytest.raises(ValueError, match="legacy_bootstrap_failed_rolled_back"):
        bootstrap_legacy.bootstrap_legacy_locked(
            topology.home,
            commit_sha=_SHA,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
            confirmation=f"BOOTSTRAP {_SHA}",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            legacy_service=services.legacy_hooks(),
            callbacks=replace(base, clone_tree=fail_first_tree_clone),
        )

    assert clone_calls == 1
    _assert_legacy_restored(topology, services)


def test_incomplete_legacy_recovery_retains_private_journal_and_snapshot(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(
        topology.plist,
        managed_healthy=False,
        legacy_healthy=False,
    )

    with pytest.raises(ValueError, match="legacy_bootstrap_recovery_failed"):
        _run(topology, services, _CallbackState())

    journal = topology.home / ".legacy-bootstrap-transaction.json"
    assert journal.is_file()
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    payload = json.loads(journal.read_text(encoding="utf-8"))
    work = topology.home / str(payload["work_name"])
    assert (work / "state" / "data" / "app.db").read_bytes() == _LIVE_DATA
    assert stat.S_IMODE((work / "legacy.plist").stat().st_mode) == 0o600
    assert "live-private-sentinel" not in journal.read_text(encoding="utf-8")


def test_rolled_back_journal_recovers_after_transaction_tree_cleanup_failure(
    tmp_path: Path,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist, managed_healthy=False)
    base = _callbacks(_CallbackState())

    def fail_transaction_cleanup(path: Path) -> None:
        if path.name.startswith(bootstrap_legacy._WORK_PREFIX):
            raise ValueError("injected-transaction-cleanup-failure")
        _remove_private_tree(path)

    with pytest.raises(ValueError, match="legacy_bootstrap_recovery_failed"):
        bootstrap_legacy.bootstrap_legacy_locked(
            topology.home,
            commit_sha=_SHA,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
            confirmation=f"BOOTSTRAP {_SHA}",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            legacy_service=services.legacy_hooks(),
            callbacks=replace(
                base,
                remove_private_tree=fail_transaction_cleanup,
            ),
        )

    journal = json.loads(
        (topology.home / ".legacy-bootstrap-transaction.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["phase"] == "rolled_back"
    _assert_legacy_restored_except_transaction(topology, services)

    services.managed_healthy = True
    with pytest.raises(ValueError, match="legacy_bootstrap_recovered_retry_required"):
        _run(topology, services, _CallbackState())

    _assert_legacy_restored(topology, services)


@pytest.mark.parametrize("failure_point", ("snapshot", "moved-data"))
def test_state_fsync_failures_restore_legacy_state(
    tmp_path: Path,
    failure_point: str,
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    base = _callbacks(_CallbackState())

    def fail_selected_tree(path: Path) -> None:
        if failure_point == "snapshot" and path.name == ".state-staging":
            raise ValueError("injected-snapshot-fsync-failure")
        if failure_point == "moved-data" and path == topology.home / "data":
            raise ValueError("injected-state-move-fsync-failure")

    with pytest.raises(ValueError, match="legacy_bootstrap_failed_rolled_back"):
        bootstrap_legacy.bootstrap_legacy_locked(
            topology.home,
            commit_sha=_SHA,
            legacy_workdir=topology.workdir,
            legacy_plist=topology.plist,
            confirmation=f"BOOTSTRAP {_SHA}",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            legacy_service=services.legacy_hooks(),
            callbacks=replace(base, fsync_tree=fail_selected_tree),
        )

    _assert_legacy_restored(topology, services)


@pytest.mark.parametrize(
    "problem", ("plist", "extra-release", "symlink", "hardlink", "special")
)
def test_unsupported_legacy_topology_fails_before_service_stop(
    tmp_path: Path, problem: str
) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    data = topology.workdir / "data" / "store"
    if problem == "plist":
        payload = _legacy_plist_payload(topology.workdir)
        payload["ProgramArguments"] = ["python", "-m", "server"]
        with topology.plist.open("wb") as stream:
            plistlib.dump(payload, stream)
        topology.plist.chmod(0o600)
    elif problem == "extra-release":
        (topology.home / "releases" / "unexpected").mkdir()
    elif problem == "symlink":
        (data / "link").symlink_to(data / "app.db")
    elif problem == "hardlink":
        os.link(data / "app.db", data / "hardlink.db")
    else:
        os.mkfifo(data / "fifo")

    with pytest.raises(ValueError):
        _run(topology, services, _CallbackState())

    assert services.events == []
    assert (topology.workdir / ".env").read_bytes() == _LIVE_ENV
    assert not (topology.home / ".legacy-bootstrap-transaction.json").exists()


def test_finalize_requires_exact_health_and_confirmation(tmp_path: Path) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)
    callbacks = _callbacks(_CallbackState())
    _run(topology, services, _CallbackState())
    quarantine = topology.home / "legacy-bootstrap-quarantine"

    with pytest.raises(ValueError, match="confirmation_required"):
        bootstrap_legacy.finalize_bootstrap_locked(
            topology.home,
            confirmation="FINALIZE",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            callbacks=callbacks,
        )
    services.managed_healthy = False
    with pytest.raises(ValueError, match="current_health_failed"):
        bootstrap_legacy.finalize_bootstrap_locked(
            topology.home,
            confirmation="FINALIZE LEGACY BOOTSTRAP",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            callbacks=callbacks,
        )
    assert quarantine.is_dir()

    services.managed_healthy = True
    result = bootstrap_legacy.finalize_bootstrap_locked(
        topology.home,
        confirmation="FINALIZE LEGACY BOOTSTRAP",
        health_timeout=7,
        managed_service=services.managed_hooks(),
        callbacks=callbacks,
    )
    assert result == {"status": "legacy_bootstrap_finalized", "current": _SHA}
    assert not quarantine.exists()
    assert services.loaded == "managed"
    assert services.events.count("managed-start") == 3


def test_finalize_refuses_an_active_bootstrap_journal(tmp_path: Path) -> None:
    topology = _topology(tmp_path)
    services = _ServiceState(topology.plist)

    def crash(phase: str) -> None:
        if phase == "committed":
            raise _Crash()

    with pytest.raises(_Crash):
        _run(topology, services, _CallbackState(), fault=crash)

    with pytest.raises(ValueError, match="recovery_required"):
        bootstrap_legacy.finalize_bootstrap_locked(
            topology.home,
            confirmation="FINALIZE LEGACY BOOTSTRAP",
            health_timeout=7,
            managed_service=services.managed_hooks(),
            callbacks=_callbacks(_CallbackState()),
        )


def test_cli_exposes_only_explicit_bootstrap_confirmations() -> None:
    bootstrap = manage_release._parser().parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            "/legacy/source",
            "--legacy-plist",
            "/legacy/service.plist",
            "--confirm",
            "BOOTSTRAP v0.3.2",
        ]
    )
    finalize = manage_release._parser().parse_args(
        [
            "finalize-bootstrap",
            "--confirm",
            "FINALIZE LEGACY BOOTSTRAP",
        ]
    )

    assert bootstrap.command == "bootstrap"
    assert bootstrap.service_port is None
    assert finalize.command == "finalize-bootstrap"

    with pytest.raises(SystemExit):
        manage_release._parser().parse_args(
            [
                "bootstrap-legacy",
                "--commit-sha",
                _SHA,
                "--confirm",
                f"BOOTSTRAP {_SHA}",
            ]
        )


def _healthy_legacy_payloads() -> tuple[dict[str, object], dict[str, object]]:
    health: dict[str, object] = {
        "schema_version": "karkinos.service_health.v1",
        "service": "karkinos",
        "status": "alive",
        "scope": "process_liveness_only",
        **{field: False for field in bootstrap_legacy._SERVICE_HEALTH_FALSE_FIELDS},
    }
    live: dict[str, object] = {
        "running": True,
        "initialized": True,
        "activation_guarded": True,
    }
    return health, live


def test_legacy_recovery_health_is_initialized_guarded_and_non_authorizing() -> None:
    health, live = _healthy_legacy_payloads()

    assert bootstrap_legacy._legacy_baseline_payload_matches(health, live)
    assert bootstrap_legacy._legacy_payload_matches(
        health,
        live,
        expected_activation_guarded=True,
    )

    for field in bootstrap_legacy._SERVICE_HEALTH_FALSE_FIELDS:
        unsafe = {**health, field: True}
        assert not bootstrap_legacy._legacy_payload_matches(
            unsafe,
            live,
            expected_activation_guarded=True,
        )
    for field in ("running", "initialized"):
        incomplete = {**live, field: False}
        assert not bootstrap_legacy._legacy_payload_matches(
            health,
            incomplete,
            expected_activation_guarded=True,
        )
    assert not bootstrap_legacy._legacy_payload_matches(
        health,
        {**live, "activation_guarded": False},
        expected_activation_guarded=True,
    )


def test_legacy_launchd_health_binds_listener_to_launchd_process_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(tmp_path)
    monkeypatch.setattr(bootstrap_legacy.platform, "system", lambda: "Darwin")
    listener_pid = "4243"
    listener_command = (
        f"{topology.workdir}/.venv/bin/python3 -m server "
        "--host 127.0.0.1 --port 8000"
    )
    change_start_identity = False
    process_calls = 0

    def launchctl_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["/bin/launchctl", "print"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "state = running\n"
                "program = /usr/bin/env\n"
                f"working directory = {topology.workdir}\n"
                "pid = 4242\n"
            ),
            stderr="",
        )

    def listener_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[0] == "/usr/sbin/lsof"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"{listener_pid}\n",
            stderr="",
        )

    def process_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal process_calls
        assert command == [
            "/bin/ps",
            "-ww",
            "-o",
            "pid=,ppid=,pgid=,lstart=,command=",
            "-p",
            f"4242,{listener_pid}",
        ]
        process_calls += 1
        parent_pid = "4242" if listener_pid == "4243" else "1"
        listener_started = (
            "Sun Aug 31 17:25:12 2026"
            if change_start_identity and process_calls % 2 == 0
            else "Sat Aug 30 17:25:12 2026"
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "4242 1 4242 Sat Aug 30 17:25:12 2026 "
                "/opt/homebrew/bin/uv run --frozen python -m server "
                "--host 127.0.0.1 --port 8000\n"
                f"{listener_pid} {parent_pid} 4242 {listener_started} "
                f"{listener_command}\n"
            ),
            stderr="",
        )

    def exact_health(
        port: int,
        timeout: float,
        *,
        expected_activation_guarded: bool | None,
        identity_probe,
    ) -> bool:
        assert port == 8000
        assert timeout in {5, 7}
        assert expected_activation_guarded in {None, True}
        return bool(identity_probe())

    monkeypatch.setattr(bootstrap_legacy, "_legacy_health", exact_health)
    hooks = bootstrap_legacy.legacy_launchd_hooks(
        topology.plist,
        runtime_home=topology.home,
        legacy_workdir=topology.workdir,
        port=8000,
        runner=launchctl_runner,
        listener_runner=listener_runner,
        process_runner=process_runner,
    )

    hooks.preflight()
    assert hooks.health(7) is True

    listener_pid = "9999"
    with pytest.raises(ValueError, match="legacy_service_identity_mismatch"):
        hooks.preflight()
    assert hooks.health(7) is False

    listener_pid = "4243"
    listener_command = (
        f"{topology.workdir}/.venv/bin/python3 -m unknown "
        "--host 127.0.0.1 --port 8000"
    )
    with pytest.raises(ValueError, match="legacy_service_identity_mismatch"):
        hooks.preflight()

    listener_command = (
        f"{topology.workdir}/.venv/bin/python3 -m server "
        "--host 127.0.0.1 --port 8000"
    )
    process_calls = 0
    change_start_identity = True
    with pytest.raises(ValueError, match="legacy_service_identity_mismatch"):
        hooks.preflight()


def test_legacy_recovery_start_uses_temporary_guarded_plist_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(tmp_path)
    monkeypatch.setattr(bootstrap_legacy.platform, "system", lambda: "Darwin")
    original = topology.plist.read_bytes()
    loaded = False
    guarded_environment: dict[str, str] | None = None

    def launchctl_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, guarded_environment
        action = command[1]
        if action == "print":
            return subprocess.CompletedProcess(
                command,
                0 if loaded else 113,
                stdout="pid = 4242\n" if loaded else "",
                stderr="",
            )
        assert action == "bootstrap"
        guarded = Path(command[-1])
        payload = plistlib.loads(guarded.read_bytes())
        guarded_environment = payload["EnvironmentVariables"]
        loaded = True
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    hooks = bootstrap_legacy.legacy_launchd_hooks(
        topology.plist,
        runtime_home=topology.home,
        legacy_workdir=topology.workdir,
        port=8000,
        runner=launchctl_runner,
        listener_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="4242\n",
            stderr="",
        ),
    )

    hooks.start()

    assert guarded_environment is not None
    assert guarded_environment["KARKINOS_HOME"] == str(topology.home)
    assert guarded_environment["KARKINOS_DATA_DIR"] == str(
        topology.workdir / "data" / "store"
    )
    assert guarded_environment["KARKINOS_CONFIG_PATH"] == str(
        topology.workdir / "config.json"
    )
    assert guarded_environment["KARKINOS_ENV_FILE"] == str(topology.workdir / ".env")
    assert topology.plist.read_bytes() == original
    assert not list(topology.plist.parent.glob("*.guarded-*"))


def test_legacy_stop_fails_closed_on_listener_without_loaded_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topology = _topology(tmp_path)
    monkeypatch.setattr(bootstrap_legacy.platform, "system", lambda: "Darwin")

    def unloaded_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[:2] == ["/bin/launchctl", "print"]
        return subprocess.CompletedProcess(command, 113, stdout="", stderr="")

    hooks = bootstrap_legacy.legacy_launchd_hooks(
        topology.plist,
        runtime_home=topology.home,
        legacy_workdir=topology.workdir,
        port=8000,
        runner=unloaded_runner,
        listener_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="7777\n",
            stderr="",
        ),
    )

    with pytest.raises(ValueError, match="legacy_bootstrap_legacy_stop_failed"):
        hooks.stop()


@pytest.mark.skipif(platform.system() != "Darwin", reason="APFS clone is macOS-only")
def test_production_file_clone_is_private_and_byte_exact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(_LIVE_CONFIG)
    source.chmod(0o600)

    bootstrap_legacy.clone_private_file_apfs(source, destination)

    assert destination.read_bytes() == _LIVE_CONFIG
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.stat().st_ino != source.stat().st_ino


@pytest.mark.skipif(platform.system() != "Darwin", reason="APFS clone is macOS-only")
def test_production_file_clone_removes_unsynced_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(_LIVE_CONFIG)
    source.chmod(0o600)

    def fail_sync(_path: Path, _error: str) -> None:
        raise ValueError("injected-clone-sync-failure")

    monkeypatch.setattr(bootstrap_legacy, "_fsync_regular_file", fail_sync)
    with pytest.raises(ValueError, match="injected-clone-sync-failure"):
        bootstrap_legacy.clone_private_file_apfs(source, destination)

    assert not destination.exists()


def test_production_quarantine_removal_does_not_follow_legacy_symlinks(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-private-state"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(_LIVE_DATA)
    quarantine = tmp_path / "legacy-bootstrap-quarantine"
    prod = quarantine / "prod"
    prod.mkdir(parents=True)
    (prod / "external").symlink_to(outside)

    bootstrap_legacy.remove_legacy_quarantine(quarantine)

    assert not quarantine.exists()
    assert sentinel.read_bytes() == _LIVE_DATA
