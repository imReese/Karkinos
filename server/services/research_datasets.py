"""供项目运行时使用的持久研究数据：准备、发现及离线读取。

复用已有的对象存储、Dataset Catalog 和行情投影；不再创建另一套行情库。
每个成功交易日先发布检查点，中途失败不会丢掉已完成的采集。研究只绑定
最终发布的数据集，检查点不是隐式的回测输入。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetSnapshot, DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    DailyBarResolutionCandidate,
    resolve_daily_bar_dataset,
)
from data.market.capture import read_provider_capture
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.market.ingestion import ingest_daily_bars
from data.market.quality import (
    RESEARCH_STRICT_DAILY,
    MarketQualityStatus,
    evaluate_daily_bar_revision,
)
from data.market.revision import (
    MarketRevisionRef,
    read_market_revision,
    read_market_revision_materialization,
)
from data.market.serving import MarketServingStore
from data.providers.tdx_runtime import TdxRuntimeSettings, prepare_tdx_runtime
from data.storage.objects import ContentAddressedObjectStore
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.verified_daily_market_data import (
    is_verified_daily_resolver_policy,
)

_POLICY = DailyBarDatasetResolverPolicy(
    policy_id="karkinos.dataset.pit.strict.v1",
    provider_priority=("tdx",),
    required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
)


class ResearchDatasetError(RuntimeError):
    """只包含可公开的错误码，不携带 SDK 自由文本或凭据。"""


def require_supported_snapshot(snapshot: DailyBarDatasetSnapshot) -> None:
    """Accept the legacy TDX lane and verification-bound v2 daily datasets."""
    legacy_tdx = snapshot.resolver_policy_id == _POLICY.policy_id and all(
        partition.provider == "tdx" for partition in snapshot.partitions
    )
    verified_v2 = snapshot.verification_bound and is_verified_daily_resolver_policy(
        snapshot.resolver_policy_id
    )
    if not legacy_tdx and not verified_v2:
        raise ResearchDatasetError("dataset_provider_or_policy_unsupported")


def dataset_summary(root: Path, ref: DatasetRef) -> dict[str, Any]:
    snapshot = read_daily_bar_dataset_manifest(
        ContentAddressedObjectStore(root / "objects"), ref
    )
    require_supported_snapshot(snapshot)
    return {
        "dataset_id": ref.dataset_id,
        "start_date": snapshot.start_date.isoformat(),
        "end_date": snapshot.end_date.isoformat(),
        "cutoff": snapshot.cutoff.isoformat(),
        "instruments": [
            {"symbol": item.symbol, "instrument_type": item.instrument_type.value}
            for item in snapshot.instruments
        ],
        "partition_count": snapshot.partition_count,
        "price_basis": "unadjusted",
        "point_in_time_verified": False,
        "cross_source_verified": snapshot.verification_bound,
    }


def _candidate_from_checkpoint(
    store: ContentAddressedObjectStore,
    ref: DatasetRef,
    instruments: tuple[InstrumentKey, ...],
) -> DailyBarResolutionCandidate | None:
    snapshot = read_daily_bar_dataset_manifest(store, ref)
    if snapshot.instruments != instruments or len(snapshot.partitions) != 1:
        return None
    require_supported_snapshot(snapshot)
    partition = snapshot.partitions[0]
    revision = read_market_revision(
        store, MarketRevisionRef(store.resolve_ref(partition.revision_id))
    )
    materialization = read_market_revision_materialization(
        store, store.resolve_ref(partition.materialization_id)
    )
    quality = evaluate_daily_bar_revision(
        store,
        revision=revision,
        materialization=materialization,
        policy=RESEARCH_STRICT_DAILY,
        expected_instruments=instruments,
    )
    if quality.status is not MarketQualityStatus.PASS:
        raise ResearchDatasetError("dataset_checkpoint_invalid")
    return DailyBarResolutionCandidate(revision, materialization, quality)


def prepare_daily_dataset(
    root: Path,
    *,
    request: DailyBarRequest,
    dates: tuple[date, ...],
    provider: DailyBarProvider,
    refresh: bool = False,
) -> DatasetRef:
    """逐日保存，再固定整个区间；缺失交易日不能悄悄当作休市。"""
    if not dates or dates != tuple(sorted(set(dates))):
        raise ResearchDatasetError("dataset_calendar_invalid")
    if any(day < request.start_date or day > request.end_date for day in dates):
        raise ResearchDatasetError("dataset_calendar_out_of_range")
    root = root.resolve()
    store = ContentAddressedObjectStore(root / "objects")
    checkpoints = DatasetCatalog(root / "checkpoints")
    serving = MarketServingStore(root)
    candidates = []
    for day in dates:
        cached = []
        if not refresh and checkpoints.path.exists():
            for entry in checkpoints.list_daily_bar_datasets(
                start_date=day, end_date=day, resolver_policy_id=_POLICY.policy_id
            ):
                candidate = _candidate_from_checkpoint(
                    store, entry.ref, request.instruments
                )
                if candidate is not None:
                    cached.append(candidate)
        if cached:
            for candidate in cached:
                serving.apply_daily_bar_revision(
                    store,
                    revision=candidate.revision,
                    materialization=candidate.materialization,
                )
            candidates.extend(cached)
            continue
        result = ingest_daily_bars(
            provider,
            store,
            request=DailyBarRequest(request.instruments, day, day),
            quality_policy=RESEARCH_STRICT_DAILY,
            normalizer_version="karkinos.market.normalize.v1",
        )
        if result.quality.status is not MarketQualityStatus.PASS:
            raise ResearchDatasetError(f"dataset_quality_blocked:{day.isoformat()}")
        candidate = DailyBarResolutionCandidate(
            result.revision, result.materialization, result.quality
        )
        daily = resolve_daily_bar_dataset(
            store,
            candidates=(candidate,),
            start_date=day,
            end_date=day,
            cutoff=result.capture.completed_at,
            instruments=request.instruments,
            expected_partition_dates=(day,),
            policy=_POLICY,
        )
        checkpoints.register(store, publish_daily_bar_dataset_manifest(store, daily))
        serving.apply_daily_bar_revision(
            store, revision=result.revision, materialization=result.materialization
        )
        candidates.append(candidate)

    # 使用已选采集的时间边界，不用每次运行的墙上时间制造新的 Dataset ID。
    cutoff = max(
        read_provider_capture(store, item.materialization.capture_ref).completed_at
        for item in candidates
    )
    snapshot = resolve_daily_bar_dataset(
        store,
        candidates=tuple(candidates),
        start_date=request.start_date,
        end_date=request.end_date,
        cutoff=cutoff,
        instruments=request.instruments,
        expected_partition_dates=dates,
        policy=_POLICY,
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    read_daily_bar_dataset(store, ref)
    DatasetCatalog(root).register(store, ref)
    return ref


class ResearchDatasetService:
    """一个应用实例持有的运行时服务；SDK 的全局单例只进入子进程。"""

    def __init__(self, root: Path, settings: TdxRuntimeSettings) -> None:
        self.root = root.resolve()
        self._settings = settings
        self._lock = Lock()

    def status(self) -> dict[str, Any]:
        catalog = DatasetCatalog(self.root)
        entries = (
            catalog.list_daily_bar_datasets(limit=100) if catalog.path.exists() else ()
        )
        return {
            "tdx_configured": self._settings.configured,
            "storage_path": str(self.root),
            "busy": self._lock.locked(),
            "datasets": [dataset_summary(self.root, item.ref) for item in entries],
        }

    def prepare(
        self,
        request: DailyBarRequest,
        *,
        db: Any,
        config: Any = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        if len(request.instruments) != 1 or request.instruments[
            0
        ].instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
            raise ResearchDatasetError("dataset_single_stock_or_etf_required")
        if (request.end_date - request.start_date).days > 730:
            raise ResearchDatasetError("dataset_range_exceeds_two_years")
        close = datetime.combine(request.end_date, time(15), ZoneInfo("Asia/Shanghai"))
        if close > datetime.now(timezone.utc):
            raise ResearchDatasetError("dataset_session_not_closed")
        if not self._lock.acquire(blocking=False):
            raise ResearchDatasetError("dataset_preparation_busy")
        try:
            # 明确的“准备”动作默认复用已经发布的完整区间；刷新必须另行指定。
            catalog = DatasetCatalog(self.root)
            store = ContentAddressedObjectStore(self.root / "objects")
            if not refresh and catalog.path.exists():
                for entry in catalog.list_daily_bar_datasets(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    resolver_policy_id=_POLICY.policy_id,
                ):
                    if (
                        entry.start_date != request.start_date
                        or entry.end_date != request.end_date
                    ):
                        continue
                    snapshot = read_daily_bar_dataset_manifest(store, entry.ref)
                    if snapshot.instruments == request.instruments:
                        read_daily_bar_dataset(store, entry.ref)
                        return {**dataset_summary(self.root, entry.ref), "reused": True}
            self._settings.require_credentials()
            dates = _verified_dates(db, request.start_date, request.end_date, config)
            return self._prepare_in_child(request, dates, refresh)
        finally:
            self._lock.release()

    def _prepare_in_child(
        self,
        request: DailyBarRequest,
        dates: tuple[date, ...],
        refresh: bool,
    ) -> dict[str, Any]:
        with prepare_tdx_runtime(self._settings) as library:
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("KARKINOS_")
            }
            environment["TDX_AI_DATA_LIB"] = str(library)
            with tempfile.TemporaryDirectory(
                prefix="karkinos-dataset-call-"
            ) as temporary:
                report = Path(temporary) / "result.json"
                message = {
                    "root": str(self.root),
                    "report": str(report),
                    "request": request.to_capture_request(),
                    "dates": [day.isoformat() for day in dates],
                    "refresh": refresh,
                }
                try:
                    completed = subprocess.run(
                        [sys.executable, "-m", "server.workers.dataset_ingestion"],
                        input=json.dumps(message),
                        text=True,
                        env=environment,
                        cwd=Path(__file__).resolve().parents[2],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=900,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    raise ResearchDatasetError("dataset_preparation_timeout") from None
                try:
                    payload = json.loads(report.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise ResearchDatasetError("dataset_worker_failed") from None
                if not isinstance(payload, dict):
                    raise ResearchDatasetError("dataset_worker_failed")
                if completed.returncode or payload.get("status") != "ok":
                    # 不回显供应商异常或子进程传回的任意自由文本。
                    code = payload.get("error_code")
                    if code not in {
                        "dataset_provider_no_data",
                        "dataset_quality_or_checkpoint_invalid",
                    }:
                        code = "dataset_preparation_failed"
                    raise ResearchDatasetError(code)
                store = ContentAddressedObjectStore(self.root / "objects")
                ref = DatasetRef(store.resolve_ref(payload["dataset_id"]))
                read_daily_bar_dataset(
                    ContentAddressedObjectStore(self.root / "objects"), ref
                )
                return {**dataset_summary(self.root, ref), "reused": False}


def _verified_dates(
    db: Any,
    start: date,
    end: date,
    config: Any = None,
) -> tuple[date, ...]:
    """复用项目已有的交易日历事实，不能用工作日或返回的行情猜交易日。"""
    dates = []
    for year in range(start.year, end.year + 1):
        row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        if not validate_verified_market_calendar(row).verified and config is not None:
            from server.services.market_calendar_automation import (
                MarketCalendarAutomationService,
            )

            # 只在用户明确准备数据时补齐日历；浏览和离线重跑不联网。
            MarketCalendarAutomationService(db=db, config=config).sync_year(year)
            row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
        if not validate_verified_market_calendar(row).verified:
            raise ResearchDatasetError(f"dataset_calendar_unavailable:{year}")
        days = row.get("days", row.get("days_json"))
        days = json.loads(days) if isinstance(days, str) else days
        dates.extend(
            date.fromisoformat(item["date"])
            for item in days
            if item["is_trading_day"]
            and start.isoformat() <= item["date"] <= end.isoformat()
        )
    if not dates:
        raise ResearchDatasetError("dataset_no_trading_sessions")
    return tuple(sorted(dates))
