"""Provider error normalization for market refresh workflows."""

from __future__ import annotations

TUSHARE_FUND_NAV_PERMISSION_DENIED = "tushare_fund_nav_permission_denied"


def provider_error_code(exc: Exception) -> str | None:
    message = str(exc)
    normalized = message.lower()
    if "fund_nav" in normalized and (
        "访问权限" in message
        or "没有接口" in message
        or "permission" in normalized
        or "access" in normalized
    ):
        return TUSHARE_FUND_NAV_PERMISSION_DENIED
    return None


def provider_error_reason(error_code: str, *, using_cache: bool) -> str:
    if error_code == TUSHARE_FUND_NAV_PERMISSION_DENIED:
        return (
            "TuShare fund_nav 权限不足，继续使用本地基金缓存"
            if using_cache
            else "TuShare fund_nav 权限不足，请使用免费盘中基金估值或提升 TuShare 权限"
        )
    return (
        "行情源刷新失败，继续使用本地缓存"
        if using_cache
        else "行情源刷新失败，暂无真实行情数据"
    )
