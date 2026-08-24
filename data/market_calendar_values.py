"""Normalization helpers for market-calendar providers and evidence."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any


def _html_fragment_text(fragment: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", fragment)
    return " ".join(html.unescape(without_tags).replace("\xa0", " ").split())


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _parse_calendar_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def _normalize_holiday_labels(
    labels: Mapping[str, Any],
    *,
    label_factory: Callable[..., Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for value, label in labels.items():
        date_text = _parse_calendar_date(value).isoformat()
        normalized[date_text] = label_factory(
            date=date_text,
            label=str(label.label).strip(),
            source=str(label.source).strip(),
            confidence=str(label.confidence).strip(),
            source_url=label.source_url,
        )
    return {
        date_text: label
        for date_text, label in normalized.items()
        if label.label and label.source and label.confidence
    }


def _holiday_label_limitations(labels: Mapping[str, Any]) -> tuple[str, ...]:
    if not labels:
        return ()
    sources = sorted({label.source for label in labels.values() if label.source})
    urls = sorted({label.source_url for label in labels.values() if label.source_url})
    limitations = [
        *(f"Holiday labels source: {source}" for source in sources),
        *urls,
    ]
    return tuple(limitations)


def _derive_china_market_holiday_label(day: date) -> str | None:
    if day.month == 1 and day.day <= 3:
        return "元旦休市"
    if day.month == 2:
        return "春节休市"
    if day.month == 4 and day.day <= 7:
        return "清明节休市"
    if day.month == 5 and day.day <= 7:
        return "劳动节休市"
    if (day.month == 5 and day.day >= 20) or (day.month == 6 and day.day <= 25):
        return "端午节休市"
    if day.month == 9 and day.day >= 15:
        return "中秋节休市"
    if day.month == 10 and day.day <= 7:
        return "国庆节休市"
    return None


def _normalize_provider_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return date.fromisoformat(text[:10]).isoformat()
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) >= 8:
        return date(
            int(digits[:4]),
            int(digits[4:6]),
            int(digits[6:8]),
        ).isoformat()
    return None


def _provider_is_open(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return int(value) == 1
    return str(value).strip() in {"1", "true", "True", "open", "OPEN"}


def _dataframe_records(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        records = value.to_dict("records")
        return [dict(record) for record in records]
    if isinstance(value, list):
        return [dict(record) for record in value]
    return []


def _fingerprint_calendar_snapshot(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


html_fragment_text = _html_fragment_text
is_leap_year = _is_leap_year
parse_calendar_date = _parse_calendar_date
normalize_holiday_labels = _normalize_holiday_labels
holiday_label_limitations = _holiday_label_limitations
derive_china_market_holiday_label = _derive_china_market_holiday_label
normalize_provider_date = _normalize_provider_date
provider_is_open = _provider_is_open
dataframe_records = _dataframe_records
fingerprint_calendar_snapshot = _fingerprint_calendar_snapshot
