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
    label: assetLabels[key] ?? key,
    value: item.value,
    weight: item.weight,
  }));
  const cash = state.summary.available_cash;
  if (cash > 0) {
    rows.push({
      key: 'cash',
      label: cashLabel,
      value: cash,
      weight: state.summary.cash_ratio,
    });
  }
  return rows.sort((a, b) => b.value - a.value);
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
  const largest = [...state.snapshot.allocation].sort(
    (a, b) => b.weight - a.weight,
  )[0];
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
    {
      key: 'drawdown',
      label: copy.overview.cards.currentDrawdown,
      value:
        drawdown == null ? labels.unavailableShort : formatPercent(drawdown),
    },
    ...investmentRisks.slice(0, 1).map((risk, index) => ({
      key: `risk-${index}`,
      label: risk.title,
      value: risk.level,
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
            <ul className="mt-3 divide-y divide-[var(--app-divider)]">
              {rows.map((row) => (
                <li key={row.key} className="py-2">
                  <div className="app-type-compact flex items-baseline justify-between gap-3">
                    <span className="font-medium text-[var(--app-text)]">
                      {row.label}
                    </span>
                    <span className="shrink-0 tabular-nums text-[var(--app-text-secondary)]">
                      {row.weight == null ? '--' : formatPercent(row.weight)}
                      {' · '}
                      {formatCurrency(row.value)}
                    </span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden bg-[var(--app-divider)]">
                    <span
                      aria-hidden="true"
                      className="block h-full bg-[var(--app-accent)]"
                      style={{
                        width: `${Math.max(
                          0,
                          Math.min(100, (row.weight ?? 0) * 100),
                        )}%`,
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="app-type-compact mt-3 text-[var(--app-text-tertiary)]">
              {labels.allocationUnavailable}
            </p>
          )}
        </div>
        <div className="min-w-0 lg:pl-6">
          <SectionHeader title={labels.riskSummary} />
          <dl className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {riskRows.map((row) => (
              <div
                key={row.key}
                className="grid min-w-0 gap-1 py-2.5 sm:grid-cols-[minmax(9rem,0.48fr)_minmax(0,1fr)] sm:items-baseline sm:gap-4"
              >
                <dt className="app-type-label text-[var(--app-text-tertiary)]">
                  {row.label}
                </dt>
                <dd className="app-type-compact min-w-0 font-semibold text-[var(--app-text)]">
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
