import { type StatusTone } from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { type Locale } from '../../../shared/preferences/context';
import { formatCurrency } from '../../../shared/format';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  formatStrategyDisplayName,
  type StrategyNameMap,
} from '../../../shared/strategy-display';
import {
  type PaperShadowCostSummary,
  type PaperShadowDivergenceSummary,
} from '../decision-feature-boundary';
import {
  type AccountTruthGateEvidence,
  type DecisionCandidate,
  type StrategyAttributionGateEvidence,
} from '../api';

export function normalizeStatus(
  value: string | null | undefined,
  locale: Locale,
) {
  return formatPublicStatus(value ?? 'unknown', locale);
}

type DecisionTone = Exclude<StatusTone, 'info'>;

export function decisionTone(value: string): DecisionTone {
  if (
    value === 'pass' ||
    value === 'passed' ||
    value === 'attached' ||
    value === 'live'
  ) {
    return 'success';
  }
  if (
    value === 'blocked' ||
    value === 'failed' ||
    value === 'missing' ||
    value === 'not_attached'
  ) {
    return 'danger';
  }
  return 'warning';
}

export function evidenceStatus(candidate: DecisionCandidate) {
  return candidate.evidence.after_cost_oos_validation.status;
}

export function manualStatus(candidate: DecisionCandidate, locale: Locale) {
  if (
    candidate.manual_confirmation_status === 'ready_for_manual_confirmation'
  ) {
    return formatPublicStatus(candidate.manual_confirmation_status, locale);
  }
  return normalizeStatus(candidate.manual_confirmation_status, locale);
}

export function accountTruthScore(
  value: AccountTruthGateEvidence | null | undefined,
) {
  if (value?.score === null || value?.score === undefined) {
    return '--';
  }
  return String(value.score);
}

export function accountTruthValue(
  value: AccountTruthGateEvidence | null | undefined,
  locale: Locale,
) {
  const status = value?.gate_status ?? 'not_evaluated';
  return `${normalizeStatus(status, locale)} · ${accountTruthScore(value)}`;
}

export function accountTruthTone(
  value: AccountTruthGateEvidence | null | undefined,
) {
  const status = value?.gate_status ?? 'not_evaluated';
  return decisionTone(status);
}

export function strategyAttributionValue(
  value: StrategyAttributionGateEvidence | null | undefined,
  locale: Locale,
  strategyNames: StrategyNameMap,
) {
  const status = value?.gate_status ?? 'not_configured';
  const strategyLabel = value?.strategy_id
    ? formatStrategyDisplayName(
        { strategy_id: value.strategy_id },
        strategyNames,
      )
    : '--';
  return `${normalizeStatus(status, locale)} · ${strategyLabel}`;
}

export function strategyAttributionAuditId(
  value: StrategyAttributionGateEvidence | null | undefined,
  strategyNames: StrategyNameMap,
) {
  if (!value?.strategy_id) {
    return null;
  }
  const strategyLabel = formatStrategyDisplayName(
    { strategy_id: value.strategy_id },
    strategyNames,
  );
  return strategyLabel === value.strategy_id ? null : value.strategy_id;
}

export function strategyDisplayNameFromId(
  strategyId: string | null | undefined,
  strategyNames: StrategyNameMap,
) {
  return formatStrategyDisplayName({ strategy_id: strategyId }, strategyNames);
}

export function strategyAuditIdFromDisplay(
  strategyId: string | null | undefined,
  strategyNames: StrategyNameMap,
) {
  const normalized = strategyId?.trim();
  if (!normalized) {
    return null;
  }
  const strategyLabel = strategyDisplayNameFromId(normalized, strategyNames);
  return strategyLabel === normalized ? null : normalized;
}

export function strategyAttributionTone(
  value: StrategyAttributionGateEvidence | null | undefined,
) {
  const status = value?.gate_status ?? 'not_configured';
  return status === 'not_configured' ? 'neutral' : decisionTone(status);
}

export type DecisionCopy = ReturnType<typeof useCopy>['decision'];
export type BacktestPageCopy = ReturnType<typeof useCopy>['backtest']['page'];

export type CandidateEvidenceChainItem = {
  label: string;
  value: string;
  tone?: 'success' | 'warning' | 'danger' | 'neutral';
};

export function numericEvidenceValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function nullableCurrency(value: unknown) {
  return formatCurrency(numericEvidenceValue(value));
}

