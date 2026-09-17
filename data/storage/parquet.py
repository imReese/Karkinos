"""Deterministic Parquet materialization for immutable data-plane objects."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pyarrow as pa
import pyarrow.parquet as pq

from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectIntegrityError,
    ObjectRef,
)

PARQUET_SERIALIZATION_PROFILE = "karkinos.parquet.zstd.v1"

_PARQUET_FORMAT_VERSION = "2.6"
_COMPRESSION = "zstd"
_COMPRESSION_LEVEL = 3
_ROW_GROUP_SIZE = 65_536
_DATA_PAGE_SIZE = 1024 * 1024
_WRITE_BATCH_SIZE = 1024


class ParquetStorageError(RuntimeError):
    """Base error for Parquet materialization operations."""


class ParquetSchemaError(ParquetStorageError):
    """Raised when a table violates the expected Arrow schema."""


class ParquetIntegrityError(ParquetStorageError):
    """Raised when persisted Parquet content violates its artifact metadata."""


@dataclass(frozen=True, slots=True)
class ParquetArtifact:
    """Physical immutable Parquet materialization.

    This describes one concrete Parquet encoding of a logical table. The
    ``ObjectRef`` identifies exact bytes; it must not be treated as the logical
    identity of a MarketRevision or Dataset.
    """

    object_ref: ObjectRef
    row_count: int
    column_count: int
    schema_fingerprint: str
    serialization_profile: str
    writer_version: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.row_count, bool)
            or not isinstance(self.row_count, int)
            or self.row_count < 0
        ):
            raise ValueError("parquet_artifact_row_count_invalid")

        if (
            isinstance(self.column_count, bool)
            or not isinstance(self.column_count, int)
            or self.column_count < 0
        ):
            raise ValueError("parquet_artifact_column_count_invalid")

        if not self.schema_fingerprint.startswith("sha256:"):
            raise ValueError("parquet_artifact_schema_fingerprint_invalid")

        if self.serialization_profile != PARQUET_SERIALIZATION_PROFILE:
            raise ValueError("parquet_artifact_profile_unsupported")

        if not self.writer_version:
            raise ValueError("parquet_artifact_writer_version_missing")


def arrow_schema_fingerprint(schema: pa.Schema) -> str:
    """Return a content fingerprint for the exact Arrow schema representation."""
    if not isinstance(schema, pa.Schema):
        raise TypeError("parquet_schema_must_be_arrow_schema")

    serialized = schema.serialize().to_pybytes()
    digest = hashlib.sha256(serialized).hexdigest()
    return f"sha256:{digest}"


def serialize_parquet(
    table: pa.Table,
    *,
    expected_schema: pa.Schema | None = None,
) -> bytes:
    """Serialize one Arrow table using the Karkinos Parquet storage profile.

    Row order is preserved. This layer never sorts, deduplicates, normalizes,
    or otherwise changes financial semantics.

    Deterministic encoding is expected for the same prepared Arrow table,
    serialization profile, and writer version. Cross-version byte identity is
    intentionally not promised.
    """
    prepared = _prepare_table(
        table,
        expected_schema=expected_schema,
    )

    sink = pa.BufferOutputStream()

    pq.write_table(
        prepared,
        sink,
        version=_PARQUET_FORMAT_VERSION,
        compression=_COMPRESSION,
        compression_level=_COMPRESSION_LEVEL,
        use_dictionary=False,
        write_statistics=True,
        row_group_size=_ROW_GROUP_SIZE,
        data_page_size=_DATA_PAGE_SIZE,
        write_batch_size=_WRITE_BATCH_SIZE,
        use_deprecated_int96_timestamps=False,
        data_page_version="1.0",
        use_byte_stream_split=False,
        store_schema=True,
        write_page_index=False,
        write_page_checksum=True,
    )

    return sink.getvalue().to_pybytes()


def materialize_parquet(
    store: ContentAddressedObjectStore,
    table: pa.Table,
    *,
    expected_schema: pa.Schema | None = None,
) -> ParquetArtifact:
    """Serialize and immutably persist one Arrow table."""
    prepared = _prepare_table(
        table,
        expected_schema=expected_schema,
    )
    payload = serialize_parquet(
        prepared,
        expected_schema=prepared.schema,
    )
    object_ref = store.put_bytes(payload)

    return ParquetArtifact(
        object_ref=object_ref,
        row_count=prepared.num_rows,
        column_count=prepared.num_columns,
        schema_fingerprint=arrow_schema_fingerprint(prepared.schema),
        serialization_profile=PARQUET_SERIALIZATION_PROFILE,
        writer_version=f"pyarrow:{pa.__version__}",
    )


def read_parquet(
    store: ContentAddressedObjectStore,
    artifact: ParquetArtifact,
    *,
    expected_schema: pa.Schema | None = None,
) -> pa.Table:
    """Read and validate one immutable Parquet materialization."""
    if artifact.serialization_profile != PARQUET_SERIALIZATION_PROFILE:
        raise ParquetIntegrityError("parquet_serialization_profile_unsupported")

    try:
        payload = store.read_bytes(artifact.object_ref)
    except ObjectIntegrityError as exc:
        raise ParquetIntegrityError("parquet_object_integrity_failed") from exc

    try:
        # Immutable object replay favors deterministic teardown over Parquet's
        # global read thread pool.  Arrow has documented Linux shutdown crashes
        # in threaded Parquet reads; object-level parallelism belongs to callers.
        table = pq.read_table(
            pa.BufferReader(payload),
            page_checksum_verification=True,
            use_threads=False,
        )
    except (pa.ArrowInvalid, pa.ArrowIOError, OSError) as exc:
        raise ParquetIntegrityError("parquet_payload_invalid") from exc

    table = table.combine_chunks()

    if table.num_rows != artifact.row_count:
        raise ParquetIntegrityError("parquet_row_count_mismatch")

    if table.num_columns != artifact.column_count:
        raise ParquetIntegrityError("parquet_column_count_mismatch")

    if arrow_schema_fingerprint(table.schema) != artifact.schema_fingerprint:
        raise ParquetIntegrityError("parquet_schema_fingerprint_mismatch")

    if expected_schema is not None and not table.schema.equals(
        expected_schema,
        check_metadata=True,
    ):
        raise ParquetSchemaError("parquet_schema_mismatch")

    return table


def _prepare_table(
    table: pa.Table,
    *,
    expected_schema: pa.Schema | None,
) -> pa.Table:
    """Validate and canonicalize only physical Arrow representation details."""
    if not isinstance(table, pa.Table):
        raise TypeError("parquet_input_must_be_arrow_table")

    if expected_schema is not None:
        if not isinstance(expected_schema, pa.Schema):
            raise TypeError("parquet_schema_must_be_arrow_schema")

        if not table.schema.equals(
            expected_schema,
            check_metadata=True,
        ):
            raise ParquetSchemaError("parquet_schema_mismatch")

    # Chunk boundaries are an Arrow in-memory implementation detail and must
    # not influence Parquet materialization identity.
    return table.combine_chunks()
