"""Deterministic no-activity roll-forward for a trusted local statement.

The writer updates only the user-managed canonical CSV.  It does not contact a
broker, mutate the production ledger, create an order, or grant authority.
Generated rows are derived snapshots whose lineage is bound to the unchanged
non-generated statement rows.
"""

from __future__ import annotations

import csv
import hashlib
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from account_truth.broker_statement import (
    BROKER_STATEMENT_OPTIONAL_COLUMNS,
    BROKER_STATEMENT_REQUIRED_COLUMNS,
    BrokerEvidenceEvent,
    parse_broker_statement_csv,
)

DAILY_SNAPSHOT_ROLL_FORWARD_SCHEMA_VERSION = (
    "karkinos.account_truth.daily_snapshot_roll_forward.v1"
)
DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX = "karkinos-daily-roll-forward-"
DAILY_SNAPSHOT_ROLL_FORWARD_NOTE = (
    "Trusted no-activity daily roll-forward from canonical broker statement; "
    "derived snapshot, not a provider capture."
)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_KNOWN_COLUMNS = tuple(
    dict.fromkeys(BROKER_STATEMENT_REQUIRED_COLUMNS + BROKER_STATEMENT_OPTIONAL_COLUMNS)
)

RollForwardStatus = Literal["disabled", "unchanged", "rolled_forward", "blocked"]


@dataclass(frozen=True)
class DailySnapshotRollForwardResult:
    schema_version: str
    status: RollForwardStatus
    run_date: str
    effective_at: str | None
    source_fact_fingerprint: str | None
    output_file_fingerprint: str | None
    base_event_count: int
    generated_cash_snapshot_count: int
    generated_position_snapshot_count: int
    blocker: str | None
    source_kind: str = "trusted_local_statement_no_activity_derivation"
    provider_contacted: bool = False
    production_ledger_mutated: bool = False
    broker_submission_enabled: bool = False
    authorizes_execution: bool = False
    changes_capital_authority: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def roll_forward_daily_broker_statement_for_state(
    *,
    state: Any,
    run_date: str,
) -> DailySnapshotRollForwardResult:
    """Apply the owner-enabled roll-forward using persisted ledger guardrails."""

    config = getattr(
        getattr(state, "config", None),
        "broker_statement_collector",
        None,
    )
    if (
        config is None
        or not getattr(config, "enabled", False)
        or not getattr(config, "daily_snapshot_roll_forward_enabled", False)
    ):
        return _result(status="disabled", run_date=run_date)

    ledger_reader = getattr(getattr(state, "db", None), "get_ledger_entries_sync", None)
    if not callable(ledger_reader):
        return _result(
            status="blocked",
            run_date=run_date,
            blocker="daily_snapshot_roll_forward_ledger_unavailable",
        )
    ledger_entries = list(ledger_reader(limit=5000, offset=0) or [])
    if len(ledger_entries) >= 5000:
        return _result(
            status="blocked",
            run_date=run_date,
            blocker="daily_snapshot_roll_forward_ledger_scope_unbounded",
        )
    return roll_forward_daily_broker_statement(
        path=getattr(config, "path", ""),
        run_date=run_date,
        max_file_bytes=int(getattr(config, "max_file_bytes", 0)),
        ledger_entries=ledger_entries,
    )