export function numericCostSummaryValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function paperShadowCostSummaryItems(
  costSummary: PaperShadowCostSummary | undefined,
  locale: Locale,
) {
  if (!costSummary) {
    return [];
  }
  const labels =
    locale === 'zh'
      ? {
          estimatedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          simulatedSlippage: '模拟滑点',
          simulatedTotal: '模拟总成本',
          feeRules: '费用规则',
        }
      : {
          estimatedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          simulatedSlippage: 'Sim slippage',
          simulatedTotal: 'Sim total cost',
          feeRules: 'Fee rules',
        };
  const feeRuleIds = (costSummary.fee_rule_ids ?? [])
    .map((item) => String(item).trim())
    .filter(Boolean);
  return [
    {
      label: labels.estimatedFee,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.estimated_total_fee),
      ),
    },
    {
      label: labels.simulatedFeeTax,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.simulated_fee_tax_cost),
      ),
    },
    {
      label: labels.simulatedSlippage,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.simulated_slippage_cost),
      ),
    },
    {
      label: labels.simulatedTotal,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.simulated_total_execution_cost),
      ),
    },
    feeRuleIds.length
      ? {
          label: labels.feeRules,
          value: feeRuleIds.join(' / '),
        }
      : null,
  ].filter((item): item is { label: string; value: string } => item !== null);
}

export type PaperShadowDivergenceEvidenceBlock = {
  title: string;
  items: string[];
};

export type BrokerTradeCostEvidence = {
  eventCountLabel: string;
  items: Array<{ label: string; value: string }>;
  safetyLabels: string[];
};

export type ManualExecutionEvidence = {
  eventCountLabel: string;
  fingerprint: string;
  items: Array<{ label: string; value: string }>;
  safetyLabels: string[];
};

export type ManualBrokerComparisonEvidence = {
  statusLabel: string;
  items: Array<{
    label: string;
    manualValue: string;
    brokerValue: string;
    isMismatch: boolean;
  }>;
  safetyLabels: string[];
};

export function objectRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatPaperShadowCountKey(value: string, locale: Locale) {
  const normalized = value.trim();
  if (!normalized) {
    return '--';
  }
  return normalized
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .toLocaleLowerCase(locale);
}

export function formatPaperShadowCountMap(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  const items = Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(
      ([key, value]) => `${formatPaperShadowCountKey(key, locale)}: ${value}`,
    );
  return items.join(locale === 'zh' ? '；' : '; ');
}

export function formatPaperShadowStatusCountMap(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  const items = Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([key, value]) => `${formatPublicStatus(key, locale)}: ${value}`);
  return items.join(locale === 'zh' ? '；' : '; ');
}

export function formatPaperShadowValueMap(
  values: Record<string, number | string> | undefined,
) {
  const items = Object.entries(values ?? {})
    .map(([key, value]) => `${key}: ${String(value).trim()}`)
    .filter((value) => value.trim().length > 0);
  return items.join('; ');
}

export function formatPaperShadowRefs(
  values: string[] | undefined,
  locale: Locale,
) {
  return (values ?? [])
    .map((value) => formatPublicEvidenceReference(value, locale))
    .filter((value) => value.trim().length > 0)
    .join(locale === 'zh' ? '；' : '; ');
}

function formatPaperShadowCurrencyList(
  values: Array<number | string> | undefined,
) {
  return (values ?? [])
    .map((value) => formatCurrency(numericCostSummaryValue(value)))
    .filter((value) => value !== '--')
    .join(', ');
}

export function paperShadowMarketContextItems(
  summary: PaperShadowDivergenceSummary,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          symbolCount: '标的数',
          priceBasis: '价格依据',
          expected: '预期',
          fills: '成交',
          slippage: '滑点',
        }
      : {
          symbolCount: 'Symbols',
          priceBasis: 'Price basis',
          expected: 'expected',
          fills: 'fills',
          slippage: 'slippage',
        };
  const context = summary.realized_market_context;
  const priceBasis = formatPaperShadowCountMap(
    context?.price_basis_counts,
    locale,
  );
  return [
    typeof context?.symbol_count === 'number'
      ? `${labels.symbolCount}: ${context.symbol_count}`
      : '',
    priceBasis ? `${labels.priceBasis}: ${priceBasis}` : '',
    ...(context?.symbols ?? []).map((item) => {
      const symbol = item.symbol?.trim() || '--';
      const expected = formatCurrency(
        numericCostSummaryValue(item.expected_price),
      );
      const fills = formatPaperShadowCurrencyList(item.simulated_fill_prices);
      const slippage = formatCurrency(
        numericCostSummaryValue(item.simulated_slippage_cost),
      );
      return [
        symbol,
        expected !== '--' ? `${labels.expected} ${expected}` : '',
        fills ? `${labels.fills} ${fills}` : '',
        slippage !== '--' ? `${labels.slippage} ${slippage}` : '',
      ]
        .filter(Boolean)
        .join(' · ');
    }),
  ].filter(Boolean);
}
