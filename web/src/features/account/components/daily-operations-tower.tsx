import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import type { DailyOperationsSummary } from '../api';

type DashboardLabels = ReturnType<typeof useCopy>['overview']['dashboard'];

type Target = {
  href: string;
  label: string;
};

function conclusionText(
  summary: DailyOperationsSummary,
  labels: DashboardLabels,
) {
  if (summary.conclusion_status === 'pending_manual_confirmation') {
    return labels.operationsPendingManual(
      Math.max(summary.pending_manual_order_count, summary.manual_ready_count),
    );
  }
  if (summary.conclusion_status === 'risk_blocked') {
    return labels.operationsRiskBlocked(summary.risk_blocked_count);
  }
  if (summary.conclusion_status === 'account_truth_blocked') {
    return labels.operationsAccountTruthBlocked;
  }
  if (summary.conclusion_status === 'data_unavailable') {
    return labels.operationsDataUnavailable;
  }
  if (summary.conclusion_status === 'execution_exception') {
    return labels.operationsExecutionException(
      summary.execution_exception_count,
    );
  }
  return labels.operationsNoManualAction;
}

function primaryTarget(
  summary: DailyOperationsSummary,
  labels: DashboardLabels,
): Target {
  if (summary.primary_target === 'trading') {
    return { href: '/trading', label: labels.operationsViewTrading };
  }
  if (summary.primary_target === 'risk') {
    return { href: '/risk', label: labels.operationsViewRisk };
  }
  if (summary.primary_target === 'account-truth') {
    return {
      href: '/account-truth',
      label: labels.operationsViewAccountTruth,
    };
  }
  if (summary.primary_target === 'market') {
    return { href: '/market', label: labels.operationsViewMarket };
  }
  if (summary.primary_target === 'ledger') {
    return { href: '/activity', label: labels.operationsViewLedger };
  }
  return { href: '/decision', label: labels.operationsViewCandidates };
}

function metricRows(summary: DailyOperationsSummary, labels: DashboardLabels) {
  return [
    [labels.operationsCandidatePool, summary.candidate_pool_count],
    [labels.operationsEvidencePassed, summary.evidence_passed_count],
    [labels.operationsRiskPassed, summary.risk_passed_count],
    [labels.operationsManualReady, summary.manual_ready_count],
    [labels.operationsExecutionRecords, summary.execution_record_count],
    [labels.operationsLedgerReview, summary.ledger_review_count],
  ] satisfies Array<[string, number]>;
}

export function DailyOperationsTower({
  summary,
}: {
  summary: DailyOperationsSummary | null | undefined;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;

  if (!summary) {
    return null;
  }

  const target = primaryTarget(summary, labels);
  const defaultMode =
    summary.default_execution_mode === 'manual_confirmation'
      ? labels.operationsManualConfirmation
      : summary.default_execution_mode;
  const brokerBridge =
    summary.broker_bridge_status === 'disabled'
      ? labels.operationsBrokerDisabled
      : summary.broker_bridge_status;

  return (
    <div data-testid="daily-operations-tower" className="min-w-0">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">{labels.dailyWorkbench}</div>
          <h2 className="app-card-title mt-1.5 text-xl">
            {conclusionText(summary, labels)}
          </h2>
          <div className="app-muted mt-2 text-xs">
            {labels.operationsConclusion}
          </div>
        </div>
        <a
          href={target.href}
          className="app-button-secondary w-fit shrink-0 rounded-2xl px-3 py-2 text-xs font-semibold"
        >
          {target.label}
        </a>
      </div>

      <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
        <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
          {labels.operationsTower}
        </div>
        <div className="mt-4 grid min-w-0 grid-cols-2 gap-2">
          {metricRows(summary, labels).map(([label, value]) => (
            <div
              key={label}
              className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2"
            >
              <div className="truncate text-[10px] font-semibold uppercase text-[var(--app-subtext-0)]">
                {label}
              </div>
              <div className="mt-1 font-mono text-lg font-semibold text-[var(--app-soft)] tabular-nums">
                {value.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US')}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 grid min-w-0 grid-cols-2 gap-2 text-xs">
          <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-2">
            <div className="text-[var(--app-subtext-0)]">
              {labels.operationsDefaultMode}
            </div>
            <div className="mt-1 font-semibold text-[var(--app-soft)]">
              {defaultMode}
            </div>
          </div>
          <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-2">
            <div className="text-[var(--app-subtext-0)]">
              {labels.operationsBrokerBridge}
            </div>
            <div className="mt-1 font-semibold text-[var(--app-soft)]">
              {brokerBridge}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
