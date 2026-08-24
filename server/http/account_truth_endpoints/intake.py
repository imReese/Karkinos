"""Account-truth intake HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from account_truth.citic_history_xls_directory import CiticHistoryXlsDirectoryRejected
from account_truth.citic_source_query_window_review import (
    CiticSourceQueryWindowReviewReadRejected,
    CiticSourceQueryWindowReviewRejected,
)
from account_truth.citic_source_scope_review import (
    CiticSourceScopeReviewReadRejected,
    CiticSourceScopeReviewRejected,
)
from server.contracts.http.account_truth import (
    BrokerStatementPreviewCreate,
    CiticHistoryXlsDirectoryIntakeCreate,
    CiticHistoryXlsDirectoryQueryWindowReviewCreate,
    CiticHistoryXlsIntakeCreate,
    CiticHistoryXlsPreviewCreate,
    CiticHistoryXlsQueryWindowReviewCreate,
    CiticHistoryXlsQueryWindowReviewRevoke,
    CiticHistoryXlsSourceScopeReviewCreate,
    CiticHistoryXlsSourceScopeReviewRevoke,
)


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/account-truth", tags=["account-truth"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _citic_history_xls_directory_config_for_state = dependency(
        "_citic_history_xls_directory_config_for_state"
    )
    _citic_history_xls_directory_scan_response = dependency(
        "_citic_history_xls_directory_scan_response"
    )
    _citic_history_xls_directory_status_response = dependency(
        "_citic_history_xls_directory_status_response"
    )
    _citic_history_xls_preview_response = dependency(
        "_citic_history_xls_preview_response"
    )
    _citic_query_window_review_http_exception = dependency(
        "_citic_query_window_review_http_exception"
    )
    _citic_query_window_review_read_http_exception = dependency(
        "_citic_query_window_review_read_http_exception"
    )
    _citic_source_intake_response = dependency("_citic_source_intake_response")
    _citic_source_reviews_for_state = dependency("_citic_source_reviews_for_state")
    _citic_source_scope_review_http_exception = dependency(
        "_citic_source_scope_review_http_exception"
    )
    _citic_source_scope_review_read_http_exception = dependency(
        "_citic_source_scope_review_read_http_exception"
    )
    _parse_citic_history_xls_transport = dependency(
        "_parse_citic_history_xls_transport"
    )
    _preview_response = dependency("_preview_response")
    _record_citic_source_intake = dependency("_record_citic_source_intake")
    build_citic_history_canonical_lineage_assessment = dependency(
        "build_citic_history_canonical_lineage_assessment"
    )
    find_citic_history_xls_directory_preview = dependency(
        "find_citic_history_xls_directory_preview"
    )
    parse_broker_statement_csv = dependency("parse_broker_statement_csv")
    parse_citic_history_xls = dependency("parse_citic_history_xls")
    record_citic_source_query_window_review = dependency(
        "record_citic_source_query_window_review"
    )
    record_citic_source_scope_review = dependency("record_citic_source_scope_review")
    revoke_citic_source_query_window_review = dependency(
        "revoke_citic_source_query_window_review"
    )
    revoke_citic_source_scope_review = dependency("revoke_citic_source_scope_review")
    scan_citic_history_xls_directory = dependency("scan_citic_history_xls_directory")

    @r.post("/broker-statement/preview")
    async def preview_broker_statement(
        body: BrokerStatementPreviewCreate,
    ) -> dict[str, object]:
        preview = parse_broker_statement_csv(body.content)
        return _preview_response(preview, source_name=body.source_name)

    @r.post("/citic-history-xls/preview")
    async def preview_citic_history_xls(
        body: CiticHistoryXlsPreviewCreate,
    ) -> dict[str, object]:
        return _citic_history_xls_preview_response(
            _parse_citic_history_xls_transport(
                body.content_base64,
                parser=parse_citic_history_xls,
            )
        )

    @r.post("/citic-history-xls/intakes")
    async def record_citic_history_xls_intake(
        body: CiticHistoryXlsIntakeCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        preview = _parse_citic_history_xls_transport(
            body.content_base64,
            parser=parse_citic_history_xls,
        )
        return _record_citic_source_intake(
            state=get_app_state(),
            preview=preview,
            expected_file_fingerprint=body.expected_file_fingerprint,
            review_status=body.review_status,
        )

    @r.get("/citic-history-xls/directory")
    async def get_citic_history_xls_directory_status() -> dict[str, object]:
        from server.dependencies import get_app_state

        config = _citic_history_xls_directory_config_for_state(get_app_state())
        return _citic_history_xls_directory_status_response(config)

    @r.post("/citic-history-xls/directory/scan")
    async def scan_configured_citic_history_xls_directory() -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        config = _citic_history_xls_directory_config_for_state(state)
        scan = scan_citic_history_xls_directory(
            path=config.path,
            enabled=config.enabled,
            max_files=config.max_files,
            max_file_bytes=config.max_file_bytes,
            max_total_bytes=config.max_total_bytes,
        )
        intakes, reviews, scope_reviews = _citic_source_reviews_for_state(
            state,
            limit=config.max_files,
        )
        canonical_lineage_assessment = build_citic_history_canonical_lineage_assessment(
            state,
            scan=scan,
        )
        return _citic_history_xls_directory_scan_response(
            scan,
            config=config,
            intakes=intakes,
            query_window_reviews=reviews,
            source_scope_reviews=scope_reviews,
            canonical_lineage_assessment=canonical_lineage_assessment,
        )

    @r.post("/citic-history-xls/directory/intakes")
    async def record_configured_citic_history_xls_directory_intake(
        body: CiticHistoryXlsDirectoryIntakeCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        config = _citic_history_xls_directory_config_for_state(state)
        try:
            preview = find_citic_history_xls_directory_preview(
                expected_file_fingerprint=body.expected_file_fingerprint,
                path=config.path,
                enabled=config.enabled,
                max_files=config.max_files,
                max_file_bytes=config.max_file_bytes,
                max_total_bytes=config.max_total_bytes,
            )
        except CiticHistoryXlsDirectoryRejected as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": "Configured CITIC source could not be re-verified.",
                },
            ) from exc
        return _record_citic_source_intake(
            state=state,
            preview=preview,
            expected_file_fingerprint=body.expected_file_fingerprint,
            review_status=body.review_status,
        )

    @r.post("/citic-history-xls/query-window-reviews")
    async def record_citic_history_xls_query_window_review(
        body: CiticHistoryXlsQueryWindowReviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        preview = _parse_citic_history_xls_transport(
            body.content_base64,
            parser=parse_citic_history_xls,
        )
        try:
            return record_citic_source_query_window_review(
                get_app_state(),
                preview=preview,
                **body.model_dump(exclude={"content_base64"}),
            )
        except CiticSourceQueryWindowReviewRejected as exc:
            raise _citic_query_window_review_http_exception(exc) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise _citic_query_window_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/directory/query-window-reviews")
    async def record_configured_citic_history_xls_query_window_review(
        body: CiticHistoryXlsDirectoryQueryWindowReviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        state = get_app_state()
        config = _citic_history_xls_directory_config_for_state(state)
        try:
            preview = find_citic_history_xls_directory_preview(
                expected_file_fingerprint=body.expected_file_fingerprint,
                path=config.path,
                enabled=config.enabled,
                max_files=config.max_files,
                max_file_bytes=config.max_file_bytes,
                max_total_bytes=config.max_total_bytes,
            )
            return record_citic_source_query_window_review(
                state,
                preview=preview,
                **body.model_dump(),
            )
        except CiticHistoryXlsDirectoryRejected as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": "Configured CITIC source could not be re-verified.",
                },
            ) from exc
        except CiticSourceQueryWindowReviewRejected as exc:
            raise _citic_query_window_review_http_exception(exc) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise _citic_query_window_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/query-window-reviews/revoke")
    async def revoke_citic_history_xls_query_window_review(
        body: CiticHistoryXlsQueryWindowReviewRevoke,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return revoke_citic_source_query_window_review(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceQueryWindowReviewRejected as exc:
            raise _citic_query_window_review_http_exception(exc) from exc
        except CiticSourceQueryWindowReviewReadRejected as exc:
            raise _citic_query_window_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/source-scope-reviews")
    async def record_citic_history_xls_source_scope_review(
        body: CiticHistoryXlsSourceScopeReviewCreate,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return record_citic_source_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceScopeReviewRejected as exc:
            raise _citic_source_scope_review_http_exception(exc) from exc
        except CiticSourceScopeReviewReadRejected as exc:
            raise _citic_source_scope_review_read_http_exception(exc) from exc

    @r.post("/citic-history-xls/source-scope-reviews/revoke")
    async def revoke_citic_history_xls_source_scope_review(
        body: CiticHistoryXlsSourceScopeReviewRevoke,
    ) -> dict[str, object]:
        from server.dependencies import get_app_state

        try:
            return revoke_citic_source_scope_review(
                get_app_state(),
                **body.model_dump(),
            )
        except CiticSourceScopeReviewRejected as exc:
            raise _citic_source_scope_review_http_exception(exc) from exc
        except CiticSourceScopeReviewReadRejected as exc:
            raise _citic_source_scope_review_read_http_exception(exc) from exc

    @r.get("/citic-history-xls/intakes")
    async def list_citic_history_xls_intakes(
        limit: int = 50,
    ) -> list[dict[str, object]]:
        from server.dependencies import get_app_state

        intakes, reviews, scope_reviews = _citic_source_reviews_for_state(
            get_app_state(),
            limit=limit,
        )
        return [
            _citic_source_intake_response(
                intake,
                query_window_review=reviews.get(intake.intake_id),
                source_scope_review=scope_reviews.get(intake.intake_id),
            )
            for intake in intakes
        ]

    return r
