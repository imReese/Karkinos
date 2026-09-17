import { formatCurrency } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import type { AccountStateResponse } from '../overview-feature-boundary';
import { overviewSessionLabels, pnlTone } from '../model/overview-presentation';

export function OverviewPerformanceDrivers({
  state,
}: {
  state: AccountStateResponse;
}) {
  const { locale } = usePreferences();
  const contributors = state.summary.today_contributors ?? [];
  if (!contributors.length) return null;
  return (
    <div
      className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-2 text-xs"
      data-testid="overview-performance-drivers"
    >
      <h3 className="font-medium text-[var(--app-text-secondary)]">
        {overviewSessionLabels(state, locale).drivers}
      </h3>
      <ul className="flex flex-wrap gap-x-5 gap-y-2">
        {contributors.map((item) => (
          <li key={item.symbol} className="flex items-baseline gap-2">
            <a
              href={`/portfolio/${encodeURIComponent(item.symbol)}`}
              className="text-[var(--app-text-secondary)] hover:text-[var(--app-accent)]"
            >
              {item.display_name || item.name || item.symbol}
            </a>
            <span
              className={`font-medium tabular-nums ${pnlTone(item.today_change)}`}
            >
              {formatCurrency(item.today_change, { signDisplay: 'exceptZero' })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
