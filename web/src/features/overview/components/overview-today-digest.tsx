import {
  formatCurrency,
  formatDate,
  formatPercent,
} from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import type { AccountStateResponse } from '../overview-feature-boundary';
import {
  overviewPresentation,
  overviewSessionLabels,
  pnlTone,
} from '../model/overview-presentation';

type Driver = NonNullable<
  AccountStateResponse['summary']['today_contributors']
>[number];

function DriverList({
  title,
  items,
  emptyLabel,
  labels,
  className,
}: {
  title: string;
  items: Driver[];
  emptyLabel: string;
  labels: (typeof overviewPresentation)[keyof typeof overviewPresentation];
  className?: string;
}) {
  return (
    <div className={('min-w-0 ' + (className ?? '')).trim()}>
      <h3 className="app-type-body mb-3 font-semibold text-[var(--app-text)]">
        {title}
      </h3>
      {items.length ? (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_max-content_max-content] gap-x-4">
          <span className="app-type-label text-[var(--app-text-tertiary)]">
            {labels.driverHolding}
          </span>
          <span className="app-type-label text-right text-[var(--app-text-tertiary)]">
            {labels.driverPnl}
          </span>
          <span className="app-type-label text-right text-[var(--app-text-tertiary)]">
            {labels.driverReturn}
          </span>
          <ol className="col-span-3 mt-2 grid grid-cols-subgrid">
            {items.map((item, index) => (
              <li
                key={item.symbol}
                className="col-span-3 grid min-w-0 grid-cols-subgrid items-center border-t border-[var(--app-divider)] py-3"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span
                    aria-hidden="true"
                    className="app-type-label shrink-0 tabular-nums text-[var(--app-text-tertiary)]"
                  >
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <a
                    href={`/portfolio/${encodeURIComponent(item.symbol)}`}
                    title={item.display_name || item.name || item.symbol}
                    className="group flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                  >
                    <span className="app-type-compact w-full truncate font-medium text-[var(--app-text)] group-hover:text-[var(--app-accent)]">
                      {item.display_name || item.name || item.symbol}
                    </span>
                    <span className="app-type-label w-full truncate text-[var(--app-text-tertiary)]">
                      {item.symbol}
                    </span>
                  </a>
                </div>
                <span
                  className={`app-type-body whitespace-nowrap text-right font-semibold tabular-nums ${pnlTone(item.today_change)}`}
                >
                  {formatCurrency(item.today_change, {
                    signDisplay: 'exceptZero',
                  })}
                </span>
                <span
                  aria-label={
                    item.today_change_pct == null
                      ? labels.returnUnavailable
                      : undefined
                  }
                  className={`app-type-compact whitespace-nowrap text-right tabular-nums ${pnlTone(item.today_change_pct)}`}
                >
                  {item.today_change_pct == null
                    ? '—'
                    : formatPercent(item.today_change_pct, {
                        signDisplay: 'exceptZero',
                      })}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : (
        <p className="app-type-compact border-t border-[var(--app-divider)] py-5 text-[var(--app-text-secondary)]">
          {emptyLabel}
        </p>
      )}
    </div>
  );
}

export function OverviewTodayDigest({
  state,
  className,
}: {
  state: AccountStateResponse;
  className?: string;
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
      className={('min-w-0 ' + (className ?? '')).trim()}
      data-testid="overview-today-digest"
    >
      <SectionHeader
        title={overviewSessionLabels(state, locale).drivers}
        meta={
          state.summary.latest_session_date
            ? formatDate(state.summary.latest_session_date)
            : undefined
        }
        description={labels.driverScope}
      />
      <div
        className="mt-5 grid min-w-0 gap-5 md:grid-cols-2 md:gap-6"
        data-testid="overview-performance-drivers"
      >
        <DriverList
          title={labels.contributors}
          items={gains}
          emptyLabel={labels.noPositiveMainDrivers}
          labels={labels}
        />
        <DriverList
          title={labels.detractors}
          items={drags}
          emptyLabel={labels.noNegativeMainDrivers}
          labels={labels}
          className="border-t border-[var(--app-divider)] pt-4 md:border-t-0 md:border-l md:pt-0 md:pl-6"
        />
      </div>
    </aside>
  );
}
