"""Immutable cross-source verification evidence for canonical market facts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import MarketDataProviderDescriptor
from data.market.model import DailyBarObservation
from data.market.quality import MarketQualityStatus
from data.market.quality_evidence import (
    MarketQualityEvidence,
    MarketQualityEvidenceIntegrityError,
    read_market_quality_evidence,
)
from data.market.reconciliation import (
    BSE_AUCTION_RELATION_KIND,
    BSE_TENCENT_AMOUNT_COMPARISON,
    BSE_TENCENT_REPORTED_RELATION_KIND,
    STRICT_DAILY_RECONCILIATION,
    BseAuctionRelation,
    BseTencentReportedRelation,
    DailyBarReconciliationPolicy,
    MarketReconciliationDifference,
    MarketReconciliationReport,
    ReconciliationDifferenceKind,
)
from data.providers.bse_sina_history import (
    TENCENT_BSE_NATIVE_ADAPTERS,
    bse_native_read_scope,
    exact_bse_arithmetic,
)
from data.storage.objects import (
    ContentAddressedObjectStore,
    ObjectRef,
    ObjectStoreError,
)

MARKET_VERIFICATION_EVIDENCE_SCHEMA_VERSION = "karkinos.market_verification_evidence.v1"
MARKET_VERIFICATION_POLICY_ID = "karkinos.market_verification.daily.v1"
BSE_AUCTION_VERIFICATION_SCHEMA = "karkinos.market_verification_evidence.v2"
_CONTENT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class MarketVerificationStatus(str, Enum):
    MATCHED = "matched"
    CONFLICT = "conflict"


class MarketVerificationEvidenceError(RuntimeError):
    """Base error for cross-source verification evidence."""


class MarketVerificationEvidenceIntegrityError(MarketVerificationEvidenceError):
    """Persisted verification evidence is unreadable or inconsistent."""


@dataclass(frozen=True, slots=True)
class MarketVerificationEvidence:
    ref: ObjectRef
    report: MarketReconciliationReport
    primary_materialization_id: str
    comparison_materialization_id: str
    primary_quality_id: str
    comparison_quality_id: str
    primary_upstream_group: str
    comparison_upstream_group: str
    primary_adapter_version: str
    comparison_adapter_version: str
    policy: DailyBarReconciliationPolicy
    checked_at: datetime
    component_relation: BseAuctionRelation | BseTencentReportedRelation | None = None

    @property
    def verification_id(self) -> str:
        return self.ref.object_id

    @property
    def status(self) -> MarketVerificationStatus:
        return (
            MarketVerificationStatus.MATCHED
            if self.report.matched
            else MarketVerificationStatus.CONFLICT
        )


def publish_market_verification_evidence(
    store: ContentAddressedObjectStore,
    *,
    report: MarketReconciliationReport,
    primary_quality: MarketQualityEvidence,
    comparison_quality: MarketQualityEvidence,
    primary_descriptor: MarketDataProviderDescriptor,
    comparison_descriptor: MarketDataProviderDescriptor,
    policy: DailyBarReconciliationPolicy,
    checked_at: datetime,
    component_relation: BseAuctionRelation | BseTencentReportedRelation | None = None,
) -> MarketVerificationEvidence:
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("market_verification_evidence_store_invalid")
    if not isinstance(report, MarketReconciliationReport):
        raise TypeError("market_verification_evidence_report_invalid")
    if not isinstance(primary_quality, MarketQualityEvidence) or not isinstance(
        comparison_quality, MarketQualityEvidence
    ):
        raise TypeError("market_verification_evidence_quality_invalid")
    if not isinstance(
        primary_descriptor, MarketDataProviderDescriptor
    ) or not isinstance(comparison_descriptor, MarketDataProviderDescriptor):
        raise TypeError("market_verification_evidence_descriptor_invalid")
    if not isinstance(policy, DailyBarReconciliationPolicy):
        raise TypeError("market_verification_evidence_policy_invalid")

    _validate_quality_binding(
        report=report,
        primary_quality=primary_quality,
        comparison_quality=comparison_quality,
        primary_descriptor=primary_descriptor,
        comparison_descriptor=comparison_descriptor,
    )
    if primary_descriptor.upstream_group == comparison_descriptor.upstream_group:
        raise MarketVerificationEvidenceError(
            "market_verification_upstream_groups_not_independent"
        )

    # Prove that both referenced quality decisions are already durable in this store.
    try:
        if read_market_quality_evidence(store, primary_quality.ref) != primary_quality:
            raise MarketVerificationEvidenceIntegrityError(
                "market_verification_primary_quality_mismatch"
            )
        if (
            read_market_quality_evidence(store, comparison_quality.ref)
            != comparison_quality
        ):
            raise MarketVerificationEvidenceIntegrityError(
                "market_verification_comparison_quality_mismatch"
            )
    except MarketQualityEvidenceIntegrityError as exc:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_quality_unreadable"
        ) from exc

    evidence = MarketVerificationEvidence(
        ref=ObjectRef(
            object_id="sha256:" + "0" * 64,
            size_bytes=0,
        ),
        report=report,
        primary_materialization_id=primary_quality.report.materialization_id,
        comparison_materialization_id=comparison_quality.report.materialization_id,
        primary_quality_id=primary_quality.quality_id,
        comparison_quality_id=comparison_quality.quality_id,
        primary_upstream_group=primary_descriptor.upstream_group,
        comparison_upstream_group=comparison_descriptor.upstream_group,
        primary_adapter_version=primary_descriptor.adapter_version,
        comparison_adapter_version=comparison_descriptor.adapter_version,
        policy=policy,
        checked_at=_utc_instant(checked_at),
        component_relation=component_relation,
    )
    if component_relation is not None:
        _validate_component_metadata(evidence)
        _replay_component_evidence(store, evidence)
    payload = _serialize(evidence)
    ref = store.put_bytes(payload)
    return MarketVerificationEvidence(
        ref=ref,
        report=evidence.report,
        primary_materialization_id=evidence.primary_materialization_id,
        comparison_materialization_id=evidence.comparison_materialization_id,
        primary_quality_id=evidence.primary_quality_id,
        comparison_quality_id=evidence.comparison_quality_id,
        primary_upstream_group=evidence.primary_upstream_group,
        comparison_upstream_group=evidence.comparison_upstream_group,
        primary_adapter_version=evidence.primary_adapter_version,
        comparison_adapter_version=evidence.comparison_adapter_version,
        policy=evidence.policy,
        checked_at=evidence.checked_at,
        component_relation=evidence.component_relation,
    )


def read_market_verification_evidence(
    store: ContentAddressedObjectStore,
    ref: ObjectRef,
) -> MarketVerificationEvidence:
    evidence, _ = read_market_verification_evidence_with_component_bars(store, ref)
    return evidence


def read_market_verification_evidence_with_component_bars(
    store: ContentAddressedObjectStore,
    ref: ObjectRef,
) -> tuple[
    MarketVerificationEvidence,
    tuple[tuple[DailyBarObservation, ...], tuple[DailyBarObservation, ...]] | None,
]:
    """Read all evidence and retain the bars from this component replay only."""
    if not isinstance(store, ContentAddressedObjectStore):
        raise TypeError("market_verification_evidence_store_invalid")
    if not isinstance(ref, ObjectRef):
        raise TypeError("market_verification_evidence_ref_invalid")
    try:
        raw = store.read_bytes(ref)
    except ObjectStoreError as exc:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_evidence_object_unreadable"
        ) from exc
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_evidence_json_invalid"
        ) from exc

    evidence = _from_payload(ref, payload)
    if _serialize(evidence) != raw:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_evidence_not_canonical"
        )
    _validate_referenced_quality(store, evidence)
    component_bars = None
    if evidence.component_relation is not None:
        try:
            component_bars = _replay_component_evidence(store, evidence)
        except (ObjectStoreError, TypeError, ValueError) as exc:
            raise MarketVerificationEvidenceIntegrityError(
                "market_verification_component_replay_failed"
            ) from exc
    return evidence, component_bars


def _validate_quality_binding(
    *,
    report: MarketReconciliationReport,
    primary_quality: MarketQualityEvidence,
    comparison_quality: MarketQualityEvidence,
    primary_descriptor: MarketDataProviderDescriptor,
    comparison_descriptor: MarketDataProviderDescriptor,
) -> None:
    if primary_descriptor.provider != report.primary_provider:
        raise MarketVerificationEvidenceError(
            "market_verification_primary_provider_mismatch"
        )
    if comparison_descriptor.provider != report.comparison_provider:
        raise MarketVerificationEvidenceError(
            "market_verification_comparison_provider_mismatch"
        )
    if primary_quality.report.revision_id != report.primary_revision_id:
        raise MarketVerificationEvidenceError(
            "market_verification_primary_revision_mismatch"
        )
    if comparison_quality.report.revision_id != report.comparison_revision_id:
        raise MarketVerificationEvidenceError(
            "market_verification_comparison_revision_mismatch"
        )
    if primary_quality.report.status is not MarketQualityStatus.PASS:
        raise MarketVerificationEvidenceError(
            "market_verification_primary_quality_not_passing"
        )
    if comparison_quality.report.status is not MarketQualityStatus.PASS:
        raise MarketVerificationEvidenceError(
            "market_verification_comparison_quality_not_passing"
        )


def _validate_referenced_quality(
    store: ContentAddressedObjectStore,
    evidence: MarketVerificationEvidence,
) -> None:
    try:
        primary = read_market_quality_evidence(
            store, store.resolve_ref(evidence.primary_quality_id)
        )
        comparison = read_market_quality_evidence(
            store, store.resolve_ref(evidence.comparison_quality_id)
        )
    except (ObjectStoreError, MarketQualityEvidenceIntegrityError) as exc:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_quality_unreadable"
        ) from exc
    if primary.report.revision_id != evidence.report.primary_revision_id:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_primary_quality_revision_mismatch"
        )
    if primary.report.materialization_id != evidence.primary_materialization_id:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_primary_quality_materialization_mismatch"
        )
    if comparison.report.revision_id != evidence.report.comparison_revision_id:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_comparison_quality_revision_mismatch"
        )
    if comparison.report.materialization_id != evidence.comparison_materialization_id:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_comparison_quality_materialization_mismatch"
        )
    if primary.report.status is not MarketQualityStatus.PASS:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_primary_quality_not_passing"
        )
    if comparison.report.status is not MarketQualityStatus.PASS:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_comparison_quality_not_passing"
        )


def _serialize(evidence: MarketVerificationEvidence) -> bytes:
    payload = {
        "schema_version": MARKET_VERIFICATION_EVIDENCE_SCHEMA_VERSION
        if evidence.component_relation is None
        else BSE_AUCTION_VERIFICATION_SCHEMA,
        "policy_id": MARKET_VERIFICATION_POLICY_ID
        if evidence.component_relation is None
        else _component_kind(evidence.component_relation),
        "checked_at": _format_utc(evidence.checked_at),
        "status": evidence.status.value,
        "policy": {
            "price_tolerance": _decimal_text(evidence.policy.price_tolerance),
            "volume_tolerance": _decimal_text(evidence.policy.volume_tolerance),
            "amount_tolerance": _decimal_text(evidence.policy.amount_tolerance),
            **(
                {"source_precision_policy": evidence.policy.source_precision_policy}
                if evidence.policy.source_precision_policy is not None
                else {}
            ),
        },
        "primary": {
            "provider": evidence.report.primary_provider,
            "upstream_group": evidence.primary_upstream_group,
            "adapter_version": evidence.primary_adapter_version,
            "revision_id": evidence.report.primary_revision_id,
            "materialization_id": _content_id(
                evidence.primary_materialization_id,
                field="primary_materialization_id",
            ),
            "quality_id": _content_id(
                evidence.primary_quality_id, field="primary_quality_id"
            ),
            "instrument_count": evidence.report.primary_instrument_count,
        },
        "comparison": {
            "provider": evidence.report.comparison_provider,
            "upstream_group": evidence.comparison_upstream_group,
            "adapter_version": evidence.comparison_adapter_version,
            "revision_id": evidence.report.comparison_revision_id,
            "materialization_id": _content_id(
                evidence.comparison_materialization_id,
                field="comparison_materialization_id",
            ),
            "quality_id": _content_id(
                evidence.comparison_quality_id, field="comparison_quality_id"
            ),
            "instrument_count": evidence.report.comparison_instrument_count,
        },
        "matched_instrument_count": evidence.report.matched_instrument_count,
        "differences": [
            _difference_payload(item) for item in evidence.report.differences
        ],
    }
    if evidence.component_relation is not None:
        relation = evidence.component_relation
        payload["component_relation"] = (
            _tencent_component_payload(relation)
            if type(relation) is BseTencentReportedRelation
            else {
                "kind": _component_kind(relation),
                "block_page_capture_ids": list(relation.block_page_capture_ids),
                "mapping_capture_id": relation.mapping_capture_id,
            }
        )
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _from_payload(ref: ObjectRef, value: object) -> MarketVerificationEvidence:
    payload = _object(value, field="root")
    component = payload.get("schema_version") == BSE_AUCTION_VERIFICATION_SCHEMA
    _exact_keys(
        payload,
        {
            "schema_version",
            "policy_id",
            "checked_at",
            "status",
            "policy",
            "primary",
            "comparison",
            "matched_instrument_count",
            "differences",
        }
        | ({"component_relation"} if component else set()),
        field="root",
    )
    if payload["schema_version"] not in (
        MARKET_VERIFICATION_EVIDENCE_SCHEMA_VERSION,
        BSE_AUCTION_VERIFICATION_SCHEMA,
    ):
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_evidence_schema_unsupported"
        )
    if payload["policy_id"] != (
        _component_kind(_component_from_payload(payload["component_relation"]))
        if component
        else MARKET_VERIFICATION_POLICY_ID
    ):
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_policy_unsupported"
        )
    primary = _side(payload["primary"], field="primary")
    comparison = _side(payload["comparison"], field="comparison")
    if primary["upstream_group"] == comparison["upstream_group"]:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_upstream_groups_not_independent"
        )
    policy_raw = _object(payload["policy"], field="policy")
    _exact_keys(
        policy_raw,
        {"price_tolerance", "volume_tolerance", "amount_tolerance"}
        | (
            {"source_precision_policy"}
            if "source_precision_policy" in policy_raw
            else set()
        ),
        field="policy",
    )
    policy = DailyBarReconciliationPolicy(
        price_tolerance=_decimal(
            policy_raw["price_tolerance"], field="price_tolerance"
        ),
        volume_tolerance=_decimal(
            policy_raw["volume_tolerance"], field="volume_tolerance"
        ),
        amount_tolerance=_decimal(
            policy_raw["amount_tolerance"], field="amount_tolerance"
        ),
        source_precision_policy=policy_raw.get("source_precision_policy"),
    )
    differences = payload["differences"]
    if not isinstance(differences, list):
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_differences_invalid"
        )
    report = MarketReconciliationReport(
        primary_revision_id=primary["revision_id"],
        comparison_revision_id=comparison["revision_id"],
        primary_provider=primary["provider"],
        comparison_provider=comparison["provider"],
        matched_instrument_count=_non_negative_int(
            payload["matched_instrument_count"], field="matched_instrument_count"
        ),
        primary_instrument_count=primary["instrument_count"],
        comparison_instrument_count=comparison["instrument_count"],
        differences=tuple(_difference_from_payload(item) for item in differences),
    )
    evidence = MarketVerificationEvidence(
        ref=ref,
        report=report,
        primary_materialization_id=primary["materialization_id"],
        comparison_materialization_id=comparison["materialization_id"],
        primary_quality_id=primary["quality_id"],
        comparison_quality_id=comparison["quality_id"],
        primary_upstream_group=primary["upstream_group"],
        comparison_upstream_group=comparison["upstream_group"],
        primary_adapter_version=primary["adapter_version"],
        comparison_adapter_version=comparison["adapter_version"],
        policy=policy,
        checked_at=_parse_utc(payload["checked_at"], field="checked_at"),
        component_relation=_component_from_payload(payload["component_relation"])
        if component
        else None,
    )
    if component:
        _validate_component_metadata(evidence)
    expected_status = (
        MarketVerificationStatus.MATCHED
        if report.matched
        else MarketVerificationStatus.CONFLICT
    )
    if (
        MarketVerificationStatus(_text(payload["status"], field="status"))
        is not expected_status
    ):
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_status_mismatch"
        )
    return evidence


def _component_kind(relation) -> str:
    if type(relation) is BseAuctionRelation:
        return BSE_AUCTION_RELATION_KIND
    if type(relation) is BseTencentReportedRelation:
        return BSE_TENCENT_REPORTED_RELATION_KIND
    raise MarketVerificationEvidenceIntegrityError(
        "market_verification_component_kind_invalid"
    )


def _tencent_component_payload(relation: BseTencentReportedRelation) -> dict:
    with exact_bse_arithmetic():
        difference = relation.tencent_amount - relation.official_amount
    return {
        "kind": BSE_TENCENT_REPORTED_RELATION_KIND,
        "block_page_capture_ids": list(relation.block_page_capture_ids),
        "mapping_capture_id": relation.mapping_capture_id,
        "amount_comparison": BSE_TENCENT_AMOUNT_COMPARISON,
        "amount_representation_grid_CNY": "100",
        "official_amount_CNY": _decimal_text(relation.official_amount),
        "tencent_amount_CNY": _decimal_text(relation.tencent_amount),
        "tencent_minus_official_amount_CNY": _decimal_text(difference),
        "raw_six_fields_exact": relation.official_amount == relation.tencent_amount,
    }


def _component_from_payload(
    value: object,
) -> BseAuctionRelation | BseTencentReportedRelation:
    payload = _object(value, field="component_relation")
    if payload.get("kind") == BSE_TENCENT_REPORTED_RELATION_KIND:
        if not isinstance(payload.get("block_page_capture_ids"), list):
            raise MarketVerificationEvidenceIntegrityError(
                "market_verification_component_refs_invalid"
            )
        relation = BseTencentReportedRelation(
            tuple(payload["block_page_capture_ids"]),
            payload.get("mapping_capture_id"),
            _decimal(payload.get("official_amount_CNY"), field="official_amount_CNY"),
            _decimal(payload.get("tencent_amount_CNY"), field="tencent_amount_CNY"),
        )
        if (
            payload != _tencent_component_payload(relation)
            or type(payload.get("raw_six_fields_exact")) is not bool
        ):
            raise MarketVerificationEvidenceIntegrityError(
                "market_verification_component_amount_metadata_invalid"
            )
        return relation
    _exact_keys(
        payload,
        {"kind", "block_page_capture_ids", "mapping_capture_id"},
        field="component_relation",
    )
    if payload["kind"] != BSE_AUCTION_RELATION_KIND or not isinstance(
        payload["block_page_capture_ids"], list
    ):
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_component_kind_invalid"
        )
    return BseAuctionRelation(
        tuple(payload["block_page_capture_ids"]), payload["mapping_capture_id"]
    )


def _validate_component_metadata(evidence: MarketVerificationEvidence) -> None:
    if type(evidence.component_relation) is BseTencentReportedRelation:
        if (
            evidence.policy != STRICT_DAILY_RECONCILIATION
            or (
                evidence.report.primary_provider,
                evidence.primary_upstream_group,
                evidence.primary_adapter_version,
            )
            != (
                "bse_official_kline_probe",
                "bse_official",
                "operation.bse.official_kline.public_probe.v1",
            )
            or (evidence.report.comparison_provider, evidence.comparison_upstream_group)
            != ("tencent_native_public_probe", "tencent")
            or evidence.comparison_adapter_version not in TENCENT_BSE_NATIVE_ADAPTERS
            or evidence.report.primary_instrument_count != 1
            or evidence.report.comparison_instrument_count != 1
        ):
            raise MarketVerificationEvidenceIntegrityError(
                "market_verification_component_pair_invalid"
            )
        return
    if (
        not isinstance(evidence.component_relation, BseAuctionRelation)
        or evidence.policy != STRICT_DAILY_RECONCILIATION
        or (
            evidence.report.primary_provider,
            evidence.primary_upstream_group,
            evidence.primary_adapter_version,
        )
        != (
            "sina_native_public_probe",
            "sina",
            "operation.sina.native_bse_history_js_probe.v1",
        )
        or (
            evidence.report.comparison_provider,
            evidence.comparison_upstream_group,
            evidence.comparison_adapter_version,
        )
        != (
            "bse_official_kline_probe",
            "bse_official",
            "operation.bse.official_kline.public_probe.v1",
        )
        or evidence.report.primary_instrument_count != 1
        or evidence.report.comparison_instrument_count != 1
    ):
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_component_pair_invalid"
        )


@bse_native_read_scope(join_existing=True)
def _replay_component_evidence(store, evidence):
    from data.market.reconciliation import reconcile_daily_bar_revisions_with_bars
    from data.market.revision import (
        MarketRevisionRef,
        read_market_revision,
        read_market_revision_materialization,
    )

    replayed, primary_bars, comparison_bars = reconcile_daily_bar_revisions_with_bars(
        store,
        primary_revision=read_market_revision(
            store,
            MarketRevisionRef(store.resolve_ref(evidence.report.primary_revision_id)),
        ),
        primary_materialization=read_market_revision_materialization(
            store, store.resolve_ref(evidence.primary_materialization_id)
        ),
        comparison_revision=read_market_revision(
            store,
            MarketRevisionRef(
                store.resolve_ref(evidence.report.comparison_revision_id)
            ),
        ),
        comparison_materialization=read_market_revision_materialization(
            store, store.resolve_ref(evidence.comparison_materialization_id)
        ),
        policy=evidence.policy,
        component_relation=evidence.component_relation,
        component_checked_at=evidence.checked_at,
    )
    if replayed != evidence.report:
        raise MarketVerificationEvidenceIntegrityError(
            "market_verification_component_report_mismatch"
        )
    return primary_bars, comparison_bars


def _side(value: object, *, field: str) -> dict[str, object]:
    payload = _object(value, field=field)
    _exact_keys(
        payload,
        {
            "provider",
            "upstream_group",
            "adapter_version",
            "revision_id",
            "materialization_id",
            "quality_id",
            "instrument_count",
        },
        field=field,
    )
    return {
        "provider": _text(payload["provider"], field=f"{field}_provider"),
        "upstream_group": _text(
            payload["upstream_group"], field=f"{field}_upstream_group"
        ),
        "adapter_version": _text(
            payload["adapter_version"], field=f"{field}_adapter_version"
        ),
        "revision_id": _content_id(
            payload["revision_id"], field=f"{field}_revision_id"
        ),
        "materialization_id": _content_id(
            payload["materialization_id"], field=f"{field}_materialization_id"
        ),
        "quality_id": _content_id(payload["quality_id"], field=f"{field}_quality_id"),
        "instrument_count": _non_negative_int(
            payload["instrument_count"], field=f"{field}_instrument_count"
        ),
    }


def _difference_payload(item: MarketReconciliationDifference) -> dict[str, object]:
    return {
        "kind": item.kind.value,
        "instrument": {
            "symbol": item.instrument.symbol,
            "instrument_type": item.instrument.instrument_type.value,
        },
        "field": item.field,
        "primary_value": item.primary_value,
        "comparison_value": item.comparison_value,
        "absolute_difference": (
            None
            if item.absolute_difference is None
            else _decimal_text(item.absolute_difference)
        ),
    }


def _difference_from_payload(value: object) -> MarketReconciliationDifference:
    payload = _object(value, field="difference")
    _exact_keys(
        payload,
        {
            "kind",
            "instrument",
            "field",
            "primary_value",
            "comparison_value",
            "absolute_difference",
        },
        field="difference",
    )
    instrument = _object(payload["instrument"], field="instrument")
    _exact_keys(instrument, {"symbol", "instrument_type"}, field="instrument")
    absolute = payload["absolute_difference"]
    return MarketReconciliationDifference(
        kind=ReconciliationDifferenceKind(
            _text(payload["kind"], field="difference_kind")
        ),
        instrument=InstrumentKey(
            _text(instrument["symbol"], field="instrument_symbol"),
            InstrumentType(
                _text(instrument["instrument_type"], field="instrument_type")
            ),
        ),
        field=_optional_text(payload["field"]),
        primary_value=_optional_text(payload["primary_value"]),
        comparison_value=_optional_text(payload["comparison_value"]),
        absolute_difference=(
            None
            if absolute is None
            else _decimal(absolute, field="absolute_difference")
        ),
    )


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("market_verification_decimal_invalid")
    return format(value, "f")


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(_text(value, field=field))
    except InvalidOperation as exc:
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_invalid"
        ) from exc
    if not result.is_finite() or result < 0:
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_invalid"
        )
    return result


def _format_utc(value: datetime) -> str:
    return _utc_instant(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object, *, field: str) -> datetime:
    text = _text(value, field=field)
    if not text.endswith("Z"):
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_invalid"
        )
    try:
        result = datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_invalid"
        ) from exc
    if _format_utc(result) != text:
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_not_canonical"
        )
    return result


def _utc_instant(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("market_verification_checked_at_must_be_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market_verification_checked_at_must_be_timezone_aware")
    return value.astimezone(timezone.utc)


def _content_id(value: object, *, field: str) -> str:
    text = _text(value, field=field)
    if _CONTENT_ID.fullmatch(text) is None:
        raise ValueError(f"market_verification_{field}_invalid")
    return text


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"market_verification_{field}_must_be_text")
    text = value.strip()
    if not text:
        raise ValueError(f"market_verification_{field}_missing")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _text(value, field="optional_text")


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"market_verification_{field}_invalid")
    return value


def _object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_must_be_object"
        )
    return value


def _exact_keys(value: dict[str, object], expected: set[str], *, field: str) -> None:
    if set(value) != expected:
        raise MarketVerificationEvidenceIntegrityError(
            f"market_verification_{field}_fields_invalid"
        )
