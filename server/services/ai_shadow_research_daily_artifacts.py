"""Compatibility facade for deterministic daily strategy artifacts.

The public service surface stays stable while pure selection, SQLite ownership,
and content-addressed file storage live in their dedicated layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from server.contracts.daily_strategy_artifacts import (
    DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
    DAILY_STRATEGY_BACKUP_SCHEMA,
    DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA,
    DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA,
    DAILY_STRATEGY_SELECTION_SCHEMA,
    DailyStrategyArtifactRejected,
    DailyStrategyBackupMismatch,
    DailyStrategyBackupUnreadable,
)
from server.persistence.daily_strategy_artifacts import (
    DailyStrategyArtifactRepository,
)
from server.persistence.daily_strategy_backups import DailyStrategyBackupStore
from server.projections.daily_strategy_artifacts import (
    build_daily_strategy_backup_payload,
    build_daily_strategy_promotion_binding,
    build_daily_strategy_selection,
    build_verified_winner_operating_constraints,
    build_verified_winner_strategy,
    selection_from_record,
)


class DailyStrategyArtifactStore:
    """Coordinate pure projections with SQLite and filesystem repositories."""

    def __init__(self, db_path: str | Path, backup_root: str | Path) -> None:
        self._backups = DailyStrategyBackupStore(backup_root)
        self._repository = DailyStrategyArtifactRepository(
            db_path,
            backup_store=self._backups,
        )

    def init(self) -> None:
        self._repository.init()

    def record_daily_artifacts(
        self,
        *,
        run: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        drafts: Sequence[Mapping[str, Any]],
        expected_candidate_count: int,
        run_status: str,
        created_at: str,
    ) -> dict[str, Any]:
        """Select, back up, and atomically record one daily research outcome."""

        self.init()
        selection = build_daily_strategy_selection(
            run=run,
            candidates=candidates,
            expected_candidate_count=expected_candidate_count,
            created_at=created_at,
        )
        payload = build_daily_strategy_backup_payload(
            run=run,
            run_status=run_status,
            candidates=candidates,
            drafts=drafts,
            selection=selection,
            created_at=created_at,
        )
        receipt = self._backups.write(payload, created_at=created_at)
        persisted = self._repository.record(
            selection=selection,
            receipt=receipt,
            created_at=created_at,
        )
        if not persisted["reused"]:
            return {"selection": selection, "backup": receipt, "reused": False}
        return {
            "selection": selection_from_record(persisted["selection_record"]),
            "backup": self._backups.project_receipt(persisted["backup_record"]),
            "reused": True,
        }

    def list_selections(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            selection_from_record(record)
            for record in self._repository.list_selection_records(limit=limit)
        ]

    def list_backups(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self._backups.project_receipt(record)
            for record in self._repository.list_backup_records(limit=limit)
        ]

    def list_superseded_selections(self, limit: int = 20) -> list[dict[str, Any]]:
        records = self._repository.list_selection_records(
            limit=limit,
            superseded=True,
        )
        return [
            {
                **selection_from_record(record),
                "superseded_by_run_id": record["superseded_by_run_id"],
                "superseded_at": record["superseded_at"],
            }
            for record in records
        ]

    def list_superseded_backups(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            self._backups.project_receipt(record)
            for record in self._repository.list_backup_records(
                limit=limit,
                superseded=True,
            )
        ]

    def load_latest_verified_research_artifacts(self) -> dict[str, Any]:
        """Read the latest selection and exact backup without requiring promotion."""

        records = self._repository.list_selection_records(limit=1)
        if not records:
            raise DailyStrategyArtifactRejected("daily_research_selection_missing")
        run_id = str(records[0].get("run_id") or "")
        selection_record, backup_record = self._repository.current_pair(run_id=run_id)
        if selection_record is None or backup_record is None:
            raise DailyStrategyArtifactRejected(
                "daily_research_selection_or_backup_missing"
            )
        selection = selection_from_record(selection_record)
        if selection.get("integrity_status") != "verified":
            raise DailyStrategyArtifactRejected(
                "daily_research_selection_fingerprint_mismatch"
            )
        backup = self._backups.project_receipt(backup_record)
        if backup.get("verification_status") != "verified":
            raise DailyStrategyArtifactRejected("daily_research_backup_not_verified")
        payload = self._load_verified_payload(
            backup_record,
            unreadable_error="daily_research_backup_unreadable",
            mismatch_error="daily_research_backup_mismatch",
        )
        payload_selection = payload.get("selection")
        expected_selection = dict(selection)
        expected_selection.pop("integrity_status", None)
        if (
            not isinstance(payload_selection, Mapping)
            or dict(payload_selection) != expected_selection
        ):
            raise DailyStrategyArtifactRejected(
                "daily_research_selection_backup_binding_mismatch"
            )
        return {
            "selection": selection,
            "backup": backup,
            "payload": dict(payload),
        }

    def require_verified_winner(
        self, *, candidate_id: str, run_id: str
    ) -> dict[str, Any]:
        """Require the exact daily winner and its untampered local backup."""

        selection_record, backup_record = self._repository.current_pair(run_id=run_id)
        if selection_record is None or backup_record is None:
            raise DailyStrategyArtifactRejected("daily_selection_or_backup_missing")
        selection = selection_from_record(selection_record)
        if (
            selection.get("integrity_status") != "verified"
            or selection.get("status") != "winner_selected"
            or selection.get("winner_candidate_id") != candidate_id
        ):
            raise DailyStrategyArtifactRejected(
                "candidate_is_not_verified_daily_winner"
            )
        backup = self._backups.project_receipt(backup_record)
        if backup.get("verification_status") != "verified":
            raise DailyStrategyArtifactRejected("daily_strategy_backup_not_verified")
        payload = self._load_verified_payload(
            backup_record,
            unreadable_error="daily_strategy_operating_constraints_unreadable",
            mismatch_error="daily_strategy_operating_constraints_backup_mismatch",
        )
        operating_constraints = build_verified_winner_operating_constraints(
            payload=payload,
            backup_record=backup_record,
            candidate_id=candidate_id,
        )
        return {
            "selection": selection,
            "backup": backup,
            "operating_constraints": operating_constraints,
        }

    def load_verified_winner_strategy(
        self,
        *,
        candidate_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Load the exact frozen Formula DSL snapshot selected for promotion."""

        verified = self.require_verified_winner(
            candidate_id=candidate_id,
            run_id=run_id,
        )
        backup_record = self._repository.backup_record(run_id=run_id)
        if backup_record is None:
            raise DailyStrategyArtifactRejected("daily_strategy_backup_missing")
        payload = self._load_verified_payload(
            backup_record,
            unreadable_error="daily_strategy_snapshot_unreadable",
            mismatch_error="daily_strategy_snapshot_backup_mismatch",
        )
        return build_verified_winner_strategy(
            payload=payload,
            candidate_id=candidate_id,
            run_id=run_id,
            selection=verified["selection"],
            backup=verified["backup"],
            operating_constraints=verified["operating_constraints"],
        )

    def _write_backup(
        self, payload: Mapping[str, Any], *, created_at: str
    ) -> dict[str, Any]:
        """Compatibility shim for legacy fixture setup; use record in production."""

        return self._backups.write(payload, created_at=created_at)

    def _load_verified_payload(
        self,
        record: Mapping[str, Any],
        *,
        unreadable_error: str,
        mismatch_error: str,
    ) -> Mapping[str, Any]:
        try:
            return self._backups.load_verified_payload(record)
        except DailyStrategyBackupUnreadable as exc:
            raise DailyStrategyArtifactRejected(unreadable_error) from exc
        except DailyStrategyBackupMismatch as exc:
            raise DailyStrategyArtifactRejected(mismatch_error) from exc


__all__ = [
    "DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA",
    "DAILY_STRATEGY_BACKUP_SCHEMA",
    "DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA",
    "DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA",
    "DAILY_STRATEGY_SELECTION_SCHEMA",
    "DailyStrategyArtifactRejected",
    "DailyStrategyArtifactStore",
    "build_daily_strategy_promotion_binding",
    "build_daily_strategy_selection",
]
