"""Point-in-Time Dataset Resolver 测试。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from core.types import InstrumentKey, InstrumentType
from data.dataset.resolver import (
    DailyBarDatasetResolverPolicy,
    DailyBarResolutionCandidate,
    DatasetPartitionAmbiguousError,
    DatasetPartitionUnresolvedError,
    DatasetResolverIntegrityError,
    resolve_daily_bar_dataset,
)
from data.market.capture import capture_provider_payload
from data.market.normalize import normalize_daily_bar
from data.market.quality import (
    RESEARCH_STRICT_DAILY,
    MarketDataQualityReport,
    MarketQualityStatus,
)
from data.market.revision import (
    publish_daily_bar_revision,
)
from data.storage.objects import ContentAddressedObjectStore

_SESSION_DATE = date(2026, 9, 15)

_EVENT_TIME = datetime(
    2026,
    9,
    15,
    7,
    0,
    tzinfo=timezone.utc,
)

_EARLY_AVAILABLE_AT = datetime(
    2026,
    9,
    15,
    7,
    1,
    tzinfo=timezone.utc,
)

_EARLY_CAPTURED_AT = datetime(
    2026,
    9,
    15,
    7,
    3,
    tzinfo=timezone.utc,
)

_LATE_AVAILABLE_AT = datetime(
    2026,
    9,
    15,
    9,
    0,
    tzinfo=timezone.utc,
)

_LATE_CAPTURED_AT = datetime(
    2026,
    9,
    15,
    9,
    3,
    tzinfo=timezone.utc,
)

_CUTOFF = datetime(
    2026,
    9,
    15,
    8,
    0,
    tzinfo=timezone.utc,
)


def _instrument(
    symbol: str,
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _universe() -> tuple[InstrumentKey, ...]:
    return (
        _instrument("000001"),
        _instrument("600000"),
    )


def _policy(
    *,
    provider_priority: tuple[str, ...] = (
        "tdx",
        "tushare",
        "akshare",
    ),
    allow_degraded_quality: bool = False,
) -> DailyBarDatasetResolverPolicy:
    return DailyBarDatasetResolverPolicy(
        policy_id="karkinos.dataset.pit.strict.v1",
        provider_priority=provider_priority,
        required_quality_policy_id=(RESEARCH_STRICT_DAILY.policy_id),
        allow_degraded_quality=(allow_degraded_quality),
    )


def _bar(
    symbol: str,
    *,
    available_at: datetime,
    captured_at: datetime,
    close: str | None = None,
):
    if symbol == "000001":
        open_value = "12.10"
        high_value = "12.50"
        low_value = "12.00"
        close_value = close if close is not None else "12.34"
        volume = "100000"
        amount = "1234000"

    elif symbol == "601398":
        open_value = "6.18"
        high_value = "6.25"
        low_value = "6.10"
        close_value = close if close is not None else "6.20"
        volume = "234567"
        amount = "1454321.54"

    else:
        open_value = "10.31"
        high_value = "10.52"
        low_value = "10.20"
        close_value = close if close is not None else "10.48"
        volume = "123456"
        amount = "1283912.42"

    return normalize_daily_bar(
        instrument=_instrument(symbol),
        session_date=_SESSION_DATE,
        event_time=_EVENT_TIME,
        available_at=available_at,
        captured_at=captured_at,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close_value,
        volume=volume,
        amount=amount,
        suspended=False,
    )


def _bars(
    *,
    available_at: datetime = _EARLY_AVAILABLE_AT,
    captured_at: datetime = _EARLY_CAPTURED_AT,
    close_600000: str = "10.48",
    include_000001: bool = True,
    extra_instrument: bool = False,
):
    result = []

    if include_000001:
        result.append(
            _bar(
                "000001",
                available_at=available_at,
                captured_at=captured_at,
            )
        )

    result.append(
        _bar(
            "600000",
            available_at=available_at,
            captured_at=captured_at,
            close=close_600000,
        )
    )

    if extra_instrument:
        result.append(
            _bar(
                "601398",
                available_at=available_at,
                captured_at=captured_at,
                close="6.20",
            )
        )

    return tuple(result)


def _capture(
    store: ContentAddressedObjectStore,
    *,
    provider: str,
    captured_at: datetime,
    raw_payload: bytes,
    record_count: int,
):
    return capture_provider_payload(
        store,
        provider=provider,
        operation="daily_bars",
        request={
            "kind": "daily_bars",
            "frequency": "1d",
            "start_date": _SESSION_DATE.isoformat(),
            "end_date": _SESSION_DATE.isoformat(),
            "instruments": [
                {
                    "symbol": "000001",
                    "instrument_type": "stock",
                },
                {
                    "symbol": "600000",
                    "instrument_type": "stock",
                },
            ],
        },
        raw_payload=raw_payload,
        payload_format=f"{provider}.daily_bars.v1",
        adapter_version=f"karkinos.{provider}.v1",
        started_at=(captured_at - timedelta(milliseconds=500)),
        completed_at=captured_at,
        record_count=record_count,
    )


def _quality_report(
    *,
    revision_id: str,
    materialization_id: str,
    status: MarketQualityStatus = (MarketQualityStatus.PASS),
    policy_id: str = (RESEARCH_STRICT_DAILY.policy_id),
    observed_count: int = 2,
) -> MarketDataQualityReport:
    return MarketDataQualityReport(
        revision_id=revision_id,
        materialization_id=materialization_id,
        policy_id=policy_id,
        status=status,
        checked_at=datetime(
            2026,
            9,
            15,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        observed_instrument_count=(observed_count),
        expected_instrument_count=2,
        diagnostics=(),
    )


def _candidate(
    store: ContentAddressedObjectStore,
    *,
    provider: str = "tdx",
    available_at: datetime = _EARLY_AVAILABLE_AT,
    captured_at: datetime = _EARLY_CAPTURED_AT,
    close_600000: str = "10.48",
    include_000001: bool = True,
    extra_instrument: bool = False,
    quality_status: MarketQualityStatus = (MarketQualityStatus.PASS),
    quality_policy_id: str = (RESEARCH_STRICT_DAILY.policy_id),
    raw_payload: bytes | None = None,
) -> DailyBarResolutionCandidate:
    bars = _bars(
        available_at=available_at,
        captured_at=captured_at,
        close_600000=close_600000,
        include_000001=include_000001,
        extra_instrument=extra_instrument,
    )

    if raw_payload is None:
        raw_payload = (
            f"{provider}:"
            f"{available_at.isoformat()}:"
            f"{captured_at.isoformat()}:"
            f"{close_600000}:"
            f"{len(bars)}"
        ).encode()

    capture = _capture(
        store,
        provider=provider,
        captured_at=captured_at,
        raw_payload=raw_payload,
        record_count=len(bars),
    )

    revision, materialization = publish_daily_bar_revision(
        store,
        capture=capture,
        bars=bars,
        normalizer_version=("karkinos.market.normalize.v1"),
    )

    quality = _quality_report(
        revision_id=(revision.ref.revision_id),
        materialization_id=(materialization.materialization_id),
        status=quality_status,
        policy_id=quality_policy_id,
        observed_count=len(bars),
    )

    return DailyBarResolutionCandidate(
        revision=revision,
        materialization=materialization,
        quality=quality,
    )


def _resolve(
    store: ContentAddressedObjectStore,
    *,
    candidates,
    cutoff: datetime = _CUTOFF,
    policy: DailyBarDatasetResolverPolicy | None = None,
    instruments: tuple[InstrumentKey, ...] | None = None,
    expected_partition_dates: tuple[date, ...] = (_SESSION_DATE,),
):
    return resolve_daily_bar_dataset(
        store,
        candidates=tuple(candidates),
        start_date=_SESSION_DATE,
        end_date=_SESSION_DATE,
        cutoff=cutoff,
        instruments=(instruments if instruments is not None else _universe()),
        expected_partition_dates=(expected_partition_dates),
        policy=(policy if policy is not None else _policy()),
    )


def test_candidate_available_before_cutoff_is_selected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        provider="tdx",
    )

    snapshot = _resolve(
        store,
        candidates=(candidate,),
    )

    assert snapshot.partition_count == 1

    partition = snapshot.partitions[0]

    assert partition.partition_date == _SESSION_DATE
    assert partition.provider == "tdx"

    assert partition.revision_id == candidate.revision.ref.revision_id

    assert partition.materialization_id == candidate.materialization.materialization_id


def test_candidate_available_exactly_at_cutoff_is_eligible(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        available_at=_CUTOFF,
        captured_at=(_CUTOFF + timedelta(minutes=1)),
    )

    snapshot = _resolve(
        store,
        candidates=(candidate,),
    )

    assert snapshot.partition_count == 1


def test_candidate_available_after_cutoff_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        available_at=_LATE_AVAILABLE_AT,
        captured_at=_LATE_CAPTURED_AT,
    )

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ) as caught:
        _resolve(
            store,
            candidates=(candidate,),
        )

    assert caught.value.partition_date == _SESSION_DATE


def test_future_revision_does_not_replace_pit_revision(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    early = _candidate(
        store,
        provider="tdx",
        available_at=_EARLY_AVAILABLE_AT,
        captured_at=_EARLY_CAPTURED_AT,
        close_600000="10.48",
        raw_payload=b"tdx-r1",
    )

    future = _candidate(
        store,
        provider="tdx",
        available_at=_LATE_AVAILABLE_AT,
        captured_at=_LATE_CAPTURED_AT,
        close_600000="10.49",
        raw_payload=b"tdx-r2",
    )

    assert early.revision.ref != future.revision.ref

    snapshot = _resolve(
        store,
        candidates=(
            future,
            early,
        ),
    )

    assert snapshot.partitions[0].revision_id == early.revision.ref.revision_id


def test_latest_available_revision_is_selected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _candidate(
        store,
        available_at=datetime(
            2026,
            9,
            15,
            7,
            1,
            tzinfo=timezone.utc,
        ),
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            3,
            tzinfo=timezone.utc,
        ),
        close_600000="10.48",
        raw_payload=b"r1",
    )

    second = _candidate(
        store,
        available_at=datetime(
            2026,
            9,
            15,
            7,
            30,
            tzinfo=timezone.utc,
        ),
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            31,
            tzinfo=timezone.utc,
        ),
        close_600000="10.49",
        raw_payload=b"r2",
    )

    snapshot = _resolve(
        store,
        candidates=(
            first,
            second,
        ),
    )

    assert snapshot.partitions[0].revision_id == second.revision.ref.revision_id


def test_provider_priority_wins_over_later_lower_priority_provider(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    tdx = _candidate(
        store,
        provider="tdx",
        available_at=datetime(
            2026,
            9,
            15,
            7,
            1,
            tzinfo=timezone.utc,
        ),
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            3,
            tzinfo=timezone.utc,
        ),
        raw_payload=b"tdx",
    )

    tushare = _candidate(
        store,
        provider="tushare",
        available_at=datetime(
            2026,
            9,
            15,
            7,
            30,
            tzinfo=timezone.utc,
        ),
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            31,
            tzinfo=timezone.utc,
        ),
        raw_payload=b"tushare",
    )

    snapshot = _resolve(
        store,
        candidates=(
            tushare,
            tdx,
        ),
    )

    assert snapshot.partitions[0].provider == "tdx"


def test_unavailable_primary_provider_falls_back(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    future_tdx = _candidate(
        store,
        provider="tdx",
        available_at=_LATE_AVAILABLE_AT,
        captured_at=_LATE_CAPTURED_AT,
        raw_payload=b"tdx-future",
    )

    tushare = _candidate(
        store,
        provider="tushare",
        raw_payload=b"tushare-available",
    )

    snapshot = _resolve(
        store,
        candidates=(
            future_tdx,
            tushare,
        ),
    )

    assert snapshot.partitions[0].provider == "tushare"


def test_blocked_quality_candidate_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        quality_status=(MarketQualityStatus.BLOCKED),
    )

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ):
        _resolve(
            store,
            candidates=(candidate,),
        )


def test_blocked_primary_provider_falls_back(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    tdx = _candidate(
        store,
        provider="tdx",
        quality_status=(MarketQualityStatus.BLOCKED),
        raw_payload=b"tdx-blocked",
    )

    tushare = _candidate(
        store,
        provider="tushare",
        raw_payload=b"tushare-pass",
    )

    snapshot = _resolve(
        store,
        candidates=(tdx, tushare),
    )

    assert snapshot.partitions[0].provider == "tushare"


def test_degraded_quality_is_rejected_by_strict_policy(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        quality_status=(MarketQualityStatus.DEGRADED),
    )

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ):
        _resolve(
            store,
            candidates=(candidate,),
        )


def test_policy_can_explicitly_allow_degraded_quality(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        quality_status=(MarketQualityStatus.DEGRADED),
    )

    snapshot = _resolve(
        store,
        candidates=(candidate,),
        policy=_policy(
            allow_degraded_quality=True,
        ),
    )

    assert snapshot.partition_count == 1


def test_quality_report_from_wrong_policy_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        quality_policy_id=("karkinos.market_quality.daily.serving_relaxed.v1"),
    )

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ):
        _resolve(
            store,
            candidates=(candidate,),
        )


def test_candidate_missing_requested_instrument_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        include_000001=False,
    )

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ):
        _resolve(
            store,
            candidates=(candidate,),
        )


def test_revision_may_contain_extra_instruments(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
        extra_instrument=True,
    )

    snapshot = _resolve(
        store,
        candidates=(candidate,),
    )

    assert snapshot.instrument_count == 2
    assert snapshot.partition_count == 1


def test_missing_expected_partition_fails_closed(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ) as caught:
        _resolve(
            store,
            candidates=(),
        )

    assert caught.value.partition_date == _SESSION_DATE


def test_same_availability_with_different_revisions_is_ambiguous(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    first = _candidate(
        store,
        provider="tdx",
        available_at=_EARLY_AVAILABLE_AT,
        captured_at=_EARLY_CAPTURED_AT,
        close_600000="10.48",
        raw_payload=b"tdx-r1",
    )

    second = _candidate(
        store,
        provider="tdx",
        available_at=_EARLY_AVAILABLE_AT,
        captured_at=_EARLY_CAPTURED_AT,
        close_600000="10.49",
        raw_payload=b"tdx-r2",
    )

    assert first.revision.ref != second.revision.ref

    with pytest.raises(
        DatasetPartitionAmbiguousError,
    ) as caught:
        _resolve(
            store,
            candidates=(
                first,
                second,
            ),
        )

    assert caught.value.partition_date == _SESSION_DATE
    assert caught.value.provider == "tdx"


def test_same_revision_multiple_materializations_selects_earliest_capture(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    early = _candidate(
        store,
        provider="tdx",
        available_at=_EARLY_AVAILABLE_AT,
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            3,
            tzinfo=timezone.utc,
        ),
        raw_payload=b"early-capture",
    )

    late = _candidate(
        store,
        provider="tdx",
        available_at=_EARLY_AVAILABLE_AT,
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            45,
            tzinfo=timezone.utc,
        ),
        raw_payload=b"late-capture",
    )

    # availability/captured_at 不属于 Revision 的逻辑市场事实 identity。
    assert early.revision.ref == late.revision.ref

    assert (
        early.materialization.materialization_id
        != late.materialization.materialization_id
    )

    snapshot = _resolve(
        store,
        candidates=(
            late,
            early,
        ),
    )

    assert (
        snapshot.partitions[0].materialization_id
        == early.materialization.materialization_id
    )


def test_candidate_input_order_does_not_change_snapshot(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    tdx = _candidate(
        store,
        provider="tdx",
        raw_payload=b"tdx",
    )

    tushare = _candidate(
        store,
        provider="tushare",
        raw_payload=b"tushare",
    )

    forward = _resolve(
        store,
        candidates=(
            tdx,
            tushare,
        ),
    )

    reverse = _resolve(
        store,
        candidates=(
            tushare,
            tdx,
        ),
    )

    assert forward == reverse


def test_provider_not_in_policy_is_ignored(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    akshare = _candidate(
        store,
        provider="akshare",
        raw_payload=b"akshare",
    )

    with pytest.raises(
        DatasetPartitionUnresolvedError,
    ):
        _resolve(
            store,
            candidates=(akshare,),
            policy=_policy(
                provider_priority=(
                    "tdx",
                    "tushare",
                )
            ),
        )


def test_quality_revision_binding_must_match_candidate(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
    )

    forged_quality = _quality_report(
        revision_id=("sha256:" + "f" * 64),
        materialization_id=(candidate.materialization.materialization_id),
    )

    forged = DailyBarResolutionCandidate(
        revision=candidate.revision,
        materialization=(candidate.materialization),
        quality=forged_quality,
    )

    with pytest.raises(
        DatasetResolverIntegrityError,
        match=("dataset_resolver_quality_revision_mismatch"),
    ):
        _resolve(
            store,
            candidates=(forged,),
        )


def test_quality_materialization_binding_must_match_candidate(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
    )

    forged_quality = _quality_report(
        revision_id=(candidate.revision.ref.revision_id),
        materialization_id=("sha256:" + "e" * 64),
    )

    forged = DailyBarResolutionCandidate(
        revision=candidate.revision,
        materialization=(candidate.materialization),
        quality=forged_quality,
    )

    with pytest.raises(
        DatasetResolverIntegrityError,
        match=("dataset_resolver_quality_materialization_mismatch"),
    ):
        _resolve(
            store,
            candidates=(forged,),
        )


def test_unexpected_candidate_partition_is_rejected(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
    )

    with pytest.raises(
        ValueError,
        match=("dataset_resolver_candidate_partition_unexpected"),
    ):
        resolve_daily_bar_dataset(
            store,
            candidates=(candidate,),
            start_date=date(
                2026,
                9,
                14,
            ),
            end_date=date(
                2026,
                9,
                15,
            ),
            cutoff=_CUTOFF,
            instruments=_universe(),
            expected_partition_dates=(
                date(
                    2026,
                    9,
                    14,
                ),
            ),
            policy=_policy(),
        )


def test_empty_expected_partition_dates_produces_empty_snapshot(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    snapshot = _resolve(
        store,
        candidates=(),
        expected_partition_dates=(),
    )

    assert snapshot.partition_count == 0
    assert snapshot.partitions == ()


def test_cutoff_is_normalized_to_utc(
    tmp_path,
) -> None:
    store = ContentAddressedObjectStore(tmp_path / "objects")

    candidate = _candidate(
        store,
    )

    shanghai = timezone(timedelta(hours=8))

    snapshot = _resolve(
        store,
        candidates=(candidate,),
        cutoff=datetime(
            2026,
            9,
            15,
            16,
            0,
            tzinfo=shanghai,
        ),
    )

    assert snapshot.cutoff == _CUTOFF
