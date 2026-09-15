"""Market Data ingestion 编排。

本模块负责把一次 Provider 数据调用串成完整的数据底座流程：

    DailyBarRequest
        ↓
    DailyBarProvider
        ↓
    ProviderDailyBarBatch
        ↓
    ProviderCapture
        ↓
    canonical normalization
        ↓
    MarketRevision
        ↓
    Quality Gate
        ↓
    DailyBarIngestionResult

本模块不负责：

- Provider SDK 的具体调用细节；
- Provider 字段解释；
- Dataset 构建；
- Serving Store 更新；
- 自动修复坏数据；
- Provider fallback。

Quality BLOCKED 不会删除或回滚 MarketRevision。
Revision 是“Provider 曾经提供过哪版市场事实”，Quality 只决定它是否
适合进入某种下游用途。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from data.market.capture import (
    ProviderCapture,
    capture_provider_payload,
)
from data.market.contracts import (
    DailyBarProvider,
    DailyBarRequest,
    ProviderDailyBarBatch,
)
from data.market.normalize import (
    canonicalize_daily_bars,
    normalize_daily_bar,
)
from data.market.quality import (
    DailyBarQualityPolicy,
    MarketDataQualityReport,
    MarketQualityDiagnostic,
    evaluate_daily_bar_revision,
)
from data.market.revision import (
    MarketRevision,
    MarketRevisionMaterialization,
    publish_daily_bar_revision,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
)

logger = logging.getLogger(__name__)


class DailyBarIngestionError(RuntimeError):
    """日线 ingestion 基础异常。"""


class DailyBarIngestionNoData(DailyBarIngestionError):
    """Provider 调用成功，但没有返回任何日线记录。"""

    def __init__(
        self,
        capture: ProviderCapture,
    ) -> None:
        self.capture = capture

        super().__init__(f"daily_bar_ingestion_no_data:{capture.capture_id}")


@dataclass(frozen=True, slots=True)
class DailyBarIngestionResult:
    """一次完整日线 ingestion 的结果。

    即使 Quality 为 BLOCKED，Capture、Revision 和 Materialization
    仍然保留，用于审计、reconciliation 和后续数据修订分析。
    """

    capture: ProviderCapture

    revision: MarketRevision

    materialization: MarketRevisionMaterialization

    quality: MarketDataQualityReport

    @property
    def eligible_for_dataset_publication(
        self,
    ) -> bool:
        """是否允许进入采用当前 Quality Policy 的 Dataset 发布路径。"""
        return not self.quality.blocks_publication


def ingest_daily_bars(
    provider: DailyBarProvider,
    store: ContentAddressedObjectStore,
    *,
    request: DailyBarRequest,
    quality_policy: DailyBarQualityPolicy,
    normalizer_version: str,
    checked_at: datetime | None = None,
    additional_diagnostics: Iterable[MarketQualityDiagnostic] = (),
) -> DailyBarIngestionResult:
    """执行一次完整的日线 Market Data ingestion。

    Provider 请求失败属于外部 I/O 失败，会记录一次异常日志并继续上抛。

    Provider 调用成功但返回空结果时，仍然先固化 Capture，然后抛出
    ``DailyBarIngestionNoData``。这样既不会制造空 MarketRevision，
    又不会丢失“Provider 当时确实返回了空结果”的证据。

    Quality BLOCKED 不抛异常，而是作为正常 ingestion 结果返回。
    """
    try:
        batch = provider.fetch_daily_bars(request)
    except Exception:
        # ingestion 是 Provider I/O 的业务边界。
        # Provider 内部不应重复记录同一个最终失败。
        logger.exception(
            "日线 Provider 调用失败 start=%s end=%s instruments=%d",
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            len(request.instruments),
        )
        raise

    capture = _capture_batch(
        store,
        request=request,
        batch=batch,
    )

    if not batch.rows:
        logger.warning(
            "日线 Provider 返回空结果 "
            "provider=%s capture_id=%s "
            "start=%s end=%s instruments=%d",
            batch.provider,
            capture.capture_id,
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            len(request.instruments),
        )

        raise DailyBarIngestionNoData(capture)

    try:
        bars = _normalize_batch(batch)

        revision, materialization = publish_daily_bar_revision(
            store,
            capture=capture,
            bars=bars,
            normalizer_version=(normalizer_version),
        )

        quality = evaluate_daily_bar_revision(
            store,
            revision=revision,
            materialization=materialization,
            policy=quality_policy,
            expected_instruments=(request.instruments),
            checked_at=checked_at,
            additional_diagnostics=(additional_diagnostics),
        )

    except Exception:
        # 到这里 Capture 已经成功固化，因此任何后续失败都可以通过
        # capture_id 回溯 Provider 原始数据。
        logger.exception(
            "日线 ingestion 处理失败 provider=%s capture_id=%s rows=%d",
            batch.provider,
            capture.capture_id,
            batch.record_count,
        )
        raise

    result = DailyBarIngestionResult(
        capture=capture,
        revision=revision,
        materialization=materialization,
        quality=quality,
    )

    logger.info(
        "日线 ingestion 完成 "
        "provider=%s capture_id=%s revision_id=%s "
        "materialization_id=%s rows=%d quality=%s "
        "dataset_eligible=%s",
        batch.provider,
        capture.capture_id,
        revision.ref.revision_id,
        materialization.materialization_id,
        revision.row_count,
        quality.status.value,
        result.eligible_for_dataset_publication,
    )

    return result


def _capture_batch(
    store: ContentAddressedObjectStore,
    *,
    request: DailyBarRequest,
    batch: ProviderDailyBarBatch,
) -> ProviderCapture:
    """将 Provider Batch 的原始响应固化为 Capture。"""
    return capture_provider_payload(
        store,
        provider=batch.provider,
        operation="daily_bars",
        request=request.to_capture_request(),
        raw_payload=batch.raw_payload,
        payload_format=batch.payload_format,
        adapter_version=batch.adapter_version,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        record_count=batch.record_count,
    )


def _normalize_batch(
    batch: ProviderDailyBarBatch,
):
    """将 Provider 边界记录转换为 canonical 日线批次。

    Provider 没有提供 ``available_at`` 时，使用本次 Provider 调用的
    ``completed_at`` 作为保守的可用时间。

    这意味着 Karkinos 不会声称某条数据在实际抓到之前就已经可用。
    """
    bars = []

    for row in batch.rows:
        available_at = (
            row.available_at if row.available_at is not None else batch.completed_at
        )

        bars.append(
            normalize_daily_bar(
                instrument=row.instrument,
                session_date=row.session_date,
                event_time=row.event_time,
                available_at=available_at,
                captured_at=batch.completed_at,
                open_value=row.open_value,
                high_value=row.high_value,
                low_value=row.low_value,
                close_value=row.close_value,
                volume=row.volume,
                amount=row.amount,
                suspended=row.suspended,
            )
        )

    return canonicalize_daily_bars(bars)
