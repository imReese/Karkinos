import { StatusBadge } from '../../../app/components/workbench';
import type { Locale } from '../../../app/preferences';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
} from '../../../shared/format';
import type { ExecutionReconciliationItem } from '../../operations/api';

type ComparisonRow = {
  key: 'quantity' | 'price' | 'cost';
  planned: string;
  paper: string;
  actual: string;
};

type ComparisonView = {
  status: string;
  fingerprint: string;
  rows: ComparisonRow[];
  blockers: string[];
  differences: string[];
  safetyLabels: string[];
};

const STATUS_TONES = {
  pass: 'success',
  review_required: 'warning',
  blocked: 'danger',
  not_applicable_paper_shadow_order: 'neutral',
} as const;

const COMPARISON_STATUSES = new Set(Object.keys(STATUS_TONES));

export function PlanPaperActualComparison({
  item,
  locale,
}: {
  item: ExecutionReconciliationItem;
  locale: Locale;
}) {
  const parsed = comparisonView(item);
  if (!parsed) return null;
  const view = localizeView(parsed, locale);
  const copy = COPY[locale];
  const status = statusLabel(view.status, locale);
  const tone =
    STATUS_TONES[view.status as keyof typeof STATUS_TONES] ?? 'danger';
  const nextStep = nextStepLabel(view.status, locale);

  return (
    <section
      aria-label={copy.title}
      className="mt-3 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3"
      data-testid="plan-paper-actual-comparison"
    >
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
            {copy.title}
          </div>
          <p className="app-muted mt-1 break-words text-xs leading-5">
            {copy.detail}
          </p>
        </div>
        <StatusBadge tone={tone}>{status}</StatusBadge>
      </div>

      {view.rows.length ? (
        <div className="mt-3 max-w-full overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-left text-xs tabular-nums">
            <thead>
              <tr className="border-y border-[var(--app-divider)] text-[var(--app-text-tertiary)]">
                <th className="px-2 py-2 font-semibold" scope="col">
                  {copy.metric}
                </th>
                <th className="px-2 py-2 text-right font-semibold" scope="col">
                  {copy.planned}
                </th>
                <th className="px-2 py-2 text-right font-semibold" scope="col">
                  {copy.paper}
                </th>
                <th className="px-2 py-2 text-right font-semibold" scope="col">
                  {copy.actual}
                </th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr
                  className="border-b border-[var(--app-divider)]"
                  key={row.key}
                >
                  <th
                    className="px-2 py-2 font-medium text-[var(--app-text)]"
                    scope="row"
                  >
                    {copy.rows[row.key]}
                  </th>
                  <td className="px-2 py-2 text-right text-[var(--app-text)]">
                    {row.planned}
                  </td>
                  <td className="px-2 py-2 text-right text-[var(--app-text)]">
                    {row.paper}
                  </td>
                  <td className="px-2 py-2 text-right text-[var(--app-text)]">
                    {row.actual}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {view.blockers.length ? (
        <div className="mt-3" data-testid="plan-paper-actual-blockers">
          <div className="text-xs font-semibold text-[var(--app-danger-text)]">
            {copy.blockers}
          </div>
          <ul className="mt-1 grid gap-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {view.blockers.map((blocker) => (
              <li
                className="border-l-2 border-[var(--app-danger-border)] pl-2"
                key={blocker}
              >
                {blockerLabel(blocker, locale)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {view.differences.length ? (
        <div className="mt-3" data-testid="plan-paper-actual-differences">
          <div className="text-xs font-semibold text-[var(--app-warning-text)]">
            {copy.differences}
          </div>
          <ul className="mt-1 grid gap-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {view.differences.map((difference) => (
              <li
                className="border-l-2 border-[var(--app-warning-border)] pl-2"
                key={difference}
              >
                {differenceLabel(difference, locale)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-3 border-l-2 border-[var(--app-divider)] pl-3 text-xs leading-5">
        <div className="font-semibold text-[var(--app-text)]">
          {copy.nextStep}
        </div>
        <div className="app-muted mt-1">{nextStep}</div>
      </div>

      {view.fingerprint ? (
        <div className="mt-3 min-w-0 text-xs">
          <span className="app-muted">{copy.fingerprint}: </span>
          <code className="break-all font-mono text-[var(--app-text)]">
            {view.fingerprint}
          </code>
        </div>
      ) : null}

      <div className="mt-3 flex min-w-0 flex-wrap gap-2">
        {view.safetyLabels.map((label) => (
          <span className="app-chip" key={label}>
            {label}
          </span>
        ))}
      </div>
    </section>
  );
}

function comparisonView(
  item: ExecutionReconciliationItem,
): ComparisonView | null {
  if (item.payload_status === 'invalid') {
    return blockedView('execution_reconciliation_payload_invalid');
  }
  if (item.payload_status === 'missing') {
    return blockedView('execution_reconciliation_payload_missing');
  }
  const payload = record(item.payload);
  const comparison = record(payload?.plan_paper_actual_comparison);
  if (!comparison) {
    return item.payload_status === 'valid'
      ? blockedView('plan_paper_actual_comparison_missing')
      : null;
  }
  const rawStatus = stringValue(comparison.status);
  const status = COMPARISON_STATUSES.has(rawStatus) ? rawStatus : 'blocked';
  const planned = record(comparison.planned) ?? {};
  const paper = record(comparison.paper) ?? {};
  const actual = record(comparison.actual) ?? {};
  const rows = [
    {
      key: 'quantity' as const,
      planned: quantityValue(planned.quantity),
      paper: quantityValue(paper.filled_quantity),
      actual: quantityValue(actual.quantity),
    },
    {
      key: 'price' as const,
      planned: priceValue(planned.limit_price),
      paper: priceValue(paper.average_fill_price),
      actual: priceValue(actual.average_fill_price),
    },
    {
      key: 'cost' as const,
      planned: '--',
      paper: currencyValue(paper.total_execution_cost),
      actual: currencyValue(actual.total_execution_cost),
    },
  ];
  return {
    status,
    fingerprint: stringValue(comparison.evidence_fingerprint),
    rows,
    blockers: [
      ...(status === 'blocked' && rawStatus !== 'blocked'
        ? ['plan_paper_actual_status_missing_or_invalid']
        : []),
      ...stringArray(comparison.blockers),
    ],
    differences: stringArray(comparison.differences),
    safetyLabels: safetyLabels(comparison, status),
  };
}

function blockedView(blocker: string): ComparisonView {
  return {
    status: 'blocked',
    fingerprint: '',
    rows: [],
    blockers: [blocker],
    differences: [],
    safetyLabels: safetyLabels({}, 'blocked'),
  };
}

function safetyLabels(
  comparison: Record<string, unknown>,
  status: string,
): string[] {
  const labels = [
    comparison.persisted_evidence_only === true ? 'persisted' : '',
    comparison.human_review_required === true || status === 'blocked'
      ? 'human_review'
      : '',
    comparison.authorizes_execution === false || status === 'blocked'
      ? 'no_execution'
      : '',
    comparison.does_not_mutate_oms === true || status === 'blocked'
      ? 'no_oms'
      : '',
    comparison.does_not_mutate_production_ledger === true ||
    status === 'blocked'
      ? 'no_ledger'
      : '',
    comparison.does_not_change_capital_authority === true ||
    status === 'blocked'
      ? 'no_capital'
      : '',
  ];
  return labels.filter(Boolean);
}

function statusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    pass: { en: 'Comparison passed', zh: '对比通过' },
    review_required: { en: 'Review required', zh: '待人工复核' },
    blocked: { en: 'Comparison blocked', zh: '对比阻断' },
    not_applicable_paper_shadow_order: {
      en: 'Paper-only order',
      zh: '仅模拟订单',
    },
  };
  return labels[status]?.[locale] ?? labels.blocked[locale];
}

function nextStepLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    pass: {
      en: 'Record the exact batch reconciliation evidence. It still does not authorize another order.',
      zh: '记录精确批次对账证据；它仍不授权下一笔订单。',
    },
    review_required: {
      en: 'Review the paper-versus-actual price and cost differences. Keep the next batch blocked until new reconciled evidence passes.',
      zh: '复核模拟与实际的价格、费用差异；新的已对账证据通过前，下一批次继续阻断。',
    },
    blocked: {
      en: 'Supply exact order-linked broker evidence and rerun reconciliation. Do not infer or accept missing values.',
      zh: '补充与订单身份精确绑定的券商证据并重新对账；不得推断或人工接受缺失值。',
    },
    not_applicable_paper_shadow_order: {
      en: 'Retain the simulation evidence; no broker outcome is expected for this paper-only order.',
      zh: '保留模拟证据；仅模拟订单不应产生券商实际结果。',
    },
  };
  return (labels[status] ?? labels.blocked)[locale];
}

function blockerLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    execution_reconciliation_payload_invalid: {
      en: 'The persisted reconciliation payload is invalid and cannot be interpreted.',
      zh: '持久化执行对账 payload 无效，无法解释。',
    },
    execution_reconciliation_payload_missing: {
      en: 'The persisted reconciliation payload is missing.',
      zh: '缺少持久化执行对账 payload。',
    },
    plan_paper_actual_comparison_missing: {
      en: 'The persisted plan, paper, and actual comparison is missing.',
      zh: '缺少持久化的计划、模拟与实际结果对比。',
    },
    plan_paper_actual_status_missing_or_invalid: {
      en: 'The persisted comparison status is missing or invalid.',
      zh: '持久化对比状态缺失或无效。',
    },
    planned_decision_action_reference_missing_or_invalid: {
      en: 'The planned order is not bound to one valid Decision action.',
      zh: '计划订单未绑定唯一有效的 Decision 动作。',
    },
    paper_shadow_run_reference_missing_or_invalid: {
      en: 'The order is not bound to one valid paper/shadow run.',
      zh: '订单未绑定唯一有效的 paper/shadow 运行。',
    },
    paper_shadow_run_not_found: {
      en: 'The bound paper/shadow run is unavailable.',
      zh: '绑定的 paper/shadow 运行不存在。',
    },
    paper_shadow_order_lineage_not_unique: {
      en: 'The paper/shadow order lineage is missing or ambiguous.',
      zh: 'paper/shadow 订单 lineage 缺失或不唯一。',
    },
    paper_shadow_outcome_not_clear: {
      en: 'The paper/shadow result is incomplete or outside expectations.',
      zh: 'paper/shadow 结果不完整或超出预期。',
    },
    paper_shadow_symbol_mismatch: {
      en: 'The paper/shadow symbol differs from the planned order.',
      zh: 'paper/shadow 标的与计划订单不一致。',
    },
    paper_shadow_side_mismatch: {
      en: 'The paper/shadow side differs from the planned order.',
      zh: 'paper/shadow 买卖方向与计划订单不一致。',
    },
    paper_shadow_quantity_mismatch: {
      en: 'The paper/shadow quantity differs from the planned order.',
      zh: 'paper/shadow 数量与计划订单不一致。',
    },
    actual_broker_evidence_missing: {
      en: 'Exact imported broker execution evidence is missing.',
      zh: '缺少精确的券商实际成交导入证据。',
    },
    actual_broker_evidence_not_exactly_linked: {
      en: 'Broker evidence exists but is not exactly linked to this order.',
      zh: '券商证据存在，但未与该订单精确绑定。',
    },
    actual_broker_import_identity_conflict: {
      en: 'Actual fills resolve to conflicting broker import identities.',
      zh: '实际成交对应多个冲突的券商导入身份。',
    },
    actual_broker_quantity_incomplete_or_conflicting: {
      en: 'Actual broker quantity is incomplete or conflicts with the order.',
      zh: '券商实际成交数量不完整或与订单冲突。',
    },
  };
  return labels[value]?.[locale] ?? COPY[locale].unknownBlocker;
}

function differenceLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    planned_paper_fill_price_difference: {
      en: 'Paper fill price differs from the planned limit price.',
      zh: '模拟成交价与计划限价不同。',
    },
    paper_actual_quantity_difference: {
      en: 'Actual filled quantity differs from the paper result.',
      zh: '实际成交数量与模拟结果不同。',
    },
    paper_actual_fill_price_difference: {
      en: 'Actual average price differs from the paper result.',
      zh: '实际平均成交价与模拟结果不同。',
    },
    paper_actual_execution_cost_difference: {
      en: 'Actual fees and taxes differ from the paper result.',
      zh: '实际费用和税费与模拟结果不同。',
    },
  };
  return labels[value]?.[locale] ?? COPY[locale].unknownDifference;
}

