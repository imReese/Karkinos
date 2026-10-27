import { formatTimestamp } from '../../../shared/format';
import type {
  ShadowResearchAutomationStatus,
  ShadowResearchPolicyInput,
} from '../api';
import type { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { StatusMetric } from './shadow-research-view';

export function TodayProviderActivityMetric({
  copy,
  activity,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  activity: ShadowResearchAutomationStatus['today_provider_activity'];
}) {
  return (
    <StatusMetric
      label={copy.todayCalls}
      value={activity ? String(activity.provider_calls) : '—'}
      detail={
        activity?.last_provider_call_at
          ? `${copy.lastProviderCall}: ${formatTimestamp(
              activity.last_provider_call_at,
            )} · ${copy.researchMarketDate}: ${activity.last_provider_call_market_date ?? '—'}`
          : `${activity?.local_date ?? '—'} · ${copy.noCallsToday}`
      }
    />
  );
}

export function ProviderCallWindowMetric({
  copy,
  providerWindow,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  providerWindow: ShadowResearchAutomationStatus['provider_call_window'];
}) {
  return (
    <StatusMetric
      label={copy.providerWindow}
      value={
        providerWindow?.status === 'eligible_off_peak'
          ? copy.offPeakEligible
          : providerWindow
            ? copy.offPeakDeferred
            : '—'
      }
      detail={
        providerWindow?.next_eligible_at
          ? `${copy.nextEligible}: ${providerWindow.next_eligible_at}`
          : copy.offPeakSchedule
      }
    />
  );
}

export function ShadowResearchUsageMetrics({
  copy,
  status,
  policy,
  providerWindow,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  status: ShadowResearchAutomationStatus | undefined;
  policy: ShadowResearchPolicyInput;
  providerWindow: ShadowResearchAutomationStatus['provider_call_window'];
}) {
  const latestRun = status?.runs[0];
  return (
    <div
      className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-5"
      data-testid="shadow-research-usage-metrics"
    >
      <StatusMetric
        label={copy.calls}
        value={`${status?.usage.provider_calls ?? 0} / ${
          status?.policy.max_provider_calls_per_market_date ??
          policy.max_provider_calls_per_market_date
        }`}
        detail={status?.usage.market_date ?? '—'}
      />
      <TodayProviderActivityMetric
        copy={copy}
        activity={status?.today_provider_activity}
      />
      <ProviderCallWindowMetric copy={copy} providerWindow={providerWindow} />
      <StatusMetric
        label={copy.tokens}
        value={String(status?.usage.actual_tokens ?? 0)}
        detail={`${
          status?.policy.token_budget_mode === 'unbounded_daily'
            ? copy.unboundedDailyTokens
            : copy.legacyBoundedDailyTokens
        } · ${copy.tokenAccountingEstimate} ${status?.usage.reserved_tokens ?? 0}`}
      />
      <StatusMetric
        label={copy.candidates}
        value={String(status?.candidates.length ?? 0)}
        detail={
          latestRun ? `${latestRun.market_date} · ${latestRun.status}` : '—'
        }
      />
    </div>
  );
}