def roll_forward_daily_broker_statement(
    *,
    path: str | Path,
    run_date: str,
    max_file_bytes: int,
    ledger_entries: Sequence[dict[str, Any]] = (),
) -> DailySnapshotRollForwardResult:
    """Atomically replace prior derived rows with one deterministic daily set."""

    try:
        target_date = date.fromisoformat(str(run_date))
    except ValueError:
        return _result(
            status="blocked",
            run_date=str(run_date),
            blocker="daily_snapshot_roll_forward_run_date_invalid",
        )
    effective_at = datetime.combine(
        target_date,
        time(hour=8, minute=45),
        tzinfo=_SHANGHAI_TZ,
    )
    statement_path = Path(path).expanduser()
    try:
        before = statement_path.stat()
        if not statement_path.is_file():
            raise OSError
        if before.st_size <= 0 or before.st_size > max_file_bytes:
            return _result(
                status="blocked",
                run_date=run_date,
                effective_at=effective_at,
                blocker="daily_snapshot_roll_forward_file_size_invalid",
            )
        content = statement_path.read_bytes()
        after_read = statement_path.stat()
    except (OSError, ValueError):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_file_unreadable",
        )
    if _file_signature(before) != _file_signature(after_read):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_file_changed_during_read",
        )

    prepared = _prepare_roll_forward(content=content, effective_at=effective_at)
    if isinstance(prepared, DailySnapshotRollForwardResult):
        return prepared
    output, source_fingerprint, base_events, cash_count, position_count = prepared

    ledger_blocker = _ledger_guardrail_blocker(
        ledger_entries=ledger_entries,
        latest_source_event_at=max(_event_timestamp(event) for event in base_events),
        source_modified_at=datetime.fromtimestamp(before.st_mtime, tz=UTC),
    )
    if ledger_blocker is not None:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            source_fact_fingerprint=source_fingerprint,
            base_event_count=len(base_events),
            blocker=ledger_blocker,
        )

    output_fingerprint = hashlib.sha256(output).hexdigest()
    if output == content:
        return _result(
            status="unchanged",
            run_date=run_date,
            effective_at=effective_at,
            source_fact_fingerprint=source_fingerprint,
            output_file_fingerprint=output_fingerprint,
            base_event_count=len(base_events),
            cash_count=cash_count,
            position_count=position_count,
        )

    try:
        current = statement_path.stat()
        if _file_signature(current) != _file_signature(before):
            return _result(
                status="blocked",
                run_date=run_date,
                effective_at=effective_at,
                source_fact_fingerprint=source_fingerprint,
                base_event_count=len(base_events),
                blocker="daily_snapshot_roll_forward_file_changed_before_write",
            )
        _atomic_replace(statement_path, output, mode=before.st_mode & 0o777)
    except OSError:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            source_fact_fingerprint=source_fingerprint,
            base_event_count=len(base_events),
            blocker="daily_snapshot_roll_forward_atomic_write_failed",
        )
    return _result(
        status="rolled_forward",
        run_date=run_date,
        effective_at=effective_at,
        source_fact_fingerprint=source_fingerprint,
        output_file_fingerprint=output_fingerprint,
        base_event_count=len(base_events),
        cash_count=cash_count,
        position_count=position_count,
    )


