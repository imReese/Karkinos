from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from zoneinfo import ZoneInfo

from data.market_calendar import (
    OfficialMarketHolidayNotice,
    build_static_market_calendar_snapshot,
)
from server.db import AppDatabase
from server.services.market_calendar_automation import (
    MarketCalendarAutomationService,
    market_calendar_automation_years,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_HOLIDAY_DATES = {
    "2026-01-01": "元旦休市",
    "2026-01-02": "元旦休市",
    "2026-02-16": "春节休市",
    "2026-02-17": "春节休市",
    "2026-02-18": "春节休市",
    "2026-02-19": "春节休市",
    "2026-02-20": "春节休市",
    "2026-02-23": "春节休市",
    "2026-04-06": "清明节休市",
    "2026-05-01": "劳动节休市",
    "2026-05-04": "劳动节休市",
    "2026-05-05": "劳动节休市",
    "2026-06-19": "端午节休市",
    "2026-09-25": "中秋节休市",
    "2026-10-01": "国庆节休市",
    "2026-10-02": "国庆节休市",
    "2026-10-05": "国庆节休市",
    "2026-10-06": "国庆节休市",
    "2026-10-07": "国庆节休市",
}


def _snapshot(*, extra_open_dates: set[str] | None = None):
    current = date(2026, 1, 1)
    open_dates: set[str] = set()
    while current.year == 2026:
        if current.weekday() < 5 and current.isoformat() not in _HOLIDAY_DATES:
            open_dates.add(current.isoformat())
        current += timedelta(days=1)
    open_dates.update(extra_open_dates or set())
    return build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="unit_fixture",
        open_dates=open_dates,
        fetched_at="2026-07-27T12:00:00+08:00",
    )


def _notice() -> OfficialMarketHolidayNotice:
    return OfficialMarketHolidayNotice(
        exchange="SSE",
        year=2026,
        source_url="https://example.test/sse-closure",
        source_fingerprint="a" * 64,
        fetched_at="2026-07-27T12:00:00+08:00",
        notice_title="2026年休市安排",
        day_labels=MappingProxyType(_HOLIDAY_DATES),
        reopen_dates=(
            "2026-01-05",
            "2026-02-24",
            "2026-04-07",
            "2026-05-06",
            "2026-06-22",
            "2026-09-28",
            "2026-10-08",
        ),
    )


class _Provider:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def fetch_snapshot(self, *, exchange: str, year: int):
        self.calls += 1
        assert (exchange, year) == ("SSE", 2026)
        return self.snapshot


class _NoticeProvider:
    def __init__(self, notice: OfficialMarketHolidayNotice) -> None:
        self.notice = notice
        self.calls = 0

    def fetch_notice(self, *, year: int) -> OfficialMarketHolidayNotice:
        self.calls += 1
        assert year == 2026
        return self.notice


def _service(db: AppDatabase, provider: _Provider, notice_provider: _NoticeProvider):
    return MarketCalendarAutomationService(
        db=db,
        config=SimpleNamespace(data_source="akshare", tushare_token=""),
        provider_factory=lambda *args, **kwargs: provider,
        official_notice_provider=notice_provider,
    )


def test_market_calendar_automation_persists_verified_calendar_once_per_day(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    provider = _Provider(_snapshot())
    notice_provider = _NoticeProvider(_notice())
    service = _service(db, provider, notice_provider)
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)

    first = service.run_due(now=now)
    second = service.run_due(now=now)

    assert first[0]["status"] == "completed"
    assert second[0]["run_id"] == first[0]["run_id"]
    assert provider.calls == 1
    assert notice_provider.calls == 1
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    assert row is not None
    assert row["official_verification_status"] == "verified"
    assert row["official_source_url"] == "https://example.test/sse-closure"
    days = {day["date"]: day for day in json.loads(row["days_json"])}
    assert days["2026-05-01"]["reason"] == "劳动节休市"
    payload = json.loads(first[0]["payload_json"])
    assert payload["changes_account_truth"] is False
    assert payload["official_verification_status"] == "verified"


