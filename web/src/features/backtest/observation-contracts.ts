export type ObservationPublication = {
  id: string;
  decision_session: string;
  published_at: string;
  dataset_id: string;
  payload: {
    forecasts: {
      symbol: string;
      instrument_type: string;
      action: 'enter' | 'exit' | 'hold';
    }[];
    previous_target_weights: Record<string, string>;
    target_weights: Record<string, string>;
    rebalance_weight_deltas: Record<string, string>;
    risk_decision: { status: 'allowed' | 'blocked'; reasons: string[] };
    reference_session: string;
    end_session: string;
    horizon_sessions: number;
  };
};

export type ObservationOutcome = {
  publication_id: string;
  horizon: number;
  measured_at: string;
  dataset_id: string;
  payload: {
    status: 'measured' | 'unavailable';
    weighted_price_response: string | null;
    return_basis: string;
    corporate_action_evidence?: unknown;
    observations: {
      symbol: string;
      target_weight: string;
      price_return: string;
      weighted_price_response: string;
    }[];
  };
};

export type ObservationHealthPolicy = {
  mode: 'observe_only' | 'pause_on_breach';
  window_intervals: number;
  minimum_eligible_intervals: number;
  minimum_mean_relative_price_response: string;
  policy_id?: string;
  metric?: string;
  comparison?: string;
  interval_selection?: string;
};

export type ObservationHealthDecision = {
  policy_id: string;
  status:
    | 'not_configured'
    | 'waiting'
    | 'insufficient_evidence'
    | 'within_rule'
    | 'threshold_breached'
    | 'unavailable';
  action: 'none' | 'pause_observation';
  evaluated_at: string | null;
  market_as_of: string | null;
  data_available: boolean;
  counts: {
    scheduled_matured: number;
    pending: number;
    missing_matured: number;
    zero_exposure: number;
    corporate_action_excluded: number;
    unresolved: number;
    eligible: number;
  };
  mean_relative_price_response: string | null;
  threshold: string | null;
  selected_publication_ids: string[];
  input_fingerprint: string | null;
  source_fingerprint?: string;
  code_fingerprint?: string;
  policy_fingerprint?: string;
  observation_id?: string;
  input_version?: number;
  decision_actor?: 'configured_rule';
  blockers: string[];
  limitations: string[];
  return_basis: 'unadjusted_price_only';
};

export type ResearchObservation = {
  id: string;
  source_backtest_result_id: number;
  lifecycle: 'active' | 'paused';
  version: number;
  started_at: string;
  last_blocker: { code: string } | null;
  source: {
    strategy_kind: string;
    start_date: string;
    dataset_id: string;
    source_code_verified: boolean;
    source_historical_pit_verified: boolean;
  };
  universe: { symbol: string; instrument_type: string }[];
  policy: {
    horizon_sessions: number;
    max_symbol_weight: string;
    max_gross_weight: string;
    health_policy?: ObservationHealthPolicy | null;
  };
  health_decision?: ObservationHealthDecision | null;
  automation?: ObservationAutomation | null;
  publications: ObservationPublication[];
  outcomes: ObservationOutcome[];
};

export type ObservationAutomation = {
  observation_id: string;
  enabled: boolean;
  generation: string | null;
  status: 'disabled' | 'paused' | 'waiting' | 'ready' | 'completed' | 'blocked';
  last_checked_at: string | null;
  last_attempt_at: string | null;
  last_blocker: { code: string } | null;
  dataset_id: string | null;
  decision_session: string | null;
  unreadable_candidate_dataset_ids?: string[];
  dataset_discovery_complete?: boolean | null;
};

export type StartObservation = {
  request_id: string;
  source_backtest_result_id: number;
  horizon_sessions: number;
  max_symbol_weight: string;
  max_gross_weight: string;
  health_policy?: ObservationHealthPolicy | null;
};

export type ObservationCommand =
  | { kind: 'start'; payload: StartObservation }
  | {
      kind: 'advance';
      id: string;
      payload: {
        request_id: string;
        expected_version: number;
        dataset_id: string;
      };
    }
  | {
      kind: 'pause';
      id: string;
      payload: { request_id: string; expected_version: number };
    };
