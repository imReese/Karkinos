import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader, ExceptionBoundary } from '../../../shared/ui/workbench';
import {
  operationsNextActionLabel,
  operationsSubsystemLabel,
  operationsTargetHref,
  type AccountStateResponse,
} from '../overview-feature-boundary';
import { overviewPresentation } from '../model/overview-presentation';

export function DashboardTodayQueue({
  overview,
}: {
  overview: AccountStateResponse['overview'];
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const count =
    overview.attention_status === 'available'
      ? overview.user_attention.length
      : null;

  return (
    <section
      data-testid="overview-today-queue"
      aria-label={labels.attention}
      className="min-w-0 border-b border-[var(--app-divider)] py-3.5"
    >
      <SectionHeader
        title={labels.attention}
        meta={count == null ? '--' : count}
      />

      {overview.attention_status !== 'available' ? (
        <ExceptionBoundary
          tone="warning"
          title={labels.attentionUnavailable}
          description={labels.attentionUnavailableDetail}
          className="mt-3"
          actions={
            <a
              href="/operations"
              className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
            >
              {copy.overview.dashboard.viewOperations}
            </a>
          }
        />
      ) : null}

      {overview.attention_status === 'available' &&
      overview.user_attention.length === 0 ? (
        <p className="app-type-compact mt-2 text-[var(--app-text-secondary)]">
          {copy.overview.dashboard.noActionItems}
        </p>
      ) : null}

      {overview.user_attention.length > 0 ? (
        <ul className="mt-2 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {overview.user_attention.map((item) => (
            <li
              key={item.task_fingerprint}
              className="grid min-w-0 gap-1 py-2.5 sm:grid-cols-[minmax(9rem,0.45fr)_minmax(0,1fr)] sm:items-baseline sm:gap-4"
            >
              <div className="app-type-label text-[var(--app-text-tertiary)]">
                {operationsSubsystemLabel(item.subsystem_id, locale)}
              </div>
              <a
                href={operationsTargetHref(item.target)}
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {operationsNextActionLabel(item.next_action, locale)}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
