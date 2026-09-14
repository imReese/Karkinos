import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
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
  return (
    <section
      data-testid="overview-today-queue"
      aria-label={labels.attention}
      className="min-w-0 border-t border-[var(--app-divider)] py-4"
    >
      <h2 className="flex items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)]">
        {labels.attention}
        <span className="font-medium tabular-nums text-[var(--app-text-secondary)]">
          {overview.attention_status === 'available'
            ? overview.user_attention.length
            : '--'}
        </span>
      </h2>
      {overview.attention_status !== 'available' ? (
        <div className="mt-3 text-xs leading-5 text-[var(--app-warning-text)]">
          <p>{labels.attentionUnavailable}</p>
          <a
            href="/operations"
            className="text-[var(--app-accent)] hover:underline"
          >
            {labels.attentionUnavailableDetail}
          </a>
        </div>
      ) : null}
      {overview.user_attention.length === 0 ? (
        overview.attention_status === 'available' ? (
          <p className="mt-3 text-sm leading-6 text-[var(--app-text-secondary)]">
            {copy.overview.dashboard.noActionItems}
          </p>
        ) : null
      ) : (
        <ul className="mt-2 divide-y divide-[var(--app-divider)]">
          {overview.user_attention.map((item) => (
            <li key={item.task_fingerprint} className="py-3">
              <div className="text-xs text-[var(--app-text-tertiary)]">
                {operationsSubsystemLabel(item.subsystem_id, locale)}
              </div>
              <a
                href={operationsTargetHref(item.target)}
                className="mt-1 block text-sm leading-6 font-medium text-[var(--app-accent)] hover:underline"
              >
                {operationsNextActionLabel(item.next_action, locale)}
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
