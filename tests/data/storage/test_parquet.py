"""Tests for immutable Parquet materialization."""

from __future__ import annotations

import os
from dataclasses import replace

import pyarrow as pa
import pytest

from data.storage.objects import ContentAddressedObjectStore
from data.storage.parquet import (
    PARQUET_SERIALIZATION_PROFILE,
    ParquetIntegrityError,
    ParquetSchemaError,
    arrow_schema_fingerprint,
    materialize_parquet,
    read_parquet,
    serialize_parquet,
)

_TEST_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()),
        ("session_date", pa.string()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
    ]
)


def _table() -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "symbol": "000001",
                "session_date": "2026-09-14",
                "close": 10.25,
                "volume": 1000.0,
            },
            {
                "symbol": "600000",
                "session_date": "2026-09-14",
                "close": 12.50,
                "volume": 2000.0,
            },
        ],
        schema=_TEST_SCHEMA,
    )


def _object_path(store: ContentAddressedObjectStore, object_id: str):
    digest = object_id.removeprefix("sha256:")
    return store.root / "sha256" / digest[:2] / digest[2:]


def test_schema_fingerprint_is_deterministic() -> None:
    first = arrow_schema_fingerprint(_TEST_SCHEMA)
    second = arrow_schema_fingerprint(_TEST_SCHEMA)

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64


def test_schema_fingerprint_changes_with_schema() -> None:
    changed = pa.schema(
        [
            ("symbol", pa.string()),
            ("session_date", pa.string()),
            ("close", pa.float32()),
            ("volume", pa.float64()),
        ]
    )

    assert arrow_schema_fingerprint(_TEST_SCHEMA) != arrow_schema_fingerprint(changed)


def test_same_table_serializes_to_same_bytes() -> None:
    table = _table()

    first = serialize_parquet(
        table,
        expected_schema=_TEST_SCHEMA,
    )
    second = serialize_parquet(
        table,
        expected_schema=_TEST_SCHEMA,
    )

    assert first == second


def test_arrow_chunk_layout_does_not_change_serialized_bytes() -> None:
    contiguous = _table()

    chunked = pa.table(
        {
            "symbol": pa.chunked_array(
                [
                    pa.array(["000001"], type=pa.string()),
                    pa.array(["600000"], type=pa.string()),
                ]
            ),
            "session_date": pa.chunked_array(
                [
                    pa.array(["2026-09-14"], type=pa.string()),
                    pa.array(["2026-09-14"], type=pa.string()),
                ]
            ),
            "close": pa.chunked_array(
                [
                    pa.array([10.25], type=pa.float64()),
                    pa.array([12.50], type=pa.float64()),
                ]
            ),
            "volume": pa.chunked_array(
                [
                    pa.array([1000.0], type=pa.float64()),
                    pa.array([2000.0], type=pa.float64()),
                ]
            ),
        },
        schema=_TEST_SCHEMA,
    )

    assert contiguous.equals(chunked)

    contiguous_bytes = serialize_parquet(
        contiguous,
        expected_schema=_TEST_SCHEMA,
    )
    chunked_bytes = serialize_parquet(
        chunked,
        expected_schema=_TEST_SCHEMA,
    )

    assert contiguous_bytes == chunked_bytes


def test_row_order_remains_part_of_physical_identity() -> None:
    table = _table()

    reversed_table = table.take(pa.array([1, 0], type=pa.int64()))

    first = serialize_parquet(
        table,
        expected_schema=_TEST_SCHEMA,
    )
    second = serialize_parquet(
        reversed_table,
        expected_schema=_TEST_SCHEMA,
    )

    assert first != second


def test_schema_mismatch_is_rejected_before_write() -> None:
    table = _table()

    wrong_schema = pa.schema(
        [
            ("symbol", pa.string()),
            ("session_date", pa.string()),
            ("close", pa.float32()),
            ("volume", pa.float64()),
        ]
    )

    with pytest.raises(
        ParquetSchemaError,
        match="parquet_schema_mismatch",
    ):
        serialize_parquet(
            table,
            expected_schema=wrong_schema,
        )


