"""Schema repository for AI shadow research evidence."""

from __future__ import annotations


class ShadowResearchSchemaRepositoryMixin:
    def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ai_shadow_research_runs (
                    run_id TEXT PRIMARY KEY,
                    market_date TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    baseline_seed_result_id INTEGER NOT NULL,
                    baseline_result_id INTEGER,
                    research_capital_mode TEXT NOT NULL DEFAULT 'legacy_unknown'
                        CHECK(research_capital_mode IN
                              ('legacy_unknown', 'normalized_notional', 'account_bound')),
                    research_context_id TEXT,
                    valuation_snapshot_id TEXT NOT NULL,
                    ledger_cutoff_id INTEGER NOT NULL,
                    session_id TEXT,
                    failure_code TEXT,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_baselines (
                    baseline_fingerprint TEXT PRIMARY KEY,
                    backtest_result_id INTEGER NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_provider_calls (
                    call_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    market_date TEXT NOT NULL,
                    call_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reserved_tokens INTEGER NOT NULL,
                    actual_tokens INTEGER,
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_provider_free_partial_resumes (
                    resume_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL,
                    failed_call_id TEXT NOT NULL UNIQUE,
                    failed_session_id TEXT NOT NULL UNIQUE,
                    failed_workflow_id TEXT NOT NULL UNIQUE,
                    failed_agent_run_id TEXT NOT NULL UNIQUE,
                    failure_code TEXT NOT NULL
                        CHECK(failure_code = 'strategy_research_citation_catalog_too_large'),
                    failure_evidence_fingerprint TEXT NOT NULL UNIQUE,
                    prior_input_fingerprint TEXT NOT NULL,
                    resumed_input_fingerprint TEXT NOT NULL UNIQUE,
                    completed_iteration_count INTEGER NOT NULL,
                    completed_evidence_fingerprint TEXT NOT NULL,
                    resume_iteration INTEGER NOT NULL,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_run_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    market_date TEXT NOT NULL,
                    superseded_run_id TEXT NOT NULL UNIQUE,
                    superseded_input_fingerprint TEXT NOT NULL UNIQUE,
                    replacement_run_id TEXT NOT NULL,
                    replacement_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL,
                    run_snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_retry_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 10),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_retry_consumptions (
                    authorization_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_citation_call_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_citation_call_extension_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_output_truncation_call_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL
                        CHECK(failure_code = 'provider_output_truncated'),
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_output_truncation_call_extension_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_timeout_resume_call_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failure_code TEXT NOT NULL
                        CHECK(failure_code = 'provider_timeout'),
                    completed_iteration_count INTEGER NOT NULL
                        CHECK(completed_iteration_count = 4),
                    completed_evidence_fingerprint TEXT NOT NULL,
                    failed_call_id TEXT NOT NULL UNIQUE,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    resume_iteration INTEGER NOT NULL
                        CHECK(resume_iteration = 5),
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_timeout_resume_call_extension_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    resumed_run_id TEXT NOT NULL UNIQUE,
                    resumed_input_fingerprint TEXT NOT NULL UNIQUE,
                    completed_evidence_fingerprint TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_corrected_panel_rearm_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    completed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    completed_input_fingerprint TEXT NOT NULL,
                    completed_selection_fingerprint TEXT NOT NULL,
                    expected_rearm_evidence_json TEXT NOT NULL,
                    expected_rearm_evidence_fingerprint TEXT NOT NULL UNIQUE,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 10),
                    provider_call_ceiling INTEGER NOT NULL,
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_corrected_panel_rearm_consumptions (
                    authorization_id TEXT PRIMARY KEY,
                    replacement_run_id TEXT NOT NULL UNIQUE,
                    replacement_input_fingerprint TEXT NOT NULL UNIQUE,
                    consumed_rearm_evidence_fingerprint TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_corrected_panel_citation_resume_extensions (
                    extension_id TEXT PRIMARY KEY,
                    failed_run_id TEXT NOT NULL UNIQUE,
                    market_date TEXT NOT NULL UNIQUE,
                    failed_input_fingerprint TEXT NOT NULL,
                    failed_call_id TEXT NOT NULL UNIQUE,
                    failed_call_failure_code TEXT NOT NULL
                        CHECK(failed_call_failure_code = 'critique_citation_outside_binding'),
                    checkpoint_fingerprint TEXT NOT NULL,
                    provider_calls_at_authorization INTEGER NOT NULL,
                    prior_provider_call_ceiling INTEGER NOT NULL,
                    authorized_additional_calls INTEGER NOT NULL
                        CHECK(authorized_additional_calls = 1),
                    provider_call_ceiling INTEGER NOT NULL,
                    resume_iteration INTEGER NOT NULL CHECK(resume_iteration = 1),
                    resume_stage TEXT NOT NULL CHECK(resume_stage = 'critique'),
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_corrected_panel_citation_resume_consumptions (
                    extension_id TEXT PRIMARY KEY,
                    resumed_run_id TEXT NOT NULL UNIQUE,
                    resumed_input_fingerprint TEXT NOT NULL UNIQUE,
                    checkpoint_fingerprint TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    backtest_run_id TEXT,
                    critique_id TEXT,
                    baseline_result_id INTEGER NOT NULL,
                    candidate_result_id INTEGER,
                    status TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    comparison_json TEXT NOT NULL,
                    promotion_status TEXT NOT NULL DEFAULT 'awaiting_human_approval',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(run_id, draft_id)
                );
                CREATE TABLE IF NOT EXISTS ai_shadow_research_promotions (
                    promotion_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    target_stage TEXT NOT NULL CHECK(target_stage = 'paper_shadow'),
                    approved_by TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    candidate_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_runs_market_date
                    ON ai_shadow_research_runs(market_date DESC, updated_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_shadow_one_run_per_market_date
                    ON ai_shadow_research_runs(market_date);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_candidates_created
                    ON ai_shadow_research_candidates(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_calls_market_date
                    ON ai_shadow_research_provider_calls(market_date, created_at);
                CREATE INDEX IF NOT EXISTS idx_ai_shadow_provider_free_partial_market_date
                    ON ai_shadow_research_provider_free_partial_resumes(
                        market_date, consumed_at
                    );
            """)
            self._init_qualification_schema(conn)
            self._ensure_run_context_columns(conn)
            self._assert_run_context_rows_valid(conn)
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS ai_shadow_run_context_insert_guard
                BEFORE INSERT ON ai_shadow_research_runs
                WHEN NEW.research_capital_mode IS NULL
                  OR NEW.research_capital_mode NOT IN
                         ('legacy_unknown', 'normalized_notional', 'account_bound')
                  OR (
                    NEW.research_capital_mode = 'legacy_unknown'
                    AND trim(COALESCE(NEW.research_context_id, '')) <> ''
                  )
                  OR (
                    NEW.research_capital_mode = 'normalized_notional'
                    AND (
                        trim(COALESCE(NEW.research_context_id, '')) = ''
                        OR trim(COALESCE(NEW.valuation_snapshot_id, '')) <> ''
                        OR NEW.ledger_cutoff_id <> 0
                    )
                  )
                  OR (
                    NEW.research_capital_mode = 'account_bound'
                    AND (
                        trim(COALESCE(NEW.research_context_id, '')) = ''
                        OR trim(COALESCE(NEW.valuation_snapshot_id, '')) = ''
                        OR NEW.ledger_cutoff_id <= 0
                        OR NEW.research_context_id <> NEW.valuation_snapshot_id
                    )
                  )
                BEGIN
                    SELECT RAISE(ABORT, 'ai shadow research run context invalid');
                END;
                CREATE TRIGGER IF NOT EXISTS ai_shadow_run_context_update_guard
                BEFORE UPDATE OF research_capital_mode, research_context_id,
                                 valuation_snapshot_id, ledger_cutoff_id
                ON ai_shadow_research_runs
                WHEN NEW.research_capital_mode IS NULL
                  OR NEW.research_capital_mode NOT IN
                         ('legacy_unknown', 'normalized_notional', 'account_bound')
                  OR (
                    NEW.research_capital_mode = 'legacy_unknown'
                    AND trim(COALESCE(NEW.research_context_id, '')) <> ''
                  )
                  OR (
                    NEW.research_capital_mode = 'normalized_notional'
                    AND (
                        trim(COALESCE(NEW.research_context_id, '')) = ''
                        OR trim(COALESCE(NEW.valuation_snapshot_id, '')) <> ''
                        OR NEW.ledger_cutoff_id <> 0
                    )
                  )
                  OR (
                    NEW.research_capital_mode = 'account_bound'
                    AND (
                        trim(COALESCE(NEW.research_context_id, '')) = ''
                        OR trim(COALESCE(NEW.valuation_snapshot_id, '')) = ''
                        OR NEW.ledger_cutoff_id <= 0
                        OR NEW.research_context_id <> NEW.valuation_snapshot_id
                    )
                  )
                BEGIN
                    SELECT RAISE(ABORT, 'ai shadow research run context invalid');
                END;
            """)
            self._init_qualification_guards(conn)

    @staticmethod
    def _init_qualification_schema(conn) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ai_shadow_research_qualification_runs (
                qualification_run_id TEXT PRIMARY KEY,
                source_run_id TEXT NOT NULL,
                market_date TEXT NOT NULL,
                source_selection_id TEXT NOT NULL,
                source_selection_fingerprint TEXT NOT NULL,
                source_backup_fingerprint TEXT NOT NULL,
                valuation_snapshot_id TEXT NOT NULL,
                valuation_snapshot_fingerprint TEXT NOT NULL,
                ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id > 0),
                ledger_fingerprint TEXT NOT NULL,
                account_evidence_reference TEXT NOT NULL,
                account_evidence_fingerprint TEXT NOT NULL,
                account_truth_source_fingerprint TEXT NOT NULL,
                account_truth_scope_fingerprint TEXT NOT NULL,
                reviewed_cost_model_reference TEXT NOT NULL,
                reviewed_fee_schedule_fingerprint TEXT NOT NULL,
                initial_cash_text TEXT NOT NULL,
                baseline_result_id INTEGER NOT NULL CHECK(baseline_result_id > 0),
                input_fingerprint TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL
                    CHECK(status IN ('running', 'blocked', 'completed', 'failed')),
                selection_json TEXT,
                selection_fingerprint TEXT,
                blockers_json TEXT NOT NULL DEFAULT '[]',
                failure_code TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_shadow_research_qualification_candidates (
                qualification_candidate_id TEXT PRIMARY KEY,
                qualification_run_id TEXT NOT NULL,
                source_candidate_id TEXT NOT NULL,
                source_draft_id TEXT NOT NULL,
                source_formula_fingerprint TEXT NOT NULL,
                qualified_formula_fingerprint TEXT NOT NULL,
                source_formula_semantic_fingerprint TEXT NOT NULL,
                qualified_formula_semantic_fingerprint TEXT NOT NULL,
                candidate_result_id INTEGER,
                comparison_json TEXT NOT NULL,
                comparison_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK(status IN ('qualified', 'blocked', 'failed')),
                recommendation TEXT NOT NULL,
                rank INTEGER NOT NULL CHECK(rank > 0),
                created_at TEXT NOT NULL,
                UNIQUE(qualification_run_id, source_candidate_id),
                UNIQUE(qualification_run_id, rank),
                UNIQUE(qualification_run_id, candidate_result_id)
            );
            CREATE TABLE IF NOT EXISTS ai_shadow_research_qualification_approvals (
                qualification_approval_id TEXT PRIMARY KEY,
                qualification_run_id TEXT NOT NULL,
                qualification_candidate_id TEXT NOT NULL UNIQUE,
                target_stage TEXT NOT NULL CHECK(target_stage = 'paper_shadow'),
                approved_by TEXT NOT NULL,
                notes TEXT NOT NULL,
                confirmation TEXT NOT NULL CHECK(
                    confirmation =
                    'approve_exact_account_qualified_candidate_for_paper_shadow_only_without_order_trade_or_capital_authority'
                ),
                qualification_candidate_fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_shadow_qualification_source
                ON ai_shadow_research_qualification_runs(
                    source_run_id, created_at DESC
                );
            CREATE INDEX IF NOT EXISTS idx_ai_shadow_qualification_date
                ON ai_shadow_research_qualification_runs(
                    market_date DESC, updated_at DESC
                );
            CREATE INDEX IF NOT EXISTS idx_ai_shadow_qualification_candidates
                ON ai_shadow_research_qualification_candidates(
                    qualification_run_id, rank
                );
        """)

    @staticmethod
    def _init_qualification_guards(conn) -> None:
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_run_update_guard
            BEFORE UPDATE ON ai_shadow_research_qualification_runs
            WHEN OLD.status <> 'running'
              OR NEW.status NOT IN ('blocked', 'completed', 'failed')
              OR OLD.qualification_run_id IS NOT NEW.qualification_run_id
              OR OLD.source_run_id IS NOT NEW.source_run_id
              OR OLD.market_date IS NOT NEW.market_date
              OR OLD.source_selection_id IS NOT NEW.source_selection_id
              OR OLD.source_selection_fingerprint
                 IS NOT NEW.source_selection_fingerprint
              OR OLD.source_backup_fingerprint IS NOT NEW.source_backup_fingerprint
              OR OLD.valuation_snapshot_id IS NOT NEW.valuation_snapshot_id
              OR OLD.valuation_snapshot_fingerprint
                 IS NOT NEW.valuation_snapshot_fingerprint
              OR OLD.ledger_cutoff_id IS NOT NEW.ledger_cutoff_id
              OR OLD.ledger_fingerprint IS NOT NEW.ledger_fingerprint
              OR OLD.account_evidence_reference
                 IS NOT NEW.account_evidence_reference
              OR OLD.account_evidence_fingerprint
                 IS NOT NEW.account_evidence_fingerprint
              OR OLD.account_truth_source_fingerprint
                 IS NOT NEW.account_truth_source_fingerprint
              OR OLD.account_truth_scope_fingerprint
                 IS NOT NEW.account_truth_scope_fingerprint
              OR OLD.reviewed_cost_model_reference
                 IS NOT NEW.reviewed_cost_model_reference
              OR OLD.reviewed_fee_schedule_fingerprint
                 IS NOT NEW.reviewed_fee_schedule_fingerprint
              OR OLD.initial_cash_text IS NOT NEW.initial_cash_text
              OR OLD.baseline_result_id IS NOT NEW.baseline_result_id
              OR OLD.input_fingerprint IS NOT NEW.input_fingerprint
              OR NEW.selection_json IS NULL
              OR trim(COALESCE(NEW.selection_fingerprint, '')) = ''
              OR (NEW.status = 'completed' AND (
                    NEW.blockers_json <> '[]'
                    OR trim(COALESCE(NEW.failure_code, '')) <> ''
              ))
              OR (NEW.status = 'blocked' AND NEW.blockers_json = '[]')
              OR (NEW.status = 'failed' AND
                    trim(COALESCE(NEW.failure_code, '')) = '')
            BEGIN
                SELECT RAISE(ABORT, 'qualification run transition invalid');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_run_delete_guard
            BEFORE DELETE ON ai_shadow_research_qualification_runs
            BEGIN
                SELECT RAISE(ABORT, 'qualification run is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_candidate_insert_guard
            BEFORE INSERT ON ai_shadow_research_qualification_candidates
            WHEN NEW.source_formula_semantic_fingerprint
                     <> NEW.qualified_formula_semantic_fingerprint
              OR NOT EXISTS (
                    SELECT 1
                    FROM ai_shadow_research_qualification_runs AS q
                    JOIN ai_shadow_research_candidates AS c
                      ON c.run_id = q.source_run_id
                    WHERE q.qualification_run_id = NEW.qualification_run_id
                      AND q.status = 'running'
                      AND c.candidate_id = NEW.source_candidate_id
                      AND c.draft_id = NEW.source_draft_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'qualification candidate binding invalid');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_candidate_update_guard
            BEFORE UPDATE ON ai_shadow_research_qualification_candidates
            BEGIN
                SELECT RAISE(ABORT, 'qualification candidate is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_candidate_delete_guard
            BEFORE DELETE ON ai_shadow_research_qualification_candidates
            BEGIN
                SELECT RAISE(ABORT, 'qualification candidate is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_approval_insert_guard
            BEFORE INSERT ON ai_shadow_research_qualification_approvals
            WHEN NOT EXISTS (
                SELECT 1
                FROM ai_shadow_research_qualification_candidates AS c
                JOIN ai_shadow_research_qualification_runs AS q
                  ON q.qualification_run_id = c.qualification_run_id
                WHERE c.qualification_candidate_id = NEW.qualification_candidate_id
                  AND c.qualification_run_id = NEW.qualification_run_id
                  AND c.status = 'qualified'
                  AND c.recommendation = 'paper_shadow_review'
                  AND q.status = 'completed'
            )
            BEGIN
                SELECT RAISE(ABORT, 'qualification approval binding invalid');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_approval_update_guard
            BEFORE UPDATE ON ai_shadow_research_qualification_approvals
            BEGIN
                SELECT RAISE(ABORT, 'qualification approval is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS ai_shadow_qualification_approval_delete_guard
            BEFORE DELETE ON ai_shadow_research_qualification_approvals
            BEGIN
                SELECT RAISE(ABORT, 'qualification approval is append-only');
            END;
        """)

    @staticmethod
    def _ensure_run_context_columns(conn) -> None:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(ai_shadow_research_runs)")
        }
        if "research_capital_mode" not in columns:
            conn.execute("""
                ALTER TABLE ai_shadow_research_runs
                ADD COLUMN research_capital_mode TEXT NOT NULL
                    DEFAULT 'legacy_unknown'
                    CHECK(research_capital_mode IN
                          ('legacy_unknown', 'normalized_notional', 'account_bound'))
                """)
        if "research_context_id" not in columns:
            conn.execute("""
                ALTER TABLE ai_shadow_research_runs
                ADD COLUMN research_context_id TEXT
                """)

    @staticmethod
    def _assert_run_context_rows_valid(conn) -> None:
        invalid = conn.execute("""
            SELECT run_id
            FROM ai_shadow_research_runs
            WHERE research_capital_mode IS NULL
               OR research_capital_mode NOT IN
                      ('legacy_unknown', 'normalized_notional', 'account_bound')
               OR (
                    research_capital_mode = 'legacy_unknown'
                    AND trim(COALESCE(research_context_id, '')) <> ''
               )
               OR (
                    research_capital_mode = 'normalized_notional'
                    AND (
                        trim(COALESCE(research_context_id, '')) = ''
                        OR trim(COALESCE(valuation_snapshot_id, '')) <> ''
                        OR ledger_cutoff_id <> 0
                    )
               )
               OR (
                    research_capital_mode = 'account_bound'
                    AND (
                        trim(COALESCE(research_context_id, '')) = ''
                        OR trim(COALESCE(valuation_snapshot_id, '')) = ''
                        OR ledger_cutoff_id <= 0
                        OR research_context_id <> valuation_snapshot_id
                    )
               )
            LIMIT 1
            """).fetchone()
        if invalid is not None:
            raise RuntimeError("ai shadow research run context migration invalid")
