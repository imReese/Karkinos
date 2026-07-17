"""Explicitly enabled, read-only local broker-statement collection.

The collector watches one user-configured local CSV, waits for a stable file
signature, validates the complete file, and stages broker evidence by content
fingerprint.  It never writes the production ledger or contacts a provider.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv

LOCAL_BROKER_STATEMENT_COLLECTOR_SCHEMA_VERSION = (
    "karkinos.account_truth.local_broker_statement_collector.v1"
)
LOCAL_FILE_EVIDENCE_LIMITATION = (
    "Local-file collection stages user-managed evidence; independent broker "
    "confirmation remains a separate review decision."
)

CollectorState = Literal[
    "disabled",
    "waiting_for_file",
    "pending_stability",
    "imported",
    "unchanged",
    "blocked",
    "error",
]


@dataclass(frozen=True)
class LocalBrokerStatementCollectorStatus:
    schema_version: str
    enabled: bool
    state: CollectorState
    configured_path: str
    source_name: str
    file_present: bool
    poll_interval_seconds: float
    stability_delay_seconds: float
    max_file_bytes: int
    last_observed_at: str | None = None
    last_processed_at: str | None = None
    last_success_at: str | None = None
    file_fingerprint: str | None = None
    import_run_id: str | None = None
    validation_status: str | None = None
    row_count: int | None = None
    valid_row_count: int | None = None
    invalid_row_count: int | None = None
    duplicate_row_count: int | None = None
    error_code: str | None = None
    message: str = ""
    source_kind: str = "local_file_readonly"
    does_not_mutate_production_ledger: bool = True
    does_not_contact_provider: bool = True
    does_not_change_execution_authority: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LocalBrokerStatementCollector:
    """Poll one local CSV and stage only complete, deterministic evidence."""

    def __init__(
        self,
        *,
        repository: BrokerEvidenceRepository | None,
        path: str | Path,
        enabled: bool,
        poll_interval_seconds: float,
        stability_delay_seconds: float,
        max_file_bytes: int,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        configured_path = str(path)
        self._path = Path(path).expanduser()
        self._repository = repository
        self._enabled = enabled
        self._poll_interval_seconds = poll_interval_seconds
        self._stability_delay_seconds = stability_delay_seconds
        self._max_file_bytes = max_file_bytes
        self._monotonic_clock = monotonic_clock
        self._utc_now = utc_now
        self._candidate_signature: tuple[int, int] | None = None
        self._candidate_first_seen: float | None = None
        self._processed_fingerprint: str | None = None
        self._status = LocalBrokerStatementCollectorStatus(
            schema_version=LOCAL_BROKER_STATEMENT_COLLECTOR_SCHEMA_VERSION,
            enabled=enabled,
            state="waiting_for_file" if enabled else "disabled",
            configured_path=configured_path,
            source_name=self._path.name,
            file_present=self._path.is_file() if enabled else False,
            poll_interval_seconds=poll_interval_seconds,
            stability_delay_seconds=stability_delay_seconds,
            max_file_bytes=max_file_bytes,
            message=(
                "Waiting for a stable local broker statement."
                if enabled
                else "Local broker-statement collection is disabled."
            ),
        )

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval_seconds

    def status(self) -> LocalBrokerStatementCollectorStatus:
        return self._status

    def collect_once(
        self,
        *,
        observed_monotonic: float | None = None,
    ) -> LocalBrokerStatementCollectorStatus:
        """Observe once; stage only after the file is unchanged for the delay."""

        if not self._enabled:
            return self._status

        observed_at = self._timestamp()
        observed_monotonic = (
            self._monotonic_clock()
            if observed_monotonic is None
            else observed_monotonic
        )
        try:
            before = self._path.stat()
        except FileNotFoundError:
            self._candidate_signature = None
            self._candidate_first_seen = None
            self._status = replace(
                self._status,
                state="waiting_for_file",
                file_present=False,
                last_observed_at=observed_at,
                error_code=None,
                message="Configured broker statement is not present.",
            )
            return self._status
        except OSError:
            return self._record_error(
                observed_at=observed_at,
                code="statement_stat_failed",
                message="Configured broker statement metadata could not be read.",
            )

        signature = (before.st_mtime_ns, before.st_size)
        if signature != self._candidate_signature:
            self._candidate_signature = signature
            self._candidate_first_seen = observed_monotonic
            self._status = replace(
                self._status,
                state="pending_stability",
                file_present=True,
                last_observed_at=observed_at,
                error_code=None,
                message="Broker statement changed; waiting for a stable complete file.",
            )
            return self._status

        first_seen = self._candidate_first_seen
        if first_seen is None or (
            observed_monotonic - first_seen < self._stability_delay_seconds
        ):
            self._status = replace(
                self._status,
                state="pending_stability",
                file_present=True,
                last_observed_at=observed_at,
                error_code=None,
                message="Broker statement is still inside the stability window.",
            )
            return self._status

        if before.st_size > self._max_file_bytes:
            self._status = replace(
                self._status,
                state="blocked",
                file_present=True,
                last_observed_at=observed_at,
                last_processed_at=observed_at,
                error_code="statement_too_large",
                message="Broker statement exceeds the configured read-only size limit.",
            )
            return self._status

        try:
            content = self._path.read_bytes()
            after = self._path.stat()
        except FileNotFoundError:
            self._candidate_signature = None
            self._candidate_first_seen = None
            self._status = replace(
                self._status,
                state="waiting_for_file",
                file_present=False,
                last_observed_at=observed_at,
                error_code=None,
                message="Broker statement disappeared before a complete read.",
            )
            return self._status
        except OSError:
            return self._record_error(
                observed_at=observed_at,
                code="statement_read_failed",
                message="Configured broker statement could not be read.",
            )

        after_signature = (after.st_mtime_ns, after.st_size)
        if signature != after_signature or len(content) != after.st_size:
            self._candidate_signature = after_signature
            self._candidate_first_seen = observed_monotonic
            self._status = replace(
                self._status,
                state="pending_stability",
                file_present=True,
                last_observed_at=observed_at,
                error_code=None,
                message="Broker statement changed during read; no evidence was staged.",
            )
            return self._status

        try:
            preview = parse_broker_statement_csv(content)
            preview = replace(
                preview,
                limitations=list(
                    dict.fromkeys(
                        [*preview.limitations, LOCAL_FILE_EVIDENCE_LIMITATION]
                    )
                ),
            )
            if preview.file_fingerprint == self._processed_fingerprint:
                self._status = replace(
                    self._status,
                    state=(
                        "blocked"
                        if self._status.validation_status == "blocked"
                        else "unchanged"
                    ),
                    file_present=True,
                    last_observed_at=observed_at,
                    error_code=None,
                    message="Broker statement fingerprint is unchanged; no new run was created.",
                )
                return self._status

            if self._repository is None:
                return self._record_error(
                    observed_at=observed_at,
                    code="collector_repository_missing",
                    message="Broker evidence repository is unavailable.",
                )

            import_run = self._repository.save_preview(
                preview,
                source_name=f"local-file:{self._path.name}",
            )
        except UnicodeDecodeError:
            return self._record_error(
                observed_at=observed_at,
                code="statement_not_utf8",
                message="Broker statement must be UTF-8 or UTF-8 with BOM.",
                state="blocked",
            )
        except Exception:
            return self._record_error(
                observed_at=observed_at,
                code="statement_stage_failed",
                message="Broker statement validation or evidence staging failed.",
            )

        self._processed_fingerprint = preview.file_fingerprint
        blocked = preview.validation_status == "blocked"
        self._status = replace(
            self._status,
            state="blocked" if blocked else "imported",
            file_present=True,
            last_observed_at=observed_at,
            last_processed_at=observed_at,
            last_success_at=(self._status.last_success_at if blocked else observed_at),
            file_fingerprint=preview.file_fingerprint,
            import_run_id=import_run.import_run_id,
            validation_status=preview.validation_status,
            row_count=preview.row_count,
            valid_row_count=preview.valid_row_count,
            invalid_row_count=preview.invalid_row_count,
            duplicate_row_count=preview.duplicate_row_count,
            error_code=("statement_validation_blocked" if blocked else None),
            message=(
                "Broker statement validation blocked; production ledger is unchanged."
                if blocked
                else "Broker statement evidence was staged and is ready for reconciliation review."
            ),
        )
        return self._status

    def _record_error(
        self,
        *,
        observed_at: str,
        code: str,
        message: str,
        state: CollectorState = "error",
    ) -> LocalBrokerStatementCollectorStatus:
        self._status = replace(
            self._status,
            state=state,
            file_present=self._path.is_file(),
            last_observed_at=observed_at,
            last_processed_at=observed_at,
            error_code=code,
            message=message,
        )
        return self._status

    def _timestamp(self) -> str:
        return self._utc_now().astimezone(UTC).isoformat()


async def run_local_broker_statement_collector(
    collector: LocalBrokerStatementCollector,
) -> None:
    """Run until application shutdown; collection errors stay fail-closed."""

    while True:
        collector.collect_once()
        await asyncio.sleep(collector.poll_interval_seconds)
