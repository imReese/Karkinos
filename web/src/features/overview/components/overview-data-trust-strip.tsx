import { usePreferences } from '../../../shared/preferences/context';
import type { AccountStateResponse } from '../overview-feature-boundary';
import { overviewPresentation } from '../model/overview-presentation';

function valueTone(status: 'ok' | 'warning' | 'neutral') {
  if (status === 'ok') return 'text-[var(--app-success-text)]';
  if (status === 'warning') return 'text-[var(--app-warning-text)]';
  return 'text-[var(--app-text-secondary)]';
}

export function OverviewDataTrustStrip({
  state,
}: {
  state: AccountStateResponse;
}) {
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const refreshLabels = {
    healthy: labels.healthy,
    degraded: labels.refreshDegraded,
    running: labels.running,
    unknown: labels.unknownHealth,
  };
  const decision =
    state.overview.decision_readiness === 'ready'
      ? labels.ready
      : state.overview.decision_readiness === 'blocked'
        ? labels.blocked
        : labels.unknownHealth;
  const items = [
    {
      label: labels.marketStatusLabel,
      value: labels[state.overview.market_session.status],
      tone:
        state.overview.market_session.status === 'unknown' ? 'neutral' : 'ok',
    },
    {
      label: labels.valuationStatus,
      value: labels[state.overview.valuation_usability],
      tone: state.overview.valuation_usability === 'usable' ? 'ok' : 'warning',
    },
    {
      label: labels.refreshStatusLabel,
      value: refreshLabels[state.overview.refresh_health.status],
      tone:
        state.overview.refresh_health.status === 'healthy'
          ? 'ok'
          : state.overview.refresh_health.status === 'running'
            ? 'neutral'
            : 'warning',
    },
    {
      label: labels.attentionStatusLabel,
      value:
        state.overview.attention_status === 'available'
          ? labels.attentionAvailable
          : labels.attentionUnavailableShort,
      tone: state.overview.attention_status === 'available' ? 'ok' : 'warning',
    },
    {
      label: labels.decisionReadiness,
      value: decision,
      tone:
        state.overview.decision_readiness === 'ready'
          ? 'ok'
          : state.overview.decision_readiness === 'blocked'
            ? 'warning'
            : 'neutral',
    },
  ] as const;

  return (
    <dl
      className="grid min-w-0 grid-cols-2 border-y border-[var(--app-divider)] sm:grid-cols-3 lg:grid-cols-5"
      data-testid="overview-data-trust-strip"
    >
      {items.map((item) => (
        <div
          key={item.label}
          className="min-w-0 border-b border-[var(--app-divider)] px-3 py-2.5 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0"
        >
          <dt className="app-type-label text-[var(--app-text-tertiary)]">
            {item.label}
          </dt>
          <dd
            className={
              'app-type-compact mt-0.5 truncate font-semibold ' +
              valueTone(item.tone)
            }
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