def test_calendar_job_recovers_publication_receipt_after_process_dies_before_finish(
    tmp_path, monkeypatch
):
    import asyncio
    from datetime import timezone

    from server.persistence.jobs import SQLiteJobStore
    from server.workers.data_worker import execute_calendar_job

    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    old = now - timedelta(seconds=61)
    scheduled = "2026-07-27T12:00:00+08:00"
    store = SQLiteJobStore(db.path)
    store.enqueue("market_calendar_sync", {"scheduled_at": scheduled}, now=old)
    first = store.claim("market_calendar_sync", "old-worker", now=old)
    provider = _Provider(_snapshot())
    notice = _NoticeProvider(_notice())
    service = MarketCalendarAutomationService(
        db=db,
        config=SimpleNamespace(data_source="akshare", tushare_token=""),
        provider_factory=lambda *a, **kw: provider,
        official_notice_provider=notice,
        job_lease=first.lease,
    )
    # Publish under the first lease, then omit JobStore.finish to model a crash.
    monkeypatch.setattr(db._market_calendar_publication, "_now", lambda tz=None: old)
    service.run_due(now=datetime.fromisoformat(scheduled))
    second = store.claim("market_calendar_sync", "new-worker", now=now)
    assert second.attempt == 2
    replay = MarketCalendarAutomationService(
        db=db,
        config=SimpleNamespace(data_source="akshare", tushare_token=""),
        provider_factory=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("replay must use receipt")
        ),
        official_notice_provider=notice,
        job_lease=second.lease,
    )
    asyncio.run(execute_calendar_job(store, second, replay))
    result = store.enqueue("market_calendar_sync", {"scheduled_at": scheduled}, now=now)
    assert result.status == "succeeded"
    assert (
        result.result_ref == "automation_runs:market_calendar_sync:SSE:2026:2026-07-27"
    )
    assert provider.calls == notice.calls == 1


def test_market_calendar_automation_fails_closed_on_cross_check_mismatch(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    provider = _Provider(_snapshot(extra_open_dates={"2026-05-02"}))
    service = _service(db, provider, _NoticeProvider(_notice()))

    result = service.run_due(now=datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI))[0]

    assert result["status"] == "needs_review"
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    assert row is not None
    assert row["official_verification_status"] == "needs_review"
    assert row["official_verified_at"] is None
    payload = json.loads(result["payload_json"])
    assert payload["persisted"] is True
    assert any(
        "weekends as trading days" in issue for issue in payload["verification_issues"]
    )


def test_market_calendar_mismatch_does_not_replace_existing_snapshot(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    original = _snapshot()
    db.upsert_market_calendar_snapshot_sync(original)
    provider = _Provider(_snapshot(extra_open_dates={"2026-05-02"}))
    service = _service(db, provider, _NoticeProvider(_notice()))

    result = service.run_due(now=datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI))[0]

    assert result["status"] == "needs_review"
    assert json.loads(result["payload_json"])["persisted"] is False
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    assert row is not None
    assert row["source_fingerprint"] == original.source_fingerprint


def test_market_calendar_automation_failure_is_audited_without_overwriting(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    original = _snapshot()
    db.upsert_market_calendar_snapshot_sync(original)

    class _FailingNoticeProvider:
        def fetch_notice(self, *, year: int):
            raise RuntimeError("official source unavailable")

    service = MarketCalendarAutomationService(
        db=db,
        config=SimpleNamespace(data_source="akshare", tushare_token=""),
        provider_factory=lambda *args, **kwargs: _Provider(_snapshot()),
        official_notice_provider=_FailingNoticeProvider(),
    )

    result = service.run_due(now=datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI))[0]

    assert result["status"] == "failed"
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    assert row is not None
    assert row["source_fingerprint"] == original.source_fingerprint
    assert json.loads(result["payload_json"])["persisted"] is False


def test_market_calendar_automation_starts_next_year_in_december() -> None:
    assert market_calendar_automation_years(
        datetime(2026, 11, 30, 12, tzinfo=_SHANGHAI)
    ) == (2026,)
    assert market_calendar_automation_years(
        datetime(2026, 12, 1, 0, tzinfo=_SHANGHAI)
    ) == (2026, 2027)
