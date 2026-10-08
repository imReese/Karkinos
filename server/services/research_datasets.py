"""供项目运行时使用的持久研究数据：准备、发现及离线读取。

复用已有的对象存储、Dataset Catalog 和行情投影；不再创建另一套行情库。
每个成功交易日先发布检查点，中途失败不会丢掉已完成的采集。研究只绑定
最终发布的数据集，检查点不是隐式的回测输入。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import date, datetime, time, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from core.types import InstrumentKey, InstrumentType
from data.dataset.catalog import DatasetCatalog
from data.dataset.manifest import (
    DatasetManifestError,
    DatasetManifestIntegrityError,
    publish_daily_bar_dataset_manifest,
    read_daily_bar_dataset_manifest,
)
from data.dataset.model import DailyBarDatasetSnapshot, DatasetRef
from data.dataset.reader import (
    DatasetReaderError,
    DatasetReaderIntegrityError,
    read_daily_bar_dataset,
    read_dataset_corporate_action_evidence,
)
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    DailyBarResolutionCandidate,
    resolve_daily_bar_dataset,
)
from data.market.capture import ProviderCaptureIntegrityError, read_provider_capture
from data.market.contracts import DailyBarProvider, DailyBarRequest
from data.market.ingestion import ingest_daily_bars
from data.market.quality import (
    RESEARCH_STRICT_DAILY,
    MarketQualityStatus,
    evaluate_daily_bar_revision,
)
from data.market.revision import (
    MarketRevisionIntegrityError,
    MarketRevisionRef,
    read_market_revision,
    read_market_revision_materialization,
)
from data.market.serving import MarketServingStore
from data.market.verification_evidence import read_market_verification_evidence
from data.providers.tdx import TdxRuntimeSettings, prepare_tdx_runtime
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectIntegrityError,
    ObjectNotFoundError,
)
from server.persistence.jobs import SQLiteJobStore
from server.services.market_calendar_evidence import validate_verified_market_calendar
from server.services.verified_daily_market_data import (
    VerifiedDailyMarketDataRequestError,
    VerifiedDailyMarketJobRequest,
    is_verified_daily_resolver_policy,
    verified_daily_resolver_policy_id,
)
from server.services.verified_daily_market_jobs import VERIFIED_DAILY_MARKET_JOB

logger = logging.getLogger(__name__)

_CACHE_INTEGRITY_ERRORS = (
    DatasetManifestIntegrityError,
    DatasetReaderIntegrityError,
    MarketRevisionIntegrityError,
    ProviderCaptureIntegrityError,
    ObjectIntegrityError,
    ObjectNotFoundError,
)

_POLICY = DailyBarDatasetResolverPolicy(
    policy_id="karkinos.dataset.pit.strict.v1",
    provider_priority=("tdx",),
    required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
)


class ResearchDatasetError(RuntimeError):
    """只包含可公开的错误码，不携带 SDK 自由文本或凭据。"""


def require_supported_snapshot(snapshot: DailyBarDatasetSnapshot) -> None:
    """Accept the legacy TDX lane and verification-bound daily datasets."""
    legacy_tdx = snapshot.resolver_policy_id == _POLICY.policy_id and all(
        partition.provider == "tdx" for partition in snapshot.partitions
    )
    verified_bars = snapshot.verification_bound and is_verified_daily_resolver_policy(
        snapshot.resolver_policy_id
    )
    if not legacy_tdx and not verified_bars:
        raise ResearchDatasetError("dataset_provider_or_policy_unsupported")


def dataset_summary(root: Path, ref: DatasetRef) -> dict[str, Any]:
    store = ContentAddressedObjectStore(root / "objects")
    snapshot = read_daily_bar_dataset_manifest(store, ref)
    require_supported_snapshot(snapshot)
    corporate_actions = read_dataset_corporate_action_evidence(
        store, snapshot, include_capture_freshness=True
    )
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
        **(
            {"corporate_action_evidence": corporate_actions}
            if corporate_actions
            else {}
        ),
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
    read_daily_bar_dataset(store, ref)
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
        raise DatasetReaderIntegrityError("dataset_checkpoint_invalid")
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
                try:
                    candidate = _candidate_from_checkpoint(
                        store, entry.ref, request.instruments
                    )
                except _CACHE_INTEGRITY_ERRORS as exc:
                    logger.warning(
                        "Skipping unreadable dataset checkpoint dataset=%s error=%s",
                        entry.ref.dataset_id,
                        type(exc).__name__,
                    )
                    continue
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
    """一个应用实例持有的服务；TDX SDK 的全局单例只进入子进程。"""

    def __init__(self, root: Path, settings: TdxRuntimeSettings) -> None:
        self.root = root.resolve()
        self._settings = settings
        self._lock = Lock()

    def status(self) -> dict[str, Any]:
        catalog = DatasetCatalog(self.root)
        entries = (
            catalog.list_daily_bar_datasets(limit=100) if catalog.path.exists() else ()
        )
        datasets = []
        unreadable_dataset_count = 0
        for entry in entries:
            try:
                datasets.append(dataset_summary(self.root, entry.ref))
            except (
                DatasetManifestError,
                DatasetReaderError,
                ResearchDatasetError,
                OSError,
            ):
                unreadable_dataset_count += 1
        return {
            "tdx_configured": self._settings.configured,
            "storage_path": str(self.root),
            "busy": self._lock.locked(),
            "datasets": datasets,
            "unreadable_dataset_count": unreadable_dataset_count,
        }

    def collect_corporate_actions(
        self, dataset_id: str, *, config: Any = None, refresh: bool = False
    ) -> dict[str, Any]:
        """Explicitly observe corporate actions and publish a new immutable binding."""
        from data.market.corporate_actions import read_corporate_action_observation
        from data.providers.tushare_corporate_actions import (
            collect_tushare_dividend_observation,
        )

        if not self._lock.acquire(blocking=False):
            raise ResearchDatasetError("dataset_preparation_busy")
        try:
            store = ContentAddressedObjectStore(self.root / "objects")
            try:
                original_ref = DatasetRef(store.resolve_ref(dataset_id))
                original = read_daily_bar_dataset(store, original_ref).snapshot
                require_supported_snapshot(original)
            except Exception:
                raise ResearchDatasetError(
                    "dataset_corporate_actions_dataset_unreadable"
                ) from None
            if any(
                item.instrument_type is not InstrumentType.STOCK
                for item in original.instruments
            ):
                raise ResearchDatasetError("dataset_corporate_actions_stock_only")
            if original.corporate_action_observation_ids and not refresh:
                return {**dataset_summary(self.root, original_ref), "reused": True}
            token = str(getattr(config, "tushare_token", "") or "").strip()
            if not token:
                raise ResearchDatasetError("tushare_token_missing")
            observation_ids, cutoff = [], original.cutoff
            try:
                for instrument in original.instruments:
                    ref = collect_tushare_dividend_observation(
                        store, instrument=instrument, token=token
                    )
                    observation = read_corporate_action_observation(store, ref)
                    cutoff = max(
                        cutoff, datetime.fromisoformat(observation["available_at"])
                    )
                    observation_ids.append(ref.object_id)
                snapshot = replace(
                    original,
                    cutoff=cutoff,
                    corporate_action_observation_ids=tuple(observation_ids),
                )
                ref = publish_daily_bar_dataset_manifest(store, snapshot)
                read_daily_bar_dataset(store, ref)
                DatasetCatalog(self.root).register(store, ref)
                return {**dataset_summary(self.root, ref), "reused": False}
            except Exception:
                # Never expose arbitrary SDK/credential-bearing exception messages.
                raise ResearchDatasetError(
                    "dataset_corporate_actions_collection_failed"
                ) from None
        finally:
            self._lock.release()

    def prepare(
        self,
        request: DailyBarRequest,
        *,
        db: Any,
        config: Any = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        if (
            not 1 <= len(request.instruments) <= 32
            or any(
                item.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
                for item in request.instruments
            )
            or len({item.symbol for item in request.instruments})
            != len(request.instruments)
        ):
            raise ResearchDatasetError("dataset_stock_or_etf_universe_required")
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
                    try:
                        snapshot = read_daily_bar_dataset_manifest(store, entry.ref)
                        if snapshot.instruments == request.instruments:
                            read_daily_bar_dataset(store, entry.ref)
                            return {
                                **dataset_summary(self.root, entry.ref),
                                "reused": True,
                            }
                    except _CACHE_INTEGRITY_ERRORS as exc:
                        logger.warning(
                            "Skipping unreadable cached dataset dataset=%s error=%s",
                            entry.ref.dataset_id,
                            type(exc).__name__,
                        )
            self._settings.require_credentials()
            dates = verified_dataset_dates(
                db, request.start_date, request.end_date, config
            )
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


def publish_verified_interval_dataset(
    root: Path,
    request: DailyBarRequest,
    *,
    db: Any,
    job_ids: tuple[str, ...],
    prefix_dataset_id: str | None = None,
) -> dict[str, Any]:
    """Freeze verified-day jobs, optionally preserving an exact original prefix."""
    if (
        not 1 <= len(request.instruments) <= 32
        or any(
            item.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
            for item in request.instruments
        )
        or len({item.symbol for item in request.instruments})
        != len(request.instruments)
    ):
        raise ResearchDatasetError("verified_interval_stock_or_etf_universe_required")
    if (request.end_date - request.start_date).days >= 366:
        raise ResearchDatasetError("verified_interval_range_exceeds_366_days")
    close = datetime.combine(request.end_date, time(16), ZoneInfo("Asia/Shanghai"))
    if close > datetime.now(timezone.utc):
        raise ResearchDatasetError("verified_interval_session_not_closed")

    expected_dates = verified_dataset_dates(db, request.start_date, request.end_date)
    root = root.resolve()
    store = ContentAddressedObjectStore(root / "objects")
    prefix = None
    if prefix_dataset_id is not None:
        try:
            prefix = read_daily_bar_dataset(
                store, DatasetRef(store.resolve_ref(prefix_dataset_id))
            ).snapshot
        except (
            DatasetReaderError,
            DatasetManifestError,
            ObjectIntegrityError,
            ObjectNotFoundError,
            OSError,
            ValueError,
        ):
            raise ResearchDatasetError("verified_interval_prefix_unreadable") from None
        if (
            not prefix.verification_bound
            or not is_verified_daily_resolver_policy(prefix.resolver_policy_id)
            or prefix.instruments != request.instruments
            or prefix.start_date != request.start_date
            or prefix.end_date > request.end_date
            or prefix.cutoff > datetime.now(timezone.utc)
        ):
            raise ResearchDatasetError("verified_interval_prefix_mismatch")
        prefix_dates = tuple(day for day in expected_dates if day <= prefix.end_date)
        if tuple(part.partition_date for part in prefix.partitions) != prefix_dates:
            raise ResearchDatasetError("verified_interval_prefix_calendar_mismatch")
    job_dates = tuple(
        day for day in expected_dates if prefix is None or day > prefix.end_date
    )
    if (
        not isinstance(job_ids, tuple)
        or len(job_ids) != len(job_dates)
        or any(not isinstance(job_id, str) for job_id in job_ids)
        or len(set(job_ids)) != len(job_ids)
    ):
        raise ResearchDatasetError("verified_interval_job_coverage_invalid")

    jobs = SQLiteJobStore(db.path)
    calendar_refs: dict[int, str] = {}
    selected: dict[date, DailyBarDatasetSnapshot] = {}
    policy_id: str | None = prefix.resolver_policy_id if prefix is not None else None
    schema_version: str | None = (
        prefix.market_schema_version if prefix is not None else None
    )

    for job_id in job_ids:
        try:
            job = jobs.get(job_id)
        except (OSError, TypeError, ValueError) as exc:
            raise ResearchDatasetError("verified_interval_job_unreadable") from exc
        if job is None or job.kind != VERIFIED_DAILY_MARKET_JOB:
            raise ResearchDatasetError("verified_interval_job_missing")
        if job.status != "succeeded":
            raise ResearchDatasetError("verified_interval_job_incomplete")
        try:
            planned = VerifiedDailyMarketJobRequest.from_payload(job.payload)
        except (TypeError, ValueError, VerifiedDailyMarketDataRequestError) as exc:
            raise ResearchDatasetError("verified_interval_job_payload_invalid") from exc
        day = planned.trade_date
        if day not in job_dates or day in selected:
            raise ResearchDatasetError("verified_interval_job_coverage_invalid")
        if planned.instruments != request.instruments:
            raise ResearchDatasetError("verified_interval_instrument_mismatch")
        if day.year not in calendar_refs:
            validation = validate_verified_market_calendar(
                db.get_market_calendar_snapshot_sync(exchange="SSE", year=day.year)
            )
            if not validation.verified or validation.evidence_ref is None:
                raise ResearchDatasetError(f"dataset_calendar_unavailable:{day.year}")
            calendar_refs[day.year] = validation.evidence_ref
        if calendar_refs[day.year] not in planned.calendar_evidence_refs:
            raise ResearchDatasetError("verified_interval_calendar_evidence_mismatch")

        result_ref = job.result_ref or ""
        if not result_ref.startswith("dataset:sha256:"):
            raise ResearchDatasetError("verified_interval_job_result_invalid")
        try:
            daily_ref = DatasetRef(
                store.resolve_ref(result_ref.removeprefix("dataset:"))
            )
            daily = read_daily_bar_dataset(store, daily_ref).snapshot
            verification_id = daily.partitions[0].verification_id
            verification = (
                read_market_verification_evidence(
                    store, store.resolve_ref(verification_id)
                )
                if verification_id is not None
                else None
            )
        except Exception:
            raise ResearchDatasetError(
                "verified_interval_daily_dataset_unreadable"
            ) from None
        expected_policy = verified_daily_resolver_policy_id(planned.source_policy_id)
        if (
            not daily.verification_bound
            or daily.resolver_policy_id != expected_policy
            or daily.start_date != day
            or daily.end_date != day
            or daily.instruments != request.instruments
            or len(daily.partitions) != 1
            or daily.partitions[0].partition_date != day
            or verification is None
            or verification.checked_at > daily.cutoff
        ):
            raise ResearchDatasetError("verified_interval_daily_dataset_mismatch")
        if policy_id is not None and policy_id != daily.resolver_policy_id:
            raise ResearchDatasetError("verified_interval_policy_mismatch")
        if schema_version is not None and schema_version != daily.market_schema_version:
            raise ResearchDatasetError("verified_interval_schema_mismatch")
        policy_id = daily.resolver_policy_id
        schema_version = daily.market_schema_version
        selected[day] = daily

    if set(selected) != set(job_dates):
        raise ResearchDatasetError("verified_interval_job_coverage_invalid")
    ordered = tuple(selected[day] for day in job_dates)
    assert policy_id is not None and schema_version is not None
    snapshot = DailyBarDatasetSnapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        cutoff=max(
            [item.cutoff for item in ordered] + ([prefix.cutoff] if prefix else [])
        ),
        instruments=request.instruments,
        resolver_policy_id=policy_id,
        market_schema_version=schema_version,
        partitions=(prefix.partitions if prefix else ())
        + tuple(item.partitions[0] for item in ordered),
        corporate_action_observation_ids=(
            prefix.corporate_action_observation_ids if prefix else ()
        ),
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    try:
        replayed = read_daily_bar_dataset(store, ref)
    except Exception:
        raise ResearchDatasetError("verified_interval_replay_failed") from None
    if replayed.snapshot != snapshot:
        raise ResearchDatasetError("verified_interval_replay_mismatch")
    DatasetCatalog(root).register(store, ref)
    return dataset_summary(root, ref)


def verified_dataset_dates(
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
