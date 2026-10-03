from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

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


def _routed_service(db, providers, notice_provider):
    calls = []

    def factory(name, **kwargs):
        calls.append(name)
        return providers[name]

    service = MarketCalendarAutomationService(
        db=db,
        config=SimpleNamespace(data_source="tushare", tushare_token="unit-token"),
        provider_factory=factory,
        official_notice_provider=notice_provider,
    )
    return service, calls


class _UnavailableProvider:
    def __init__(self, error) -> None:
        self.error = error
        self.calls = 0

    def fetch_snapshot(self, **kwargs):
        self.calls += 1
        raise self.error


def test_rate_limited_primary_uses_verified_backup_and_preserves_daily_receipt(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    primary = _UnavailableProvider(RuntimeError("抱歉，您每分钟最多访问该接口2次"))
    backup = _Provider(replace(_snapshot(), provider="akshare"))
    notice = _NoticeProvider(_notice())
    service, calls = _routed_service(
        db, {"tushare": primary, "akshare": backup}, notice
    )
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)

    result = service.run_due(now=now)[0]
    replay = service.sync_year(2026, now=now + timedelta(hours=4))

    assert result["status"] == "completed"
    assert replay == result
    assert calls == ["tushare", "akshare"]
    assert primary.calls == backup.calls == notice.calls == 1
    payload = json.loads(result["payload_json"])
    assert payload["provider"] == "akshare"
    assert payload["source_failures"][0]["kind"] == "rate_limited"
    assert payload["source_failures"][0]["retry_after"] == "2026-07-28T00:00:00+08:00"
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    assert row["provider"] == "akshare"
    assert row["official_verification_status"] == "verified"


def test_backup_is_verified_after_primary_official_mismatch(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    primary = _Provider(_snapshot(extra_open_dates={"2026-05-02"}))
    backup = _Provider(replace(_snapshot(), provider="akshare"))
    notice = _NoticeProvider(_notice())
    service, calls = _routed_service(
        db, {"tushare": primary, "akshare": backup}, notice
    )

    result = service.run_due(now=datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI))[0]

    assert result["status"] == "completed"
    assert calls == ["tushare", "akshare"]
    assert notice.calls == 1
    payload = json.loads(result["payload_json"])
    assert payload["source_failures"][0]["kind"] == "verification_mismatch"
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    assert row["source_fingerprint"] == backup.snapshot.source_fingerprint


def test_empty_or_truncated_backup_cannot_replace_verified_calendar(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    original = _snapshot()
    db.upsert_market_calendar_snapshot_sync(original)
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint=original.source_fingerprint,
        verification_status="verified",
        official_source_url=_notice().source_url,
        official_source_fingerprint=_notice().source_fingerprint,
        verified_by="unit-fixture",
    )
    before = db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026)
    primary = _UnavailableProvider(RuntimeError("too many requests"))
    truncated = build_static_market_calendar_snapshot(
        exchange="SSE", year=2026, provider="akshare", open_dates=["2026-01-05"]
    )
    service, _ = _routed_service(
        db,
        {"tushare": primary, "akshare": _Provider(truncated)},
        _NoticeProvider(_notice()),
    )

    result = service.run_due(now=datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI))[0]

    assert result["status"] == "needs_review"
    assert json.loads(result["payload_json"])["persisted"] is False
    assert db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026) == before


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (RuntimeError("您每天最多访问该接口2次"), "rate_limited"),
        (RuntimeError("抱歉，您没有访问该接口的权限"), "access_denied"),
    ],
)
def test_provider_cooldown_survives_restart_and_explicit_other_year_request(
    tmp_path, error, kind
) -> None:
    path = tmp_path / "calendar.db"
    db = AppDatabase(path)
    db.init_sync()
    primary = _UnavailableProvider(error)
    backup = _UnavailableProvider(error)
    notice = _NoticeProvider(_notice())
    providers = {"tushare": primary, "akshare": backup}
    service, _ = _routed_service(db, providers, notice)
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)

    first = service.run_due(now=now)[0]
    restarted, restarted_calls = _routed_service(AppDatabase(path), providers, notice)
    same_year = restarted.sync_year(2026, now=now + timedelta(hours=2))
    other_year = restarted.sync_year(2025, now=now + timedelta(hours=2))

    assert same_year == first
    assert other_year["status"] == "failed"
    assert restarted_calls == []
    assert primary.calls == backup.calls == notice.calls == 1
    payload = json.loads(other_year["payload_json"])
    assert payload["retryable"] is False
    assert payload["retry_after"] == "2026-07-28T00:00:00+08:00"
    assert {row["kind"] for row in payload["source_failures"]} == {kind}

    next_day = restarted.sync_year(2026, now=now + timedelta(days=1))
    assert next_day["status"] == "failed"
    assert restarted_calls == ["tushare", "akshare"]
    assert primary.calls == backup.calls == notice.calls == 2


