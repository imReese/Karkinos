"""不可变 Dataset Manifest 的发布与读取。

Dataset Snapshot 是内存中的 PIT selection：

    DailyBarDatasetSnapshot

Manifest 将这份 selection 编码成稳定、规范的 JSON，并存入
ContentAddressedObjectStore：

    DailyBarDatasetSnapshot
        ↓
    canonical JSON
        ↓
    ObjectRef
        ↓
    DatasetRef

DatasetRef 的 identity 就是 manifest bytes 的内容地址。

本模块不负责：

- 解析哪些 MarketRevision 应当被选择；
- 判断交易日覆盖是否完整；
- 查询 Provider；
- 维护 latest/current Dataset；
- 读取 Market Data Parquet；
- 执行 Research。

这些职责分别属于 resolver.py、catalog.py 和 reader.py。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from core.types import InstrumentKey, InstrumentType
from data.dataset.model import (
    DATASET_KIND_DAILY_BARS,
    DailyBarDatasetPartition,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectStoreError,
)

DATASET_MANIFEST_SCHEMA_VERSION = "karkinos.dataset_manifest.v1"


class DatasetManifestError(RuntimeError):
    """Dataset Manifest 基础异常。"""


class DatasetManifestIntegrityError(DatasetManifestError):
    """Dataset Manifest 无法通过完整性或语义验证。"""


def publish_daily_bar_dataset_manifest(
    store: ContentAddressedObjectStore,
    snapshot: DailyBarDatasetSnapshot,
) -> DatasetRef:
    """发布一份不可变的日线 PIT Dataset Manifest。

    相同 Snapshot 会生成完全相同的 canonical JSON，
    因此得到相同的 DatasetRef。

    Manifest 不包含 published_at、created_at 等运行时字段，
    避免同一个逻辑 Dataset 因发布时间不同而产生不同 identity。
    """
    if not isinstance(
        snapshot,
        DailyBarDatasetSnapshot,
    ):
        raise TypeError("dataset_manifest_snapshot_invalid")

    payload = serialize_daily_bar_dataset_manifest(snapshot)

    manifest_ref = store.put_bytes(payload)

    return DatasetRef(manifest_ref=manifest_ref)


def read_daily_bar_dataset_manifest(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
) -> DailyBarDatasetSnapshot:
    """读取并验证一个 Dataset Manifest。

    验证包括：

    1. Content-addressed Object 完整性；
    2. JSON 格式；
    3. Manifest schema version；
    4. Dataset kind；
    5. Snapshot 结构与 domain invariants；
    6. JSON 是否采用唯一 canonical encoding。

    最后一项可以避免同一语义 Dataset 被不同 JSON 格式编码成多个
    DatasetRef。
    """
    if not isinstance(
        ref,
        DatasetRef,
    ):
        raise TypeError("dataset_manifest_ref_invalid")

    try:
        payload = store.read_bytes(ref.manifest_ref)
    except ObjectStoreError as exc:
        raise DatasetManifestIntegrityError(
            "dataset_manifest_object_unreadable"
        ) from exc

    snapshot = deserialize_daily_bar_dataset_manifest(payload)

    canonical_payload = serialize_daily_bar_dataset_manifest(snapshot)

    if payload != canonical_payload:
        raise DatasetManifestIntegrityError("dataset_manifest_not_canonical")

    return snapshot


def serialize_daily_bar_dataset_manifest(
    snapshot: DailyBarDatasetSnapshot,
) -> bytes:
    """把 Dataset Snapshot 编码成唯一 canonical JSON bytes。"""
    if not isinstance(
        snapshot,
        DailyBarDatasetSnapshot,
    ):
        raise TypeError("dataset_manifest_snapshot_invalid")

    payload = {
        "schema_version": (DATASET_MANIFEST_SCHEMA_VERSION),
        "kind": snapshot.kind,
        "start_date": (snapshot.start_date.isoformat()),
        "end_date": (snapshot.end_date.isoformat()),
        "cutoff": _format_utc_instant(snapshot.cutoff),
        "resolver_policy_id": (snapshot.resolver_policy_id),
        "market_schema_version": (snapshot.market_schema_version),
        "instruments": [
            _instrument_payload(instrument) for instrument in snapshot.instruments
        ],
        "partitions": [
            _partition_payload(partition) for partition in snapshot.partitions
        ],
    }

    return _canonical_json(payload)


def deserialize_daily_bar_dataset_manifest(
    payload: bytes,
) -> DailyBarDatasetSnapshot:
    """从 canonical Dataset Manifest bytes 重建 Snapshot。

    本函数验证 manifest 的 schema 和 domain 语义，但不会访问
    ObjectStore 中被引用的 Revision / Materialization。
    """
    if not isinstance(
        payload,
        bytes,
    ):
        raise TypeError("dataset_manifest_payload_must_be_bytes")

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetManifestIntegrityError("dataset_manifest_utf8_invalid") from exc

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetManifestIntegrityError("dataset_manifest_json_invalid") from exc

    root = _require_object(
        value,
        field="root",
    )

    _require_exact_keys(
        root,
        {
            "schema_version",
            "kind",
            "start_date",
            "end_date",
            "cutoff",
            "resolver_policy_id",
            "market_schema_version",
            "instruments",
            "partitions",
        },
        field="root",
    )

    schema_version = _require_text(
        root["schema_version"],
        field="schema_version",
    )

    if schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
        raise DatasetManifestIntegrityError("dataset_manifest_schema_unsupported")

    kind = _require_text(
        root["kind"],
        field="kind",
    )

    if kind != DATASET_KIND_DAILY_BARS:
        raise DatasetManifestIntegrityError("dataset_manifest_kind_unsupported")

    instruments_value = _require_list(
        root["instruments"],
        field="instruments",
    )

    partitions_value = _require_list(
        root["partitions"],
        field="partitions",
    )

    instruments = tuple(_instrument_from_payload(item) for item in instruments_value)

    partitions = tuple(_partition_from_payload(item) for item in partitions_value)

    try:
        return DailyBarDatasetSnapshot(
            start_date=_parse_date(
                root["start_date"],
                field="start_date",
            ),
            end_date=_parse_date(
                root["end_date"],
                field="end_date",
            ),
            cutoff=_parse_utc_instant(
                root["cutoff"],
                field="cutoff",
            ),
            instruments=instruments,
            resolver_policy_id=(
                _require_text(
                    root["resolver_policy_id"],
                    field=("resolver_policy_id"),
                )
            ),
            market_schema_version=(
                _require_text(
                    root["market_schema_version"],
                    field=("market_schema_version"),
                )
            ),
            partitions=partitions,
        )
    except DatasetManifestIntegrityError:
        raise
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetManifestIntegrityError(
            "dataset_manifest_semantics_invalid"
        ) from exc


def _instrument_payload(
    instrument: InstrumentKey,
) -> dict[str, str]:
    return {
        "symbol": instrument.symbol,
        "instrument_type": (instrument.instrument_type.value),
    }


def _partition_payload(
    partition: DailyBarDatasetPartition,
) -> dict[str, str]:
    return {
        "partition_date": (partition.partition_date.isoformat()),
        "provider": partition.provider,
        "revision_id": (partition.revision_id),
        "materialization_id": (partition.materialization_id),
    }


def _instrument_from_payload(
    value: object,
) -> InstrumentKey:
    payload = _require_object(
        value,
        field="instrument",
    )

    _require_exact_keys(
        payload,
        {
            "symbol",
            "instrument_type",
        },
        field="instrument",
    )

    symbol = _require_text(
        payload["symbol"],
        field="instrument_symbol",
    )

    instrument_type_text = _require_text(
        payload["instrument_type"],
        field="instrument_type",
    )

    try:
        instrument_type = InstrumentType(instrument_type_text)
    except ValueError as exc:
        raise DatasetManifestIntegrityError(
            "dataset_manifest_instrument_type_invalid"
        ) from exc

    try:
        return InstrumentKey(
            symbol=symbol,
            instrument_type=instrument_type,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetManifestIntegrityError(
            "dataset_manifest_instrument_invalid"
        ) from exc


def _partition_from_payload(
    value: object,
) -> DailyBarDatasetPartition:
    payload = _require_object(
        value,
        field="partition",
    )

    _require_exact_keys(
        payload,
        {
            "partition_date",
            "provider",
            "revision_id",
            "materialization_id",
        },
        field="partition",
    )

    try:
        return DailyBarDatasetPartition(
            partition_date=_parse_date(
                payload["partition_date"],
                field="partition_date",
            ),
            provider=_require_text(
                payload["provider"],
                field="partition_provider",
            ),
            revision_id=_require_text(
                payload["revision_id"],
                field="revision_id",
            ),
            materialization_id=(
                _require_text(
                    payload["materialization_id"],
                    field=("materialization_id"),
                )
            ),
        )
    except DatasetManifestIntegrityError:
        raise
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetManifestIntegrityError(
            "dataset_manifest_partition_invalid"
        ) from exc


def _canonical_json(
    value: object,
) -> bytes:
    """生成稳定的 JSON bytes。

    sort_keys 固定 object key 顺序；
    separators 去掉无语义空白；
    ensure_ascii=False 保持 UTF-8；
    allow_nan=False 防止非标准 JSON 数值。
    """
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetManifestError(
            "dataset_manifest_json_serialization_failed"
        ) from exc

    return text.encode("utf-8")


def _format_utc_instant(
    value: datetime,
) -> str:
    """使用唯一 UTC 表示写入 manifest。"""
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError("dataset_manifest_datetime_invalid")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("dataset_manifest_datetime_naive")

    utc = value.astimezone(timezone.utc)

    return utc.isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _parse_utc_instant(
    value: object,
    *,
    field: str,
) -> datetime:
    text = _require_text(
        value,
        field=field,
    )

    # v1 manifest 固定使用 UTC 的 Z 表示。
    if not text.endswith("Z"):
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_invalid")

    try:
        result = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise DatasetManifestIntegrityError(
            f"dataset_manifest_{field}_invalid"
        ) from exc

    result = result.astimezone(timezone.utc)

    # 拒绝语义相同但编码方式不同的时间字符串，
    # 保证一份 Snapshot 只有一种 manifest 表达。
    if _format_utc_instant(result) != text:
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_not_canonical")

    return result


def _parse_date(
    value: object,
    *,
    field: str,
) -> date:
    text = _require_text(
        value,
        field=field,
    )

    try:
        result = date.fromisoformat(text)
    except ValueError as exc:
        raise DatasetManifestIntegrityError(
            f"dataset_manifest_{field}_invalid"
        ) from exc

    if result.isoformat() != text:
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_not_canonical")

    return result


def _require_object(
    value: object,
    *,
    field: str,
) -> dict[str, object]:
    if not isinstance(
        value,
        dict,
    ):
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_must_be_object")

    if not all(isinstance(key, str) for key in value):
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_keys_invalid")

    return value


def _require_list(
    value: object,
    *,
    field: str,
) -> list[object]:
    if not isinstance(
        value,
        list,
    ):
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_must_be_list")

    return value


def _require_text(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_missing")

    return normalized


def _require_exact_keys(
    value: dict[str, object],
    expected: set[str],
    *,
    field: str,
) -> None:
    if set(value) != expected:
        raise DatasetManifestIntegrityError(f"dataset_manifest_{field}_fields_invalid")
