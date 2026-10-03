export type ChronologicalSweepValidation = {
  role?: 'training' | 'test';
  schema_version: 'karkinos.chronological_sweep.v1';
  experiment_id: string;
  source_dataset_id: string;
  test_start_date: string;
  rank_by: string;
  selection_basis: 'training_only';
  selected_params: Record<string, unknown>;
  selected_training_result_id?: number;
  training_result_ids: number[];
  tested_count: number;
  exploratory: true;
  independent_final: false;
  fingerprint: string;
  limitations: string[];
};

export type BacktestExecutionWindow = {
  schema_version: 'karkinos.backtest_execution_window.v1';
  source_dataset_id: string;
  source_snapshot_id: string;
  source_start_date: string;
  source_end_date: string;
  history_end_date: string;
  evaluation_start_date: string;
  evaluation_end_date: string;
  metric_start_date: string;
  metric_end_date: string;
  warmup_policy: 'strategy_state_only_no_orders_or_book_carry';
  independent_initial_cash: true;
  exploratory: true;
  independent_final: false;
  fingerprint: string;
};
