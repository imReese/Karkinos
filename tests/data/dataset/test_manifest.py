"""不可变 Dataset Manifest 测试。"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.manifest import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    DatasetManifestIntegrityError,
    deserialize_daily_bar_dataset_manifest,
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
    serialize_daily_bar_dataset_manifest,
)
from data.dataset.model import (
    DATASET_KIND_DAILY_BARS,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.storage.objects import ContentAddressedObjectStore

_START_DATE = date(2026, 9, 14)
_END_DATE = date(2026, 9, 16)

_CUTOFF = datetime(
    2026,
    9,
    17,
    1,
    0,
    tzinfo=timezone.utc,
)


def _content_id(
    digit: str,
) -> str:
    return f"sha256:{digit * 64}"


def _instrument(
    symbol: str,
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _partition(
    partition_date: date,
    *,
    provider: str = "tdx",
    revision_digit: str = "a",
    materialization_digit: str = "b",
) -> DailyBarDatasetPartition:
    return DailyBarDatasetPartition(
        partition_date=partition_date,
        provider=provider,
        revision_id=_content_id(revision_digit),
        materialization_id=_content_id(materialization_digit),
    )


def _snapshot(
    *,
    cutoff: datetime = _CUTOFF,
    instruments=None,
    partitions=None,
    resolver_policy_id: str = ("karkinos.dataset.pit.strict.v1"),
) -> DailyBarDatasetSnapshot:
    return DailyBarDatasetSnapshot(
        start_date=_START_DATE,
        end_date=_END_DATE,
        cutoff=cutoff,
        instruments=(
            instruments
            if instruments is not None
            else (
                _instrument("000001"),
                _instrument("600000"),
            )
        ),
        resolver_policy_id=resolver_policy_id,
        market_schema_version=("karkinos.market.daily_bar.v1"),
        partitions=(
            partitions
            if partitions is not None
            else (
                _partition(
                    date(2026, 9, 14),
                    revision_digit="a",
                    materialization_digit="b",
                ),
                _partition(
                    date(2026, 9, 15),
                    revision_digit="c",
                    materialization_digit="d",
                ),
            )
        ),
    )


def _object_path(
    store: ContentAddressedObjectStore,
    object_id: str,
) -> Path:
    digest = object_id.removeprefix("sha256:")

    return store.root / "sha256" / digest[:2] / digest[2:]


def _decode_manifest(
    payload: bytes,
) -> dict:
    return json.loads(payload.decode("utf-8"))


def _encode_json(
    value: object,
) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def test_manifest_round_trip_preserves_snapshot(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    snapshot = _snapshot()

    ref = publish_daily_bar_dataset_manifest(
        store,
        snapshot,
    )

    restored = read_daily_bar_dataset_manifest(
        store,
        ref,
    )

    assert restored == snapshot


def test_same_snapshot_publishes_same_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    snapshot = _snapshot()

    first = publish_daily_bar_dataset_manifest(
        store,
        snapshot,
    )

    second = publish_daily_bar_dataset_manifest(
        store,
        snapshot,
    )

    assert first == second
    assert first.dataset_id == second.dataset_id


def test_equivalent_input_order_publishes_same_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _snapshot(
        instruments=(
            _instrument("600000"),
            _instrument("000001"),
        ),
        partitions=(
            _partition(
                date(2026, 9, 15),
                revision_digit="c",
                materialization_digit="d",
            ),
            _partition(
                date(2026, 9, 14),
                revision_digit="a",
                materialization_digit="b",
            ),
        ),
    )

    second = _snapshot(
        instruments=(
            _instrument("000001"),
            _instrument("600000"),
        ),
        partitions=(
            _partition(
                date(2026, 9, 14),
                revision_digit="a",
                materialization_digit="b",
            ),
            _partition(
                date(2026, 9, 15),
                revision_digit="c",
                materialization_digit="d",
            ),
        ),
    )

    first_ref = publish_daily_bar_dataset_manifest(
        store,
        first,
    )

    second_ref = publish_daily_bar_dataset_manifest(
        store,
        second,
    )

    assert first == second
    assert first_ref == second_ref


def test_different_cutoff_changes_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _snapshot(
        cutoff=datetime(
            2026,
            9,
            17,
            1,
            0,
            tzinfo=timezone.utc,
        )
    )

    second = _snapshot(
        cutoff=datetime(
            2026,
            9,
            18,
            1,
            0,
            tzinfo=timezone.utc,
        )
    )

    first_ref = publish_daily_bar_dataset_manifest(
        store,
        first,
    )

    second_ref = publish_daily_bar_dataset_manifest(
        store,
        second,
    )

    assert first_ref != second_ref


def test_different_materialization_changes_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    revision_id = _content_id("a")

    first = _snapshot(
        partitions=(
            DailyBarDatasetPartition(
                partition_date=date(
                    2026,
                    9,
                    15,
                ),
                provider="tdx",
                revision_id=revision_id,
                materialization_id=(_content_id("b")),
            ),
        )
    )

    second = _snapshot(
        partitions=(
            DailyBarDatasetPartition(
                partition_date=date(
                    2026,
                    9,
                    15,
                ),
                provider="tdx",
                revision_id=revision_id,
                materialization_id=(_content_id("c")),
            ),
        )
    )

    first_ref = publish_daily_bar_dataset_manifest(
        store,
        first,
    )

    second_ref = publish_daily_bar_dataset_manifest(
        store,
        second,
    )

    assert first_ref != second_ref


def test_different_revision_changes_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _snapshot(
        partitions=(
            _partition(
                date(2026, 9, 15),
                revision_digit="a",
                materialization_digit="b",
            ),
        )
    )

    second = _snapshot(
        partitions=(
            _partition(
                date(2026, 9, 15),
                revision_digit="c",
                materialization_digit="b",
            ),
        )
    )

    first_ref = publish_daily_bar_dataset_manifest(
        store,
        first,
    )

    second_ref = publish_daily_bar_dataset_manifest(
        store,
        second,
    )

    assert first_ref != second_ref


def test_different_resolver_policy_changes_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _snapshot(resolver_policy_id=("karkinos.dataset.pit.strict.v1"))

    second = _snapshot(resolver_policy_id=("karkinos.dataset.pit.strict.v2"))

    assert publish_daily_bar_dataset_manifest(
        store,
        first,
    ) != publish_daily_bar_dataset_manifest(
        store,
        second,
    )


def test_manifest_contains_expected_semantic_fields() -> None:
    snapshot = _snapshot()

    payload = serialize_daily_bar_dataset_manifest(snapshot)

    manifest = _decode_manifest(payload)

    assert manifest["schema_version"] == DATASET_MANIFEST_SCHEMA_VERSION
    assert manifest["kind"] == DATASET_KIND_DAILY_BARS

    assert manifest["start_date"] == "2026-09-14"
    assert manifest["end_date"] == "2026-09-16"

    assert manifest["cutoff"] == "2026-09-17T01:00:00.000000Z"

    assert manifest["resolver_policy_id"] == "karkinos.dataset.pit.strict.v1"

    assert manifest["market_schema_version"] == "karkinos.market.daily_bar.v1"

    assert len(manifest["instruments"]) == 2

    assert len(manifest["partitions"]) == 2


def test_manifest_contains_no_runtime_publication_timestamp() -> None:
    payload = serialize_daily_bar_dataset_manifest(_snapshot())

    manifest = _decode_manifest(payload)

    assert "published_at" not in manifest
    assert "created_at" not in manifest


def test_manifest_serialization_is_deterministic() -> None:
    snapshot = _snapshot()

    first = serialize_daily_bar_dataset_manifest(snapshot)

    second = serialize_daily_bar_dataset_manifest(snapshot)

    assert first == second


def test_manifest_serialization_uses_canonical_json() -> None:
    payload = serialize_daily_bar_dataset_manifest(_snapshot())

    text = payload.decode("utf-8")

    # canonical JSON 不包含格式化空白或换行。
    assert "\n" not in text
    assert ": " not in text
    assert ", " not in text

    parsed = json.loads(text)

    assert payload == _encode_json(parsed)


def test_cutoff_equivalent_timezone_has_same_manifest_identity(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    utc_snapshot = _snapshot(
        cutoff=datetime(
            2026,
            9,
            17,
            1,
            0,
            tzinfo=timezone.utc,
        )
    )

    shanghai = timezone(timedelta(hours=8))

    local_snapshot = _snapshot(
        cutoff=datetime(
            2026,
            9,
            17,
            9,
            0,
            tzinfo=shanghai,
        )
    )

    first = publish_daily_bar_dataset_manifest(
        store,
        utc_snapshot,
    )

    second = publish_daily_bar_dataset_manifest(
        store,
        local_snapshot,
    )

    assert first == second


def test_deserialize_valid_manifest() -> None:
    snapshot = _snapshot()

    payload = serialize_daily_bar_dataset_manifest(snapshot)

    restored = deserialize_daily_bar_dataset_manifest(payload)

    assert restored == snapshot


def test_deserialize_rejects_invalid_utf8() -> None:
    with pytest.raises(
        DatasetManifestIntegrityError,
        match="dataset_manifest_utf8_invalid",
    ):
        deserialize_daily_bar_dataset_manifest(b"\xff\xfe\xfa")


def test_deserialize_rejects_invalid_json() -> None:
    with pytest.raises(
        DatasetManifestIntegrityError,
        match="dataset_manifest_json_invalid",
    ):
        deserialize_daily_bar_dataset_manifest(b"{not-json")


def test_deserialize_rejects_unsupported_schema_version() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    manifest["schema_version"] = "karkinos.dataset_manifest.v999"

    with pytest.raises(
        DatasetManifestIntegrityError,
        match=("dataset_manifest_schema_unsupported"),
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_deserialize_rejects_unsupported_kind() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    manifest["kind"] = "ticks"

    with pytest.raises(
        DatasetManifestIntegrityError,
        match="dataset_manifest_kind_unsupported",
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_deserialize_rejects_unknown_root_field() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    manifest["unexpected"] = "value"

    with pytest.raises(
        DatasetManifestIntegrityError,
        match=("dataset_manifest_root_fields_invalid"),
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_deserialize_rejects_missing_root_field() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    del manifest["resolver_policy_id"]

    with pytest.raises(
        DatasetManifestIntegrityError,
        match=("dataset_manifest_root_fields_invalid"),
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_deserialize_rejects_invalid_instrument_type() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    manifest["instruments"][0]["instrument_type"] = "spaceship"

    with pytest.raises(
        DatasetManifestIntegrityError,
        match=("dataset_manifest_instrument_type_invalid"),
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_deserialize_rejects_invalid_partition_content_id() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    manifest["partitions"][0]["revision_id"] = "revision-1"

    with pytest.raises(
        DatasetManifestIntegrityError,
        match="dataset_manifest_partition_invalid",
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_deserialize_rejects_noncanonical_cutoff() -> None:
    manifest = _decode_manifest(serialize_daily_bar_dataset_manifest(_snapshot()))

    manifest["cutoff"] = "2026-09-17T01:00:00Z"

    with pytest.raises(
        DatasetManifestIntegrityError,
        match=("dataset_manifest_cutoff_not_canonical"),
    ):
        deserialize_daily_bar_dataset_manifest(_encode_json(manifest))


def test_read_rejects_noncanonical_json_encoding(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    canonical = serialize_daily_bar_dataset_manifest(_snapshot())

    value = json.loads(canonical.decode("utf-8"))

    noncanonical = json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")

    assert noncanonical != canonical

    object_ref = store.put_bytes(noncanonical)

    ref = DatasetRef(manifest_ref=object_ref)

    with pytest.raises(
        DatasetManifestIntegrityError,
        match="dataset_manifest_not_canonical",
    ):
        read_daily_bar_dataset_manifest(
            store,
            ref,
        )


def test_read_rejects_corrupted_manifest_object(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    ref = publish_daily_bar_dataset_manifest(
        store,
        _snapshot(),
    )

    path = _object_path(
        store,
        ref.manifest_ref.object_id,
    )

    # 主动绕过只读权限，模拟磁盘损坏。
    os.chmod(
        path,
        0o644,
    )

    path.write_bytes(b"corrupted dataset manifest")

    with pytest.raises(
        DatasetManifestIntegrityError,
        match=("dataset_manifest_object_unreadable"),
    ):
        read_daily_bar_dataset_manifest(
            store,
            ref,
        )


def test_publish_requires_snapshot_instance(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        TypeError,
        match="dataset_manifest_snapshot_invalid",
    ):
        publish_daily_bar_dataset_manifest(
            store,
            "not-a-snapshot",
        )


def test_serialize_requires_snapshot_instance() -> None:
    with pytest.raises(
        TypeError,
        match="dataset_manifest_snapshot_invalid",
    ):
        serialize_daily_bar_dataset_manifest("not-a-snapshot")


def test_read_requires_dataset_ref(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        TypeError,
        match="dataset_manifest_ref_invalid",
    ):
        read_daily_bar_dataset_manifest(
            store,
            "sha256:not-a-dataset-ref",
        )
