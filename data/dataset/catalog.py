"""Dataset Catalog：不可变 DatasetRef 的可重建索引。

Dataset 的事实来源始终是：

    DatasetRef
        ↓
    immutable Dataset Manifest
        ↓
    ObjectStore

Catalog 只是为了发现、查询和浏览已经发布的 Dataset。

它不是 Dataset identity 的组成部分，也不能修改 Dataset Manifest。
Catalog 删除或重建以后，同一个 DatasetRef 仍然可以完全离线 replay。

职责：

    DatasetRef
        ↓
    validate manifest
        ↓
    extract searchable metadata
        ↓
    SQLite index

本模块不负责：

- 生成 DatasetRef；
- 执行 PIT Resolver；
- 修改 Dataset Manifest；
- 读取 Market Data；
- 访问 Provider；
- 定义“当前最新数据就是研究输入”。

Research 必须显式绑定 DatasetRef。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from data.dataset.manifest import (
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import (
    DATASET_KIND_DAILY_BARS,
    DatasetRef,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
)

_DATASET_CATALOG_SCHEMA_VERSION = 1


class DatasetCatalogError(RuntimeError):
    """Dataset Catalog 基础异常。"""


class DatasetCatalogIntegrityError(DatasetCatalogError):
    """Catalog 中的索引记录不可信。"""


class DatasetCatalogNotFoundError(DatasetCatalogError):
    """Catalog 中不存在请求的 Dataset。"""


@dataclass(frozen=True, slots=True)
class DatasetCatalogEntry:
    """一条可搜索的 Dataset Catalog 索引记录。

    这些字段都是 Dataset Manifest 的派生 metadata。

    registered_at 只是 Catalog operational metadata，
    不属于 Dataset identity。
    """

    ref: DatasetRef

    kind: str

    start_date: date
    end_date: date

    cutoff: datetime

    resolver_policy_id: str
    market_schema_version: str

    instrument_count: int
    partition_count: int

    registered_at: datetime


class DatasetCatalog:
    """本地 DatasetRef SQLite 索引。"""

    def __init__(
        self,
        root: str | Path,
    ) -> None:
        self._root = Path(root)

        self._path = self._root / "catalog" / "datasets.sqlite3"

    @property
    def root(self) -> Path:
        return self._root

    @property
    def path(self) -> Path:
        return self._path

    def register(
        self,
        store: ContentAddressedObjectStore,
        ref: DatasetRef,
        *,
        registered_at: datetime | None = None,
    ) -> DatasetCatalogEntry:
        """验证并登记一个已经发布的 DatasetRef。

        register 不会创建 Dataset，也不会修改 Manifest。

        同一个 DatasetRef 重复登记是幂等操作。
        第一次登记的 registered_at 会被保留。
        """
        if not isinstance(
            store,
            ContentAddressedObjectStore,
        ):
            raise TypeError("dataset_catalog_store_invalid")

        if not isinstance(
            ref,
            DatasetRef,
        ):
            raise TypeError("dataset_catalog_ref_invalid")

        registered_at = _utc_instant(
            (
                registered_at
                if registered_at is not None
                else datetime.now(timezone.utc)
            ),
            field="registered_at",
        )

        # Catalog 只能索引能够完整读取的 Dataset Manifest。
        snapshot = read_daily_bar_dataset_manifest(
            store,
            ref,
        )

        entry = DatasetCatalogEntry(
            ref=ref,
            kind=snapshot.kind,
            start_date=snapshot.start_date,
            end_date=snapshot.end_date,
            cutoff=snapshot.cutoff,
            resolver_policy_id=(snapshot.resolver_policy_id),
            market_schema_version=(snapshot.market_schema_version),
            instrument_count=(snapshot.instrument_count),
            partition_count=(snapshot.partition_count),
            registered_at=registered_at,
        )

        self._ensure_schema()

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                """
                SELECT
                    dataset_id,
                    manifest_size_bytes,
                    kind,
                    start_date,
                    end_date,
                    cutoff,
                    resolver_policy_id,
                    market_schema_version,
                    instrument_count,
                    partition_count,
                    registered_at
                FROM dataset_catalog
                WHERE dataset_id = ?
                """,
                (ref.dataset_id,),
            ).fetchone()

            if existing is not None:
                stored = _entry_from_row(existing)

                _validate_same_dataset_entry(
                    stored,
                    entry,
                )

                connection.commit()

                # registered_at 属于首次登记 metadata。
                return stored

            connection.execute(
                """
                INSERT INTO dataset_catalog (
                    dataset_id,
                    manifest_size_bytes,
                    kind,
                    start_date,
                    end_date,
                    cutoff,
                    resolver_policy_id,
                    market_schema_version,
                    instrument_count,
                    partition_count,
                    registered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.ref.dataset_id,
                    (entry.ref.manifest_ref.size_bytes),
                    entry.kind,
                    entry.start_date.isoformat(),
                    entry.end_date.isoformat(),
                    _format_utc_instant(entry.cutoff),
                    entry.resolver_policy_id,
                    entry.market_schema_version,
                    entry.instrument_count,
                    entry.partition_count,
                    _format_utc_instant(entry.registered_at),
                ),
            )

            connection.commit()

        return entry

    def get(
        self,
        dataset_id: str,
    ) -> DatasetCatalogEntry:
        """通过 Dataset content id 查询 Catalog metadata。"""
        dataset_id = _require_content_id(dataset_id)

        self._require_catalog()

        with closing(self._connect(read_only=True)) as connection:
            row = connection.execute(
                """
                SELECT
                    dataset_id,
                    manifest_size_bytes,
                    kind,
                    start_date,
                    end_date,
                    cutoff,
                    resolver_policy_id,
                    market_schema_version,
                    instrument_count,
                    partition_count,
                    registered_at
                FROM dataset_catalog
                WHERE dataset_id = ?
                """,
                (dataset_id,),
            ).fetchone()

        if row is None:
            raise DatasetCatalogNotFoundError(f"dataset_catalog_not_found:{dataset_id}")

        return _entry_from_row(row)

    def list_daily_bar_datasets(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        cutoff_lte: datetime | None = None,
        resolver_policy_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[
        DatasetCatalogEntry,
        ...,
    ]:
        """查询已登记的 Daily Bar Dataset。

        默认排序：

            cutoff DESC
            dataset_id ASC

        因此查询结果稳定，但不会隐式把第一条当作 Research 输入。
        """
        self._require_catalog()

        clauses = [
            "kind = ?",
        ]
        parameters: list[object] = [
            DATASET_KIND_DAILY_BARS,
        ]

        if start_date is not None:
            start_date = _require_date(
                start_date,
                field="start_date",
            )

            clauses.append("start_date >= ?")
            parameters.append(start_date.isoformat())

        if end_date is not None:
            end_date = _require_date(
                end_date,
                field="end_date",
            )

            clauses.append("end_date <= ?")
            parameters.append(end_date.isoformat())

        if cutoff_lte is not None:
            cutoff_lte = _utc_instant(
                cutoff_lte,
                field="cutoff_lte",
            )

            clauses.append("cutoff <= ?")
            parameters.append(_format_utc_instant(cutoff_lte))

        if resolver_policy_id is not None:
            resolver_policy_id = _require_non_empty_text(
                resolver_policy_id,
                field=("resolver_policy_id"),
            )

            clauses.append("resolver_policy_id = ?")
            parameters.append(resolver_policy_id)

        if limit is not None:
            if isinstance(limit, bool) or not isinstance(
                limit,
                int,
            ):
                raise TypeError("dataset_catalog_limit_must_be_int")

            if limit <= 0:
                raise ValueError("dataset_catalog_limit_invalid")

        sql = f"""
            SELECT
                dataset_id,
                manifest_size_bytes,
                kind,
                start_date,
                end_date,
                cutoff,
                resolver_policy_id,
                market_schema_version,
                instrument_count,
                partition_count,
                registered_at
            FROM dataset_catalog
            WHERE {" AND ".join(clauses)}
            ORDER BY cutoff DESC, dataset_id ASC
        """

        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)

        with closing(self._connect(read_only=True)) as connection:
            rows = connection.execute(
                sql,
                tuple(parameters),
            ).fetchall()

        return tuple(_entry_from_row(row) for row in rows)

    def contains(
        self,
        dataset_id: str,
    ) -> bool:
        """判断 Dataset 是否已经登记。"""
        dataset_id = _require_content_id(dataset_id)

        if not self._path.exists():
            return False

        with closing(self._connect(read_only=True)) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM dataset_catalog
                WHERE dataset_id = ?
                """,
                (dataset_id,),
            ).fetchone()

        return row is not None

    def _ensure_schema(
        self,
    ) -> None:
        self._path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with closing(self._connect()) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS catalog_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS dataset_catalog (
                    dataset_id TEXT PRIMARY KEY,
                    manifest_size_bytes INTEGER NOT NULL,

                    kind TEXT NOT NULL,

                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    cutoff TEXT NOT NULL,

                    resolver_policy_id TEXT NOT NULL,
                    market_schema_version TEXT NOT NULL,

                    instrument_count INTEGER NOT NULL,
                    partition_count INTEGER NOT NULL,

                    registered_at TEXT NOT NULL
                )
                """)

            existing = connection.execute("""
                SELECT value
                FROM catalog_metadata
                WHERE key = 'schema_version'
                """).fetchone()

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO catalog_metadata (
                        key,
                        value
                    )
                    VALUES (
                        'schema_version',
                        ?
                    )
                    """,
                    (str(_DATASET_CATALOG_SCHEMA_VERSION),),
                )

            elif existing[0] != str(_DATASET_CATALOG_SCHEMA_VERSION):
                raise DatasetCatalogIntegrityError("dataset_catalog_schema_unsupported")

            connection.commit()

    def _require_catalog(
        self,
    ) -> None:
        if not self._path.exists():
            raise DatasetCatalogNotFoundError("dataset_catalog_missing")

        # 即使只读，也先确认 schema version。
        with closing(self._connect(read_only=True)) as connection:
            try:
                row = connection.execute("""
                    SELECT value
                    FROM catalog_metadata
                    WHERE key = 'schema_version'
                    """).fetchone()
            except sqlite3.DatabaseError as exc:
                raise DatasetCatalogIntegrityError("dataset_catalog_invalid") from exc

        if row is None:
            raise DatasetCatalogIntegrityError("dataset_catalog_schema_missing")

        if row[0] != str(_DATASET_CATALOG_SCHEMA_VERSION):
            raise DatasetCatalogIntegrityError("dataset_catalog_schema_unsupported")

    def _connect(
        self,
        *,
        read_only: bool = False,
    ) -> sqlite3.Connection:
        if read_only:
            uri = self._path.resolve().as_uri() + "?mode=ro"

            connection = sqlite3.connect(
                uri,
                uri=True,
            )

        else:
            connection = sqlite3.connect(self._path)

        connection.execute("PRAGMA foreign_keys=ON")

        return connection


def _entry_from_row(
    row,
) -> DatasetCatalogEntry:
    (
        dataset_id,
        manifest_size_bytes,
        kind,
        start_date,
        end_date,
        cutoff,
        resolver_policy_id,
        market_schema_version,
        instrument_count,
        partition_count,
        registered_at,
    ) = row

    try:
        manifest_ref = ObjectRef(
            object_id=dataset_id,
            size_bytes=manifest_size_bytes,
        )

        ref = DatasetRef(manifest_ref=manifest_ref)

        entry = DatasetCatalogEntry(
            ref=ref,
            kind=_require_non_empty_text(
                kind,
                field="kind",
            ),
            start_date=_parse_date(
                start_date,
                field="start_date",
            ),
            end_date=_parse_date(
                end_date,
                field="end_date",
            ),
            cutoff=_parse_utc_instant(
                cutoff,
                field="cutoff",
            ),
            resolver_policy_id=(
                _require_non_empty_text(
                    resolver_policy_id,
                    field=("resolver_policy_id"),
                )
            ),
            market_schema_version=(
                _require_non_empty_text(
                    market_schema_version,
                    field=("market_schema_version"),
                )
            ),
            instrument_count=(
                _require_non_negative_int(
                    instrument_count,
                    field=("instrument_count"),
                )
            ),
            partition_count=(
                _require_non_negative_int(
                    partition_count,
                    field=("partition_count"),
                )
            ),
            registered_at=(
                _parse_utc_instant(
                    registered_at,
                    field="registered_at",
                )
            ),
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise DatasetCatalogIntegrityError("dataset_catalog_entry_invalid") from exc

    if entry.start_date > entry.end_date:
        raise DatasetCatalogIntegrityError("dataset_catalog_entry_date_range_invalid")

    return entry


def _validate_same_dataset_entry(
    stored: DatasetCatalogEntry,
    incoming: DatasetCatalogEntry,
) -> None:
    """防止同一个 DatasetRef 在 Catalog 中出现冲突 metadata。"""
    if (
        stored.ref != incoming.ref
        or stored.kind != incoming.kind
        or stored.start_date != incoming.start_date
        or stored.end_date != incoming.end_date
        or stored.cutoff != incoming.cutoff
        or stored.resolver_policy_id != incoming.resolver_policy_id
        or stored.market_schema_version != incoming.market_schema_version
        or stored.instrument_count != incoming.instrument_count
        or stored.partition_count != incoming.partition_count
    ):
        raise DatasetCatalogIntegrityError("dataset_catalog_entry_conflict")


def _require_content_id(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError("dataset_catalog_dataset_id_must_be_text")

    if not value.startswith("sha256:"):
        raise ValueError("dataset_catalog_dataset_id_invalid")

    digest = value.removeprefix("sha256:")

    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("dataset_catalog_dataset_id_invalid")

    return value


def _require_date(
    value: date,
    *,
    field: str,
) -> date:
    if isinstance(
        value,
        datetime,
    ) or not isinstance(
        value,
        date,
    ):
        raise TypeError(f"dataset_catalog_{field}_must_be_date")

    return value


def _parse_date(
    value: object,
    *,
    field: str,
) -> date:
    if not isinstance(
        value,
        str,
    ):
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid")

    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid") from exc

    if result.isoformat() != value:
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid")

    return result


def _utc_instant(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(f"dataset_catalog_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"dataset_catalog_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


def _format_utc_instant(
    value: datetime,
) -> str:
    value = _utc_instant(
        value,
        field="timestamp",
    )

    return value.isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _parse_utc_instant(
    value: object,
    *,
    field: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid")

    if not value.endswith("Z"):
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid")

    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid") from exc

    result = result.astimezone(timezone.utc)

    if _format_utc_instant(result) != value:
        raise DatasetCatalogIntegrityError(f"dataset_catalog_{field}_invalid")

    return result


def _require_non_empty_text(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(f"dataset_catalog_{field}_must_be_text")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"dataset_catalog_{field}_missing")

    return normalized


def _require_non_negative_int(
    value: object,
    *,
    field: str,
) -> int:
    if isinstance(value, bool) or not isinstance(
        value,
        int,
    ):
        raise TypeError(f"dataset_catalog_{field}_must_be_int")

    if value < 0:
        raise ValueError(f"dataset_catalog_{field}_invalid")

    return value
