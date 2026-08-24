"""Account-truth reviews HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from account_truth.broker_evidence import BrokerEvidenceReadRejected
from account_truth.citic_source_canonical_resolution import (
    CiticSourceCanonicalResolutionReadRejected,
    CiticSourceCanonicalResolutionRejected,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRejected,
)
from account_truth.manual_review import ManualReviewReadRejected
from server.contracts.http.account_truth import (
    CiticSourceCanonicalResolutionCreate,
    CiticSourceCanonicalResolutionRevoke,
    EvidenceScopeReviewCreate,
    EvidenceScopeReviewRevoke,
    ReviewedFeeSchedulePreviewCreate,
    ReviewedFeeScheduleReviewCreate,
    ReviewedFeeScheduleReviewRevoke,
)
from server.services.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
)


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _account_truth_read_http_exception = dependency(
        "_account_truth_read_http_exception"
    )
    _citic_canonical_resolution_http_exception = dependency(
        "_citic_canonical_resolution_http_exception"
    )
    _citic_canonical_resolution_read_http_exception = dependency(
        "_citic_canonical_resolution_read_http_exception"
    )
    _evidence_scope_review_http_exception = dependency(
        "_evidence_scope_review_http_exception"
    )
    _reviewed_fee_schedule_http_exception = dependency(
        "_reviewed_fee_schedule_http_exception"
    )
    _reviewed_fee_schedule_read_http_exception = dependency(
        "_reviewed_fee_schedule_read_http_exception"
    )
    _reviewed_fee_schedule_repository_for_state = dependency(
        "_reviewed_fee_schedule_repository_for_state"
    )
    build_reviewed_fee_schedule_preview = dependency(
        "build_reviewed_fee_schedule_preview"
    )
    build_reviewed_fee_schedule_review_status = dependency(
        "build_reviewed_fee_schedule_review_status"
    )
    record_account_truth_evidence_scope_review = dependency(
        "record_account_truth_evidence_scope_review"
    )
    record_citic_source_canonical_resolution = dependency(
        "record_citic_source_canonical_resolution"
    )
    revoke_account_truth_evidence_scope_review = dependency(
        "revoke_account_truth_evidence_scope_review"
    )
    revoke_citic_source_canonical_resolution = dependency(
        "revoke_citic_source_canonical_resolution"
    )

    @r.post("/fee-schedule/preview")
    async def preview_reviewed_fee_schedule(
        body: ReviewedFeeSchedulePreviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return build_reviewed_fee_schedule_preview(
                get_app_state(), **body.model_dump()
            )
        except ReviewedFeeScheduleRejected as exc:
            raise _reviewed_fee_schedule_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.get("/fee-schedule/review")
    async def get_reviewed_fee_schedule_review() -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return build_reviewed_fee_schedule_review_status(get_app_state())
        except ReviewedFeeScheduleReadRejected as exc:
            raise _reviewed_fee_schedule_read_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/fee-schedule/reviews")
    async def record_reviewed_fee_schedule_review(
        body: ReviewedFeeScheduleReviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        try:
            preview = build_reviewed_fee_schedule_preview(
                state,
                effective_start_date=body.effective_start_date,
                effective_end_date=body.effective_end_date,
                reviewed_asset_classes=body.reviewed_asset_classes,
            )
            review = _reviewed_fee_schedule_repository_for_state(state).record_review(
                preview=preview,
                expected_preview_fingerprint=body.expected_preview_fingerprint,
                reviewer=body.reviewer,
                confirmation=body.confirmation,
            )
        except ReviewedFeeScheduleRejected as exc:
            raise _reviewed_fee_schedule_http_exception(exc) from exc
        except ReviewedFeeScheduleReadRejected as exc:
            raise _reviewed_fee_schedule_read_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc
        return {
            "status": "accepted",
            "review": review.to_json_dict(),
            "approval_confirmation": REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }

    @r.post("/fee-schedule/reviews/revoke")
    async def revoke_reviewed_fee_schedule_review(
        body: ReviewedFeeScheduleReviewRevoke,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            review = _reviewed_fee_schedule_repository_for_state(
                get_app_state()
            ).revoke_latest(**body.model_dump())
        except ReviewedFeeScheduleRejected as exc:
            raise _reviewed_fee_schedule_http_exception(exc) from exc
        except ReviewedFeeScheduleReadRejected as exc:
            raise _reviewed_fee_schedule_read_http_exception(exc) from exc
        return {
            "status": "revoked",
            "review": review.to_json_dict(),
            "revocation_confirmation": REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
            "authorizes_execution": False,
            "changes_capital_authority": False,
        }

    @r.post("/evidence-scope/reviews")
    async def record_evidence_scope_review(
        body: EvidenceScopeReviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return record_account_truth_evidence_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except EvidenceScopeReviewRejected as exc:
            raise _evidence_scope_review_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/evidence-scope/reviews/revoke")
    async def revoke_evidence_scope_review(
        body: EvidenceScopeReviewRevoke,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return revoke_account_truth_evidence_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except EvidenceScopeReviewRejected as exc:
            raise _evidence_scope_review_http_exception(exc) from exc
        except (
            BrokerEvidenceReadRejected,
            ManualReviewReadRejected,
            EvidenceScopeReviewReadRejected,
        ) as exc:
            raise _account_truth_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/canonical-resolutions")
    async def record_citic_canonical_resolution(
        body: CiticSourceCanonicalResolutionCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return record_citic_source_canonical_resolution(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceCanonicalResolutionRejected as exc:
            raise _citic_canonical_resolution_http_exception(exc) from exc
        except CiticSourceCanonicalResolutionReadRejected as exc:
            raise _citic_canonical_resolution_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/canonical-resolutions/revoke")
    async def revoke_citic_canonical_resolution(
        body: CiticSourceCanonicalResolutionRevoke,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return revoke_citic_source_canonical_resolution(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceCanonicalResolutionRejected as exc:
            raise _citic_canonical_resolution_http_exception(exc) from exc
        except CiticSourceCanonicalResolutionReadRejected as exc:
            raise _citic_canonical_resolution_read_http_exception(exc) from exc

    return r
