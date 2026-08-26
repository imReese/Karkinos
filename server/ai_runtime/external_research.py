"""Stable public facade for human-started external backtest research."""

from server.contracts.external_research import (
    EXTERNAL_BACKTEST_REPORT_CONFIRMATION,
    EXTERNAL_BACKTEST_REPORT_CONTRACT,
    EXTERNAL_BACKTEST_REPORT_DEFINITION,
    EXTERNAL_BACKTEST_REPORT_PROMPT,
    EXTERNAL_BACKTEST_REPORT_ROLE,
    ExternalBacktestReportRecord,
    ExternalBacktestReportRejected,
    HumanExternalBacktestReportRequest,
)

from .external_research_errors import (
    ExternalResearchAuthenticationError,
    ExternalResearchHttpError,
    ExternalResearchInvalidResponseError,
    ExternalResearchNetworkError,
    ExternalResearchRateLimitedError,
    ExternalResearchTimeoutError,
)
from .external_research_output import decode_external_report
from .external_research_provider import OpenAICompatibleBacktestReportProvider
from .external_research_result import ExternalBacktestReportResult
from .external_research_service import HumanExternalBacktestReportService
from .external_research_store import ExternalBacktestReportAuditStore
from .openai_compatibility import edge_request_options, message_text, safe_usage

# Backward-compatible spellings for existing callers; implementations have one owner.
_decode_external_report = decode_external_report
_edge_request_options = edge_request_options
_message_text = message_text
_safe_usage = safe_usage

__all__ = [
    "EXTERNAL_BACKTEST_REPORT_CONFIRMATION",
    "EXTERNAL_BACKTEST_REPORT_CONTRACT",
    "EXTERNAL_BACKTEST_REPORT_DEFINITION",
    "EXTERNAL_BACKTEST_REPORT_PROMPT",
    "EXTERNAL_BACKTEST_REPORT_ROLE",
    "ExternalBacktestReportAuditStore",
    "ExternalBacktestReportRecord",
    "ExternalBacktestReportRejected",
    "ExternalBacktestReportResult",
    "ExternalResearchAuthenticationError",
    "ExternalResearchHttpError",
    "ExternalResearchInvalidResponseError",
    "ExternalResearchNetworkError",
    "ExternalResearchRateLimitedError",
    "ExternalResearchTimeoutError",
    "HumanExternalBacktestReportRequest",
    "HumanExternalBacktestReportService",
    "OpenAICompatibleBacktestReportProvider",
    "_decode_external_report",
    "_edge_request_options",
    "_message_text",
    "_safe_usage",
    "edge_request_options",
    "message_text",
]