def test_materialize_and_read_round_trip(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    table = _table()

    artifact = materialize_parquet(
        store,
        table,
        expected_schema=_TEST_SCHEMA,
    )

    restored = read_parquet(
        store,
        artifact,
        expected_schema=_TEST_SCHEMA,
    )

    assert restored.equals(table.combine_chunks())
    assert artifact.row_count == table.num_rows
    assert artifact.column_count == table.num_columns
    assert artifact.schema_fingerprint == arrow_schema_fingerprint(_TEST_SCHEMA)
    assert artifact.serialization_profile == PARQUET_SERIALIZATION_PROFILE
    assert artifact.writer_version.startswith("pyarrow:")
    assert store.verify(artifact.object_ref) is True


def test_same_table_materializes_to_same_object(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    table = _table()

    first = materialize_parquet(
        store,
        table,
        expected_schema=_TEST_SCHEMA,
    )
    second = materialize_parquet(
        store,
        table,
        expected_schema=_TEST_SCHEMA,
    )

    assert first.object_ref == second.object_ref
    assert first == second


def test_corrupted_parquet_object_fails_closed(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    artifact = materialize_parquet(
        store,
        _table(),
        expected_schema=_TEST_SCHEMA,
    )

    path = _object_path(
        store,
        artifact.object_ref.object_id,
    )

    os.chmod(path, 0o644)
    path.write_bytes(b"corrupted parquet bytes")

    with pytest.raises(
        ParquetIntegrityError,
        match="parquet_object_integrity_failed",
    ):
        read_parquet(
            store,
            artifact,
            expected_schema=_TEST_SCHEMA,
        )


def test_forged_row_count_is_rejected(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    artifact = materialize_parquet(
        store,
        _table(),
        expected_schema=_TEST_SCHEMA,
    )

    forged = replace(
        artifact,
        row_count=artifact.row_count + 1,
    )

    with pytest.raises(
        ParquetIntegrityError,
        match="parquet_row_count_mismatch",
    ):
        read_parquet(
            store,
            forged,
            expected_schema=_TEST_SCHEMA,
        )


def test_forged_schema_fingerprint_is_rejected(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    artifact = materialize_parquet(
        store,
        _table(),
        expected_schema=_TEST_SCHEMA,
    )

    forged = replace(
        artifact,
        schema_fingerprint="sha256:" + "0" * 64,
    )

    with pytest.raises(
        ParquetIntegrityError,
        match="parquet_schema_fingerprint_mismatch",
    ):
        read_parquet(
            store,
            forged,
            expected_schema=_TEST_SCHEMA,
        )


def test_expected_schema_is_checked_on_read(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    artifact = materialize_parquet(
        store,
        _table(),
        expected_schema=_TEST_SCHEMA,
    )

    incompatible_schema = pa.schema(
        [
            ("symbol", pa.string()),
            ("session_date", pa.string()),
            ("close", pa.float64()),
            ("volume", pa.int64()),
        ]
    )

    with pytest.raises(
        ParquetSchemaError,
        match="parquet_schema_mismatch",
    ):
        read_parquet(
            store,
            artifact,
            expected_schema=incompatible_schema,
        )


def test_empty_table_is_valid(tmp_path) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    table = pa.Table.from_pylist(
        [],
        schema=_TEST_SCHEMA,
    )

    artifact = materialize_parquet(
        store,
        table,
        expected_schema=_TEST_SCHEMA,
    )

    restored = read_parquet(
        store,
        artifact,
        expected_schema=_TEST_SCHEMA,
    )

    assert artifact.row_count == 0
    assert restored.num_rows == 0
    assert restored.schema.equals(
        _TEST_SCHEMA,
        check_metadata=True,
    )
