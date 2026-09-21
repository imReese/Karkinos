import { formatCurrency, formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import type { AccountStateResponse } from '../overview-feature-boundary';
import { overviewPresentation } from '../model/overview-presentation';

type AllocationRow = {
  key: string;
  label: string;
  value: number;
  weight: number | null;
};

function allocationRows(
  state: AccountStateResponse,
  assetLabels: Record<string, string>,
  cashLabel: string,
): AllocationRow[] {
  const grouped = new Map<string, { value: number; weight: number }>();
  for (const item of state.snapshot.allocation) {
    const current = grouped.get(item.asset_class) ?? { value: 0, weight: 0 };
    current.value += item.value;
    current.weight += item.weight;
    grouped.set(item.asset_class, current);
  }

  const rows: AllocationRow[] = [...grouped.entries()].map(([key, item]) => ({
    key,
    label: key === 'cash' ? cashLabel : (assetLabels[key] ?? key),
    value: item.value,
    weight: item.weight,
  }));
  const cash = state.summary.available_cash;
  if (!grouped.has('cash') && cash > 0) {
    const totalEquity = state.summary.total_equity;
    const cashWeight =
      state.summary.cash_ratio ??
      (typeof totalEquity === 'number' && totalEquity > 0
        ? cash / totalEquity
        : null);
    rows.push({
      key: 'cash',
      label: cashLabel,
      value: cash,
      weight: cashWeight,
    });
  }
  return rows.sort((a, b) => b.value - a.value);
}

function allocationColor(assetClass: string) {
  if (assetClass === 'cash') return 'var(--app-chart-sell)';
  if (assetClass === 'stock') return 'var(--app-accent-secondary)';
  if (assetClass === 'fund') return 'var(--app-success)';
  return 'var(--app-warning)';
}

function riskLevelLabel(level: string, locale: 'en' | 'zh') {
  const normalized = level.toLowerCase();
  if (locale === 'zh') {
    if (normalized === 'high') return '高';
    if (normalized === 'medium') return '中';
    if (normalized === 'low') return '低';
  }
  if (normalized === 'high') return 'High';
  if (normalized === 'medium') return 'Medium';
  if (normalized === 'low') return 'Low';
  return level;
}

export function OverviewAllocationRiskSection({
  state,
}: {
  state: AccountStateResponse;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const assetLabels = copy.overview.dashboard
    .valuationCoverageAssetClasses as Record<string, string>;
  const rows = allocationRows(
    state,
    assetLabels,
    copy.overview.breakdown.cashReserve,
  );
  const largest = state.snapshot.allocation
    .filter((item) => item.asset_class !== 'cash')
    .sort((a, b) => b.weight - a.weight)[0];
  const drawdown = state.summary.current_drawdown;
  const investmentRisks = state.risks.filter((risk) => risk.kind !== 'data');
  const riskRows = [
    {
      key: 'largest',
      label: largest
        ? `${copy.overview.risk.concentration} · ${largest.name ?? largest.symbol}`
        : copy.overview.risk.concentration,
      value: largest ? formatPercent(largest.weight) : '--',
    },
    {
      key: 'cash',
      label: copy.overview.risk.cashBuffer,
      value:
        state.summary.cash_ratio == null
          ? '--'
          : formatPercent(state.summary.cash_ratio),
    },
    ...(drawdown == null
      ? []
      : [
          {
            key: 'drawdown',
            label: copy.overview.cards.currentDrawdown,
            value: formatPercent(drawdown),
          },
        ]),
    ...investmentRisks.slice(0, 1).map((risk, index) => ({
      key: `risk-${index}`,
      label: risk.title,
      value: riskLevelLabel(risk.level, locale),
    })),
  ];

  return (
    <section
      className="min-w-0 border-b border-[var(--app-divider)] py-4"
      data-testid="overview-allocation-risk"
    >
      <div className="grid min-w-0 gap-6 lg:grid-cols-2 lg:gap-0 lg:divide-x lg:divide-[var(--app-divider)]">
        <div className="min-w-0 lg:pr-6">
          <SectionHeader title={labels.assetAllocation} />
          {rows.length ? (
            <div className="mt-3 space-y-3">
              <div
                aria-hidden="true"
                className="flex h-2.5 w-full overflow-hidden rounded-full bg-[var(--app-divider)]"
              >
                {rows.map((row, idx) => {
                  const pct = Math.max(
                    0,
                    Math.min(100, (row.weight ?? 0) * 100),
                  );
                  if (pct <= 0) return null;
                  return (
                    <span
                      key={row.key}
                      className={`h-full ${idx === 0 ? 'rounded-l-full' : ''} ${idx === rows.length - 1 ? 'rounded-r-full' : ''}`}
                      style={{
                        backgroundColor: allocationColor(row.key),
                        width: `${pct}%`,
                      }}
                      title={`${row.label} ${row.weight == null ? '' : formatPercent(row.weight)}`}
                    />
                  );
                })}
              </div>

              <ul className="divide-y divide-[var(--app-divider)]">
                {rows.map((row) => (
                  <li key={row.key} className="py-2">
                    <div className="app-type-compact flex items-baseline justify-between gap-3">
                      <span className="flex items-center gap-2 font-medium text-[var(--app-text)]">
                        <span
                          aria-hidden="true"
                          className="h-2 w-2 rounded-full shrink-0"
                          style={{ backgroundColor: allocationColor(row.key) }}
                        />
                        {row.label}
                      </span>
                      <span className="shrink-0 tabular-nums text-[var(--app-text-secondary)]">
                        {row.weight == null ? '--' : formatPercent(row.weight)}
                        {' · '}
                        {formatCurrency(row.value)}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="app-type-compact mt-3 text-[var(--app-text-tertiary)]">
              {labels.allocationUnavailable}
            </p>
          )}
        </div>
        <div className="min-w-0 lg:pl-6">
          <SectionHeader title={labels.riskSummary} />
          <dl className="mt-3 grid gap-2.5 sm:grid-cols-2">
            {riskRows.map((row) => (
              <div
                key={row.key}
                className="flex flex-col justify-between rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 p-3"
              >
                <dt className="app-type-label text-[var(--app-text-tertiary)]">
                  {row.label}
                </dt>
                <dd className="app-type-body mt-1 min-w-0 font-semibold tabular-nums text-[var(--app-text)]">
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}
