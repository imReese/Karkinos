import { formatCurrency, formatPercent } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import {
  operationsNextActionLabel,
  operationsSubsystemLabel,
  operationsTargetHref,
  type AccountStateResponse,
} from '../overview-feature-boundary';
import {
  overviewPresentation,
  overviewSessionLabels,
  shortDate,
} from '../model/overview-presentation';

type Driver = NonNullable<
  AccountStateResponse['summary']['today_contributors']
>[number];

function DriverList({
  title,
  items,
  emptyLabel,
}: {
  title: string;
  items: Driver[];
  emptyLabel: string;
}) {
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
        <p className="app-type-compact mt-1.5 text-[var(--app-text-tertiary)]">
          {emptyLabel}
        </p>
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
  const attention = state.overview.user_attention.slice(0, 3);

  return (
    <aside
      className="min-w-0 xl:border-l xl:border-[var(--app-divider)] xl:pl-6"
      data-testid="overview-today-digest"
    >
      <SectionHeader
        title={labels.todayNarrative}
        meta={shortDate(state.summary.latest_session_date)}
      />
      <div className="mt-3" data-testid="overview-performance-drivers">
        <p className="app-type-micro mb-2 text-[var(--app-text-tertiary)]">
          {overviewSessionLabels(state, locale).drivers}
        </p>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
          <DriverList
            title={labels.contributors}
            items={gains}
            emptyLabel={labels.noPositiveDrivers}
          />
          <DriverList
            title={labels.detractors}
            items={drags}
            emptyLabel={labels.noNegativeDrivers}
          />
        </div>
      </div>
      <div className="mt-4 border-t border-[var(--app-divider)] pt-3">
        <h3 className="app-type-label font-semibold text-[var(--app-text-secondary)]">
          {labels.accountEvents}
        </h3>
        {state.overview.attention_status !== 'available' ? (
          <p className="app-type-compact mt-1.5 text-[var(--app-warning-text)]">
            {labels.attentionUnavailable}
          </p>
        ) : attention.length ? (
          <ul className="mt-1.5 divide-y divide-[var(--app-divider)]">
            {attention.map((item) => (
              <li
                key={item.task_fingerprint}
                className="app-type-compact flex min-w-0 items-baseline justify-between gap-3 py-1.5"
              >
                <span className="shrink-0 text-[var(--app-text-tertiary)]">
                  {operationsSubsystemLabel(item.subsystem_id, locale)}
                </span>
                <a
                  href={operationsTargetHref(item.target)}
                  className="min-w-0 truncate text-right font-medium text-[var(--app-accent)] hover:underline"
                >
                  {operationsNextActionLabel(item.next_action, locale)}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="app-type-compact mt-1.5 text-[var(--app-text-secondary)]">
            {labels.noAccountEvents}
          </p>
        )}
      </div>
    </aside>
  );
}
