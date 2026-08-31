"""Content-addressed filesystem adapter for daily strategy backups."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.daily_strategy_artifacts import (
    DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
    DailyStrategyArtifactRejected,
    DailyStrategyBackupMismatch,
    DailyStrategyBackupUnreadable,
)


class DailyStrategyBackupStore:
    """Write and re-verify privacy-minimized local strategy snapshots."""

    def __init__(self, backup_root: str | Path) -> None:
        self._root = Path(backup_root)

    def write(self, payload: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
        market_date = str(payload.get("market_date") or "")
        try:
            date.fromisoformat(market_date)
        except ValueError as exc:
            raise DailyStrategyArtifactRejected("backup_market_date_invalid") from exc
        artifact_fingerprint = content_fingerprint(payload)
        fingerprint_token = artifact_fingerprint.removeprefix("sha256:")
        relative_path = Path(market_date) / f"{fingerprint_token}.json"
        target = self._root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        body = (canonical_json(dict(payload)) + "\n").encode("utf-8")
        if target.exists():
            if target.read_bytes() != body:
                raise DailyStrategyArtifactRejected("daily_backup_content_conflict")
        else:
            self._write_atomic(target, body)
        selection = payload.get("selection")
        selection_id = (
            selection.get("selection_id") if isinstance(selection, Mapping) else None
        )
        backup_id = (
            "ai-shadow-backup-"
            + content_fingerprint(
                {"run_id": payload.get("run_id"), "artifact": artifact_fingerprint}
            ).removeprefix("sha256:")[:24]
        )
        return {
            "schema_version": DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
            "backup_id": backup_id,
            "run_id": payload.get("run_id"),
            "market_date": market_date,
            "selection_id": selection_id,
            "relative_path": relative_path.as_posix(),
            "artifact_fingerprint": artifact_fingerprint,
            "byte_count": len(body),
            "created_at": created_at,
            "verification_status": "verified",
            "contains_private_account_identifiers": False,
            "contains_broker_export_rows": False,
        }

    def project_receipt(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Return a persisted receipt with live file-integrity status."""

        result = dict(record)
        result.update(
            {
                "schema_version": DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
                "verification_status": "unverified",
                "contains_private_account_identifiers": False,
                "contains_broker_export_rows": False,
            }
        )
        try:
            candidate = self.resolve_path(record)
            if not candidate.is_file():
                result["verification_status"] = "missing"
                return result
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                result["verification_status"] = "invalid_payload"
                return result
            if content_fingerprint(payload) != record.get("artifact_fingerprint"):
                result["verification_status"] = "fingerprint_mismatch"
                return result
            if candidate.stat().st_size != int(record["byte_count"]):
                result["verification_status"] = "byte_count_mismatch"
                return result
            selection = payload.get("selection")
            if (
                payload.get("run_id") != record.get("run_id")
                or payload.get("market_date") != record.get("market_date")
                or not isinstance(selection, Mapping)
                or selection.get("selection_id") != record.get("selection_id")
            ):
                result["verification_status"] = "identity_mismatch"
                return result
            result["verification_status"] = "verified"
            return result
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            result["verification_status"] = "read_failed"
            return result

    def load_verified_payload(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            payload = json.loads(self.resolve_path(record).read_text(encoding="utf-8"))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DailyStrategyBackupUnreadable from exc
        if not isinstance(payload, Mapping) or content_fingerprint(
            payload
        ) != record.get("artifact_fingerprint"):
            raise DailyStrategyBackupMismatch
        return payload

    def resolve_path(self, record: Mapping[str, Any]) -> Path:
        candidate = (self._root / str(record["relative_path"])).resolve()
        candidate.relative_to(self._root.resolve())
        return candidate

    @staticmethod
    def _write_atomic(target: Path, body: bytes) -> None:
        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".daily-strategy-", suffix=".tmp", dir=target.parent
            )
            temp_path = Path(temp_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()


__all__ = ["DailyStrategyBackupStore"]
