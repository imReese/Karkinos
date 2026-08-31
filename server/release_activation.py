"""Runtime guard for journaled release activation."""

from __future__ import annotations

import asyncio
import json
import re
import stat
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from server.runtime_paths import resolve_runtime_home

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


RELEASE_ACTIVATION_GUARD_DETAIL = "release_activation_in_progress"
RELEASE_ACTIVATION_JOURNALS = (
    ".release-transaction.json",
    ".legacy-bootstrap-transaction.json",
)
_UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_RELEASE_TRANSACTION_SCHEMA = "karkinos.release_transaction.v2"
_RELEASE_TRANSACTION_KEYS = {
    "schema_version",
    "operation",
    "old_current",
    "old_previous",
    "target",
    "snapshot_id",
    "phase",
}
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SNAPSHOT_ID = re.compile(r"^[0-9a-f]{32}$")
_SCHEDULER_READINESS_PHASE = "readiness"
_LEGACY_TRANSACTION_SCHEMA = "karkinos.legacy_bootstrap_transaction.v1"
_LEGACY_TRANSACTION_KEYS = {
    "schema_version",
    "phase",
    "transaction_id",
    "commit_sha",
    "legacy_workdir",
    "legacy_plist",
    "work_name",
}
_LEGACY_WORK_PREFIX = ".legacy-bootstrap-work-"


def is_release_activation_guarded(home: Path | None = None) -> bool:
    """Return whether a durable activation journal currently blocks side effects."""

    try:
        runtime_home = home if home is not None else resolve_runtime_home()
    except (OSError, RuntimeError):
        return True
    if runtime_home is None:
        return False
    for name in RELEASE_ACTIVATION_JOURNALS:
        try:
            (runtime_home / name).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        return True
    return False


def is_scheduler_release_activation_guarded(home: Path | None = None) -> bool:
    """Block the scheduler except during the journaled readiness phase.

    Unsafe HTTP and all other guarded background work remain blocked until the
    journal is removed. Only a strictly valid standard or legacy bootstrap
    transaction in its explicit readiness phase lets the live scheduler
    complete a readiness iteration before the controller commits it.
    """

    try:
        runtime_home = home if home is not None else resolve_runtime_home()
    except (OSError, RuntimeError):
        return True
    if runtime_home is None:
        return False

    legacy_journal = runtime_home / RELEASE_ACTIVATION_JOURNALS[1]
    legacy_readiness = False
    legacy_exists = False
    try:
        legacy_metadata = legacy_journal.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        return True
    else:
        legacy_exists = True
        if not stat.S_ISREG(legacy_metadata.st_mode):
            return True
        try:
            legacy_payload = json.loads(legacy_journal.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return True
        legacy_readiness = _legacy_scheduler_readiness_payload_valid(legacy_payload)

    journal = runtime_home / RELEASE_ACTIVATION_JOURNALS[0]
    try:
        metadata = journal.lstat()
    except FileNotFoundError:
        return not legacy_readiness if legacy_exists else False
    except OSError:
        return True
    if legacy_exists:
        return True
    if not stat.S_ISREG(metadata.st_mode):
        return True
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    return not _scheduler_readiness_payload_valid(payload)


def _scheduler_readiness_payload_valid(payload: object) -> bool:
    if not isinstance(payload, dict) or set(payload) != _RELEASE_TRANSACTION_KEYS:
        return False
    if payload.get("schema_version") != _RELEASE_TRANSACTION_SCHEMA:
        return False
    if payload.get("operation") not in {"deploy", "rollback", "recover"}:
        return False
    if payload.get("phase") != _SCHEDULER_READINESS_PHASE:
        return False
    if not _valid_optional_sha(payload.get("old_current")) or not _valid_optional_sha(
        payload.get("old_previous")
    ):
        return False
    if payload.get("old_current") is None and payload.get("old_previous") is not None:
        return False
    target = payload.get("target")
    snapshot_id = payload.get("snapshot_id")
    return (
        isinstance(target, str)
        and _FULL_SHA.fullmatch(target) is not None
        and isinstance(snapshot_id, str)
        and _SNAPSHOT_ID.fullmatch(snapshot_id) is not None
    )


def _valid_optional_sha(value: object) -> bool:
    return value is None or (
        isinstance(value, str) and _FULL_SHA.fullmatch(value) is not None
    )


def _legacy_scheduler_readiness_payload_valid(payload: object) -> bool:
    if not isinstance(payload, dict) or set(payload) != _LEGACY_TRANSACTION_KEYS:
        return False
    transaction_id = payload.get("transaction_id")
    commit_sha = payload.get("commit_sha")
    workdir = payload.get("legacy_workdir")
    plist = payload.get("legacy_plist")
    return (
        payload.get("schema_version") == _LEGACY_TRANSACTION_SCHEMA
        and payload.get("phase") == _SCHEDULER_READINESS_PHASE
        and isinstance(transaction_id, str)
        and _SNAPSHOT_ID.fullmatch(transaction_id) is not None
        and isinstance(commit_sha, str)
        and _FULL_SHA.fullmatch(commit_sha) is not None
        and payload.get("work_name") == f"{_LEGACY_WORK_PREFIX}{transaction_id}"
        and isinstance(workdir, str)
        and Path(workdir).is_absolute()
        and isinstance(plist, str)
        and Path(plist).is_absolute()
    )


async def wait_for_release_activation(
    *,
    activation_guarded: Callable[[], bool] = is_release_activation_guarded,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    poll_interval: float = 0.2,
) -> None:
    """Wait until activation commits without requiring a process restart."""

    while _activation_guarded_fail_closed(activation_guarded):
        await sleep(poll_interval)


def _activation_guarded_fail_closed(
    activation_guarded: Callable[[], bool],
) -> bool:
    try:
        return bool(activation_guarded())
    except Exception:
        return True


class ReleaseActivationGuardMiddleware:
    """Reject state-changing HTTP requests during journaled activation."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        activation_guarded: Callable[[], bool] = is_release_activation_guarded,
    ) -> None:
        self.app = app
        self._activation_guarded = activation_guarded

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] == "http"
            and str(scope.get("method") or "").upper() in _UNSAFE_HTTP_METHODS
            and _activation_guarded_fail_closed(self._activation_guarded)
        ):
            response = JSONResponse(
                status_code=503,
                content={"detail": RELEASE_ACTIVATION_GUARD_DETAIL},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
