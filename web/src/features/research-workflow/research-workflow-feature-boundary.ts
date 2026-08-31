/** Explicit evidence ports consumed by the research workflow feature. */
export type StrategyHypothesisBacktestEvidence = {
  id: number;
  config: {
    start_date: string;
    end_date: string;
    initial_cash: number;
    assets?: Array<{ symbol: string; asset_class: string }> | null;
  };
  metrics_json?: {
    dataset_snapshot?: {
      snapshot_id: string;
      data_quality: { status: string };
    };
    fee_component_evidence?: {
      status?: string;
      cost_model_reference?: string;
      account_specific?: boolean;
      broker_statement_reconciled?: boolean;
    };
  };
};
