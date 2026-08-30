import type { Locale } from '../../../shared/preferences/context';
import { StatusBadge } from '../../../shared/ui/workbench';
import type { ReconciliationReportDetail } from '../api';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode, statusTone } from './account-truth-review-format';

export function AccountTruthReconciliationLanes({
  locale,
  report,
}: {
  locale: Locale;
  report: ReconciliationReportDetail | null;
}) {
  const reconciliation = report?.asset_reconciliation;
  if (!reconciliation) return null;

  const text = labels[locale];
  const lanes = [
    {
      id: 'stock',
      label: text.reconciliationStockLane,
      detail: text.reconciliationStockLaneDetail,
      evidence: reconciliation.stock,
    },
    {
      id: 'fund',
      label: text.reconciliationFundLane,
      detail: text.reconciliationFundLaneDetail,
      evidence: reconciliation.fund,
    },
    {
      id: 'cash',
      label: text.reconciliationCashLane,
      detail: text.reconciliationCashLaneDetail,
      evidence: reconciliation.cash,
    },
    {
      id: 'account',
      label: text.reconciliationAccountLane,
      detail:
        reconciliation.account.status === 'pass'
          ? text.reconciliationAccountPassDetail
          : text.reconciliationAccountBlockedDetail,
      evidence: reconciliation.account,
    },
  ];

  return (
    <section
      className="mt-3 border-y border-[var(--app-divider)] py-3"
      data-testid="account-truth-reconciliation-lanes"
    >
      <div className="app-type-overline text-[var(--app-text-tertiary)]">
        {text.reconciliationLanes}
      </div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {text.reconciliationLanesDetail}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {lanes.map((lane) => (
          <div
            key={lane.id}
            className="min-w-0 border-l-2 border-[var(--app-divider)] py-1 pl-3"
            data-testid={`account-truth-reconciliation-lane-${lane.id}`}
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <span className="text-xs font-semibold text-[var(--app-text)]">
                {lane.label}
              </span>
              <StatusBadge tone={statusTone(lane.evidence.status)}>
                {formatCode(lane.evidence.status, locale, 'status')}
              </StatusBadge>
            </div>
            <div className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
              {text.reconciliationLaneUnresolved(
                lane.evidence.unresolved_count,
              )}
            </div>
            <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
              {lane.detail}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
