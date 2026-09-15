"""Market Data 不可变版本。

MarketRevision 表示某个 Provider 在某个数据分区上的一版 canonical 市场事实。

Capture 与 Revision 是两个不同概念：

    ProviderCapture
        “Karkinos 在什么时候看到了什么原始响应”

    MarketRevision
        “这些响应规范化后，对应哪一版市场事实”

同一份市场事实可以被多次抓取：

    Capture C1 ─┐
                ├── Revision R1
    Capture C2 ─┘

如果 Provider 后续修正数据，则生成新的 Revision：

    Revision R1
        ↓
    Revision R2

旧 Revision 永远不会被覆盖。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa

from data.market.capture import (
    ProviderCapture,
    read_provider_capture,
)
from data.market.model import DailyBarObservation
from data.market.normalize import canonicalize_daily_bars
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    DAILY_BAR_SCHEMA_VERSION,
    daily_bars_from_table,
    daily_bars_to_table,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
    object_id_from_bytes,
)
from data.storage.parquet import (
    ParquetArtifact,
    materialize_parquet,
    read_parquet,
)

logger = logging.getLogger(__name__)


MARKET_REVISION_SCHEMA_VERSION = "karkinos.market_revision.v1"

MARKET_REVISION_MATERIALIZATION_SCHEMA_VERSION = (
    "karkinos.market_revision_materialization.v1"
)

MARKET_DATA_KIND_DAILY_BARS = "daily_bars"


class MarketRevisionError(RuntimeError):
    """Market Revision 基础异常。"""


class MarketRevisionIntegrityError(MarketRevisionError):
    """Market Revision 或其物化结果完整性校验失败。"""


@dataclass(frozen=True, slots=True)
class MarketRevisionRef:
    """一版 canonical Market Data 的稳定逻辑身份。

    Revision Manifest 本身存放在 ObjectStore 中，因此其 ObjectID
    就是 revision_id。
    """

    manifest_ref: ObjectRef

    @property
    def revision_id(self) -> str:
        return self.manifest_ref.object_id


@dataclass(frozen=True, slots=True)
class MarketRevision:
    """一版不可变的 canonical 市场事实。

    Revision 只描述逻辑市场数据，不绑定某一次 Capture，也不绑定
    某一种 Parquet 编码方式。

    因此同一 Revision 可以拥有多份不同的物理 materialization。
    """

    ref: MarketRevisionRef

    provider: str
    kind: str
    partition_date: date

    market_schema_version: str
    content_fingerprint: str

    row_count: int

    first_event_time: datetime
    last_event_time: datetime


@dataclass(frozen=True, slots=True)
class MarketRevisionMaterialization:
    """某个 MarketRevision 的一次可重放物化结果。

    Materialization 负责连接：

        Revision
            +
        ProviderCapture
            +
        ParquetArtifact

    它属于 provenance / replay evidence，不参与 Revision 的逻辑身份。
    """

    manifest_ref: ObjectRef

    revision_ref: MarketRevisionRef
    capture_ref: ObjectRef

    artifact: ParquetArtifact
    normalizer_version: str

    @property
    def materialization_id(self) -> str:
        return self.manifest_ref.object_id


def publish_daily_bar_revision(
    store: ContentAddressedObjectStore,
    *,
    capture: ProviderCapture,
    bars: Iterable[DailyBarObservation],
    normalizer_version: str,
) -> tuple[
    MarketRevision,
    MarketRevisionMaterialization,
]:
    """固化一版单交易日日线 MarketRevision。

    ``bars`` 必须：

    - 全部来自同一次 Capture；
    - 全部属于同一个交易日；
    - 已经通过 canonical normalization；
    - 不存在重复 InstrumentKey；
    - 允许任意输入顺序，本函数会先进行 canonical 排序。

    Revision 的逻辑身份只取决于：

    - Provider；
    - 数据类型；
    - 分区日期；
    - Market Schema；
    - canonical 市场事实内容。

    Capture 时间、available_at、captured_at 和 Parquet writer
    不参与 Revision identity。
    """
    provider = _require_non_empty_text(
        capture.provider,
        field="provider",
    )
    normalizer_version = _require_non_empty_text(
        normalizer_version,
        field="normalizer_version",
    )

    canonical_bars = canonicalize_daily_bars(tuple(bars))

    if not canonical_bars:
        raise ValueError("market_revision_daily_bars_empty")

    partition_date = canonical_bars[0].session_date

    if any(bar.session_date != partition_date for bar in canonical_bars):
        raise ValueError("market_revision_multiple_partitions")

    # captured_at 表示 Karkinos 实际完成本次数据观察的时间。
    # 同一个 revision 可以来自不同 capture，但一次 materialization
    # 中的所有记录必须明确绑定当前 Capture。
    if any(bar.captured_at != capture.completed_at for bar in canonical_bars):
        raise ValueError("market_revision_capture_time_mismatch")

    table = daily_bars_to_table(canonical_bars)

    content_fingerprint = daily_bar_content_fingerprint(table)

    artifact = materialize_parquet(
        store,
        table,
        expected_schema=DAILY_BAR_SCHEMA,
    )

    first_event_time = min(bar.event_time for bar in canonical_bars)
    last_event_time = max(bar.event_time for bar in canonical_bars)

    revision_payload = {
        "schema_version": (MARKET_REVISION_SCHEMA_VERSION),
        "provider": provider,
        "kind": MARKET_DATA_KIND_DAILY_BARS,
        "partition_date": (partition_date.isoformat()),
        "market_schema_version": (DAILY_BAR_SCHEMA_VERSION),
        "content_fingerprint": (content_fingerprint),
        "row_count": len(canonical_bars),
        "first_event_time": (first_event_time.isoformat()),
        "last_event_time": (last_event_time.isoformat()),
    }

    revision_manifest_ref = store.put_bytes(
        _canonical_json(revision_payload).encode("utf-8")
    )

    revision = MarketRevision(
        ref=MarketRevisionRef(
            manifest_ref=revision_manifest_ref,
        ),
        provider=provider,
        kind=MARKET_DATA_KIND_DAILY_BARS,
        partition_date=partition_date,
        market_schema_version=(DAILY_BAR_SCHEMA_VERSION),
        content_fingerprint=(content_fingerprint),
        row_count=len(canonical_bars),
        first_event_time=first_event_time,
        last_event_time=last_event_time,
    )

    materialization_payload = {
        "schema_version": (MARKET_REVISION_MATERIALIZATION_SCHEMA_VERSION),
        "revision_id": revision.ref.revision_id,
        "revision_manifest": _object_ref_payload(revision.ref.manifest_ref),
        "capture_id": capture.capture_id,
        "capture_manifest": _object_ref_payload(capture.capture_ref),
        "artifact": _parquet_artifact_payload(artifact),
        "normalizer_version": (normalizer_version),
    }

    materialization_manifest_ref = store.put_bytes(
        _canonical_json(materialization_payload).encode("utf-8")
    )

    materialization = MarketRevisionMaterialization(
        manifest_ref=(materialization_manifest_ref),
        revision_ref=revision.ref,
        capture_ref=capture.capture_ref,
        artifact=artifact,
        normalizer_version=normalizer_version,
    )

    logger.info(
        "Market Revision 已固化 "
        "provider=%s partition=%s revision_id=%s "
        "materialization_id=%s capture_id=%s rows=%d",
        revision.provider,
        revision.partition_date.isoformat(),
        revision.ref.revision_id,
        materialization.materialization_id,
        capture.capture_id,
        revision.row_count,
    )

    return revision, materialization


def daily_bar_content_fingerprint(
    table: pa.Table,
) -> str:
    """计算 canonical 日线市场事实的逻辑内容身份。

    这里故意不包含：

    - available_at
    - captured_at

    因为它们属于“什么时候知道这些事实”的 provenance，
    不属于“这些市场事实本身是哪一版”。

    例如同一批行情在 10:00 和 10:05 被重复抓取：

        Capture C1 != Capture C2

    但只要市场事实没有变化：

        Revision R1 == Revision R1
    """
    if not isinstance(table, pa.Table):
        raise TypeError("market_revision_table_must_be_arrow_table")

    if not table.schema.equals(
        DAILY_BAR_SCHEMA,
        check_metadata=True,
    ):
        raise ValueError("market_revision_daily_bar_schema_mismatch")

    rows: list[dict[str, object]] = []

    for row in table.to_pylist():
        rows.append(
            {
                "symbol": row["symbol"],
                "instrument_type": (row["instrument_type"]),
                "session_date": (row["session_date"].isoformat()),
                "event_time": (row["event_time"].isoformat()),
                "open": _decimal_text(row["open"]),
                "high": _decimal_text(row["high"]),
                "low": _decimal_text(row["low"]),
                "close": _decimal_text(row["close"]),
                "volume": _decimal_text(row["volume"]),
                "amount": _decimal_text(row["amount"]),
                "suspended": row["suspended"],
            }
        )

    payload = {
        "market_schema_version": (DAILY_BAR_SCHEMA_VERSION),
        "rows": rows,
    }

    return object_id_from_bytes(_canonical_json(payload).encode("utf-8"))


def read_market_revision(
    store: ContentAddressedObjectStore,
    ref: MarketRevisionRef,
) -> MarketRevision:
    """读取并验证 MarketRevision Manifest。"""
    manifest_bytes = store.read_bytes(ref.manifest_ref)

    payload = _load_json_object(
        manifest_bytes,
        error="market_revision_manifest_invalid",
    )

    if payload.get("schema_version") != MARKET_REVISION_SCHEMA_VERSION:
        raise MarketRevisionIntegrityError("market_revision_schema_version_unsupported")

    try:
        provider = _require_non_empty_text(
            payload["provider"],
            field="provider",
        )

        kind = str(payload["kind"])

        if kind != MARKET_DATA_KIND_DAILY_BARS:
            raise MarketRevisionIntegrityError("market_revision_kind_unsupported")

        partition_date = date.fromisoformat(payload["partition_date"])

        market_schema_version = str(payload["market_schema_version"])

        if market_schema_version != DAILY_BAR_SCHEMA_VERSION:
            raise MarketRevisionIntegrityError(
                "market_revision_market_schema_unsupported"
            )

        content_fingerprint = str(payload["content_fingerprint"])

        _require_sha256_id(
            content_fingerprint,
            field="content_fingerprint",
        )

        row_count = payload["row_count"]

        if (
            isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count <= 0
        ):
            raise MarketRevisionIntegrityError("market_revision_row_count_invalid")

        first_event_time = datetime.fromisoformat(payload["first_event_time"])
        last_event_time = datetime.fromisoformat(payload["last_event_time"])

        if (
            first_event_time.tzinfo is None
            or last_event_time.tzinfo is None
            or first_event_time > last_event_time
        ):
            raise MarketRevisionIntegrityError("market_revision_event_range_invalid")

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        if isinstance(
            exc,
            MarketRevisionIntegrityError,
        ):
            raise

        raise MarketRevisionIntegrityError("market_revision_manifest_invalid") from exc

    return MarketRevision(
        ref=ref,
        provider=provider,
        kind=kind,
        partition_date=partition_date,
        market_schema_version=(market_schema_version),
        content_fingerprint=(content_fingerprint),
        row_count=row_count,
        first_event_time=first_event_time,
        last_event_time=last_event_time,
    )


def read_market_revision_materialization(
    store: ContentAddressedObjectStore,
    manifest_ref: ObjectRef,
) -> MarketRevisionMaterialization:
    """读取并验证 Revision Materialization Manifest。"""
    manifest_bytes = store.read_bytes(manifest_ref)

    payload = _load_json_object(
        manifest_bytes,
        error=("market_revision_materialization_manifest_invalid"),
    )

    if payload.get("schema_version") != MARKET_REVISION_MATERIALIZATION_SCHEMA_VERSION:
        raise MarketRevisionIntegrityError(
            "market_revision_materialization_schema_unsupported"
        )

    try:
        revision_manifest_ref = _object_ref_from_payload(payload["revision_manifest"])

        revision_ref = MarketRevisionRef(manifest_ref=revision_manifest_ref)

        if payload["revision_id"] != revision_ref.revision_id:
            raise MarketRevisionIntegrityError(
                "market_revision_materialization_revision_mismatch"
            )

        capture_ref = _object_ref_from_payload(payload["capture_manifest"])

        if payload["capture_id"] != capture_ref.object_id:
            raise MarketRevisionIntegrityError(
                "market_revision_materialization_capture_mismatch"
            )

        artifact = _parquet_artifact_from_payload(payload["artifact"])

        normalizer_version = _require_non_empty_text(
            payload["normalizer_version"],
            field="normalizer_version",
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        if isinstance(
            exc,
            MarketRevisionIntegrityError,
        ):
            raise

        raise MarketRevisionIntegrityError(
            "market_revision_materialization_manifest_invalid"
        ) from exc

    return MarketRevisionMaterialization(
        manifest_ref=manifest_ref,
        revision_ref=revision_ref,
        capture_ref=capture_ref,
        artifact=artifact,
        normalizer_version=normalizer_version,
    )


def validate_daily_bar_materialization(
    store: ContentAddressedObjectStore,
    *,
    revision: MarketRevision,
    materialization: MarketRevisionMaterialization,
) -> None:
    """验证物化数据、Capture 与逻辑 Revision 是否完全一致。

    成功时不返回值；任何不一致都 fail closed。
    """
    if materialization.revision_ref != revision.ref:
        raise MarketRevisionIntegrityError(
            "market_revision_materialization_revision_mismatch"
        )

    capture = read_provider_capture(
        store,
        materialization.capture_ref,
    )

    if capture.provider != revision.provider:
        raise MarketRevisionIntegrityError("market_revision_provider_mismatch")

    table = read_parquet(
        store,
        materialization.artifact,
        expected_schema=DAILY_BAR_SCHEMA,
    )

    if table.num_rows != revision.row_count:
        raise MarketRevisionIntegrityError("market_revision_row_count_mismatch")

    actual_fingerprint = daily_bar_content_fingerprint(table)

    if actual_fingerprint != revision.content_fingerprint:
        raise MarketRevisionIntegrityError(
            "market_revision_content_fingerprint_mismatch"
        )

    bars = daily_bars_from_table(table)

    if any(bar.session_date != revision.partition_date for bar in bars):
        raise MarketRevisionIntegrityError("market_revision_partition_mismatch")

    if any(bar.captured_at != capture.completed_at for bar in bars):
        raise MarketRevisionIntegrityError("market_revision_capture_time_mismatch")

    first_event_time = min(bar.event_time for bar in bars)
    last_event_time = max(bar.event_time for bar in bars)

    if (
        first_event_time != revision.first_event_time
        or last_event_time != revision.last_event_time
    ):
        raise MarketRevisionIntegrityError("market_revision_event_range_mismatch")


def _canonical_json(
    value: Any,
) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("market_revision_value_not_json_serializable") from exc


def _load_json_object(
    data: bytes,
    *,
    error: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise MarketRevisionIntegrityError(error) from exc

    if not isinstance(payload, dict):
        raise MarketRevisionIntegrityError(error)

    return payload


def _decimal_text(
    value: Decimal,
) -> str:
    if not isinstance(value, Decimal):
        raise TypeError("market_revision_decimal_expected")

    return format(value, "f")


def _object_ref_payload(
    ref: ObjectRef,
) -> dict[str, object]:
    return {
        "object_id": ref.object_id,
        "size_bytes": ref.size_bytes,
    }


def _object_ref_from_payload(
    value: Any,
) -> ObjectRef:
    if not isinstance(value, dict):
        raise MarketRevisionIntegrityError("market_revision_object_ref_invalid")

    try:
        return ObjectRef(
            object_id=value["object_id"],
            size_bytes=value["size_bytes"],
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise MarketRevisionIntegrityError(
            "market_revision_object_ref_invalid"
        ) from exc


def _parquet_artifact_payload(
    artifact: ParquetArtifact,
) -> dict[str, object]:
    return {
        "object_ref": _object_ref_payload(artifact.object_ref),
        "row_count": artifact.row_count,
        "column_count": artifact.column_count,
        "schema_fingerprint": (artifact.schema_fingerprint),
        "serialization_profile": (artifact.serialization_profile),
        "writer_version": (artifact.writer_version),
    }


def _parquet_artifact_from_payload(
    value: Any,
) -> ParquetArtifact:
    if not isinstance(value, dict):
        raise MarketRevisionIntegrityError("market_revision_parquet_artifact_invalid")

    try:
        return ParquetArtifact(
            object_ref=_object_ref_from_payload(value["object_ref"]),
            row_count=value["row_count"],
            column_count=value["column_count"],
            schema_fingerprint=(value["schema_fingerprint"]),
            serialization_profile=(value["serialization_profile"]),
            writer_version=(value["writer_version"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise MarketRevisionIntegrityError(
            "market_revision_parquet_artifact_invalid"
        ) from exc


def _require_non_empty_text(
    value: Any,
    *,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"market_revision_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"market_revision_{field}_missing")

    return normalized


def _require_sha256_id(
    value: str,
    *,
    field: str,
) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != len("sha256:") + 64
        or any(char not in "0123456789abcdef" for char in value.removeprefix("sha256:"))
    ):
        raise MarketRevisionIntegrityError(f"market_revision_{field}_invalid")
