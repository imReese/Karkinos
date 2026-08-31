import type { Locale } from '../../../shared/preferences/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  EvidenceLoadingLayout,
  EvidenceState,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { AccountTruthEvidenceSections } from './account-truth-evidence-sections';
import { openAccountTruthReadinessTarget } from './account-truth-evidence-readiness';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode } from './account-truth-review-format';
import { AccountTruthReconciliationWorkspace } from './account-truth-reconciliation-workspace';
import {
  useAccountTruthReviewState,
  type AccountTruthReviewState,
} from './account-truth-review-state';

export function AccountTruthReviewPage() {
  const { locale } = usePreferences();
  const text = labels[locale];
  const state = useAccountTruthReviewState(locale);

  if (!state.hasSummaryEvidence) {
    return (
      <AccountTruthPageFrame locale={locale}>
        {state.hasError ? (
          <EvidenceState kind="error" title={text.error} />
        ) : (
          <EvidenceLoadingLayout
            title={text.loading}
            metricCount={4}
            rowCount={4}
          />
        )}
      </AccountTruthPageFrame>
    );
  }

  return (
    <AccountTruthPageFrame locale={locale}>
      {state.hasError ? (
        <EvidenceState kind="error" title={text.error} />
      ) : null}
      <AccountTruthReadinessPriority locale={locale} state={state} />
      <AccountTruthReconciliationWorkspace locale={locale} state={state} />
      <AccountTruthEvidenceSections locale={locale} state={state} />
    </AccountTruthPageFrame>
  );
}

function AccountTruthPageFrame({
  children,
  locale,
}: {
  children: React.ReactNode;
  locale: Locale;
}) {
  const text = labels[locale];
  return (
    <section
      className="app-account-truth-route app-workbench-route mx-auto grid w-full max-w-[1440px] gap-5 sm:gap-6"
      data-workbench-route="account-truth"
    >
      <WorkspaceHeader
        eyebrow={text.kicker}
        title={text.title}
        description={text.subtitle}
        context={text.safety}
      />
      {children}
    </section>
  );
}

function AccountTruthReadinessPriority({
  locale,
  state,
}: {
  locale: Locale;
  state: AccountTruthReviewState;
}) {
  const readiness = state.readiness.data;
  if (!readiness) return null;
  const text = labels[locale];
  return (
    <div data-testid="account-truth-readiness-priority">
      <EvidenceState
        kind={readiness.status === 'ready' ? 'ready' : 'partial'}
        statusLabel={
          readiness.status === 'ready'
            ? text.readinessClear
            : formatCode(readiness.status, locale, 'status')
        }
        title={
          readiness.status === 'ready'
            ? text.readinessPriorityReadyTitle
            : text.readinessPriorityBlockedTitle
        }
        description={
          <>
            {readiness.status === 'ready'
              ? text.readinessPriorityReadyDetail
              : text.readinessPriorityBlockedDetail}
            {readiness.status !== 'ready' &&
            readiness.account_truth_gate_status === 'pass'
              ? ` ${text.readinessPriorityLocalPassDetail}`
              : null}
            {readiness.next_manual_action !== 'none'
              ? ` ${text.readinessNextAction}: ${formatCode(
                  readiness.next_manual_action,
                  locale,
                  'code',
                )}`
              : null}
          </>
        }
        action={
          <a
            aria-controls="account-truth-evidence-readiness-disclosure"
            className="app-button-secondary inline-flex min-h-10 items-center rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
            href="#account-truth-evidence-readiness-disclosure"
            onClick={() =>
              openAccountTruthReadinessTarget(
                'account-truth-evidence-readiness-disclosure',
              )
            }
          >
            {text.readinessPriorityAction}
          </a>
        }
      />
    </div>
  );
}