const COPY = {
  en: {
    title: 'Plan / paper / actual comparison',
    detail:
      'Canonical persisted values only; this comparison does not calculate or grant authority in the browser.',
    metric: 'Metric',
    planned: 'Planned',
    paper: 'Paper/shadow',
    actual: 'Actual broker',
    rows: {
      quantity: 'Quantity',
      price: 'Order / fill price',
      cost: 'Execution cost',
    },
    blockers: 'Blocking evidence',
    differences: 'Observed differences',
    nextStep: 'Safe next step',
    fingerprint: 'Evidence fingerprint',
    unknownBlocker: 'An unrecognized persisted blocker requires review.',
    unknownDifference: 'An unrecognized persisted difference requires review.',
  },
  zh: {
    title: '计划 / 模拟 / 实际结果对比',
    detail: '只展示 canonical 持久化值；浏览器不计算财务结果，也不授予权限。',
    metric: '指标',
    planned: '计划',
    paper: 'Paper/shadow',
    actual: '券商实际',
    rows: { quantity: '数量', price: '委托 / 成交价', cost: '执行成本' },
    blockers: '证据阻断项',
    differences: '已观察差异',
    nextStep: '安全下一步',
    fingerprint: '证据指纹',
    unknownBlocker: '存在未识别的持久化阻断项，需要复核。',
    unknownDifference: '存在未识别的持久化差异，需要复核。',
  },
} as const;