def _prepare_roll_forward(
    *,
    content: bytes,
    effective_at: datetime,
) -> (
    tuple[bytes, str, list[BrokerEvidenceEvent], int, int]
    | DailySnapshotRollForwardResult
):
    run_date = effective_at.date().isoformat()
    try:
        raw_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_encoding_invalid",
        )
    reader = csv.DictReader(StringIO(raw_text))
    columns = tuple(reader.fieldnames or ())
    if (
        not columns
        or len(columns) != len(set(columns))
        or any(column not in _KNOWN_COLUMNS for column in columns)
        or any(column not in columns for column in BROKER_STATEMENT_REQUIRED_COLUMNS)
    ):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_schema_invalid",
        )

    base_rows: list[dict[str, str]] = []
    for raw_row in reader:
        if None in raw_row:
            return _result(
                status="blocked",
                run_date=run_date,
                effective_at=effective_at,
                blocker="daily_snapshot_roll_forward_row_shape_invalid",
            )
        row = {column: str(raw_row.get(column) or "").strip() for column in columns}
        if row.get("event_id", "").startswith(DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX):
            continue
        base_rows.append(row)
    if not base_rows:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_source_events_missing",
        )

    base_content = _render_rows(columns=columns, rows=base_rows)
    preview = parse_broker_statement_csv(base_content)
    if preview.validation_status != "pass" or len(preview.events) != len(base_rows):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_source_validation_blocked",
        )
    if len({event.event_id for event in preview.events}) != len(preview.events):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_event_identity_conflict",
        )

    try:
        ordered = sorted(
            enumerate(preview.events),
            key=lambda item: (_event_timestamp(item[1]), item[0]),
        )
    except ValueError:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_event_time_invalid",
        )
    if _event_timestamp(ordered[-1][1]) > effective_at:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_source_after_decision_cutoff",
        )
    if any(not _event_decimals_finite(event) for _, event in ordered):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_non_finite_value",
        )

    cash_candidates = [
        (index, event) for index, event in ordered if event.cash_balance is not None
    ]
    if not cash_candidates:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_cash_anchor_missing",
        )
    cash_anchor_index, cash_anchor = cash_candidates[-1]
    cash_balance = cash_anchor.cash_balance
    assert cash_balance is not None
    anchor_key = (_event_timestamp(cash_anchor), cash_anchor_index)
    for index, event in ordered:
        if (_event_timestamp(event), index) > anchor_key and event.event_type not in {
            "cash_snapshot",
            "position_snapshot",
        }:
            cash_balance += event.net_amount
    if not cash_balance.is_finite():
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_cash_invalid",
        )

    latest_by_symbol: dict[str, BrokerEvidenceEvent] = {}
    for _, event in ordered:
        if event.symbol:
            latest_by_symbol[event.symbol] = event
    if not latest_by_symbol:
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_position_scope_missing",
        )
    if any(
        event.position_quantity is None
        or event.cost_basis is None
        or not event.instrument_name
        or not event.asset_class
        or not event.currency
        for event in latest_by_symbol.values()
    ):
        return _result(
            status="blocked",
            run_date=run_date,
            effective_at=effective_at,
            blocker="daily_snapshot_roll_forward_position_state_incomplete",
        )

    source_fingerprint = hashlib.sha256(base_content).hexdigest()
    timestamp = effective_at.isoformat()
    generated_rows = [
        _snapshot_row(
            columns=columns,
            event_id=(
                f"{DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX}"
                f"{run_date.replace('-', '')}-cash-{source_fingerprint[:12]}"
            ),
            event_type="cash_snapshot",
            occurred_at=timestamp,
            settled_at=run_date,
            currency=cash_anchor.currency,
            cash_balance=_decimal_text(cash_balance),
        )
    ]
    for symbol, event in sorted(latest_by_symbol.items()):
        symbol_fingerprint = hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:12]
        generated_rows.append(
            _snapshot_row(
                columns=columns,
                event_id=(
                    f"{DAILY_SNAPSHOT_ROLL_FORWARD_EVENT_PREFIX}"
                    f"{run_date.replace('-', '')}-position-{symbol_fingerprint}-"
                    f"{source_fingerprint[:12]}"
                ),
                event_type="position_snapshot",
                occurred_at=timestamp,
                settled_at=run_date,
                symbol=symbol,
                instrument_name=event.instrument_name,
                asset_class=event.asset_class,
                currency=event.currency,
                price=_decimal_text(event.price),
                position_quantity=_decimal_text(event.position_quantity),
                cost_basis=_decimal_text(event.cost_basis),
                cost_basis_method=event.cost_basis_method,
            )
        )
    output = _render_rows(columns=columns, rows=[*base_rows, *generated_rows])
    return output, source_fingerprint, preview.events, 1, len(latest_by_symbol)


