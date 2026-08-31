import { useCopy } from '../../../shared/i18n/context';
import type {
  AccountStrategyAttributionSummary,
  AccountStrategyContributionReport,
  BacktestReport,
  BacktestRunRequest,
  BacktestStrategyInfo,
  StrategyParameterSchema,
} from '../api';

export function todayDate() {
  return new Date().toISOString().slice(0, 10);
}

export const fallbackStrategies: BacktestStrategyInfo[] = [
  {
    strategy_id: 'dual_ma',
    name: 'dual_ma',
    display_name: 'Dual Moving Average',
    description: 'Dual moving-average crossover baseline.',
    source_type: 'builtin',
    is_extension: false,
    params: [],
    parameter_schema: [
      {
        name: 'short_period',
        type: 'int',
        default: 5,
        required: false,
        min: 1,
        max: 250,
        allowed_values: null,
        description: 'Short moving-average window in trading bars.',
      },
      {
        name: 'long_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Long moving-average window in trading bars.',
      },
    ],
  },
];

export function buildSingleAsset(
  symbol: string,
  assetClass: string,
): BacktestRunRequest['assets'] {
  const normalized = symbol.trim();
  if (!normalized) {
    return undefined;
  }
  return [{ symbol: normalized, asset_class: assetClass }];
}

const allowedBacktestAssetClasses = new Set([
  'stock',
  'etf',
  'fund',
  'gold',
  'bond',
]);

export function readBacktestSearchDefaults(search: string) {
  const params = new URLSearchParams(search);
  const symbol = params.get('symbol')?.trim() ?? '';
  const hasAssetClassParam =
    params.has('assetClass') || params.has('asset_class');
  const rawAssetClass =
    params.get('assetClass')?.trim() ?? params.get('asset_class')?.trim() ?? '';
  const strategy = params.get('strategy')?.trim() ?? '';
  const source = params.get('source')?.trim() ?? '';
  return {
    symbol,
    assetClass: allowedBacktestAssetClasses.has(rawAssetClass)
      ? rawAssetClass
      : 'stock',
    strategy: strategy || 'dual_ma',
    handoffSource: source === 'portfolio' ? 'portfolio' : 'decision',
    hasHandoffContext:
      Boolean(symbol) || hasAssetClassParam || Boolean(strategy),
  };
}

export function currentBacktestSearchDefaults() {
  if (typeof window === 'undefined') {
    return {
      symbol: '',
      assetClass: 'stock',
      strategy: 'dual_ma',
      handoffSource: 'decision',
      hasHandoffContext: false,
    };
  }
  return readBacktestSearchDefaults(window.location.search);
}

export function isPositiveNumber(value: string) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0;
}

export function schemaDefaultValue(param: StrategyParameterSchema) {
  if (param.default === null || param.default === undefined) {
    return '';
  }
  if (typeof param.default === 'object') {
    return JSON.stringify(param.default);
  }
  return String(param.default);
}

export function parseParamValue(param: StrategyParameterSchema, value: string) {
  if (value.trim() === '') {
    return null;
  }
  if (param.type === 'int') {
    return Number.parseInt(value, 10);
  }
  if (param.type === 'float') {
    return Number(value);
  }
  if (param.type === 'bool') {
    return value === 'true';
  }
  return value;
}

export function buildParamValues(
  schema: StrategyParameterSchema[],
): Record<string, string> {
  return Object.fromEntries(
    schema.map((param) => [param.name, schemaDefaultValue(param)]),
  );
}

export function strategyDescription(
  strategy: BacktestStrategyInfo,
  localizedDescriptions: Record<string, string>,
) {
  return (
    localizedDescriptions[strategy.name] ??
    localizedDescriptions[strategy.strategy_id] ??
    strategy.description
  );
}

export function strategySourceDisplayName(
  strategy: BacktestStrategyInfo,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  return strategy.is_extension || strategy.source_type === 'extension'
    ? labels.strategySourceExtension
    : labels.strategySourceBuiltin;
}

export function benchmarkRoleDisplayName(
  role: string | null | undefined,
  localizedRoles: Record<string, string>,
  fallback: string,
) {
  if (!role) {
    return fallback;
  }
  return localizedRoles[role] ?? role;
}

