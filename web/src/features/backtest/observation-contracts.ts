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
  };
  publications: ObservationPublication[];
  outcomes: ObservationOutcome[];
};

export type StartObservation = {
  request_id: string;
  source_backtest_result_id: number;
  horizon_sessions: number;
  max_symbol_weight: string;
  max_gross_weight: string;
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
