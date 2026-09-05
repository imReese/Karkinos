"""Immutable PIT daily datasets: Parquet bytes, SQLite manifests, explicit reads."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA_VERSION = "karkinos.pit_daily.v1"
PIT_POLICY = "source_available_at_lte_cutoff.v1"
_COMMON_FIELDS = [
    (name, pa.string())
    for name in (
        "symbol",
        "instrument_type",
        "session_date",
        "source_revision",
        "availability_evidence_ref",
        "event_time",
        "available_at",
        "captured_at",
    )
] + [("suspended", pa.bool_())]
_SCHEMAS = {
    "universe": pa.schema(
        _COMMON_FIELDS
        + [
            (name, pa.string())
            for name in ("membership_status", "listed_on", "delisted_on")
        ]
    ),
    "daily": pa.schema(
        _COMMON_FIELDS
        + [
            (name, pa.float64())
            for name in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "adjustment_factor",
            )
        ]
    ),
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("dataset_timestamp_requires_timezone")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class DatasetRef:
    dataset_id: str
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class DatasetManifest:
    ref: DatasetRef
    universe_identity: str
    start: str
    end: str
    frequency: str
    pit_policy: str
    cutoff: str
    source_revisions: tuple[str, ...]
    row_counts: dict[str, int]
    partitions: dict[str, str]
    quality: dict[str, Any]
    published_at: str


class DatasetCatalog:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "catalog" / "catalog.db"

    def publish_daily(
        self,
        *,
        universe: Iterable[dict[str, Any]],
        daily: Iterable[dict[str, Any]],
        cutoff: str,
        expected_sessions: Iterable[str],
        published_at: str,
    ) -> DatasetManifest:
        """Publish only a complete, explicitly scoped input; never fetch or infer rows."""
        cutoff_instant = _instant(cutoff)
        if _instant(published_at) < cutoff_instant:
            raise ValueError("dataset_publication_precedes_cutoff")
        sessions = sorted(set(expected_sessions))
        if not sessions or any(
            date.fromisoformat(day).isoformat() != day for day in sessions
        ):
            raise ValueError("dataset_sessions_invalid")
        universe_rows = _normalize(universe, cutoff_instant, universe=True)
        daily_rows = _normalize(daily, cutoff_instant, universe=False)
        if any(
            _instant(row["captured_at"]) > _instant(published_at)
            for row in universe_rows + daily_rows
        ):
            raise ValueError("dataset_capture_after_publication")
        if not universe_rows or not daily_rows:
            raise ValueError("dataset_empty")
        if sorted({row["session_date"] for row in universe_rows}) != sessions:
            raise ValueError("dataset_universe_session_coverage_incomplete")
        membership = {_key(row): row for row in universe_rows}
        bars = {_key(row): row for row in daily_rows}
        if set(bars) != set(membership):
            raise ValueError("dataset_daily_universe_coverage_mismatch")
        for key, row in bars.items():
            if row["suspended"] != membership[key]["suspended"]:
                raise ValueError("dataset_tradability_conflict")
        tables = {
            "universe": pa.Table.from_pylist(
                universe_rows, schema=_SCHEMAS["universe"]
            ),
            "daily": pa.Table.from_pylist(daily_rows, schema=_SCHEMAS["daily"]),
        }
        partitions = {
            name: self._write_partition(table) for name, table in tables.items()
        }
        identity = {
            "schema_version": SCHEMA_VERSION,
            "universe_identity": partitions["universe"],
            "start": sessions[0],
            "end": sessions[-1],
            "frequency": "1d",
            "pit_policy": PIT_POLICY,
            "cutoff": cutoff_instant.isoformat(),
            "source_revisions": sorted(
                {r["source_revision"] for r in universe_rows + daily_rows}
            ),
            "row_counts": {name: table.num_rows for name, table in tables.items()},
            "partitions": partitions,
            "quality": {
                "status": "complete",
                "expected_sessions": sessions,
                "availability_provenance": "input_evidence_refs",
                "provider_coverage_verified": False,
            },
        }
        dataset_id = _digest(_json(identity).encode())
        payload = {
            "ref": asdict(DatasetRef(dataset_id)),
            **{k: v for k, v in identity.items() if k != "schema_version"},
            "published_at": published_at,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dataset_manifests(dataset_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS dataset_current(kind TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES dataset_manifests(dataset_id))"
            )
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT manifest_json FROM dataset_manifests WHERE dataset_id=?",
                (dataset_id,),
            ).fetchone()
            if existing:
                stored = json.loads(existing[0])
                if {k: v for k, v in stored.items() if k != "published_at"} != {
                    k: v for k, v in payload.items() if k != "published_at"
                }:
                    raise ValueError("dataset_manifest_identity_conflict")
                payload = stored
            else:
                conn.execute(
                    "INSERT INTO dataset_manifests VALUES (?,?)",
                    (dataset_id, _json(payload)),
                )
            conn.execute(
                "INSERT INTO dataset_current VALUES ('pit_daily',?) ON CONFLICT(kind) DO UPDATE SET dataset_id=excluded.dataset_id",
                (dataset_id,),
            )
            conn.commit()
        return _manifest(payload)

    def get(self, ref: DatasetRef) -> DatasetManifest:
        if (
            ref.schema_version != SCHEMA_VERSION
            or len(ref.dataset_id) != 64
            or any(c not in "0123456789abcdef" for c in ref.dataset_id)
        ):
            raise ValueError("dataset_ref_invalid")
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as conn:
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute(
                "SELECT manifest_json FROM dataset_manifests WHERE dataset_id=?",
                (ref.dataset_id,),
            ).fetchone()
        if row is None:
            raise LookupError("dataset_not_found")
        payload = json.loads(row[0])
        identity = {
            "schema_version": payload["ref"]["schema_version"],
            **{k: v for k, v in payload.items() if k not in {"ref", "published_at"}},
        }
        if (
            payload["ref"] != asdict(ref)
            or _digest(_json(identity).encode()) != ref.dataset_id
        ):
            raise ValueError("dataset_manifest_digest_mismatch")
        return _manifest(payload)

    def read(self, ref: DatasetRef, partition: str) -> pa.Table:
        manifest = self.get(ref)
        digest = manifest.partitions[partition]
        path = self._partition_path(digest)
        contents = path.read_bytes()
        if path.is_symlink() or _digest(contents) != digest:
            raise ValueError("dataset_content_digest_mismatch")
        table = pq.read_table(pa.BufferReader(contents))
        if table.num_rows != manifest.row_counts[partition]:
            raise ValueError("dataset_row_count_mismatch")
        if table.schema != _SCHEMAS[partition]:
            raise ValueError("dataset_schema_mismatch")
        return table

    def read_as_of(self, ref: DatasetRef, partition: str, *, as_of: str) -> pa.Table:
        """Require a generation wholly available as of the requested instant.

        This catalog retains one revision per row in each generation. Filtering
        a newer revision away cannot reconstruct an older complete PIT panel.
        Callers must bind a suitable earlier immutable generation instead.
        """
        instant = _instant(as_of)
        if instant > _instant(self.get(ref).cutoff):
            raise ValueError("dataset_as_of_exceeds_cutoff")
        tables = {name: self.read(ref, name) for name in ("universe", "daily")}
        if any(
            _instant(value.as_py()) > instant
            for table in tables.values()
            for value in table["available_at"]
        ):
            raise ValueError("dataset_as_of_generation_incomplete")
        return tables[partition]

    def _partition_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("dataset_partition_digest_invalid")
        return self.root / "lake" / "daily" / f"{digest}.parquet"

    def _write_partition(self, table: pa.Table) -> str:
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression="zstd")
        data = sink.getvalue().to_pybytes()
        digest = _digest(data)
        destination = self._partition_path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".stage-")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o444)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if (
                    destination.is_symlink()
                    or _digest(destination.read_bytes()) != digest
                ):
                    raise ValueError("dataset_immutable_content_conflict")
            directory = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(temporary)
        return digest


def _key(row):
    return row["session_date"], row["instrument_type"], row["symbol"]


def _normalize(rows, cutoff, *, universe):
    result = []
    seen = set()
    for source in rows:
        row = dict(source)
        schema = _SCHEMAS["universe" if universe else "daily"]
        if set(row) - set(schema.names):
            raise ValueError("dataset_unknown_fields")
        for name in (
            "symbol",
            "instrument_type",
            "session_date",
            "source_revision",
            "availability_evidence_ref",
        ):
            if not isinstance(row.get(name), str) or not row[name].strip():
                raise ValueError(f"dataset_missing_{name}")
        if row["instrument_type"] not in {"stock", "etf", "index"}:
            raise ValueError("dataset_instrument_type_unsupported")
        session = date.fromisoformat(row["session_date"])
        event, available, captured = (
            _instant(row[name])
            for name in ("event_time", "available_at", "captured_at")
        )
        if available > cutoff or event > available or captured < available:
            raise ValueError("dataset_time_semantics_invalid")
        if event.astimezone(ZoneInfo("Asia/Shanghai")).date() != session:
            raise ValueError("dataset_event_session_mismatch")
        for name, instant in (
            ("event_time", event),
            ("available_at", available),
            ("captured_at", captured),
        ):
            row[name] = instant.isoformat()
        if not isinstance(row.get("suspended"), bool):
            raise ValueError("dataset_suspension_evidence_missing")
        if universe:
            row.setdefault("delisted_on", None)
            if date.fromisoformat(row["listed_on"]) > session:
                raise ValueError("dataset_universe_before_listing")
            if (
                row.get("delisted_on")
                and date.fromisoformat(row["delisted_on"]) <= session
            ):
                raise ValueError("dataset_universe_after_delisting")
            if row.get("membership_status") != "member":
                raise ValueError("dataset_membership_evidence_missing")
        else:
            for name in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "adjustment_factor",
            ):
                value = row.get(name)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(f"dataset_invalid_{name}")
                row[name] = float(value)
            if (
                row["adjustment_factor"] <= 0
                or row["low"] > min(row["open"], row["close"])
                or row["high"] < max(row["open"], row["close"])
            ):
                raise ValueError("dataset_ohlc_invalid")
            if row["low"] <= 0 or (
                row["suspended"] and (row["volume"] != 0 or row["amount"] != 0)
            ):
                raise ValueError("dataset_tradability_invalid")
        key = _key(row)
        if key in seen:
            raise ValueError("dataset_duplicate_instrument_session")
        seen.add(key)
        result.append(row)
    return sorted(result, key=_key)


def _manifest(payload):
    return DatasetManifest(
        **{
            **payload,
            "ref": DatasetRef(**payload["ref"]),
            "source_revisions": tuple(payload["source_revisions"]),
        }
    )