def _snapshot_row(
    *,
    columns: tuple[str, ...],
    event_id: str,
    event_type: str,
    occurred_at: str,
    settled_at: str,
    currency: str,
    symbol: str = "",
    instrument_name: str = "",
    asset_class: str = "",
    price: str = "0",
    cash_balance: str = "",
    position_quantity: str = "",
    cost_basis: str = "",
    cost_basis_method: str = "",
) -> dict[str, str]:
    row = {column: "" for column in columns}
    row.update(
        {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "settled_at": settled_at,
            "symbol": symbol,
            "instrument_name": instrument_name,
            "asset_class": asset_class,
            "currency": currency,
            "quantity": "0",
            "price": price,
            "gross_amount": "0",
            "fee": "0",
            "tax": "0",
            "net_amount": "0",
            "cash_balance": cash_balance,
            "position_quantity": position_quantity,
            "cost_basis": cost_basis,
            "note": DAILY_SNAPSHOT_ROLL_FORWARD_NOTE,
        }
    )
    if "cost_basis_method" in row:
        row["cost_basis_method"] = cost_basis_method
    if "transfer_fee" in row:
        row["transfer_fee"] = "0"
    return row


def _ledger_guardrail_blocker(
    *,
    ledger_entries: Sequence[dict[str, Any]],
    latest_source_event_at: datetime,
    source_modified_at: datetime,
) -> str | None:
    latest_event_at: datetime | None = None
    latest_created_at: datetime | None = None
    for row in ledger_entries:
        if not isinstance(row, dict):
            return "daily_snapshot_roll_forward_ledger_record_invalid"
        try:
            event_at = _ledger_timestamp(row.get("timestamp"))
            created_at = _ledger_timestamp(row.get("created_at"))
        except ValueError:
            return "daily_snapshot_roll_forward_ledger_record_invalid"
        latest_event_at = (
            max(latest_event_at, event_at) if latest_event_at else event_at
        )
        latest_created_at = (
            max(latest_created_at, created_at) if latest_created_at else created_at
        )
    if latest_event_at is not None and latest_event_at > latest_source_event_at:
        return "daily_snapshot_roll_forward_source_predates_latest_ledger_event"
    if latest_created_at is not None and latest_created_at > source_modified_at:
        return "daily_snapshot_roll_forward_source_predates_latest_ledger_revision"
    return None


def _event_timestamp(event: BrokerEvidenceEvent) -> datetime:
    return _aware_timestamp(event.occurred_at)


def _aware_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed


def _ledger_timestamp(value: object) -> datetime:
    """Match canonical ledger legacy semantics for timezone-naive rows."""

    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("invalid ledger timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed


def _event_decimals_finite(event: BrokerEvidenceEvent) -> bool:
    values = (
        event.quantity,
        event.price,
        event.gross_amount,
        event.fee,
        event.tax,
        event.net_amount,
        event.transfer_fee,
        event.cash_balance,
        event.position_quantity,
        event.cost_basis,
    )
    return all(value is None or value.is_finite() for value in values)


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def _render_rows(*, columns: tuple[str, ...], rows: Sequence[dict[str, str]]) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _atomic_replace(path: Path, content: bytes, *, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode or 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _file_signature(stat_result: os.stat_result) -> tuple[int, int, int]:
    return stat_result.st_mtime_ns, stat_result.st_size, stat_result.st_ino


def _result(
    *,
    status: RollForwardStatus,
    run_date: str,
    effective_at: datetime | None = None,
    source_fact_fingerprint: str | None = None,
    output_file_fingerprint: str | None = None,
    base_event_count: int = 0,
    cash_count: int = 0,
    position_count: int = 0,
    blocker: str | None = None,
) -> DailySnapshotRollForwardResult:
    return DailySnapshotRollForwardResult(
        schema_version=DAILY_SNAPSHOT_ROLL_FORWARD_SCHEMA_VERSION,
        status=status,
        run_date=run_date,
        effective_at=effective_at.isoformat() if effective_at else None,
        source_fact_fingerprint=source_fact_fingerprint,
        output_file_fingerprint=output_file_fingerprint,
        base_event_count=base_event_count,
        generated_cash_snapshot_count=cash_count,
        generated_position_snapshot_count=position_count,
        blocker=blocker,
    )