def test_transient_failure_retries_after_persistent_backoff_with_daily_bound(
    tmp_path,
) -> None:
    path = tmp_path / "calendar.db"
    db = AppDatabase(path)
    db.init_sync()
    provider = _UnavailableProvider(TimeoutError("network timed out"))
    notice = _NoticeProvider(_notice())
    service = _service(db, provider, notice)
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)

    first = service.run_due(now=now)[0]
    restarted = _service(AppDatabase(path), provider, notice)
    assert restarted.run_due(now=now + timedelta(minutes=59))[0] == first
    second = restarted.run_due(now=now + timedelta(hours=1))[0]
    third = restarted.run_due(now=now + timedelta(hours=2))[0]
    assert restarted.run_due(now=now + timedelta(hours=3))[0] == third

    assert provider.calls == 3
    assert notice.calls == 3
    assert (
        json.loads(first["payload_json"])["retry_after"] == "2026-07-27T13:00:00+08:00"
    )
    assert json.loads(second["payload_json"])["retryable"] is True
    assert json.loads(third["payload_json"])["retryable"] is False
    assert (
        json.loads(third["payload_json"])["retry_after"] == "2026-07-28T00:00:00+08:00"
    )


def test_unpublished_official_year_does_not_spend_provider_calls(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    provider = _Provider(_snapshot())

    class _UnpublishedNotice:
        calls = 0

        def fetch_notice(self, **kwargs):
            self.calls += 1
            raise ValueError(
                "official SSE holiday notice does not contain requested year"
            )

    notice = _UnpublishedNotice()
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)
    service = _service(db, provider, notice)
    result = service.sync_year(2026, now=now)
    restarted = _service(db, provider, notice)
    assert restarted.sync_year(2026, now=now + timedelta(hours=4)) == result
    assert provider.calls == 0
    assert notice.calls == 1
    assert result["status"] == "failed"
    payload = json.loads(result["payload_json"])
    assert payload["source_failures"][0]["kind"] == "invalid_data"
    assert payload["retryable"] is False


def test_existing_legacy_rate_limit_audit_is_respected_after_upgrade(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)
    db.upsert_automation_run_sync(
        {
            "run_id": "market_calendar_sync:SSE:2026:2026-07-27",
            "run_type": "market_calendar_sync",
            "run_date": "2026-07-27",
            "status": "failed",
            "execution_mode": "market_data_ingestion",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "payload": {
                "provider": "tushare",
                "attempt": 1,
                "error": {
                    "type": "Exception",
                    "message": "抱歉，您每分钟最多访问该接口2次",
                },
                "retryable": True,
            },
        }
    )
    primary = _UnavailableProvider(AssertionError("limited source must not be retried"))
    backup = _Provider(replace(_snapshot(), provider="akshare"))
    service, calls = _routed_service(
        db,
        {"tushare": primary, "akshare": backup},
        _NoticeProvider(_notice()),
    )

    result = service.run_due(now=now + timedelta(minutes=10))[0]

    assert result["status"] == "completed"
    assert calls == ["akshare"]
    assert primary.calls == 0
    payload = json.loads(result["payload_json"])
    assert payload["source_failures"][0]["kind"] == "rate_limited"
    assert payload["source_failures"][0]["error"]["type"] == "Exception"


def test_cooldown_is_saved_before_fallback_crashes(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    primary = _UnavailableProvider(RuntimeError("too many requests"))

    class _CrashingProvider:
        def fetch_snapshot(self, **kwargs):
            raise SystemExit("simulated process exit during fallback")

    notice = _NoticeProvider(_notice())
    service, _ = _routed_service(
        db, {"tushare": primary, "akshare": _CrashingProvider()}, notice
    )
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)
    with pytest.raises(SystemExit):
        service.run_due(now=now)
    restarted, calls = _routed_service(
        AppDatabase(db.path),
        {"tushare": primary, "akshare": _Provider(_snapshot())},
        notice,
    )

    result = restarted.run_due(now=now + timedelta(minutes=1))[0]

    assert result["status"] == "completed"
    assert primary.calls == 1
    assert calls == ["akshare"]


def test_wrong_year_candidate_does_not_write_a_different_year_snapshot(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    wrong_year = replace(_snapshot(), year=2025)
    service = _service(db, _Provider(wrong_year), _NoticeProvider(_notice()))

    result = service.run_due(now=datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI))[0]

    assert result["status"] == "needs_review"
    assert json.loads(result["payload_json"])["retryable"] is False
    assert db.get_market_calendar_snapshot_sync(exchange="SSE", year=2025) is None
    assert db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026) is None


def test_primary_mismatch_does_not_end_backup_transient_retry_window(tmp_path) -> None:
    db = AppDatabase(tmp_path / "calendar.db")
    db.init_sync()
    primary = _Provider(_snapshot(extra_open_dates={"2026-05-02"}))
    backup = _UnavailableProvider(TimeoutError("network timed out"))
    notice = _NoticeProvider(_notice())
    service, _ = _routed_service(db, {"tushare": primary, "akshare": backup}, notice)
    now = datetime(2026, 7, 27, 12, tzinfo=_SHANGHAI)

    first = service.run_due(now=now)[0]
    assert first["status"] == "failed"
    assert json.loads(first["payload_json"])["retryable"] is True
    assert db.get_market_calendar_snapshot_sync(exchange="SSE", year=2026) is None
    restarted, calls = _routed_service(
        AppDatabase(db.path),
        {"tushare": primary, "akshare": _Provider(_snapshot())},
        notice,
    )
    second = restarted.run_due(now=now + timedelta(hours=1))[0]

    assert second["status"] == "completed"
    assert calls == ["akshare"]
    assert primary.calls == 1