export function humanizeParameterName(name: string) {
  return name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function parameterDisplayName(
  param: StrategyParameterSchema,
  localizedNames?: Record<string, string>,
) {
  return localizedNames?.[param.name] ?? humanizeParameterName(param.name);
}

export function parameterDescription(
  param: StrategyParameterSchema,
  localizedDescriptions?: Record<string, string>,
) {
  return localizedDescriptions?.[param.name] ?? param.description;
}

export function buildRunPayload({
  startDate,
  endDate,
  initialCash,
  strategy,
  parameterSchema,
  parameterValues,
  symbol,
  assetClass,
}: {
  startDate: string;
  endDate: string;
  initialCash: string;
  strategy: string;
  parameterSchema: StrategyParameterSchema[];
  parameterValues: Record<string, string>;
  symbol: string;
  assetClass: string;
}): BacktestRunRequest {
  const params = Object.fromEntries(
    parameterSchema.map((param) => [
      param.name,
      parseParamValue(param, parameterValues[param.name] ?? ''),
    ]),
  );
  const shortPeriod = params.short_period;
  const longPeriod = params.long_period;
  return {
    start_date: startDate,
    end_date: endDate,
    initial_cash: Number(initialCash),
    strategy: strategy.trim() || 'dual_ma',
    ...(typeof shortPeriod === 'number' ? { short_period: shortPeriod } : {}),
    ...(typeof longPeriod === 'number' ? { long_period: longPeriod } : {}),
    params,
    assets: buildSingleAsset(symbol, assetClass),
  };
}

export function resultSummary(report: BacktestReport | null) {
  if (!report) {
    return null;
  }
  const metrics = { ...report.metrics, ...report.metrics_json };
  const costs = report.cost_summary_json ?? {};
  return {
    returnValue: metrics.total_return,
    drawdown: metrics.max_drawdown,
    trades:
      costs.total_trades ?? metrics.total_trades ?? report.fills?.length ?? 0,
    cost:
      (costs.total_commission ?? metrics.total_commission ?? 0) +
      (costs.total_slippage ?? metrics.total_slippage ?? 0),
  };
}

export type LoopStepState = 'ready' | 'waiting' | 'blocked';

export type LoopStep = {
  key: string;
  label: string;
  state: LoopStepState;
  evidenceHref: string;
  evidenceLabel: string;
};

export function hasDatasetSnapshotEvidence(report: BacktestReport) {
  return Boolean(report.metrics_json?.dataset_snapshot?.snapshot_id);
}

export function hasAfterCostEvidence(report: BacktestReport) {
  return Boolean(
    report.evidence_json ||
    report.metrics_json?.evidence_bundle ||
    report.cost_summary_json,
  );
}

export function formatGateScore(score: number | null) {
  return score === null ? '--' : String(score);
}

export function lookupLabel<T extends Record<string, string>>(
  labels: T,
  key: string,
  fallback: string,
) {
  return labels[key] ?? fallback;
}

export function accountStrategyPnlAttributionTier(
  attribution: AccountStrategyAttributionSummary | null,
  contribution: AccountStrategyContributionReport | null,
) {
  const attributionStatus = attribution?.attribution_status ?? 'not_started';
  const contributionStatus =
    contribution?.contribution_status ?? 'no_linked_fills';
  const linkedEvidenceCount =
    (attribution?.signal_count ?? 0) +
    (attribution?.action_count ?? 0) +
    (attribution?.risk_decision_count ?? 0) +
    (attribution?.order_count ?? 0) +
    (attribution?.fill_count ?? 0) +
    (contribution?.linked_fill_count ?? 0);
  const hasMissingValuation =
    contributionStatus === 'valuation_missing' ||
    contributionStatus === 'valuation_snapshot_missing' ||
    Boolean(contribution?.missing_valuation_symbols.length);
  const hasBoundContribution =
    contributionStatus === 'evidence_bound_from_posted_fills' &&
    contribution?.evidence_binding_status === 'bound' &&
    Boolean(contribution.valuation_snapshot_id) &&
    (contribution.ledger_cutoff_id ?? 0) > 0 &&
    Boolean(contribution.contribution_fingerprint);
  const hasBlockingEvidenceStatus = [
    'ledger_posting_pending',
    'ledger_evidence_drift',
    'valuation_snapshot_invalid',
    'valuation_identity_drift',
    'inventory_lineage_incomplete',
  ].includes(contributionStatus);

  if (
    attributionStatus === 'blocked' ||
    attributionStatus === 'failed' ||
    contributionStatus === 'blocked' ||
    contributionStatus === 'failed' ||
    hasBlockingEvidenceStatus
  ) {
    return 'blocked';
  }
  if (hasMissingValuation) {
    return 'stale';
  }
  if (hasBoundContribution) {
    return 'complete';
  }
  if (
    contributionStatus === 'no_linked_fills' ||
    (linkedEvidenceCount === 0 &&
      ['not_started', 'assignment_only'].includes(attributionStatus))
  ) {
    return 'not_started';
  }
  return 'partial';
}
