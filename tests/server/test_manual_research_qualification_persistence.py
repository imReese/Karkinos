"""Synthetic manual qualification lineage and actual SQL migration boundaries."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from server.contracts.ai_shadow_research_qualification import (
    MANUAL_QUALIFICATION_BACKUP,
    SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
    ShadowResearchQualificationRejected,
    manual_qualification_source_id,
    qualification_outcome_projection,
)
from server.contracts.content_identity import canonical_json, content_fingerprint
from server.db import AppDatabase
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.backtest_results import insert_backtest_result
from server.persistence.strategy_research import StrategyResearchAuditStore
from server.services.ai_shadow.ai_shadow_research_qualification_support import (
    formula_binding,
)
from tests.server.test_ai_shadow_research_qualification_persistence import (
    _atomic_candidate_args,
    _backtest_values,
    _run_args,
)
from tests.server.test_ai_shadow_research_qualification_service import (
    _draft,
    _source_selection,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]
STAMP = "2026-09-01T08:00:00+00:00"


def _insert(conn, table, **values):
    names = tuple(values)
    conn.execute(
        f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
        tuple(values.values()),
    )


def manual_source(tmp_path):
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()
    store = ShadowResearchStore(path)
    store.init()
    StrategyResearchAuditStore(path).init()
    selection = _source_selection()
    draft = _draft(1, selection)
    with sqlite3.connect(path) as conn:
        result_id = insert_backtest_result(
            conn,
            created_at=STAMP,
            **{
                **_backtest_values(),
                "metrics_json": canonical_json(
                    {"formula_binding": formula_binding(selection, draft).to_dict()}
                ),
            },
        )
    refs = dict(
        session_id="manual-session",
        draft_id="manual-draft",
        backtest_run_id="manual-backtest",
        critique_id="manual-critique",
        canonical_backtest_result_id=result_id,
    )
    artifact = {"review": "synthetic"}
    fp = "sha256:" + "b" * 64
    evidence = {
        "reservation": {
            "manual_source_refs": refs,
            "manual_source_fingerprint": fp,
            "champion_formula_fingerprint": "sha256:"
            + content_fingerprint(draft["formula_ast"]),
        },
        "deployment_assessment": {"status": "pass"},
    }
    evidence["evidence_fingerprint"] = content_fingerprint(evidence)
    binding = dict(
        source_kind="manual_research",
        manual_source_refs=refs,
        manual_source_fingerprint=fp,
        final_evaluation_id="manual-final",
        final_evidence_fingerprint=evidence["evidence_fingerprint"],
    )
    with sqlite3.connect(path) as conn:
        _insert(
            conn,
            "ai_strategy_research_sessions",
            session_id=refs["session_id"],
            idempotency_key="session-key",
            request_fingerprint="request",
            request_json="{}",
            selection_fingerprint="selection-fp",
            status="completed",
            prompt_version="fixture",
            created_at=STAMP,
            updated_at=STAMP,
        )
        _insert(
            conn,
            "ai_strategy_hypothesis_drafts",
            draft_id=refs["draft_id"],
            session_id=refs["session_id"],
            ordinal=1,
            contract_json=canonical_json(draft),
            artifact_fingerprint=content_fingerprint(draft),
            formula_fingerprint=draft["formula_fingerprint"],
            validation_status="valid",
            validation_errors_json="[]",
            created_at=STAMP,
        )
        _insert(
            conn,
            "ai_strategy_formula_backtests",
            backtest_run_id=refs["backtest_run_id"],
            idempotency_key="backtest-key",
            request_fingerprint="request",
            session_id=refs["session_id"],
            draft_id=refs["draft_id"],
            formula_fingerprint=draft["formula_fingerprint"],
            dataset_snapshot_id=selection.dataset_snapshot_id,
            cost_model_reference=selection.cost_model_reference,
            status="completed",
            canonical_backtest_result_id=result_id,
            created_at=STAMP,
            updated_at=STAMP,
        )
        _insert(
            conn,
            "ai_strategy_backtest_critiques",
            critique_id=refs["critique_id"],
            idempotency_key="critique-key",
            request_fingerprint="request",
            session_id=refs["session_id"],
            draft_id=refs["draft_id"],
            backtest_run_id=refs["backtest_run_id"],
            status="completed",
            normalized_artifact_json=canonical_json(artifact),
            artifact_fingerprint=content_fingerprint(artifact),
            prompt_version="fixture",
            created_at=STAMP,
            updated_at=STAMP,
        )
        _insert(
            conn,
            "ai_strategy_sealed_tests",
            sealed_test_id="manual-final",
            idempotency_key="final-key",
            request_fingerprint="request",
            session_id=refs["session_id"],
            draft_id=refs["draft_id"],
            backtest_run_id=refs["backtest_run_id"],
            research_family_id="fixture-family",
            partition_fingerprint="partition",
            champion_formula_fingerprint="sha256:"
            + content_fingerprint(draft["formula_ast"]),
            consumed_at=STAMP,
            status="completed",
            evidence_json=canonical_json(evidence),
            evidence_fingerprint=evidence["evidence_fingerprint"],
            created_at=STAMP,
            updated_at=STAMP,
        )
    args = {
        **_run_args(),
        "source_binding": binding,
        "source_run_id": manual_qualification_source_id(binding),
        "source_selection_id": refs["session_id"],
        "source_selection_fingerprint": "selection-fp",
        "source_backup_fingerprint": MANUAL_QUALIFICATION_BACKUP,
    }
    return store, binding, args


def save_candidate(store, run, binding):
    source_formula = StrategyResearchAuditStore(store.path).get_draft(
        binding["manual_source_refs"]["session_id"],
        binding["manual_source_refs"]["draft_id"],
    )["formula_fingerprint"]
    args = _atomic_candidate_args(
        run,
        {
            "candidate_id": manual_qualification_source_id(binding),
            "draft_id": binding["manual_source_refs"]["draft_id"],
        },
    )
    args["source_formula_fingerprint"] = source_formula
    return store.save_qualification_candidate_with_backtest(
        **args,
        backtest_values=_backtest_values(),
        candidate_evidence_builder=lambda row: (
            {
                "source_binding": binding,
                "research_capital_mode": "account_bound",
                "account_qualification_status": "passed",
                "promotion_gate": {"status": "passed", "blockers": []},
            },
            "qualified",
            "paper_shadow_review",
        ),
    )


def test_manual_run_cold_reopens_without_daily_candidate_or_fake_winner(tmp_path):
    store, binding, args = manual_source(tmp_path)
    run, reused = store.create_or_get_qualification_run(**args)
    assert not reused and run["source_binding"] == binding
    candidate = save_candidate(store, run, binding)
    selection = {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_run_id": run["qualification_run_id"],
        "source_run_id": run["source_run_id"],
        "market_date": run["market_date"],
        "source_binding": binding,
        "status": "specified_candidate_qualified",
        "selected_qualification_candidate_id": candidate["qualification_candidate_id"],
        "winner_qualification_candidate_id": None,
        "provider_call_performed": False,
        "broker_order_created": False,
        "capital_authority_granted": False,
    }
    finished = store.finish_qualification_run(
        run["qualification_run_id"],
        status="completed",
        selection=selection,
        blockers=[],
        failure_code=None,
        now=STAMP,
    )
    assert qualification_outcome_projection(finished)["status"] == "passed"
    assert (
        store.get_qualification_run(run["qualification_run_id"])["source_binding"]
        == binding
    )
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_candidates"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ai_shadow_research_runs").fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "changed",
    [
        "draft_id",
        "critique_id",
        "canonical_backtest_result_id",
        "final_evidence_fingerprint",
    ],
)
def test_manual_run_rejects_wrong_lineage_before_write(tmp_path, changed):
    store, binding, args = manual_source(tmp_path)
    bad = copy.deepcopy(binding)
    if changed in bad["manual_source_refs"]:
        bad["manual_source_refs"][changed] = (
            999 if changed == "canonical_backtest_result_id" else "not-real"
        )
    else:
        bad[changed] = "c" * 64
    with pytest.raises(
        ShadowResearchQualificationRejected, match="manual_source_binding_invalid"
    ):
        store.create_or_get_qualification_run(**{**args, "source_binding": bad})
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_runs"
            ).fetchone()[0]
            == 0
        )


def test_sql_guard_rejects_self_declared_manual_lineage_and_source_drift(tmp_path):
    store, binding, args = manual_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**args)
    candidate = save_candidate(store, run, binding)
    with sqlite3.connect(store.path) as conn:
        row = conn.execute(
            "SELECT * FROM ai_shadow_research_qualification_candidates"
        ).fetchone()
        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(ai_shadow_research_qualification_candidates)"
            )
        ]
        values = dict(zip(cols, row, strict=True))
        values["qualification_candidate_id"] += "-forged"
        values["source_candidate_id"] = "manual-research:" + "c" * 24
        values["candidate_result_id"] = None
        with pytest.raises(
            sqlite3.IntegrityError, match="qualification candidate binding invalid"
        ):
            _insert(conn, "ai_shadow_research_qualification_candidates", **values)
        with pytest.raises(
            sqlite3.IntegrityError, match="qualification source binding is immutable"
        ):
            conn.execute(
                "UPDATE ai_shadow_research_qualification_runs SET status='failed',selection_json='{}',selection_fingerprint='x',failure_code='fixture' WHERE qualification_run_id=?",
                (run["qualification_run_id"],),
            )
        assert candidate["source_candidate_id"] == manual_qualification_source_id(
            binding
        )


def test_v25_upgrade_keeps_history_and_legacy_guard(monkeypatch, tmp_path):
    from server.persistence import migrations
    from tests.server.test_ai_shadow_research_qualification_persistence import (
        _save_qualified_candidate,
        _seed_source,
    )

    registered = migrations._MIGRATIONS
    monkeypatch.setattr(
        migrations,
        "_MIGRATIONS",
        tuple(item for item in registered if item.version <= 25),
    )
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    store, source = _seed_source(tmp_path)
    with sqlite3.connect(database.path) as conn:
        before = conn.execute(
            "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        source_rows = conn.execute(
            "SELECT * FROM ai_shadow_research_candidates"
        ).fetchall()
        assert len(before) == 25
    monkeypatch.setattr(migrations, "_MIGRATIONS", registered)
    database.init_sync()
    store.init()  # Legacy optional initialization must not restore its old trigger.
    with sqlite3.connect(database.path) as conn:
        assert (
            conn.execute(
                "SELECT version,name,checksum,applied_at FROM schema_migrations WHERE version<=25 ORDER BY version"
            ).fetchall()
            == before
        )
        assert (
            conn.execute("SELECT * FROM ai_shadow_research_candidates").fetchall()
            == source_rows
        )
        guard = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='ai_shadow_qualification_candidate_insert_guard'"
        ).fetchone()[0]
        assert (
            "manual_research" in guard and "JOIN ai_shadow_research_candidates" in guard
        )
    run, _ = store.create_or_get_qualification_run(**_run_args())
    assert _save_qualified_candidate(store, run, source)["status"] == "qualified"


@pytest.mark.parametrize(
    "damage", ["missing_result", "formula_drift", "uncompleted_final", "failed_final"]
)
def test_same_transaction_owner_rejects_source_or_final_drift(tmp_path, damage):
    store, binding, args = manual_source(tmp_path)
    with sqlite3.connect(store.path) as conn:
        if damage == "missing_result":
            conn.execute(
                "DELETE FROM backtest_results WHERE id=?",
                (binding["manual_source_refs"]["canonical_backtest_result_id"],),
            )
        elif damage == "formula_drift":
            conn.execute(
                "UPDATE ai_strategy_formula_backtests SET formula_fingerprint=?",
                ("sha256:" + "c" * 64,),
            )
        elif damage == "uncompleted_final":
            conn.execute("UPDATE ai_strategy_sealed_tests SET status='reserved'")
        else:
            import json

            evidence = json.loads(
                conn.execute(
                    "SELECT evidence_json FROM ai_strategy_sealed_tests"
                ).fetchone()[0]
            )
            evidence["deployment_assessment"]["status"] = "insufficient_evidence"
            evidence.pop("evidence_fingerprint")
            evidence["evidence_fingerprint"] = content_fingerprint(evidence)
            binding["final_evidence_fingerprint"] = evidence["evidence_fingerprint"]
            conn.execute(
                "UPDATE ai_strategy_sealed_tests SET evidence_json=?,evidence_fingerprint=?",
                (canonical_json(evidence), evidence["evidence_fingerprint"]),
            )
    with pytest.raises(
        ShadowResearchQualificationRejected, match="manual_source_binding_invalid"
    ):
        store.create_or_get_qualification_run(**args)
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_runs"
            ).fetchone()[0]
            == 0
        )


def test_manual_pre_run_failure_attempt_retains_original_blocker(tmp_path):
    from server.services.ai_shadow.ai_shadow_research_qualification_support import (
        latest_qualification_attempt,
        record_blocked_qualification_attempt,
    )

    store, binding, args = manual_source(tmp_path)
    db = AppDatabase(store.path)
    batch = {
        "source_binding": binding,
        "run_id": args["source_run_id"],
        "market_date": args["market_date"],
        "selection_id": args["source_selection_id"],
        "selection_fingerprint": "1" * 64,
        "backup_artifact_fingerprint": MANUAL_QUALIFICATION_BACKUP,
    }
    attempt = record_blocked_qualification_attempt(
        db,
        batch=batch,
        blocker="qualification_valuation_snapshot_stale",
        recorded_at=STAMP,
    )
    assert attempt["blockers"] == ["qualification_valuation_snapshot_stale"]
    assert attempt["source_binding"] == binding
    assert (
        latest_qualification_attempt(db, source_run_id=args["source_run_id"]) == attempt
    )
    batch["selection_id"] = "unrelated-session"
    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_attempt_source_identity_invalid",
    ):
        record_blocked_qualification_attempt(
            db,
            batch=batch,
            blocker="qualification_valuation_snapshot_stale",
            recorded_at=STAMP,
        )
