"""日线采集、数据集发布与离线重放的集成测试。

只替换外部 TDX SDK，并注入固定时钟；标准化、质量评估、不可变存储、
Dataset 解析与发布、Catalog 和 Serving 均使用真实实现。
这些测试不验证真实 TDX 认证，也不代替回测逐决策时点的可用性检查。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.model import DatasetRef
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    DailyBarResolutionCandidate,
    DatasetPartitionUnresolvedError,
    resolve_daily_bar_dataset,
)
from data.market.capture import read_provider_capture, read_provider_raw_payload
from data.market.contracts import DailyBarRequest
from data.market.ingestion import (
    DailyBarIngestionNoData,
    DailyBarIngestionResult,
    ingest_daily_bars,
)
from data.market.quality import (
    RESEARCH_STRICT_DAILY,
    MarketQualityDiagnosticKind,
    MarketQualityStatus,
)
from data.market.schema import DAILY_BAR_SCHEMA
from data.market.serving import MarketServingStore
from data.providers.tdx import TdxDailyBarProvider
from data.storage.objects import ContentAddressedObjectStore

_DAY = date(2026, 9, 15)
_DAYS = (date(2026, 9, 14), _DAY)
_UNIVERSE = (
    InstrumentKey(symbol="000001", instrument_type=InstrumentType.STOCK),
    InstrumentKey(symbol="600000", instrument_type=InstrumentType.STOCK),
)
_FIELDS = ("Open", "High", "Low", "Close", "Volume", "Amount")
_POLICY = DailyBarDatasetResolverPolicy(
    policy_id="karkinos.dataset.pit.strict.v1",
    provider_priority=("tdx",),
    required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
)


def _instant(session_date: date, hour: int = 7, minute: int = 3) -> datetime:
    return datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        hour,
        minute,
        tzinfo=timezone.utc,
    )


def _response(
    session_date: date,
    *,
    close: float = 10.48,
    missing_instrument: bool = False,
) -> dict[str, pd.DataFrame]:
    # 返回顺序故意与 canonical 标的顺序相反，避免读取顺序碰巧正确。
    values = {"600000.SH": (10.31, 10.52, 10.20, close, 123456, 128.391242)}
    if not missing_instrument:
        values["000001.SZ"] = (12.10, 12.50, 12.00, 12.34, 100000, 123.4)
    return {
        field: pd.DataFrame(
            [[row[index] for row in values.values()]],
            index=[session_date.isoformat()],
            columns=list(values),
        )
        for index, field in enumerate(_FIELDS)
    }


class FakeTdxClient:
    """只模拟一次 SDK 返回，不替换 Provider 或任何下游模块。"""

    def __init__(self, response: dict[str, pd.DataFrame]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get_market_data(self, **kwargs: object) -> dict[str, pd.DataFrame]:
        self.calls.append(kwargs)
        return self.response


def _ingest(
    store: ContentAddressedObjectStore,
    session_date: date = _DAY,
    *,
    captured_at: datetime | None = None,
    close: float = 10.48,
    missing_instrument: bool = False,
    empty: bool = False,
) -> DailyBarIngestionResult:
    completed_at = captured_at if captured_at is not None else _instant(session_date)
    response = (
        {field: pd.DataFrame() for field in _FIELDS}
        if empty
        else _response(session_date, close=close, missing_instrument=missing_instrument)
    )
    client = FakeTdxClient(response)
    times = iter((completed_at - timedelta(seconds=1), completed_at))
    provider = TdxDailyBarProvider(client, clock=times.__next__)
    result = ingest_daily_bars(
        provider,
        store,
        request=DailyBarRequest(
            instruments=_UNIVERSE,
            start_date=session_date,
            end_date=session_date,
        ),
        quality_policy=RESEARCH_STRICT_DAILY,
        normalizer_version="karkinos.market.normalize.v1",
        checked_at=completed_at + timedelta(seconds=1),
    )
    assert len(client.calls) == 1
    assert client.calls[0]["dividend_type"] == "none"
    assert client.calls[0]["fill_data"] is False
    return result


def _publish(
    store: ContentAddressedObjectStore,
    catalog: DatasetCatalog,
    results: tuple[DailyBarIngestionResult, ...],
    *,
    days: tuple[date, ...] = (_DAY,),
    cutoff: datetime = _instant(_DAY, 8, 0),
) -> DatasetRef:
    # 必须使用 ingestion 实际产生的质量报告，不能手工构造 PASS。
    snapshot = resolve_daily_bar_dataset(
        store,
        candidates=tuple(
            DailyBarResolutionCandidate(
                revision=result.revision,
                materialization=result.materialization,
                quality=result.quality,
            )
            for result in results
        ),
        start_date=days[0],
        end_date=days[-1],
        cutoff=cutoff,
        instruments=_UNIVERSE,
        expected_partition_dates=days,
        policy=_POLICY,
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    catalog.register(store, ref, registered_at=cutoff + timedelta(seconds=30))
    return ref


_OFFLINE_REPLAY = """\
import json
import socket
import sys


