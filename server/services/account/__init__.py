"""Account truth, valuation and capital domain package.

High-cohesion domain package owning:
- fees: Fee schedules, commissions, reconciliation, and policy (`server.services.account.fees`)
- state: Canonical account state and overview projections
- permissions: Broker board access resolution and policy freezing
- valuation: Application boundary for valuation projections
- performance: Deterministic daily performance attribution primitives
- strategy: Account-strategy assignment, evidence linking, and attribution projections
- replay: Replay evidence for historical Account Truth bindings
- roll_forward: Guardrails for snapshot roll-forward
- session_truth: Source-rechecked Account Truth evidence for session start
- paper_shadow: Simulation orchestration for account plans
"""

from __future__ import annotations

from server.services.account import reviewed_fee_schedule as reviewed_fee_schedule
from server.services.account.paper_shadow import orchestrate_account_paper_shadow
from server.services.account.performance import (
    AccountDailyPerformance,
    DailySellLot,
    DailyTradeLot,
    PositionDailyContext,
    PositionDailyMark,
    build_position_daily_context,
    calculate_account_daily_performance,
    mark_position_daily,
    price_at_tick,
)
from server.services.account.permissions import (
    BOARD_NAMES,
    BOARD_PERMISSION_REVIEW_DAYS,
    BOARD_PERMISSION_SOURCE,
    entry_board_policy_blocker,
    entry_board_policy_symbols,
    freeze_entry_board_policy,
    resolve_board_buy_permissions,
    validate_entry_board_policy,
)
from server.services.account.replay import (
    ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION,
    build_account_truth_replay_evidence,
)
from server.services.account.roll_forward import (
    roll_forward_daily_broker_statement_for_state,
)
from server.services.account.session_truth import (
    SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE,
    SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE,
    SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
    SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS,
    SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION,
    SESSION_START_ACCOUNT_TRUTH_STATUS_SCHEMA_VERSION,
    SessionStartAccountTruthRejected,
    SessionStartAccountTruthService,
)
from server.services.account.state import (
    AccountStateProjection,
    build_account_state_projection,
    build_overview_state,
    read_overview_refresh_health,
)
from server.services.account.strategy import (
    ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY,
    ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION,
    account_strategy_assignment_from_payload,
    assignment_matches_signal,
    build_attribution_summary,
    build_contribution_report,
    default_account_strategy_assignment,
    fill_metadata,
    is_simulation_order,
    json_dict,
    linked_strategy_evidence,
    order_source_signal_id,
    same_symbol,
    source_signal_id,
)
from server.services.account.valuation import (
    VALUATION_POLICY_VERSION,
    build_current_valuation_snapshot,
    is_asset_class_valuation_healthy,
    ledger_identity_from_rows,
    load_persisted_quote_rows,
    portfolio_equity_from_valuation,
    require_valuation_recovery_clear,
    select_latest_observation_rows,
    validate_valuation_snapshot,
    valuation_identity_fields,
    valuation_lane_status,
    valuation_snapshot_from_row,
)

__all__ = [
    "ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY",
    "ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION",
    "ACCOUNT_TRUTH_REPLAY_EVIDENCE_SCHEMA_VERSION",
    "AccountDailyPerformance",
    "AccountStateProjection",
    "BOARD_NAMES",
    "BOARD_PERMISSION_REVIEW_DAYS",
    "BOARD_PERMISSION_SOURCE",
    "DailySellLot",
    "DailyTradeLot",
    "PositionDailyContext",
    "PositionDailyMark",
    "SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT",
    "SESSION_START_ACCOUNT_TRUTH_ENTITY_TYPE",
    "SESSION_START_ACCOUNT_TRUTH_EVENT_SOURCE",
    "SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE",
    "SESSION_START_ACCOUNT_TRUTH_MAX_AGE_SECONDS",
    "SESSION_START_ACCOUNT_TRUTH_SCHEMA_VERSION",
    "SESSION_START_ACCOUNT_TRUTH_STATUS_SCHEMA_VERSION",
    "SessionStartAccountTruthRejected",
    "SessionStartAccountTruthService",
    "VALUATION_POLICY_VERSION",
    "account_strategy_assignment_from_payload",
    "assignment_matches_signal",
    "build_account_state_projection",
    "build_account_truth_replay_evidence",
    "build_attribution_summary",
    "build_contribution_report",
    "build_current_valuation_snapshot",
    "build_overview_state",
    "build_position_daily_context",
    "calculate_account_daily_performance",
    "default_account_strategy_assignment",
    "entry_board_policy_blocker",
    "entry_board_policy_symbols",
    "fill_metadata",
    "freeze_entry_board_policy",
    "is_asset_class_valuation_healthy",
    "is_simulation_order",
    "json_dict",
    "ledger_identity_from_rows",
    "linked_strategy_evidence",
    "load_persisted_quote_rows",
    "mark_position_daily",
    "order_source_signal_id",
    "orchestrate_account_paper_shadow",
    "portfolio_equity_from_valuation",
    "price_at_tick",
    "read_overview_refresh_health",
    "require_valuation_recovery_clear",
    "resolve_board_buy_permissions",
    "roll_forward_daily_broker_statement_for_state",
    "same_symbol",
    "select_latest_observation_rows",
    "source_signal_id",
    "validate_entry_board_policy",
    "validate_valuation_snapshot",
    "valuation_identity_fields",
    "valuation_lane_status",
    "valuation_snapshot_from_row",
]
