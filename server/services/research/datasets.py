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
from datetime import date, datetime, time, timedelta, timezone
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
from data.dataset.model import (
    DailyBarDatasetMembership,
    DailyBarDatasetSnapshot,
    DatasetRef,
)
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
from server.services.verified_daily_market_jobs import (
    MAX_VERIFIED_DAILY_JOB_INSTRUMENTS,
    VERIFIED_DAILY_MARKET_JOB,
)

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


def _active_reader() -> Any:
    legacy = sys.modules.get("server.services.research_datasets")
    return (
        getattr(legacy, "read_daily_bar_dataset", read_daily_bar_dataset)
        if legacy
        else read_daily_bar_dataset
    )


def _active_verified_dataset_dates() -> Any:
    legacy = sys.modules.get("server.services.research_datasets")
    return (
        getattr(legacy, "verified_dataset_dates", verified_dataset_dates)
        if legacy
        else verified_dataset_dates
    )


def _active_prepare_tdx_runtime() -> Any:
    legacy = sys.modules.get("server.services.research_datasets")
    return (
        getattr(legacy, "prepare_tdx_runtime", prepare_tdx_runtime)
        if legacy
        else prepare_tdx_runtime
    )


def _active_subprocess() -> Any:
    legacy = sys.modules.get("server.services.research_datasets")
    return getattr(legacy, "subprocess", subprocess) if legacy else subprocess


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
        "session_count": len({part.partition_date for part in snapshot.partitions}),
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
                original = _active_reader()(store, original_ref).snapshot
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
                dataset_ref = publish_daily_bar_dataset_manifest(store, snapshot)
                read_daily_bar_dataset(store, dataset_ref)
                DatasetCatalog(self.root).register(store, dataset_ref)
                return {**dataset_summary(self.root, dataset_ref), "reused": False}
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
            not request.instruments
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
                            _active_reader()(store, entry.ref)
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
            dates = _active_verified_dataset_dates()(
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
        with _active_prepare_tdx_runtime()(self._settings) as library:
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
                    completed = _active_subprocess().run(
                        [sys.executable, "-m", "server.workers.dataset_ingestion"],
                        input=json.dumps(message),
                        text=True,
                        env=environment,
                        cwd=Path(__file__).resolve().parents[3],
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
                _active_reader()(
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
    session_memberships: tuple[DailyBarDatasetMembership, ...] = (),
    universe_policy_id: str | None = None,
) -> dict[str, Any]:
    """Freeze verified-day jobs, optionally preserving an exact original prefix."""
    if (
        not request.instruments
        or any(
            item.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}
            for item in request.instruments
        )
        or len({item.symbol for item in request.instruments})
        != len(request.instruments)
    ):
        raise ResearchDatasetError("verified_interval_stock_or_etf_universe_required")
    dated_scope = bool(session_memberships and universe_policy_id)
    if (request.end_date - request.start_date).days >= (3653 if dated_scope else 366):
        raise ResearchDatasetError(
            "verified_interval_range_exceeds_ten_years"
            if dated_scope
            else "verified_interval_range_exceeds_366_days"
        )
    close = datetime.combine(request.end_date, time(16), ZoneInfo("Asia/Shanghai"))
    if close > datetime.now(timezone.utc):
        raise ResearchDatasetError("verified_interval_session_not_closed")

    expected_dates = _active_verified_dataset_dates()(
        db, request.start_date, request.end_date
    )
    if dated_scope and len(expected_dates) > 2000:
        raise ResearchDatasetError("verified_interval_session_budget_exceeded")
    root = root.resolve()
    store = ContentAddressedObjectStore(root / "objects")
    prefix = None
    if prefix_dataset_id is not None:
        try:
            prefix = _active_reader()(
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
            or (
                not prefix.session_memberships
                and prefix.instruments != request.instruments
            )
            or (
                prefix.session_memberships
                and not set(prefix.instruments) <= set(request.instruments)
            )
            or prefix.start_date != request.start_date
            or prefix.end_date > request.end_date
            or prefix.cutoff > datetime.now(timezone.utc)
        ):
            raise ResearchDatasetError("verified_interval_prefix_mismatch")
        prefix_dates = tuple(day for day in expected_dates if day <= prefix.end_date)
        if (
            tuple(sorted({part.partition_date for part in prefix.partitions}))
            != prefix_dates
        ):
            raise ResearchDatasetError("verified_interval_prefix_calendar_mismatch")
    job_dates = tuple(
        day for day in expected_dates if prefix is None or day > prefix.end_date
    )
    if (
        not isinstance(job_ids, tuple)
        or (bool(job_dates) and not job_ids)
        or any(not isinstance(job_id, str) for job_id in job_ids)
        or len(set(job_ids)) != len(job_ids)
    ):
        raise ResearchDatasetError("verified_interval_job_coverage_invalid")

    jobs = SQLiteJobStore(db.path)
    calendar_refs: dict[int, str] = {}
    selected: dict[date, list[DailyBarDatasetSnapshot]] = {}
    membership_by_date = {item.partition_date: item for item in session_memberships}
    if session_memberships and (
        len(membership_by_date) != len(session_memberships)
        or set(membership_by_date) != set(expected_dates)
        or not universe_policy_id
        or {
            key
            for item in session_memberships
            for key in (*item.instruments, *item.maintenance_instruments)
        }
        != set(request.instruments)
    ):
        raise ResearchDatasetError("verified_interval_membership_coverage_invalid")
    if prefix is not None and prefix.session_memberships:
        if (
            universe_policy_id is not None
            and universe_policy_id != prefix.universe_policy_id
        ):
            raise ResearchDatasetError("verified_interval_prefix_policy_mismatch")
        if (
            session_memberships
            and tuple(
                membership_by_date[item.partition_date]
                for item in prefix.session_memberships
            )
            != prefix.session_memberships
        ):
            raise ResearchDatasetError("verified_interval_prefix_membership_changed")
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
        if (
            planned.is_range
            and planned.expected_sessions()
            != _active_verified_dataset_dates()(
                db, planned.range_start_date, planned.range_end_date
            )
        ):
            raise ResearchDatasetError("verified_interval_job_calendar_mismatch")
        for planned_day in planned.expected_sessions():
            if planned_day.year not in calendar_refs:
                validation = validate_verified_market_calendar(
                    db.get_market_calendar_snapshot_sync(
                        exchange="SSE", year=planned_day.year
                    )
                )
                if not validation.verified or validation.evidence_ref is None:
                    raise ResearchDatasetError(
                        f"dataset_calendar_unavailable:{planned_day.year}"
                    )
                calendar_refs[planned_day.year] = validation.evidence_ref
            if calendar_refs[planned_day.year] not in planned.calendar_refs_for_session(
                planned_day
            ):
                raise ResearchDatasetError(
                    "verified_interval_calendar_evidence_mismatch"
                )
        daily_snapshots = _verified_job_daily_snapshots(store, job, planned)
        if not set(planned.expected_sessions()) <= set(job_dates):
            raise ResearchDatasetError("verified_interval_job_coverage_invalid")
        for day, daily in daily_snapshots.items():
            members = planned.instruments_for_session(day)
            expected_instruments = (
                (
                    *membership_by_date[day].instruments,
                    *membership_by_date[day].maintenance_instruments,
                )
                if session_memberships
                else request.instruments
            )
            already_supplied = {
                key
                for previous in selected.get(day, [])
                for key in previous.instruments
            }
            if not set(members) <= set(
                expected_instruments
            ) or already_supplied.intersection(members):
                raise ResearchDatasetError("verified_interval_instrument_mismatch")
            if day.year not in calendar_refs:
                validation = validate_verified_market_calendar(
                    db.get_market_calendar_snapshot_sync(exchange="SSE", year=day.year)
                )
                if not validation.verified or validation.evidence_ref is None:
                    raise ResearchDatasetError(
                        f"dataset_calendar_unavailable:{day.year}"
                    )
                calendar_refs[day.year] = validation.evidence_ref
            if calendar_refs[day.year] not in planned.calendar_refs_for_session(day):
                raise ResearchDatasetError(
                    "verified_interval_calendar_evidence_mismatch"
                )
            if policy_id is not None and policy_id != daily.resolver_policy_id:
                raise ResearchDatasetError("verified_interval_policy_mismatch")
            if (
                schema_version is not None
                and schema_version != daily.market_schema_version
            ):
                raise ResearchDatasetError("verified_interval_schema_mismatch")
            policy_id = daily.resolver_policy_id
            schema_version = daily.market_schema_version
            selected.setdefault(day, []).append(daily)

    if set(selected) != set(job_dates):
        raise ResearchDatasetError("verified_interval_job_coverage_invalid")
    for day in job_dates:
        expected_instruments = (
            (
                *membership_by_date[day].instruments,
                *membership_by_date[day].maintenance_instruments,
            )
            if session_memberships
            else request.instruments
        )
        if {key for daily in selected[day] for key in daily.instruments} != set(
            expected_instruments
        ):
            raise ResearchDatasetError(
                "verified_interval_instrument_coverage_incomplete"
            )
    ordered = tuple(daily for day in job_dates for daily in selected[day])
    assert policy_id is not None and schema_version is not None
    sharded = bool(
        session_memberships
        or (prefix is not None and prefix.session_memberships)
        or any(len(rows) > 1 for rows in selected.values())
    )
    memberships = session_memberships
    if sharded and not memberships:
        previous_memberships = ()
        if prefix is not None:
            previous_memberships = prefix.session_memberships or tuple(
                DailyBarDatasetMembership(day, prefix.instruments, prefix.cutoff)
                for day in sorted({part.partition_date for part in prefix.partitions})
            )
        memberships = previous_memberships + tuple(
            DailyBarDatasetMembership(
                day, request.instruments, max(item.cutoff for item in selected[day])
            )
            for day in job_dates
        )
    prefix_instruments = prefix.instruments if prefix is not None else ()
    prefix_partitions = tuple(
        replace(part, instruments=part.instruments or prefix_instruments)
        if sharded
        else part
        for part in (prefix.partitions if prefix else ())
    )
    snapshot = DailyBarDatasetSnapshot(
        start_date=request.start_date,
        end_date=request.end_date,
        cutoff=max(
            [item.cutoff for item in ordered]
            + ([prefix.cutoff] if prefix else [])
            + [item.decision_at or item.available_at for item in memberships]
        ),
        instruments=request.instruments,
        resolver_policy_id=policy_id,
        market_schema_version=schema_version,
        partitions=prefix_partitions
        + tuple(
            replace(item.partitions[0], instruments=item.instruments)
            if sharded
            else item.partitions[0]
            for item in ordered
        ),
        corporate_action_observation_ids=(
            prefix.corporate_action_observation_ids if prefix else ()
        ),
        session_memberships=memberships,
        universe_policy_id=(
            universe_policy_id
            or (prefix.universe_policy_id if prefix else None)
            or "karkinos.dataset.explicit_fixed_membership.v1"
        )
        if sharded
        else None,
    )
    ref = publish_daily_bar_dataset_manifest(store, snapshot)
    try:
        replayed = _active_reader()(store, ref)
    except Exception:
        raise ResearchDatasetError("verified_interval_replay_failed") from None
    if replayed.snapshot != snapshot:
        raise ResearchDatasetError("verified_interval_replay_mismatch")
    DatasetCatalog(root).register(store, ref)
    return dataset_summary(root, ref)


def _verified_job_daily_snapshots(store, job, planned):
    result_ref = job.result_ref or ""
    if not result_ref.startswith("dataset:sha256:"):
        raise ResearchDatasetError("verified_interval_job_result_invalid")
    try:
        snapshot = read_daily_bar_dataset(
            store, DatasetRef(store.resolve_ref(result_ref.removeprefix("dataset:")))
        ).snapshot
        expected = {
            day: planned.instruments_for_session(day)
            for day in planned.expected_sessions()
            if planned.instruments_for_session(day)
        }
        partitions = {part.partition_date: part for part in snapshot.partitions}
        if (
            not snapshot.verification_bound
            or snapshot.resolver_policy_id
            != verified_daily_resolver_policy_id(planned.source_policy_id)
            or snapshot.instruments != planned.instruments
            or snapshot.start_date != min(expected)
            or snapshot.end_date != max(expected)
            or len(partitions) != len(snapshot.partitions)
            or set(partitions) != set(expected)
        ):
            raise ResearchDatasetError("verified_interval_daily_dataset_mismatch")
        rows = {}
        for day, members in expected.items():
            part = partitions[day]
            actual = snapshot.instruments_for_session(day)
            if actual != members or (part.instruments and part.instruments != members):
                raise ResearchDatasetError("verified_interval_daily_dataset_mismatch")
            verification = read_market_verification_evidence(
                store, store.resolve_ref(part.verification_id)
            )
            if verification.checked_at > snapshot.cutoff:
                raise ResearchDatasetError("verified_interval_daily_dataset_mismatch")
            rows[day] = replace(
                snapshot,
                start_date=day,
                end_date=day,
                instruments=members,
                partitions=(replace(part, instruments=()),),
                session_memberships=(),
                universe_policy_id=None,
            )
        return rows
    except ResearchDatasetError:
        raise
    except Exception:
        raise ResearchDatasetError(
            "verified_interval_daily_dataset_unreadable"
        ) from None


def _forward_seed_expected(
    market_store,
    config,
    *,
    dates,
    through,
    current,
    warmup_universe,
    now,
    pinned_binding=None,
    prefix=None,
):
    # Membership in the old warmup is explicit and exploratory. Only the
    # current session binds the actual observed master for a new decision.
    expected = {
        date.fromisoformat(item.trade_date): current
        if item.trade_date == through.isoformat()
        else warmup_universe
        for item in dates
    }
    # Historical warmup is an explicit composition of rows that actually
    # exist in frozen receipts, not a claim that today's IPOs existed then.
    # The separate verified jobs still capture/reconcile the requested bars.
    market_binding = pinned_binding
    receipts = (
        []
        if market_binding
        else market_store.list_market_daily_ingestion_receipts(
            start_date=min(expected).isoformat(), end_date=through.isoformat()
        )
    )
    if market_binding or receipts:
        from data.research_market_data import (
            complete_research_market_binding,
            load_research_market_frames,
            research_market_binding,
            resolve_daily_bar_receipts,
        )

        if market_binding is None:
            receipts = resolve_daily_bar_receipts(
                data_store=market_store,
                start_date=min(expected).isoformat(),
                end_date=through.isoformat(),
                config=config,
            )
            market_binding, frames = complete_research_market_binding(
                market_store._root,
                binding=research_market_binding(receipts),
                symbols=[key.symbol for key in warmup_universe],
                start_date=min(expected).isoformat(),
                end_date=through.isoformat(),
                as_of=now,
            )
        else:
            frames = load_research_market_frames(
                market_store._root,
                binding=market_binding,
                symbols=[key.symbol for key in warmup_universe],
                start_date=min(expected).isoformat(),
                end_date=through.isoformat(),
            )
        observed_dates = {
            symbol: {value.date() for value in frame["timestamp"]}
            for symbol, frame in frames.items()
        }
        for day in expected:
            if day == through:
                continue
            observed = tuple(
                key
                for key in warmup_universe
                if day in observed_dates.get(key.symbol, ())
            )
            if not observed:
                raise ValueError("forward_seed_warmup_session_unavailable")
            expected[day] = observed
    if prefix is not None:
        for membership in prefix.session_memberships:
            expected[membership.partition_date] = membership.instruments
    return expected, market_binding


def _publish_forward_seed(
    db,
    root,
    objects,
    *,
    jobs,
    expected,
    master,
    identity,
    prefix,
    through,
    latest_through,
    now,
    scope,
    prefix_dataset_id=None,
):
    job_snapshots = []
    for job in jobs:
        if not job.result_ref or not job.result_ref.startswith("dataset:sha256:"):
            raise ResearchDatasetError("verified_interval_job_result_invalid")
        job_snapshots.append(
            (
                VerifiedDailyMarketJobRequest.from_payload(job.payload),
                read_daily_bar_dataset(
                    objects,
                    DatasetRef(
                        objects.resolve_ref(job.result_ref.removeprefix("dataset:"))
                    ),
                ).snapshot,
            )
        )
    memberships = list(prefix.session_memberships) if prefix is not None else []
    for day, members in expected.items():
        if prefix is not None and day <= prefix.end_date:
            continue
        available = max(
            snapshot.cutoff
            for planned, snapshot in job_snapshots
            if planned.instruments_for_session(day)
        )
        memberships.append(
            DailyBarDatasetMembership(
                day,
                members,
                datetime.fromisoformat(master["available_at"])
                if day == through
                else available,
                (identity,) if day == through else (),
                now if day == through and through == latest_through else None,
            )
        )
    all_instruments = tuple(
        sorted(
            {key for members in expected.values() for key in members},
            key=lambda key: (key.instrument_type.value, key.symbol),
        )
    )
    summary = publish_verified_interval_dataset(
        root,
        DailyBarRequest(all_instruments, min(expected), through),
        db=db,
        job_ids=tuple(job.job_id for job in jobs),
        session_memberships=tuple(memberships),
        universe_policy_id=scope["deployment_scope_fingerprint"],
        prefix_dataset_id=prefix_dataset_id,
    )
    return summary


def _existing_forward_seed(
    db,
    config,
    objects,
    catalog,
    *,
    dates,
    through,
    latest_through,
    expected,
    scope,
    now,
    forward_sessions,
):
    entries = (
        catalog.list_daily_bar_datasets(
            start_date=date.fromisoformat(dates[0].trade_date), end_date=through
        )
        if catalog.path.exists()
        else ()
    )
    for entry in entries:
        if (
            entry.start_date != date.fromisoformat(dates[0].trade_date)
            or entry.end_date != through
        ):
            continue
        candidate = read_daily_bar_dataset_manifest(objects, entry.ref)
        # Range transport jobs are not a full-scope seed. Reject their
        # declared scope cheaply; a matching seed still reopens all proof.
        if candidate.universe_policy_id != scope["deployment_scope_fingerprint"]:
            continue
        restored = read_daily_bar_dataset(objects, entry.ref)
        snapshot = restored.snapshot
        if (
            snapshot.universe_policy_id == scope["deployment_scope_fingerprint"]
            and snapshot.verification_bound
            and snapshot.cutoff <= now
            and all(
                snapshot.instruments_for_session(day) == members
                for day, members in expected.items()
            )
            and snapshot.session_memberships[-1].source_observation_ids
            and through == latest_through
        ):
            if forward_sessions:
                from server.services.research_corporate_action_jobs import (
                    ensure_dataset_corporate_actions,
                )

                return ensure_dataset_corporate_actions(
                    db,
                    config,
                    snapshot=snapshot,
                    now=now,
                    prospective_start=through,
                    previous_observation_ids=snapshot.corporate_action_observation_ids,
                )
            return {
                "status": "ready",
                "dataset_id": entry.ref.dataset_id,
                "job_ids": [],
                "last_blocker": None,
            }
    return None


def _forward_seed_jobs(db, config, *, expected, prefix, through, now, replacements):
    from server.services.verified_daily_market_jobs import (
        enqueue_verified_daily_market_jobs_for_range,
    )

    job_expected = {
        day: members
        for day, members in expected.items()
        if prefix is None or day > prefix.end_date
    }
    all_members = tuple(
        sorted(
            {key for members in job_expected.values() for key in members},
            key=lambda key: (key.instrument_type.value, key.symbol),
        )
    )
    jobs = (
        enqueue_verified_daily_market_jobs_for_range(
            db,
            config,
            SQLiteJobStore(db.path),
            instruments=all_members,
            start_date=min(job_expected),
            end_date=through,
            now=now,
            historical_range=True,
            session_instruments=job_expected,
        )
        if job_expected and prefix is None
        else tuple(
            job
            for day, members in job_expected.items()
            for job in enqueue_verified_daily_market_jobs_for_range(
                db,
                config,
                SQLiteJobStore(db.path),
                instruments=members,
                start_date=day,
                end_date=day,
                now=now,
            )
        )
    )
    jobs = _forward_seed_replacement_jobs(SQLiteJobStore(db.path), jobs, replacements)
    if any(job.status != "succeeded" for job in jobs):
        from server.persistence.market_daily_call_budget import BUDGET_DEFERRED_CODE

        deferred = [job for job in jobs if job.error == BUDGET_DEFERRED_CODE]
        retry_at = min(
            (job.available_at for job in deferred if job.available_at is not None),
            default=None,
        )
        return {
            "status": "blocked"
            if any(job.status == "failed" for job in jobs)
            else "waiting",
            "job_ids": [job.job_id for job in jobs],
            "last_blocker": {"code": BUDGET_DEFERRED_CODE, "available_at": retry_at}
            if deferred
            else {"code": "forward_seed_verified_jobs_incomplete"},
        }
    return jobs


def forward_seed_origin_id(
    scope: dict[str, Any],
    minimum_bars: int,
    verification_policy_id: str,
    *,
    start_date: str | None = None,
) -> str:
    """Stable scheduler identity, independent of a changing latest session."""
    from server.contracts.content_identity import content_fingerprint

    return "forward_seed_origin:" + content_fingerprint(
        {
            "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
            "minimum_bars": max(
                minimum_bars, int(scope["universe_policy"]["minimum_history_rows"])
            ),
            "verification_source_policy_id": verification_policy_id,
            **(
                {"declared_start_date": date.fromisoformat(start_date).isoformat()}
                if start_date is not None
                else {}
            ),
        }
    )


def read_forward_seed_origin(db, origin_id: str):
    """Read the current preparation revision; this is not Dataset validation."""
    from server.persistence.automation_runs import AutomationRunRepository

    repository = AutomationRunRepository(db.path)
    previous, seen = None, set()
    while origin_id not in seen and len(seen) < 32:
        seen.add(origin_id)
        row = repository.get_automation_run_sync(origin_id)
        if row is None:
            if previous is not None:
                raise ValueError("forward_seed_origin_revision_missing")
            return None
        payload = json.loads(row["payload_json"])
        if row["run_type"] != "forward_seed_preparation":
            raise ValueError("forward_seed_origin_revision_invalid")
        if previous is not None:
            prior_payload = json.loads(previous["payload_json"])
            if (
                prior_payload.get("alias_of_origin_id") != row["run_id"]
                and payload.get("supersedes_origin_id") != previous["run_id"]
            ) or any(
                payload.get(key) != prior_payload.get(key)
                for key in (
                    "deployment_scope_fingerprint",
                    "minimum_bars",
                    "verification_source_policy_id",
                    "start_date",
                    "end_date",
                    "master_observation_id",
                    "warmup_instruments",
                )
            ):
                raise ValueError("forward_seed_origin_revision_invalid")
        if row["status"] != "superseded":
            return row
        previous, origin_id = row, row["source_ref"]
        if not isinstance(origin_id, str) or not origin_id.startswith(
            "forward_seed_origin:"
        ):
            raise ValueError("forward_seed_origin_revision_invalid")
    raise ValueError("forward_seed_origin_revision_cycle")


def _forward_seed_replacement_jobs(store, jobs, replacements):
    resolved = []
    for job in jobs:
        replacement_id = replacements.get(job.job_id)
        replacement = store.get(replacement_id) if replacement_id else job
        if (
            replacement is None
            or replacement.kind != VERIFIED_DAILY_MARKET_JOB
            or {
                key: value
                for key, value in replacement.payload.items()
                if key != "observation_round"
            }
            != {
                key: value
                for key, value in job.payload.items()
                if key != "observation_round"
            }
        ):
            raise ValueError("forward_seed_replacement_job_mismatch")
        resolved.append(replacement)
    return tuple(resolved)


def revise_pending_forward_seed_origin(
    db,
    config,
    *,
    origin_id,
    scope,
    now,
    data_store,
    job_replacements=None,
    declared_start_date=None,
):
    """Explicitly inherit one pending window while correcting its actual inputs.

    Original recipes and jobs remain audit records. New jobs arise only for
    changed dated members; exact unchanged transport identities are reused.
    """
    from data.research_market_data import complete_research_market_binding
    from data.source_policy import verification_source_policy_for_config
    from server.contracts.content_identity import content_fingerprint
    from server.persistence.automation_runs import AutomationRunRepository

    row = read_forward_seed_origin(db, origin_id)
    if row is None or row["status"] != "claimed" or row.get("source_ref") is not None:
        raise ValueError("forward_seed_origin_revision_conflict")
    origin = json.loads(row["payload_json"])
    if (
        origin["deployment_scope_fingerprint"] != scope["deployment_scope_fingerprint"]
        or origin["verification_source_policy_id"]
        != verification_source_policy_for_config(config).policy_id
    ):
        raise ValueError("forward_seed_origin_revision_scope_mismatch")
    canonical_alias = None
    if declared_start_date is not None:
        from server.services.market_calendar_dates import (
            resolve_verified_closed_trading_dates_in_range,
        )

        start = date.fromisoformat(declared_start_date)
        days = resolve_verified_closed_trading_dates_in_range(
            db,
            now,
            start_date=start,
            end_date=date.fromisoformat(origin["end_date"]),
            maximum_calendar_days=3653,
        )
        if not days or days[0].trade_date != origin["start_date"]:
            raise ValueError("forward_seed_origin_declared_start_mismatch")
        canonical_id = forward_seed_origin_id(
            scope,
            origin["minimum_bars"],
            origin["verification_source_policy_id"],
            start_date=start.isoformat(),
        )
        if canonical_id != origin_id:
            existing = read_forward_seed_origin(db, canonical_id)
            if existing is not None and existing["run_id"] != row["run_id"]:
                raise ValueError("forward_seed_canonical_origin_conflict")
            if existing is None:
                canonical_alias = {
                    "run_id": canonical_id,
                    "run_type": "forward_seed_preparation",
                    "run_date": row["run_date"],
                    "status": "superseded",
                    "execution_mode": row["execution_mode"],
                    "started_at": now.isoformat(),
                    "source_ref": row["run_id"],
                    "payload": {
                        **origin,
                        "alias_of_origin_id": row["run_id"],
                        "declared_start_date": start.isoformat(),
                    },
                }
    binding, _ = complete_research_market_binding(
        data_store._root,
        binding=origin["market_data_binding"],
        symbols=[key["symbol"] for key in origin["warmup_instruments"]],
        start_date=origin["start_date"],
        end_date=origin["end_date"],
        as_of=now,
    )
    replacements = {**origin.get("job_replacements", {}), **(job_replacements or {})}
    store = SQLiteJobStore(db.path)
    for original, replacement in replacements.items():
        old_job = store.get(original)
        if old_job is None:
            raise ValueError("forward_seed_replacement_job_mismatch")
        _forward_seed_replacement_jobs(store, (old_job,), {original: replacement})
    if (
        canonical_alias is None
        and binding == origin["market_data_binding"]
        and replacements == origin.get("job_replacements", {})
    ):
        return row
    revision_id = "forward_seed_origin:" + content_fingerprint(
        {
            "supersedes_origin_id": row["run_id"],
            "market_data_binding": binding,
            "job_replacements": replacements,
        }
    )
    revision = {
        "run_id": revision_id,
        "run_type": "forward_seed_preparation",
        "run_date": row["run_date"],
        "status": "claimed",
        "execution_mode": row["execution_mode"],
        "started_at": now.isoformat(),
        "source_ref": None,
        "payload": {
            **origin,
            "market_data_binding": binding,
            "job_replacements": replacements,
            "supersedes_origin_id": row["run_id"],
        },
    }
    return AutomationRunRepository(db.path).revise_pending_forward_seed_origin_sync(
        row["run_id"], revision, canonical_alias=canonical_alias
    )


def ensure_forward_seed_for_source(
    db: Any,
    config: Any,
    *,
    source: dict[str, Any],
    now: datetime,
    data_store: Any = None,
) -> dict[str, Any]:
    """Prepare a bounded, real verified warmup; never certify historical PIT.

    Calls only queue existing provider-budgeted jobs. Repeated calls reuse their
    immutable results, so automatic observation startup can resume after waiting.
    """
    from data.dataset.manifest import bind_stock_master_observation
    from data.source_policy import verification_source_policy_for_config
    from data.store import DataStore
    from server.bootstrap import resolve_data_dir
    from server.persistence.automation_runs import AutomationRunRepository
    from server.services.market_calendar_dates import (
        resolve_latest_verified_closed_trading_date,
        resolve_verified_closed_trading_dates_in_range,
    )
    from server.services.market_universe_truth import (
        MarketUniversePolicy,
        market_deployment_scope,
        market_master_buy_instruments,
        require_complete_market_universe_snapshot,
    )

    selection = source.get("source_selection") or source.get("selection") or {}
    scope = selection.get("deployment_scope") or {}
    try:
        if (
            scope
            != market_deployment_scope(
                MarketUniversePolicy.from_dict(scope["universe_policy"])
            )
            or scope.get("scope_kind") != "full_declared_market"
        ):
            raise ValueError("forward_seed_scope_invalid")
        minimum = max(
            int(source["minimum_bars"]),
            int(scope["universe_policy"]["minimum_history_rows"]),
        )
        forward_sessions = source.get("forward_minimum_observations", 0)
        if type(forward_sessions) is not int or forward_sessions < 0:
            return {
                "status": "blocked",
                "job_ids": [],
                "last_blocker": {"code": "forward_seed_resource_limits_invalid"},
            }
        if minimum + forward_sessions > 2000:
            return {
                "status": "blocked",
                "job_ids": [],
                "last_blocker": {
                    "code": "forward_seed_session_budget_exceeded",
                    "warmup_sessions": minimum,
                    "minimum_forward_sessions": forward_sessions,
                    "limit": 2000,
                },
            }
        verification_policy = verification_source_policy_for_config(config).policy_id
        declared_start = source.get("start_date") or selection.get("start_date")
        if declared_start is not None:
            declared_start = date.fromisoformat(declared_start).isoformat()
        origins = AutomationRunRepository(db.path)
        origin_id = forward_seed_origin_id(
            scope, minimum, verification_policy, start_date=declared_start
        )
        origin_run = read_forward_seed_origin(db, origin_id)
        if origin_run is not None:
            origin_id = origin_run["run_id"]
        origin = json.loads(origin_run["payload_json"]) if origin_run else None
        root = db.path.resolve().parent / "research"
        objects = ContentAddressedObjectStore(root / "objects")
        catalog = DatasetCatalog(root)
        prefix = None
        if origin_run and origin_run.get("source_ref"):
            prefix = read_daily_bar_dataset(
                objects, DatasetRef(objects.resolve_ref(origin_run["source_ref"]))
            ).snapshot
            if (
                prefix.universe_policy_id != scope["deployment_scope_fingerprint"]
                or not prefix.verification_bound
                or prefix.start_date.isoformat() != origin["start_date"]
                or prefix.cutoff > now
            ):
                raise ValueError("forward_seed_origin_dataset_invalid")
        closed = resolve_latest_verified_closed_trading_date(db, now)
        if closed is None:
            raise ValueError("forward_seed_calendar_unavailable")
        latest_through = date.fromisoformat(closed.trade_date)
        through = (
            date.fromisoformat(origin["end_date"])
            if origin and prefix is None
            else latest_through
        )
        dates = resolve_verified_closed_trading_dates_in_range(
            db,
            now,
            start_date=date.fromisoformat(origin["start_date"])
            if origin
            else date.fromisoformat(declared_start)
            if declared_start
            else through - timedelta(days=min(3652, max(30, minimum * 2))),
            end_date=through,
            maximum_calendar_days=3653,
        )
        if minimum < 1 or len(dates) < minimum:
            raise ValueError("forward_seed_warmup_unavailable")
        if not origin and not declared_start:
            dates = dates[-minimum:]
        if len(dates) + forward_sessions > 2000:
            return {
                "status": "blocked",
                "job_ids": [],
                "last_blocker": {
                    "code": "forward_seed_session_budget_exceeded",
                    "warmup_sessions": len(dates),
                    "minimum_forward_sessions": forward_sessions,
                    "limit": 2000,
                },
            }
        original = tuple(
            sorted(
                (
                    InstrumentKey.from_values(row["symbol"], row["instrument_type"])
                    for row in (
                        origin["warmup_instruments"]
                        if origin and prefix is None
                        else source["instruments"]
                    )
                ),
                key=lambda key: (key.instrument_type.value, key.symbol),
            )
        )
        market_store = data_store or DataStore(resolve_data_dir())
        raw_master = (
            {
                **json.loads(
                    objects.read_bytes(
                        objects.resolve_ref(origin["master_observation_id"])
                    )
                ),
                "snapshot_id": origin["master_observation_id"],
            }
            if origin and prefix is None
            else market_store.get_market_universe_snapshot(
                trade_date=through.isoformat(), as_of=now
            )
        )
        master = require_complete_market_universe_snapshot(
            raw_master,
            policy=MarketUniversePolicy.from_dict(scope["universe_policy"]),
            expected_trade_date=through.isoformat(),
            available_as_of=now,
        )
        identity = bind_stock_master_observation(objects, master)
        current = market_master_buy_instruments(
            master, MarketUniversePolicy.from_dict(scope["universe_policy"])
        )
        warmup_universe = tuple(
            sorted(
                set(original)
                | set(current)
                | (set(prefix.instruments) if prefix is not None else set()),
                key=lambda key: (key.instrument_type.value, key.symbol),
            )
        )
        if len(warmup_universe) > 10_000:
            return {
                "status": "blocked",
                "job_ids": [],
                "last_blocker": {
                    "code": "forward_seed_instrument_budget_exceeded",
                    "instruments": len(warmup_universe),
                    "limit": 10_000,
                },
            }
        expected, market_binding = _forward_seed_expected(
            market_store,
            config,
            dates=dates,
            through=through,
            current=current,
            warmup_universe=warmup_universe,
            now=now,
            pinned_binding=origin.get("market_data_binding")
            if origin and prefix is None
            else None,
            prefix=prefix,
        )
        warmup_rows = sum(len(members) for members in expected.values())
        forward_rows = len(current) * forward_sessions
        if warmup_rows + forward_rows > 20_000_000:
            return {
                "status": "blocked",
                "job_ids": [],
                "last_blocker": {
                    "code": "forward_seed_row_budget_exceeded",
                    "warmup_rows": warmup_rows,
                    "minimum_forward_rows": forward_rows,
                    "limit": 20_000_000,
                },
            }
        if origin is None:
            origin = {
                "schema_version": "karkinos.forward_seed_origin.v1",
                "deployment_scope_fingerprint": scope["deployment_scope_fingerprint"],
                "minimum_bars": minimum,
                "verification_source_policy_id": verification_policy,
                "start_date": min(expected).isoformat(),
                "end_date": through.isoformat(),
                "master_observation_id": identity,
                "warmup_instruments": [
                    {"symbol": key.symbol, "instrument_type": key.instrument_type.value}
                    for key in warmup_universe
                ],
                "market_data_binding": market_binding,
            }
            try:
                claimed = origins.claim_automation_run_once_sync(
                    run_id=origin_id,
                    run_type="forward_seed_preparation",
                    run_date=now.date().isoformat(),
                    claimed_at=now.isoformat(),
                    execution_mode="paper_shadow",
                    payload=origin,
                )
            except RuntimeError:
                if origins.get_automation_run_sync(origin_id) is None:
                    raise
                return ensure_forward_seed_for_source(
                    db, config, source=source, now=now, data_store=market_store
                )
            origin_run = claimed["run"]
            if not claimed["claimed"]:
                return ensure_forward_seed_for_source(
                    db, config, source=source, now=now, data_store=market_store
                )
        existing = _existing_forward_seed(
            db,
            config,
            objects,
            catalog,
            dates=dates,
            through=through,
            latest_through=latest_through,
            expected=expected,
            scope=scope,
            now=now,
            forward_sessions=forward_sessions,
        )
        if existing is not None:
            return existing
        jobs = _forward_seed_jobs(
            db,
            config,
            expected=expected,
            prefix=prefix,
            through=through,
            now=now,
            replacements=origin.get("job_replacements", {}),
        )
        if isinstance(jobs, dict):
            return jobs
        summary = _publish_forward_seed(
            db,
            root,
            objects,
            jobs=jobs,
            expected=expected,
            master=master,
            identity=identity,
            prefix=prefix,
            through=through,
            latest_through=latest_through,
            now=now,
            scope=scope,
            prefix_dataset_id=origin_run["source_ref"] if prefix is not None else None,
        )
        origins.upsert_automation_run_sync(
            {
                "run_id": origin_id,
                "run_type": "forward_seed_preparation",
                "run_date": origin_run["run_date"],
                "status": "completed",
                "execution_mode": "paper_shadow",
                "started_at": origin_run["started_at"],
                "finished_at": now.isoformat(),
                "source_ref": summary["dataset_id"],
                "payload": {**origin, "prepared_through": through.isoformat()},
            }
        )
        if through < latest_through:
            return ensure_forward_seed_for_source(
                db, config, source=source, now=now, data_store=market_store
            )
        if forward_sessions:
            from server.services.research_corporate_action_jobs import (
                ensure_dataset_corporate_actions,
            )

            snapshot = read_daily_bar_dataset(
                objects, DatasetRef(objects.resolve_ref(summary["dataset_id"]))
            ).snapshot
            return ensure_dataset_corporate_actions(
                db,
                config,
                snapshot=snapshot,
                now=now,
                prospective_start=through,
            )
        return {
            "status": "ready",
            "dataset_id": summary["dataset_id"],
            "job_ids": [job.job_id for job in jobs],
            "last_blocker": None,
        }
    except (ValueError, KeyError, TypeError, ResearchDatasetError) as exc:
        return {"status": "waiting", "job_ids": [], "last_blocker": {"code": str(exc)}}


def resolve_deployment_evaluation_dataset(
    db: Any,
    *,
    source_result_id: int,
    scope: dict[str, Any],
    start_date: str,
    end_date: str,
    cutoff: datetime,
    data_store: Any = None,
) -> dict[str, Any]:
    """Resolve a frozen source's actual forward inputs, or wait for its worker."""
    from analytics.dataset_snapshot import (
        build_backtest_dataset_snapshot,
        load_immutable_dataset_inputs,
    )
    from server.persistence.automation_runs import AutomationRunRepository
    from server.persistence.research_observations import ResearchObservationsRepository
    from server.persistence.research_paper_books import ResearchPaperBooksRepository
    from server.services.market_universe_truth import (
        MarketUniversePolicy,
        market_master_buy_instruments,
    )

    root = db.path.resolve().parent / "research"
    objects = ContentAddressedObjectStore(root / "objects")
    try:
        required_sessions = verified_dataset_dates(
            db, date.fromisoformat(start_date), date.fromisoformat(end_date)
        )
        calendar_sessions = verified_dataset_dates(
            db,
            date.fromisoformat(start_date),
            date.fromisoformat(end_date) + timedelta(days=15),
        )
    except ResearchDatasetError:
        return {
            "status": "waiting",
            "last_blocker": {"code": "deployment_final_calendar_unavailable"},
        }
    if not required_sessions:
        return {
            "status": "waiting",
            "last_blocker": {"code": "deployment_final_sessions_unavailable"},
        }
    observations = ResearchObservationsRepository(db.path).list(
        limit=100, source_backtest_result_id=source_result_id
    )
    for observation in observations:
        source = observation["source"]
        selection = source.get("source_selection") or source.get("selection") or {}
        if selection.get("deployment_scope") != scope:
            continue
        identities = []
        run = AutomationRunRepository(db.path).get_automation_run_sync(
            f"research-observation-automation:{observation['id']}:latest:data"
        )
        if run is not None:
            identities.append(json.loads(run["payload_json"]).get("dataset_id"))
        book = ResearchPaperBooksRepository(db.path, clock=lambda: cutoff).get(
            observation["id"]
        )
        for rows in (
            observation.get("publications", []),
            observation.get("outcomes", []),
            (book or {}).get("steps", []),
        ):
            identities.extend(row["dataset_id"] for row in rows)
        for identity in dict.fromkeys(item for item in identities if item):
            ref = DatasetRef(objects.resolve_ref(identity))
            try:
                candidate = read_daily_bar_dataset_manifest(objects, ref)
            except DatasetManifestError as exc:
                raise DatasetReaderIntegrityError(
                    "dataset_reader_manifest_invalid"
                ) from exc
            # Manifest bounds only reject irrelevant prefixes. An admissible
            # candidate still reopens all canonical market and source evidence.
            if (
                candidate.universe_policy_id
                != scope.get("deployment_scope_fingerprint")
                or candidate.cutoff > cutoff
                or candidate.start_date > date.fromisoformat(start_date)
                or candidate.end_date < required_sessions[-1]
            ):
                continue
            result = read_daily_bar_dataset(objects, ref)
            snapshot = result.snapshot
            if (
                snapshot.universe_policy_id != scope.get("deployment_scope_fingerprint")
                or snapshot.cutoff > cutoff
                or snapshot.start_date > date.fromisoformat(start_date)
                or snapshot.end_date < required_sessions[-1]
            ):
                continue
            future = [
                item
                for item in snapshot.session_memberships
                if date.fromisoformat(start_date)
                <= item.partition_date
                <= date.fromisoformat(end_date)
            ]
            if not future or any(
                not item.source_observation_ids or item.decision_at is None
                for item in future
            ):
                continue
            if tuple(item.partition_date for item in future) != required_sessions:
                continue
            valid_memberships = True
            for item in future:
                following = next(
                    (day for day in calendar_sessions if day > item.partition_date),
                    None,
                )
                close = datetime.combine(
                    item.partition_date, time(15), ZoneInfo("Asia/Shanghai")
                )
                deadline = (
                    datetime.combine(following, time(9, 30), ZoneInfo("Asia/Shanghai"))
                    if following is not None
                    else None
                )
                if (
                    item.decision_at is None
                    or deadline is None
                    or not close <= item.decision_at < deadline
                ):
                    valid_memberships = False
                    break
                if len(item.source_observation_ids) != 1:
                    valid_memberships = False
                    break
                observed = json.loads(
                    objects.read_bytes(
                        objects.resolve_ref(item.source_observation_ids[0])
                    )
                )
                try:
                    expected_members = market_master_buy_instruments(
                        observed,
                        MarketUniversePolicy.from_dict(scope["universe_policy"]),
                    )
                except ValueError:
                    valid_memberships = False
                    break
                if item.instruments != expected_members:
                    valid_memberships = False
                    break
            if not valid_memberships:
                continue
            if snapshot.end_date != date.fromisoformat(end_date):
                selected_memberships = tuple(
                    item
                    for item in snapshot.session_memberships
                    if item.partition_date <= date.fromisoformat(end_date)
                )
                selected_instruments = tuple(
                    sorted(
                        {
                            key
                            for item in selected_memberships
                            for key in (
                                *item.instruments,
                                *item.maintenance_instruments,
                            )
                        },
                        key=lambda key: (key.instrument_type.value, key.symbol),
                    )
                )
                if (
                    snapshot.corporate_action_observation_ids
                    and selected_instruments != snapshot.instruments
                ):
                    # A new action composition needs its own exact coverage;
                    # never drop reports or rewrite settled financial prefixes.
                    continue
                snapshot = replace(
                    snapshot,
                    end_date=date.fromisoformat(end_date),
                    instruments=selected_instruments,
                    partitions=tuple(
                        part
                        for part in snapshot.partitions
                        if part.partition_date <= date.fromisoformat(end_date)
                    ),
                    session_memberships=selected_memberships,
                )
                ref = publish_daily_bar_dataset_manifest(objects, snapshot)
                read_daily_bar_dataset(objects, ref)
                identity = ref.dataset_id
            _, handlers, binding = load_immutable_dataset_inputs(
                root, {"immutable_dataset_id": identity}
            )
            report_snapshot = build_backtest_dataset_snapshot(
                start_date=snapshot.start_date.isoformat(),
                end_date=snapshot.end_date.isoformat(),
                configured_source="verified_forward_dataset",
                data_handlers=handlers,
                store=data_store,
                source_names=binding["source_names"],
                research_dataset_binding=binding,
            )
            return {
                "status": "ready",
                "dataset_id": identity,
                "dataset_snapshot": report_snapshot,
                "observation_id": observation["id"],
                "last_blocker": None,
            }
    return {
        "status": "waiting",
        "last_blocker": {"code": "deployment_final_inputs_pending"},
    }


def verified_dataset_dates(
    db: Any,
    start: date,
    end: date,
    config: Any = None,
) -> tuple[date, ...]:
    """复用项目已有的交易日历事实，不能用工作日或返回的行情猜交易日。"""
    dates: list[date] = []
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