def deny_network(*args, **kwargs):
    raise AssertionError("offline replay must not access the network")


socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.getaddrinfo = deny_network

from data.dataset.catalog import DatasetCatalog
from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.storage.objects import ContentAddressedObjectStore

store = ContentAddressedObjectStore(sys.argv[1])
if sys.argv[3] == "-":
    ref = DatasetRef(manifest_ref=store.resolve_ref(sys.argv[2]))
else:
    ref = DatasetCatalog(sys.argv[3]).get(sys.argv[2]).ref
result = read_daily_bar_dataset(store, ref)
print(json.dumps({"dataset_id": ref.dataset_id, "rows": result.table.to_pylist()},
                 default=str, sort_keys=True))
"""


def _replay_in_new_process(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
    *,
    catalog: DatasetCatalog | None = None,
) -> dict[str, object]:
    # 新进程只接收磁盘路径和内容 ID，不继承候选、报告或存储实例。
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _OFFLINE_REPLAY,
            str(store.root),
            ref.dataset_id,
            str(catalog.root) if catalog is not None else "-",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def test_multi_session_pipeline_replays_without_network_or_projections(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    serving = MarketServingStore(tmp_path / "market")
    results = tuple(_ingest(store, day) for day in _DAYS)

    for result in results:
        assert result.quality.status is MarketQualityStatus.PASS
        assert result.quality.diagnostics == ()
        assert result.quality.revision_id == result.revision.ref.revision_id
        assert (
            result.quality.materialization_id
            == result.materialization.materialization_id
        )
        capture = read_provider_capture(store, result.materialization.capture_ref)
        assert capture == result.capture
        raw = json.loads(read_provider_raw_payload(store, capture))
        assert raw["fields"]["Amount"]["data"] == [[128.391242, 123.4]]
        applied = serving.apply_daily_bar_revision(
            store, revision=result.revision, materialization=result.materialization
        )
        assert applied.inserted_count == len(_UNIVERSE)

    ref = _publish(store, catalog, tuple(reversed(results)), days=_DAYS)
    # 候选顺序和重复发布不能改变数据集身份，也不能重复登记。
    assert _publish(store, catalog, results, days=_DAYS) == ref
    assert tuple(entry.ref for entry in catalog.list_daily_bar_datasets()) == (ref,)
    replayed = read_daily_bar_dataset(store, catalog.get(ref.dataset_id).ref)
    assert replayed.row_count == 4
    assert replayed.table.schema.equals(DAILY_BAR_SCHEMA, check_metadata=True)
    assert [(bar.session_date, bar.instrument) for bar in replayed.bars] == [
        (day, instrument) for day in _DAYS for instrument in _UNIVERSE
    ]
    expected_numbers = {
        "000001": ("12.10", "12.50", "12.00", "12.34", "100000", "1234000"),
        "600000": ("10.31", "10.52", "10.20", "10.48", "123456", "1283912.42"),
    }
    for bar in replayed.bars:
        numbers = (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount)
        assert numbers == tuple(
            Decimal(value) for value in expected_numbers[bar.instrument.symbol]
        )
        assert bar.event_time == _instant(bar.session_date, 7, 0)
        assert bar.available_at == bar.captured_at == _instant(bar.session_date)
        assert bar.suspended is False
    assert [partition.revision_id for partition in replayed.snapshot.partitions] == [
        result.revision.ref.revision_id for result in results
    ]
    assert [
        partition.materialization_id for partition in replayed.snapshot.partitions
    ] == [result.materialization.materialization_id for result in results]

    expected = json.loads(
        json.dumps(
            {"dataset_id": ref.dataset_id, "rows": replayed.table.to_pylist()},
            default=str,
        )
    )
    assert _replay_in_new_process(store, ref, catalog=catalog) == expected
    catalog.path.unlink()
    serving.path.unlink()
    assert _replay_in_new_process(store, ref) == expected


def test_correction_updates_serving_but_preserves_published_dataset(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    serving = MarketServingStore(tmp_path / "market")
    original = _ingest(store)
    old_ref = _publish(store, catalog, (original,))
    old_bytes = store.read_bytes(old_ref.manifest_ref)
    before = read_daily_bar_dataset(store, old_ref)
    serving.apply_daily_bar_revision(
        store, revision=original.revision, materialization=original.materialization
    )

    corrected = _ingest(store, captured_at=_instant(_DAY, 9, 3), close=10.49)
    assert corrected.quality.status is MarketQualityStatus.PASS
    assert corrected.revision.ref != original.revision.ref
    applied = serving.apply_daily_bar_revision(
        store, revision=corrected.revision, materialization=corrected.materialization
    )
    assert applied.updated_count == 2
    current = serving.read_daily_bars(
        provider="tdx", start_date=_DAY, end_date=_DAY, instruments=(_UNIVERSE[1],)
    )
    assert current[0].close == Decimal("10.49")

    candidates = (corrected, original)
    assert _publish(store, catalog, candidates) == old_ref
    new_ref = _publish(store, catalog, candidates, cutoff=_instant(_DAY, 10, 0))
    assert new_ref != old_ref
    assert read_daily_bar_dataset(store, new_ref).bars[1].close == Decimal("10.49")
    assert store.read_bytes(old_ref.manifest_ref) == old_bytes
    restored = read_daily_bar_dataset(ContentAddressedObjectStore(store.root), old_ref)
    assert restored == before
    assert before.bars[1].close == Decimal("10.48")


def test_recapture_reuses_revision_without_rewriting_original_materialization(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    original = _ingest(store)
    ref = _publish(store, catalog, (original,))
    later = _ingest(store, captured_at=_instant(_DAY, 9, 3))
    assert later.capture.raw_object_ref == original.capture.raw_object_ref
    assert later.capture.capture_id != original.capture.capture_id
    assert later.revision.ref == original.revision.ref
    assert later.materialization.manifest_ref != original.materialization.manifest_ref
    assert _publish(store, catalog, (later, original)) == ref
    assert all(
        bar.captured_at == original.capture.completed_at
        for bar in read_daily_bar_dataset(store, ref).bars
    )


def test_real_quality_gate_blocks_incomplete_universe_and_retains_evidence(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    incomplete = _ingest(store, missing_instrument=True)
    assert incomplete.quality.status is MarketQualityStatus.BLOCKED
    assert incomplete.eligible_for_dataset_publication is False
    assert any(
        diagnostic.kind is MarketQualityDiagnosticKind.MISSING_INSTRUMENT
        and diagnostic.instrument == _UNIVERSE[0]
        for diagnostic in incomplete.quality.diagnostics
    )
    with pytest.raises(DatasetPartitionUnresolvedError) as caught:
        _publish(store, catalog, (incomplete,))
    assert caught.value.partition_date == _DAY
    assert not catalog.path.exists()
    assert store.verify(incomplete.capture.raw_object_ref)
    assert store.verify(incomplete.revision.ref.manifest_ref)
    assert store.verify(incomplete.materialization.artifact.object_ref)


def test_empty_session_preserves_capture_and_missing_partition_can_be_backfilled(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    first = _ingest(store, _DAYS[0])
    with pytest.raises(DailyBarIngestionNoData) as empty:
        _ingest(store, empty=True)
    capture = read_provider_capture(store, empty.value.capture.capture_ref)
    assert capture.record_count == 0
    raw = json.loads(read_provider_raw_payload(store, capture))
    assert all(field["data"] == [] for field in raw["fields"].values())
    with pytest.raises(DatasetPartitionUnresolvedError) as missing:
        _publish(store, catalog, (first,), days=_DAYS)
    assert missing.value.partition_date == _DAY
    assert not catalog.path.exists()

    # 只补采缺失日期，不重新采集或改写此前已经落盘的分区。
    second = _ingest(store)
    ref = _publish(store, catalog, (first, second), days=_DAYS)
    replayed = read_daily_bar_dataset(store, ref)
    assert replayed.row_count == 4
    assert replayed.snapshot.partitions[0].revision_id == first.revision.ref.revision_id
    assert store.verify(capture.capture_ref)
    assert store.verify(capture.raw_object_ref)


def test_historical_backfill_does_not_invent_earlier_availability(
    tmp_path: Path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    captured_at = _instant(date(2026, 9, 16), 8, 0)
    backfill = _ingest(store, captured_at=captured_at)
    assert backfill.quality.status is MarketQualityStatus.PASS
    with pytest.raises(DatasetPartitionUnresolvedError):
        _publish(store, catalog, (backfill,))
    with pytest.raises(DatasetPartitionUnresolvedError):
        _publish(
            store, catalog, (backfill,), cutoff=captured_at - timedelta(microseconds=1)
        )
    assert not catalog.path.exists()

    ref = _publish(store, catalog, (backfill,), cutoff=captured_at)
    for bar in read_daily_bar_dataset(store, ref).bars:
        assert bar.event_time == _instant(_DAY, 7, 0)
        assert bar.available_at == bar.captured_at == captured_at


@pytest.mark.parametrize("target", ["dataset_manifest", "materialization", "parquet"])
@pytest.mark.parametrize("damage", ["missing", "corrupted"])
def test_replay_rejects_damaged_published_objects_despite_catalog_entry(
    tmp_path: Path, target: str, damage: str
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")
    catalog = DatasetCatalog(tmp_path / "index")
    results = tuple(_ingest(store, day) for day in _DAYS)
    ref = _publish(store, catalog, results, days=_DAYS)
    objects = {
        "dataset_manifest": ref.manifest_ref,
        "materialization": results[1].materialization.manifest_ref,
        "parquet": results[1].materialization.artifact.object_ref,
    }
    damaged = objects[target]
    path = store.root / "sha256" / damaged.digest[:2] / damaged.digest[2:]
    if damage == "missing":
        path.unlink()
    else:
        # 仅在测试临时目录绕过只读权限，模拟磁盘损坏。
        path.chmod(0o644)
        path.write_bytes(b"damaged object")
    indexed_ref = DatasetCatalog(catalog.root).get(ref.dataset_id).ref
    expected_error = (
        "dataset_reader_manifest_invalid"
        if target == "dataset_manifest"
        else f"dataset_reader_partition_unreadable:{_DAY.isoformat()}"
    )
    # Catalog 仍有记录也不能绕过完整性检查，或只返回未损坏的第一天。
    with pytest.raises(DatasetReaderIntegrityError, match=expected_error):
        read_daily_bar_dataset(ContentAddressedObjectStore(store.root), indexed_ref)
