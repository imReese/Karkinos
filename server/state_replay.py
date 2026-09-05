"""Provider-free migration/read/restart verification on a disposable state clone."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from server.contracts.jobs import job_time
from server.persistence.jobs import SQLiteJobStore
from server.persistence.valuation_publication_recovery import unresolved_publications
from server.projections.system_readiness import build_system_readiness
from server.projections.valuation_snapshot import (
    ledger_identity_from_rows,
    valuation_snapshot_from_row,
)
from server.runtime_paths import resolve_data_dir, resolve_runtime_home
from server.state_preflight import preflight_persistent_state


def _published(path: Path):
    if not path.exists():
        return None
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"valuation_snapshots", "runtime_controls"}.issubset(tables):
            return None
        row = conn.execute(
            "SELECT s.* FROM valuation_snapshots s JOIN runtime_controls c "
            "ON s.snapshot_id=json_extract(c.value_json,'$.snapshot_id') "
            "WHERE c.key='valuation_snapshot_publication' AND json_extract(c.value_json,'$.status')='ready'"
        ).fetchone()
        return valuation_snapshot_from_row(dict(row)) if row else None


def _ledger_identity(path: Path):
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        conn.row_factory = sqlite3.Row
        return ledger_identity_from_rows(
            [
                dict(row)
                for row in conn.execute("SELECT * FROM ledger_entries ORDER BY id")
            ]
        )


def _incidents(path: Path):
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        return unresolved_publications(conn)


def _require_isolated_clone():
    from server.release_activation import is_release_activation_guarded

    root = resolve_runtime_home()
    data = Path(resolve_data_dir())
    if (
        os.environ.get("KARKINOS_STATE_CLONE") != "1"
        or root is None
        or not is_release_activation_guarded()
    ):
        raise ValueError("state_replay_isolated_clone_required")
    root = Path(os.environ["KARKINOS_HOME"]).expanduser()
    marker = root / ".state-clone.json"
    if root.is_symlink() or data.is_symlink() or marker.is_symlink():
        raise ValueError("state_replay_clone_symlink_rejected")
    if (
        root.resolve().parent != Path(tempfile.gettempdir()).resolve()
        or not root.name.startswith("karkinos-state-clone-")
        or data.resolve() != root.resolve() / "candidate"
    ):
        raise ValueError("state_replay_clone_path_invalid")
    evidence = json.loads(marker.read_text())
    if (
        evidence
        != {
            "schema_version": 1,
            "token": os.environ.get("KARKINOS_STATE_CLONE_TOKEN"),
            "data_dir": str(data.resolve()),
            "device": data.stat().st_dev,
            "inode": data.stat().st_ino,
        }
        or not evidence["token"]
    ):
        raise ValueError("state_replay_clone_identity_invalid")
    if any(
        path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1)
        for path in data.rglob("*")
    ):
        raise ValueError("state_replay_clone_external_file_rejected")


def replay_persistent_state(app_factory):
    _require_isolated_clone()
    network_attempts = []

    def reject_network(*args, **kwargs):
        network_attempts.append(True)
        raise RuntimeError("state_replay_network_forbidden")

    with (
        patch.object(socket.socket, "connect", reject_network),
        patch.object(socket.socket, "connect_ex", reject_network),
        patch.object(socket, "getaddrinfo", reject_network),
    ):
        result = _replay(app_factory)
    if network_attempts:
        raise ValueError("state_replay_attempted_network_contact")
    return {
        **result,
        "python_socket_attempts": 0,
        "network_detection_scope": "current_interpreter_python_socket_hooks",
    }


def _replay(app_factory):
    path = Path(resolve_data_dir()) / "app.db"
    before = _published(path)
    ledger_before = _ledger_identity(path)
    incidents_before = _incidents(path)
    preflight_persistent_state()
    after = _published(path)
    if before is not None and after != before:
        raise ValueError("state_replay_last_good_changed")
    # Exercise the durable-worker database boundary without constructing providers.
    now = datetime.now(timezone.utc)
    jobs = SQLiteJobStore(path)
    queued = jobs.enqueue("state_clone_probe", {"at": job_time(now)}, now=now)
    claimed = jobs.claim("state_clone_probe", "state-clone-gate", now=now)
    if claimed is None or claimed.job_id != queued.job_id:
        raise ValueError("state_replay_worker_claim_failed")
    jobs.finish(claimed.lease, now=now, result_ref="state-clone:verified")
    from fastapi.testclient import TestClient

    with (
        TestClient(app_factory()) as client,
        closing(sqlite3.connect(path)) as observer,
    ):
        started_publication = _published(path)
        read_version = observer.execute("PRAGMA data_version").fetchone()[0]
        for endpoint in ("/api/health", "/api/health/readiness"):
            response = client.get(endpoint)
            if response.status_code != 200:
                raise ValueError("state_replay_api_read_failed")
        # Missing evidence must produce the explicit blocked read, too.
        for endpoint in ("/api/portfolio", "/api/portfolio/overview"):
            response = client.get(endpoint)
            if started_publication is None:
                if response.status_code != 503 or not isinstance(
                    response.json().get("detail"), str
                ):
                    raise ValueError("state_replay_missing_evidence_not_blocked")
                continue
            if response.status_code != 200:
                raise ValueError("state_replay_financial_read_failed")
            body = response.json()
            if (
                body.get("valuation_snapshot_id") != started_publication["snapshot_id"]
                or body.get("ledger_cutoff_id")
                != started_publication["ledger_cutoff_id"]
            ):
                raise ValueError("state_replay_financial_read_identity_mismatch")
        if observer.execute("PRAGMA data_version").fetchone()[0] != read_version:
            raise ValueError("state_replay_read_mutated_database")
    if after is not None and _published(path) != after:
        raise ValueError("state_replay_restart_changed_publication")
    if _ledger_identity(path) != ledger_before:
        raise ValueError("state_replay_ledger_changed")
    if _incidents(path) != incidents_before:
        raise ValueError("state_replay_incidents_changed")
    readiness = build_system_readiness(path, now=now)
    if (
        started_publication is not None
        and readiness["subsystems"]["valuation_read"]["status"] == "unavailable"
    ):
        raise ValueError("state_replay_published_read_unavailable")
    return {
        "schema_version": "karkinos.state_clone_replay.v1",
        "status": "passed",
        "migration": "passed",
        "last_good_read": "passed" if after else "no_publication",
        "current_publication_read": "passed" if started_publication else "unavailable",
        "valuation_blockers": readiness["subsystems"]["valuation_read"]["blockers"],
        "financial_readiness_claimed": False,
        "durable_job_roundtrip": "passed",
        "application_start_read_stop": "passed",
        "read_transport": "in_process_asgi",
        "read_database_writes": False,
        "read_database_scope": "app.db",
        "ledger_preserved": True,
        "unresolved_incidents_preserved": True,
    }
