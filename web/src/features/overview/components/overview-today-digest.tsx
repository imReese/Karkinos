import { formatCurrency, formatPercent } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import type { AccountStateResponse } from '../overview-feature-boundary';
import {
  overviewPresentation,
  overviewSessionLabels,
} from '../model/overview-presentation';

type Driver = NonNullable<
  AccountStateResponse['summary']['today_contributors']
>[number];

function DriverList({ title, items }: { title: string; items: Driver[] }) {
  return (
    <div className="min-w-0">
      <h3 className="app-type-label font-semibold text-[var(--app-text-secondary)]">
        {title}
      </h3>
      {items.length ? (
        <ul className="mt-1.5 space-y-1.5">
          {items.map((item) => (
            <li
              key={item.symbol}
              className="app-type-compact flex min-w-0 items-baseline justify-between gap-3"
            >
              <a
                href={`/portfolio/${encodeURIComponent(item.symbol)}`}
                className="min-w-0 truncate text-[var(--app-text-secondary)] hover:text-[var(--app-accent)]"
              >
                {item.display_name || item.name || item.symbol}
              </a>
              <span
                className={
                  'shrink-0 tabular-nums font-medium ' +
                  (item.today_change > 0
                    ? 'text-[var(--app-pnl-positive)]'
                    : 'text-[var(--app-pnl-negative)]')
                }
              >
                {formatCurrency(item.today_change, {
                  signDisplay: 'exceptZero',
                })}
                {item.today_change_pct == null
                  ? null
                  : ` · ${formatPercent(item.today_change_pct)}`}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <span className="app-type-compact mt-1.5 block text-[var(--app-text-tertiary)]">
          —
        </span>
      )}
    </div>
  );
}

export function OverviewTodayDigest({
  state,
}: {
  state: AccountStateResponse;
}) {
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const contributors = [...(state.summary.today_contributors ?? [])];
  const gains = contributors
    .filter((item) => item.today_change > 0)
    .sort((a, b) => b.today_change - a.today_change)
    .slice(0, 3);
  const drags = contributors
    .filter((item) => item.today_change < 0)
    .sort((a, b) => a.today_change - b.today_change)
    .slice(0, 3);

  return (
    <aside
      className="min-w-0 xl:border-l xl:border-[var(--app-divider)] xl:pl-6"
      data-testid="overview-today-digest"
    >
      <SectionHeader title={overviewSessionLabels(state, locale).drivers} />
      <div
        className="mt-3 grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2"
        data-testid="overview-performance-drivers"
      >
        <DriverList title={labels.contributors} items={gains} />
        <DriverList title={labels.detractors} items={drags} />
      </div>
    </aside>
  );
}
