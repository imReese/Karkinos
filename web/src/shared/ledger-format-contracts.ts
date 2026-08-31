export type PublicLedgerEntry = {
  id?: number;
  entry_type: string;
  timestamp?: string | null;
  amount?: number | null;
  symbol?: string | null;
  display_name?: string | null;
  direction?: string | null;
  quantity?: number | null;
  price?: number | null;
  commission?: number | null;
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  cost_basis_method?: string | null;
  asset_class?: string | null;
  note?: string | null;
  source?: string | null;
  source_ref?: string | null;
  created_at?: string | null;
};

export type LedgerSummaryKind =
  | 'trade_buy'
  | 'trade_sell'
  | 'cash_deposit'
  | 'cash_withdrawal'
  | 'cash_interest'
  | 'dividend'
  | 'manual_adjustment'
  | 'other';

export type LedgerEntrySummary = {
  kind: LedgerSummaryKind;
  grossAmount: number | null;
  cashImpact: number | null;
};

export type LedgerActivitySummaryTone =
  'credit' | 'debit' | 'adjustment' | 'neutral';

export type LedgerActivitySummary = {
  label: string;
  shortLabel: string;
  amount: string;
  cashImpactLabel: string;
  tone: LedgerActivitySummaryTone;
};

export type LedgerDashboardPresentation = {
  title: string;
  details: string[];
  amount: string;
  publicNote: string | null;
};

export type LedgerExecutionDetailLabels = {
  amount: string;
  grossAmount: string;
  netCashImpact: string;
  quantity: string;
  price: string;
  fee: string;
  commission: string;
  stampTax: string;
  transferFee: string;
  otherFees: string;
  costBasis: string;
};

export type LedgerExecutionDetailLine = {
  label: string;
  value: string;
};

export type LedgerExplainabilityItem = {
  kind?: string;
  title?: string;
  detail?: string;
  timestamp?: string;
  symbol?: string | null;
  amount?: number | null;
  quantity?: number | null;
  price?: number | null;
  commission?: number | null;
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  asset_class?: string | null;
};
