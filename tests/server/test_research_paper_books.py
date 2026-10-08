"""Independent paper cash/positions through real immutable inputs and HTTP."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from data.dataset.manifest import publish_daily_bar_dataset_manifest
from data.dataset.reader import read_daily_bar_dataset
from data.providers import tushare_corporate_actions as ca_provider
from server.routes import research_paper_books as routes
from server.services.research_paper_books import ResearchPaperBookService
from tests.server.test_research_observation_inputs import DAYS, STOCK, dataset
from tests.server.test_research_observations_journey import journey, start  # noqa: F401

pytestmark = pytest.mark.product_smoke


@pytest.fixture
def paper(journey, monkeypatch):
    client, observations, current, ref, result_id = journey
    service = ResearchPaperBookService(observations.db, clock=lambda: current[0])
    monkeypatch.setattr(routes, "_service", lambda: service)
    client.app.include_router(routes.create_router())
    observation, _ = start(client, result_id)
    path = f"/api/research-observations/{observation['id']}/paper-book"
    return client, service, current, observation, path


def bound_dataset(tmp_path, *, count, now, records=(), closes=None):
    objects, ref = dataset(
        tmp_path / "research", days=DAYS[:count], cutoff=now, closes=closes
    )
    response = pd.DataFrame(records, columns=ca_provider.DIVIDEND_FIELDS.split(","))
    observed = ca_provider.collect_tushare_dividend_observation(
        objects,
        instrument=STOCK,
        client=SimpleNamespace(dividend=lambda **_: response),
        clock=lambda: now,
    )
    snapshot = read_daily_bar_dataset(objects, ref).snapshot
    return publish_daily_bar_dataset_manifest(
        objects,
        replace(snapshot, corporate_action_observation_ids=(observed.object_id,)),
    )


def create(client, path, *, health_policy=None):
    request = {
        "request_id": str(uuid4()),
        "initial_cash": "100000",
        "cost_assumptions": {
            "stock_commission_rate": 0,
            "stock_min_commission": 5,
            "slippage_bps": 0,
            "max_volume_participation": 1,
        },
    }
    if health_policy is not None:
        request["health_policy"] = health_policy
    result = client.post(path, json=request)
    assert result.status_code == 200, result.text
    return result.json(), request


def publish(client, observation, ref):
    result = client.post(
        f"/api/research-observations/{observation['id']}/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": observation["version"],
            "dataset_id": ref.dataset_id,
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["publication_id"], result.text
    return result.json()


def settle(client, path, version, ref):
    request = {
        "request_id": str(uuid4()),
        "expected_version": version,
        "dataset_id": ref.dataset_id,
    }
    response = client.post(path + "/settle", json=request)
    assert response.status_code == 200, response.text
    return response.json(), request


def prepare_trade(paper, tmp_path, *, records=(), health_policy=None):
    client, service, current, observation, path = paper
    created, start_request = create(client, path, health_policy=health_policy)
    current[0] += timedelta(seconds=1)
    closes = dict(zip(DAYS[:5], ("12", "11", "10", "9", "12"), strict=True))
    ref = bound_dataset(tmp_path, count=5, now=current[0], closes=closes)
    publication = publish(client, observation, ref)
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    closes[DAYS[5]] = "10"
    ref = bound_dataset(
        tmp_path, count=6, now=current[0], closes=closes, records=records
    )
    settled, settle_request = settle(client, path, 0, ref)
    return created, settled, start_request, settle_request, closes, publication


def test_cash_fill_restart_pause_and_mark_without_shared_account_writes(
    paper, tmp_path, monkeypatch
):
    client, service, current, observation, path = paper
    created, first, start_request, settle_request, closes, publication = prepare_trade(
        paper, tmp_path
    )
    assert created["state"] == {
        "cash": "100000",
        "equity": "100000",
        "dividend_receivable": "0",
        "dividend_income": "0",
        "positions": {},
    }
    assert created["evaluation_start"] == "2026-09-21"
    assert first["state"]["positions"]["600000"]["quantity"] == "2500"
    fill = first["fills"][0]
    assert fill["fill_price"] == "10"
    assert fill["fee_breakdown"]["total_fee"] == "5.25"
    assert first["state"]["cash"] == "74994.75"
    assert first["state"]["equity"] == "99994.75"
    assert first["steps"][0]["book_version"] == 1
    assert fill["timestamp"] != first["steps"][0]["settled_at"]
    reopened = ResearchPaperBookService(service.db, clock=lambda: current[0])
    monkeypatch.setattr(routes, "_service", lambda: reopened)
    assert client.post(path, json=start_request).json() == created
    assert client.post(path + "/settle", json=settle_request).json() == first
    pause_request = {"request_id": str(uuid4()), "expected_version": 1}
    paused_response = client.post(path + "/pause", json=pause_request)
    assert paused_response.status_code == 200, paused_response.text
    paused = paused_response.json()
    assert paused["version"] == 2
    current[0] += timedelta(seconds=1)
    # A new publication after the paper pause remains a shadow target only.
    publish(
        client,
        {**observation, "version": publication["version"]},
        bound_dataset(tmp_path, count=6, now=current[0], closes=closes),
    )
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "11"
    final, _ = settle(
        client, path, 2, bound_dataset(tmp_path, count=7, now=current[0], closes=closes)
    )
    assert final["lifecycle"] == "paused"
    assert final["state"]["equity"] == "102494.75"
    assert final["state"]["positions"]["600000"]["available_qty"] == "2500"
    assert final["fills"] == first["fills"]
    assert final["steps"][0] == first["steps"][0]
    assert client.post(path + "/pause", json=pause_request).json() == paused
    assert client.get(path).json() == final
    with sqlite3.connect(service.db.path) as conn:
        for table in ("orders", "fills", "ledger_entries"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    # Sanitized fixture consumed by UI/recovery tests, never a private account export.
    (tmp_path / "paper-book-journey.json").write_text(
        json.dumps(
            {"created": created, "settled": first, "paused": paused, "marked": final},
            indent=2,
        )
    )


def test_missing_ca_no_new_work_and_receipt_survives_code_change(
    paper, tmp_path, monkeypatch
):
    client, service, current, _, path = paper
    book, request = create(client, path)
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    _, unbound = dataset(tmp_path / "research", days=DAYS[:6], cutoff=current[0])
    bad = client.post(
        path + "/settle",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": unbound.dataset_id,
        },
    )
    assert bad.status_code == 422, bad.text
    assert "cash_dividend_evidence_required" in bad.text
    assert service.get(book["observation_id"])["version"] == 0
    settled, operation = settle(
        client, path, 0, bound_dataset(tmp_path, count=6, now=current[0])
    )
    duplicate = client.post(
        path + "/settle",
        json={**operation, "request_id": str(uuid4()), "expected_version": 1},
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == "paper_book_no_new_sessions"
    monkeypatch.setattr(
        "server.services.research_paper_books.paper_book_code_binding",
        lambda: {"changed": True},
    )
    monkeypatch.setattr(
        "server.services.research_paper_books.observation_code_binding",
        lambda: {"changed": True},
    )
    assert client.post(path, json=request).json() == book
    assert client.post(path + "/settle", json=operation).json() == settled
    assert (
        client.post(
            path + "/settle",
            json={**operation, "request_id": str(uuid4()), "expected_version": 1},
        ).json()["detail"]
        == "paper_book_code_changed"
    )


def ca_record(**changes):
    result = {
        "ts_code": "600000.SH",
        "div_proc": "实施",
        "end_date": "20251231",
        "ann_date": "20260901",
        "imp_ann_date": "20260902",
        "record_date": "20260921",
        "ex_date": "20260922",
        "pay_date": "20260923",
        "cash_div_tax": "0.1",
        "cash_div": "0.09",
        "stk_div": "0",
        "stk_bo_rate": "0",
        "stk_co_rate": "0",
    }
    return {**result, **changes}


def test_ca_recapture_once_and_pay_day_releases_gross_receivable(paper, tmp_path):
    client, _, current, _, path = paper
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path, records=[ca_record()])
    assert first["steps"][0]["projection"]["corporate_actions"] == []
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "10"
    second, _ = settle(
        client,
        path,
        1,
        bound_dataset(
            tmp_path,
            count=7,
            now=current[0],
            closes=closes,
            records=[ca_record(imp_ann_date="20260903")],
        ),
    )
    assert second["state"]["dividend_receivable"] == "250"
    assert second["state"]["dividend_income"] == "250"
    assert second["state"]["cash"] == "74994.75"
    assert len(second["steps"][-1]["projection"]["corporate_actions"]) == 1
    current[0] = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
    closes[DAYS[7]] = "10"
    third, _ = settle(
        client,
        path,
        2,
        bound_dataset(
            tmp_path,
            count=8,
            now=current[0],
            closes=closes,
            records=[ca_record(imp_ann_date="20260904")],
        ),
    )
    assert third["state"]["dividend_receivable"] == "0"
    assert third["state"]["cash"] == "75244.75"
    assert third["state"]["dividend_income"] == "250"
    assert third["steps"][:2] == second["steps"]


def test_ca_report_period_date_revision_blocks_even_when_moved_to_future(
    paper, tmp_path
):
    client, _, current, _, path = paper
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path, records=[ca_record()])
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    revised = ca_record(
        imp_ann_date="20260922",
        record_date="20261012",
        ex_date="20261013",
        pay_date="20261014",
    )
    ref = bound_dataset(
        tmp_path, count=7, now=current[0], closes=closes, records=[revised]
    )
    result = client.post(
        path + "/settle",
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "dataset_id": ref.dataset_id,
        },
    )
    assert result.status_code == 409, result.text
    assert result.json()["detail"] == "paper_book_corporate_action_revision_conflict"
    assert client.get(path).json() == first


@pytest.mark.parametrize("prestart", [False, True])
def test_report_can_drop_only_proven_zero_prestart_entitlements(
    paper, tmp_path, prestart
):
    client, _, current, _, path = paper
    event = (
        ca_record(record_date="20260917", ex_date="20260918", pay_date="20260918")
        if prestart
        else ca_record()
    )
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path, records=[event])
    assert first["state"]["dividend_receivable"] == "0"
    assert first["steps"][0]["projection"]["corporate_actions"] == []
    # Fresh capture alone cannot establish that the previously reported
    # entitlement is still valid when the provider no longer reports it.
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    ref = bound_dataset(tmp_path, count=7, now=current[0], closes=closes, records=[])
    response = client.post(
        path + "/settle",
        json={
            "request_id": str(uuid4()),
            "expected_version": first["version"],
            "dataset_id": ref.dataset_id,
        },
    )
    if prestart:
        assert response.status_code == 200, response.text
        assert response.json()["steps"][:-1] == first["steps"]
        assert response.json()["state"]["dividend_income"] == "0"
    else:
        assert response.status_code == 409, response.text
        assert (
            response.json()["detail"] == "paper_book_corporate_action_revision_conflict"
        )
        assert client.get(path).json() == first


def test_late_ca_cannot_rewrite_settled_cash_or_nav(paper, tmp_path):
    client, _, current, _, path = paper
    _, _, _, _, closes, _ = prepare_trade(paper, tmp_path)
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    second, _ = settle(
        client, path, 1, bound_dataset(tmp_path, count=7, now=current[0], closes=closes)
    )
    current[0] = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
    ref = bound_dataset(
        tmp_path, count=8, now=current[0], closes=closes, records=[ca_record()]
    )
    result = client.post(
        path + "/settle",
        json={
            "request_id": str(uuid4()),
            "expected_version": 2,
            "dataset_id": ref.dataset_id,
        },
    )
    assert result.status_code == 409, result.text
    assert result.json()["detail"] == "paper_book_settled_prefix_conflict"
    assert client.get(path).json() == second


def test_historical_revision_uses_original_inputs_and_corruption_is_recoverable(
    paper, tmp_path
):
    client, service, current, _, path = paper
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path)
    original = service.observations.objects.resolve_ref(first["steps"][0]["dataset_id"])
    target = service.observations.objects._path_for(original.object_id)
    original_bytes = target.read_bytes()
    target.chmod(0o600)
    target.write_bytes(b"corrupt")
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[5]], closes[DAYS[6]] = "11", "11"
    ref = bound_dataset(tmp_path, count=7, now=current[0], closes=closes)
    request = {
        "request_id": str(uuid4()),
        "expected_version": 1,
        "dataset_id": ref.dataset_id,
    }
    blocked = client.post(path + "/settle", json=request)
    assert blocked.status_code == 422, blocked.text
    assert client.get(path).json() == first
    target.write_bytes(original_bytes)
    recovered = client.post(path + "/settle", json=request)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["steps"][0] == first["steps"][0]
    assert recovered.json()["state"]["equity"] == "102494.75"


def test_pause_race_aborts_computed_settlement_and_retry_preserves_cutoff(
    paper, tmp_path, monkeypatch
):
    client, service, current, _, path = paper
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path)
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    ref = bound_dataset(tmp_path, count=7, now=current[0], closes=closes)
    original = service.repository.settle

    def paused_before_lock(**kwargs):
        service.pause(
            first["observation_id"], request_id=str(uuid4()), expected_version=1
        )
        return original(**kwargs)

    monkeypatch.setattr(service.repository, "settle", paused_before_lock)
    response = client.post(
        path + "/settle",
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "dataset_id": ref.dataset_id,
        },
    )
    assert response.status_code == 409, response.text
    book = client.get(path).json()
    assert book["lifecycle"] == "paused"
    assert book["steps"] == first["steps"]
    monkeypatch.setattr(service.repository, "settle", original)
    settled, _ = settle(client, path, 2, ref)
    assert settled["paused_at"] == book["paused_at"]


def test_prestart_publication_is_not_a_paper_holding(paper, tmp_path):
    client, _, current, observation, path = paper
    closes = dict(zip(DAYS[:5], ("12", "11", "10", "9", "12"), strict=True))
    ref = bound_dataset(tmp_path, count=5, now=current[0], closes=closes)
    publish(client, observation, ref)
    current[0] += timedelta(seconds=1)
    create(client, path)
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    book, _ = settle(
        client, path, 0, bound_dataset(tmp_path, count=6, now=current[0], closes=closes)
    )
    assert book["state"]["positions"] == {}
    assert book["state"]["equity"] == "100000"
    assert book["fills"] == []


def test_http_configuration_and_observation_lifecycle_gates(paper, monkeypatch):
    client, _, _, observation, path = paper
    assert client.get(path).json() is None
    for changes in (
        {"initial_cash": "NaN"},
        {"initial_cash": "0"},
        {"account_id": "private"},
    ):
        assert (
            client.post(
                path,
                json={"request_id": str(uuid4()), "initial_cash": "100000", **changes},
            ).status_code
            == 422
        )
    monkeypatch.setattr(
        "server.services.research_paper_books.observation_code_binding",
        lambda: {"changed": True},
    )
    assert (
        client.post(
            path, json={"request_id": str(uuid4()), "initial_cash": "100000"}
        ).json()["detail"]
        == "paper_book_observation_code_changed"
    )


def test_receipts_cas_rollback_and_append_only_database_guards(
    paper, tmp_path, monkeypatch
):
    client, service, current, _, path = paper
    _, first, _, first_request, closes, _ = prepare_trade(paper, tmp_path)
    assert (
        client.post(
            path + "/settle", json={**first_request, "dataset_id": "sha256:" + "a" * 64}
        ).status_code
        == 409
    )
    current[0] = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
    ref = bound_dataset(tmp_path, count=8, now=current[0], closes=closes)
    request = {
        "request_id": str(uuid4()),
        "expected_version": 1,
        "dataset_id": ref.dataset_id,
    }
    original_record = service.repository._record

    def fail_receipt(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic disk failure")

    monkeypatch.setattr(service.repository, "_record", fail_receipt)
    with pytest.raises(sqlite3.OperationalError, match="synthetic"):
        client.post(path + "/settle", json=request)
    assert client.get(path).json() == first
    monkeypatch.setattr(service.repository, "_record", original_record)
    response = client.post(path + "/settle", json=request)
    assert response.status_code == 200, response.text
    assert len(response.json()["steps"]) == 3
    assert client.post(path + "/settle", json=request).json() == response.json()
    with sqlite3.connect(service.db.path) as conn:
        for statement in (
            "UPDATE research_paper_steps SET projection_json='{}'",
            "DELETE FROM research_paper_steps",
            "UPDATE research_paper_operations SET result_json='{}'",
            "DELETE FROM research_paper_operations",
            "UPDATE research_paper_books SET initial_cash='900000'",
            "DELETE FROM research_paper_books",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)


def test_settlement_uses_locked_real_commit_time_and_rejects_clock_reversal(
    paper, tmp_path, monkeypatch
):
    client, service, current, _, path = paper
    create(client, path)
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    ref = bound_dataset(tmp_path, count=6, now=current[0])
    monkeypatch.setattr(
        service.repository, "clock", lambda: current[0] - timedelta(seconds=1)
    )
    request = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "dataset_id": ref.dataset_id,
    }
    failed = client.post(path + "/settle", json=request)
    assert failed.json()["detail"] == "paper_book_clock_reversed"
    assert client.get(path).json()["steps"] == []
    monkeypatch.setattr(
        service.repository, "clock", lambda: current[0] + timedelta(seconds=2)
    )
    settled = client.post(path + "/settle", json=request)
    assert settled.status_code == 200, settled.text
    step = settled.json()["steps"][0]
    assert step["input"]["read_at"] == current[0].isoformat()
    assert step["settled_at"] == (current[0] + timedelta(seconds=2)).isoformat()


def test_paused_observation_cannot_start_but_existing_paper_can_settle(paper, tmp_path):
    client, _, current, observation, path = paper
    create(client, path)
    paused = client.post(
        f"/api/research-observations/{observation['id']}/pause",
        json={"request_id": str(uuid4()), "expected_version": 0},
    )
    assert paused.status_code == 200, paused.text
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    book, _ = settle(client, path, 0, bound_dataset(tmp_path, count=6, now=current[0]))
    assert book["state"]["equity"] == "100000"
    assert book["lifecycle"] == "active"


def test_new_book_rejects_paused_observation(paper):
    client, _, _, observation, path = paper
    client.post(
        f"/api/research-observations/{observation['id']}/pause",
        json={"request_id": str(uuid4()), "expected_version": 0},
    )
    response = client.post(
        path, json={"request_id": str(uuid4()), "initial_cash": "100000"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "paper_book_observation_paused"


def test_schema_24_upgrade_preserves_existing_database(tmp_path, monkeypatch):
    from server.db import AppDatabase
    from server.persistence import migrations

    database = AppDatabase(tmp_path / "migration.db")
    registered = migrations._MIGRATIONS
    with monkeypatch.context() as previous:
        previous.setattr(
            migrations,
            "_MIGRATIONS",
            tuple(item for item in registered if item.version < 24),
        )
        database.init_sync()
    with sqlite3.connect(database.path) as conn:
        old = conn.execute(
            "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
    database.init_sync()
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        assert (
            conn.execute(
                "SELECT version,name,checksum,applied_at FROM schema_migrations WHERE version<24 ORDER BY version"
            ).fetchall()
            == old
        )
        assert conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone() == (24,)
        for name in (
            "research_paper_books",
            "research_paper_steps",
            "research_paper_operations",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone() == (0,)


def test_proven_zero_prestart_ca_does_not_require_missing_historical_payment(
    paper, tmp_path
):
    client, _, current, _, path = paper
    create(client, path)
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    old = ca_record(
        end_date="20051231",
        ann_date="20060301",
        imp_ann_date="20060401",
        record_date="20060410",
        ex_date="20060411",
        pay_date=None,
    )
    book, _ = settle(
        client, path, 0, bound_dataset(tmp_path, count=6, now=current[0], records=[old])
    )
    assert book["state"]["cash"] == "100000"
    assert book["state"]["dividend_income"] == "0"
    assert book["steps"][0]["projection"]["corporate_actions"] == []


def test_prestart_record_with_inbook_ex_date_still_blocks_ex_day_order(paper, tmp_path):
    client, _, _, _, _ = paper
    old = ca_record(record_date="20260918", ex_date="20260921", pay_date="20260922")
    _, first, _, _, _, _ = prepare_trade(paper, tmp_path, records=[old])
    assert first["fills"] == []
    assert first["state"]["cash"] == "100000"
    assert (
        first["attempts"][0]["reason"]
        == "corporate_action_price_limit_reference_missing"
    )


def test_book_start_clock_cannot_reclassify_existing_publication_as_future(
    paper, tmp_path
):
    client, _, current, observation, path = paper
    start_clock = current[0]
    current[0] += timedelta(minutes=10)
    closes = dict(zip(DAYS[:5], ("12", "11", "10", "9", "12"), strict=True))
    publish(
        client,
        observation,
        bound_dataset(tmp_path, count=5, now=current[0], closes=closes),
    )
    current[0] = start_clock + timedelta(minutes=5)
    request = {"request_id": str(uuid4()), "initial_cash": "100000"}
    response = client.post(path, json=request)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "paper_book_clock_reversed"
    assert client.get(path).json() is None
    current[0] = start_clock + timedelta(minutes=11)
    created = client.post(path, json=request)
    assert created.status_code == 200, created.text
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    book, _ = settle(
        client, path, 0, bound_dataset(tmp_path, count=6, now=current[0], closes=closes)
    )
    assert book["fills"] == []
    assert book["state"]["equity"] == "100000"


def test_net_book_health_pauses_acceptance_but_retains_positions_and_replay(
    paper, tmp_path
):
    client, _, current, observation, path = paper
    policy = {
        "mode": "pause_on_breach",
        "minimum_settled_sessions": 1,
        "maximum_drawdown": "0",
        "minimum_net_excess_return": "-1",
    }
    created, first, _, _, closes, publication = prepare_trade(
        paper, tmp_path, health_policy=policy
    )
    assert created["health"]["status"] == "unavailable"
    assert first["lifecycle"] == "paused"
    assert first["health"]["action"] == "pause_paper_target_acceptance"
    assert first["performance"]["net_pnl"] == "-5.25"
    assert first["performance"]["max_drawdown"] == "0.0000525"
    assert first["performance"]["equity_series"][0]["equity"] == "100000"
    assert first["performance"]["modeled_net_excess_return"] == "0"
    assert first["performance"]["pnl_reconciliation_residual"] == "0"
    current[0] += timedelta(seconds=1)
    publish(
        client,
        {**observation, "version": publication["version"]},
        bound_dataset(tmp_path, count=6, now=current[0], closes=closes),
    )
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "11"
    final, _ = settle(
        client,
        path,
        first["version"],
        bound_dataset(tmp_path, count=7, now=current[0], closes=closes),
    )
    assert final["lifecycle"] == "paused"
    assert final["fills"] == first["fills"]
    assert final["state"]["equity"] == "102494.75"
    assert final["steps"][0] == first["steps"][0]


def test_paper_automation_is_separate_opt_in_and_marks_paused_observation(
    paper, tmp_path
):
    from server.services import research_observation_automation as automation
    from tests.server.test_research_observation_automation import register

    client, books, current, observation, path = paper
    _, first, _, _, closes, publication = prepare_trade(paper, tmp_path)
    observations = books.observations
    # A publication schedule alone has no permission to write paper settlement.
    response = client.put(
        f"/api/research-observations/{observation['id']}/automation",
        json={"enabled": True},
    )
    assert response.status_code == 200, response.text
    enabled = response.json()
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "11"
    ref = bound_dataset(tmp_path, count=7, now=current[0], closes=closes)
    register(observations, ref)
    automation.run_research_observation_automation_once(observations)
    assert books.get(observation["id"])["version"] == first["version"]
    current_observation = observations.repository.get(observation["id"])
    observations.pause(
        observation["id"],
        request_id=str(uuid4()),
        expected_version=current_observation["version"],
    )
    response = client.put(
        f"/api/research-observations/{observation['id']}/automation",
        json={
            "enabled": False,
            "paper_settlement_enabled": True,
            "expected_generation": enabled["generation"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["paper_settlement_enabled"] is True
    result = automation.run_research_observation_automation_once(observations)
    assert result[0]["status"] == "completed", result
    marked = books.get(observation["id"])
    assert marked["version"] == first["version"] + 1
    assert marked["state"]["equity"] == "102494.75"
    automation.run_research_observation_automation_once(observations)
    assert books.get(observation["id"])["version"] == marked["version"]


def test_frozen_etf_rotation_publishes_and_settles_with_etf_fees_without_fake_ca_coverage(
    journey, tmp_path, monkeypatch
):
    from core.types import InstrumentKey, InstrumentType
    from tests.server import test_research_observation_inputs as inputs

    client, observations, current, _, _ = journey
    etf = InstrumentKey("510300", InstrumentType.ETF)
    monkeypatch.setattr(inputs, "STOCK", etf)
    closes = {
        day: str(Decimal("10") + Decimal(index) / 10)
        for index, day in enumerate(DAYS[:5])
    }
    _, ref = inputs.dataset(tmp_path / "research", cutoff=current[0], closes=closes)
    config = json.loads(inputs.source(ref)["config_json"])
    config.update(
        strategy="etf_rotation",
        assets=[{"symbol": etf.symbol, "instrument_type": "etf"}],
        params={
            "lookback_period": 2,
            "volatility_window": 2,
            "top_k": 1,
            "rebalance_interval": 1,
            "use_risk_adjusted": False,
            "cash_proxy": "",
        },
    )
    result_id = asyncio.run(
        observations.db.save_backtest_result(
            config_json=json.dumps(config),
            metrics_json=json.dumps(
                {"dataset_binding": {"dataset_id": ref.dataset_id}}
            ),
            initial_cash=100000,
            final_equity=100000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    observation, _ = start(client, result_id)
    books = ResearchPaperBookService(observations.db, clock=lambda: current[0])
    monkeypatch.setattr(routes, "_service", lambda: books)
    client.app.include_router(routes.create_router())
    path = f"/api/research-observations/{observation['id']}/paper-book"
    created, _ = create(client, path)
    assert created["policy"]["corporate_action_mode"] == "price_only"
    assert created["instruments"][etf.symbol]["commission_type"] == "fund_etf"
    current[0] += timedelta(seconds=1)
    publish(client, observation, ref)
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    closes[DAYS[5]] = "10.5"
    _, later = inputs.dataset(
        tmp_path / "research", days=DAYS[:6], cutoff=current[0], closes=closes
    )
    settled, _ = settle(client, path, 0, later)
    assert settled["state"]["positions"][etf.symbol]["quantity"] == "2300"
    assert settled["fills"][0]["fee_breakdown"]["stamp_tax"] == "0"
    assert settled["performance"]["corporate_action_coverage_complete"] is False
    assert settled["performance"]["return_basis"] == "price_only"
    assert settled["performance"]["benchmark_status"] == "measured"


def test_paper_scheduling_disable_during_replay_fences_the_commit(
    paper, tmp_path, monkeypatch
):
    from server.services import research_observation_automation as automation
    from server.services import research_paper_books as paper_service
    from tests.server.test_research_observation_automation import register

    client, books, current, observation, path = paper
    _, first, _, _, closes, _ = prepare_trade(paper, tmp_path)
    api = f"/api/research-observations/{observation['id']}/automation"
    configured = client.put(
        api, json={"enabled": False, "paper_settlement_enabled": True}
    ).json()
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "11"
    register(
        books.observations,
        bound_dataset(tmp_path, count=7, now=current[0], closes=closes),
    )
    original = paper_service.replay_paper_book
    interrupted = []

    def replay_and_disable(**kwargs):
        result = original(**kwargs)
        if not interrupted:
            disabled = client.put(
                api,
                json={
                    "enabled": False,
                    "paper_settlement_enabled": False,
                    "expected_generation": configured["generation"],
                },
            )
            assert disabled.status_code == 200, disabled.text
            interrupted.append(True)
        return result

    monkeypatch.setattr(paper_service, "replay_paper_book", replay_and_disable)
    assert automation.run_research_observation_automation_once(books.observations) == []
    assert books.get(observation["id"]) == first
    assert (
        client.get(f"/api/research-observations/{observation['id']}").json()[
            "automation"
        ]["paper_settlement"]["status"]
        == "disabled"
    )


def test_waiting_cash_cannot_earn_health_excess_against_an_early_benchmark(
    paper, tmp_path
):
    from tests.server.test_research_observation_automation import extend_calendar

    client, books, current, observation, path = paper
    extend_calendar(books.observations)
    policy = {
        "mode": "report_only",
        "minimum_settled_sessions": 1,
        "maximum_drawdown": "1",
        "minimum_net_excess_return": "0.05",
    }
    created, _ = create(client, path, health_policy=policy)
    assert (
        created["policy"]["benchmark"]["activation"]
        == "first_real_published_target_accepted_after_book_start"
    )
    closes = dict(zip(DAYS[:5], ("12", "11", "10", "9", "12"), strict=True))
    current[0] = datetime(2026, 9, 21, 8, tzinfo=timezone.utc)
    closes[DAYS[5]] = "10"
    first, _ = settle(
        client, path, 0, bound_dataset(tmp_path, count=6, now=current[0], closes=closes)
    )
    assert first["performance"]["benchmark_start_session"] is None
    assert first["health"]["status"] == "insufficient_evidence"
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    closes[DAYS[6]] = "8"
    waiting, _ = settle(
        client, path, 1, bound_dataset(tmp_path, count=7, now=current[0], closes=closes)
    )
    assert waiting["steps"][0] == first["steps"][0]
    assert waiting["performance"]["modeled_net_excess_return"] == "0"
    assert waiting["performance"]["waiting_sessions_before_first_target"] == 2
    assert waiting["health"]["status"] == "insufficient_evidence"
    current[0] += timedelta(seconds=1)
    # This first genuine future target elects cash; its comparator starts at the
    # same future session instead of manufacturing gains from the earlier fall.
    publish(
        client,
        observation,
        bound_dataset(tmp_path, count=7, now=current[0], closes=closes),
    )
    current[0] = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
    closes[DAYS[7]] = "8"
    measured, _ = settle(
        client, path, 2, bound_dataset(tmp_path, count=8, now=current[0], closes=closes)
    )
    assert measured["steps"][:2] == waiting["steps"]
    assert measured["performance"]["benchmark_start_session"] == "2026-09-23"
    assert measured["performance"]["sessions_since_first_accepted_target"] == 1
    assert Decimal(measured["performance"]["modeled_net_excess_return"]) < Decimal(
        "0.05"
    )
    assert measured["health"]["status"] == "threshold_breached"
    assert measured["health"]["action"] == "review"
    assert (
        measured["health"]["comparison_basis"]
        == "book_cash_baseline_with_synchronized_first_accepted_target"
    )
