"""Canonical account_truth repositories projections."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from account_truth.broker_evidence import (
    BrokerEvidenceReadRejected,
    BrokerEvidenceRepository,
)
from account_truth.citic_source_canonical_resolution import (
    CiticSourceCanonicalResolutionReadRejected,
    CiticSourceCanonicalResolutionRejected,
)
from account_truth.citic_source_intake import (
    CiticSourceIntakeRepository,
)
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRejected,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReviewReadRejected,
    CiticSourceScopeReviewRejected,
)
from account_truth.evidence_scope_review import (
    EvidenceScopeReviewReadRejected,
    EvidenceScopeReviewRejected,
)
from account_truth.manual_review import (
    ManualReviewReadRejected,
    ManualReviewRepository,
)
from server.services.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
    ReviewedFeeScheduleReviewRepository,
)


def repository_for_state(state) -> BrokerEvidenceRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return BrokerEvidenceRepository(Path(db_path))


def reviewed_fee_schedule_repository_for_state(
    state,
) -> ReviewedFeeScheduleReviewRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return ReviewedFeeScheduleReviewRepository(Path(db_path))


def reviewed_fee_schedule_http_exception(
    exc: ReviewedFeeScheduleRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "Reviewed fee schedule remains in no-action state.",
        },
    )


def reviewed_fee_schedule_read_http_exception(
    exc: ReviewedFeeScheduleReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted reviewed fee schedule is unavailable.",
        },
    )


def account_truth_read_http_exception(
    exc: (
        BrokerEvidenceReadRejected
        | ManualReviewReadRejected
        | EvidenceScopeReviewReadRejected
    ),
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted Account Truth evidence is unavailable.",
        },
    )


def evidence_scope_review_http_exception(
    exc: EvidenceScopeReviewRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "Account Truth evidence scope could not be recorded safely.",
        },
    )


def citic_canonical_resolution_http_exception(
    exc: CiticSourceCanonicalResolutionRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "CITIC source canonical coverage could not be recorded safely.",
        },
    )


def citic_canonical_resolution_read_http_exception(
    exc: CiticSourceCanonicalResolutionReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted CITIC source canonical coverage is unavailable.",
        },
    )


def citic_query_window_review_http_exception(
    exc: CiticSourceQueryWindowReviewRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "CITIC source query-window review could not be recorded safely.",
        },
    )


def citic_query_window_review_read_http_exception(
    exc: CiticSourceQueryWindowReviewReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted CITIC source query-window reviews are unavailable.",
        },
    )


def citic_source_scope_review_http_exception(
    exc: CiticSourceScopeReviewRejected,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": "CITIC source-scope review could not be recorded safely.",
        },
    )


def citic_source_scope_review_read_http_exception(
    exc: CiticSourceScopeReviewReadRejected,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": "Persisted CITIC source-scope reviews are unavailable.",
        },
    )


def manual_review_repository_for_state(state) -> ManualReviewRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return ManualReviewRepository(Path(db_path))


def citic_intake_repository_for_state(state) -> CiticSourceIntakeRepository:
    db_path = getattr(getattr(state, "db", None), "_path", None)
    if db_path is None:
        raise HTTPException(
            status_code=503, detail="Account Truth database unavailable"
        )
    return CiticSourceIntakeRepository(Path(db_path))


__all__ = (
    "account_truth_read_http_exception",
    "citic_canonical_resolution_http_exception",
    "citic_canonical_resolution_read_http_exception",
    "citic_intake_repository_for_state",
    "citic_query_window_review_http_exception",
    "citic_query_window_review_read_http_exception",
    "citic_source_scope_review_http_exception",
    "citic_source_scope_review_read_http_exception",
    "evidence_scope_review_http_exception",
    "manual_review_repository_for_state",
    "repository_for_state",
    "reviewed_fee_schedule_http_exception",
    "reviewed_fee_schedule_read_http_exception",
    "reviewed_fee_schedule_repository_for_state",
)
