"""Asset configuration, fund confirmation, and allocation projections."""

from __future__ import annotations

import json
from collections import defaultdict

from server.models import AllocationGroup, AllocationItem

_ASSET_CLASS_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


def normalize_asset_class(value: str | None) -> str:
    if not value:
        return "other"
    normalized = str(value).strip().lower()
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash"}:
        return normalized
    return "other"


def build_grouped_allocation(
    allocation: list[AllocationItem], total_equity: float
) -> list[AllocationGroup]:
    """按 asset_class 聚合 allocation 列表。"""
    groups: dict[str, list[AllocationItem]] = defaultdict(list)
    for item in allocation:
        groups[item.asset_class].append(item)

    result = []
    for ac, items in groups.items():
        group_value = sum(i.value for i in items)
        result.append(
            AllocationGroup(
                asset_class=ac,
                name=_ASSET_CLASS_LABELS.get(ac, ac),
                value=group_value,
                weight=group_value / total_equity if total_equity > 0 else 0,
                items=items,
            )
        )
    # 现金排第一，其余按市值降序
    result.sort(key=lambda g: (g.asset_class != "cash", -g.value))
    return result


def parse_fee_breakdown(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