const SAFETY_COPY = {
  en: {
    persisted: 'Persisted evidence only',
    human_review: 'Human review required',
    no_execution: 'No execution authority',
    no_oms: 'No OMS mutation',
    no_ledger: 'No ledger mutation',
    no_capital: 'No capital authority change',
  },
  zh: {
    persisted: '仅持久化证据',
    human_review: '需要人工复核',
    no_execution: '无执行权限',
    no_oms: '不修改 OMS',
    no_ledger: '不修改账本',
    no_capital: '不改变资本权限',
  },
} as const;

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function numericValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function quantityValue(value: unknown) {
  return formatQuantity(numericValue(value));
}

function priceValue(value: unknown) {
  return formatPrice(numericValue(value));
}

function currencyValue(value: unknown) {
  return formatCurrency(numericValue(value));
}

function localizedSafetyLabels(keys: string[], locale: Locale) {
  const labels = SAFETY_COPY[locale];
  return keys.map((key) => labels[key as keyof typeof labels]).filter(Boolean);
}

// Convert internal keys only after the comparison has been parsed; the component
// never exposes imported event ids, account references, or source file details.
function localizeView(view: ComparisonView, locale: Locale): ComparisonView {
  return {
    ...view,
    safetyLabels: localizedSafetyLabels(view.safetyLabels, locale),
  };
}
