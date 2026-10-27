import type { Dispatch, SetStateAction } from 'react';
import { ChevronDown } from 'lucide-react';

import type {
  ShadowResearchAutomationStatus,
  ShadowResearchPolicyInput,
  useRunShadowResearchMutation,
} from '../api';
import type { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { ShadowResearchPolicyCard } from './shadow-research-policy-card';
import { StatusMetric } from './shadow-research-view';
import { ShadowResearchUsageMetrics } from './shadow-research-usage-metrics';

export function ShadowResearchAutomationDisclosure({
  copy,
  dailyOutcome,
  datesValid,
  draftPolicyReady,
  hasError,
  latestBackup,
  locale,
  onRun,
  onSavePolicy,
  persistedPolicyReady,
  policy,
  policyConfirmed,
  policyDirty,
  providerWindow,
  providerWindowEligible,
  runPending,
  runReceipt,
  setPolicy,
  setPolicyConfirmed,
  status,
  updatePolicyPending,
  updatePolicySuccess,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  dailyOutcome: { value: string; detail: string };
  datesValid: boolean;
  draftPolicyReady: boolean;
  hasError: boolean;
  latestBackup:
    ShadowResearchAutomationStatus['daily_backups'][number] | undefined;
  locale: string;
  onRun: () => void;
  onSavePolicy: () => void;
  persistedPolicyReady: boolean;
  policy: ShadowResearchPolicyInput;
  policyConfirmed: boolean;
  policyDirty: boolean;
  providerWindow: ShadowResearchAutomationStatus['provider_call_window'];
  providerWindowEligible: boolean;
  runPending: boolean;
  runReceipt: ReturnType<typeof useRunShadowResearchMutation>['data'];
  setPolicy: Dispatch<SetStateAction<ShadowResearchPolicyInput>>;
  setPolicyConfirmed: Dispatch<SetStateAction<boolean>>;
  status: ShadowResearchAutomationStatus | undefined;
  updatePolicyPending: boolean;
  updatePolicySuccess: boolean;
}) {
  return (
    <details
      className="group rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-4"
      data-testid="research-automation-disclosure"
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)] transition-colors">
        <span>
          {locale === 'zh'
            ? '自动化研究运行诊断与策略配置'
            : 'Automation Diagnostics & Policy Configuration'}
        </span>
        <ChevronDown
          aria-hidden="true"
          className="size-4 shrink-0 transition-transform group-open:rotate-180"
        />
      </summary>

      <div className="mt-4 space-y-6">
        <ShadowResearchUsageMetrics
          copy={copy}
          status={status}
          policy={policy}
          providerWindow={providerWindow}
        />

        <div className="grid gap-3 sm:grid-cols-2">
          <StatusMetric
            label={copy.dailyWinner}
            value={dailyOutcome.value}
            detail={dailyOutcome.detail}
          />
          <StatusMetric
            label={copy.backup}
            value={
              latestBackup?.verification_status === 'verified'
                ? copy.backupVerified
                : latestBackup?.verification_status || '—'
            }
            detail={latestBackup?.artifact_fingerprint || '—'}
          />
        </div>

        <p className="sr-only">{copy.fiveCandidateRule}</p>

        <div className="mt-4">
          <ShadowResearchPolicyCard
            copy={copy}
            datesValid={datesValid}
            draftPolicyReady={draftPolicyReady}
            locale={locale}
            onRun={onRun}
            onSavePolicy={onSavePolicy}
            persistedPolicyReady={persistedPolicyReady}
            policy={policy}
            policyConfirmed={policyConfirmed}
            policyDirty={policyDirty}
            providerWindowEligible={providerWindowEligible}
            runPending={runPending}
            runReceipt={runReceipt}
            setPolicy={setPolicy}
            setPolicyConfirmed={setPolicyConfirmed}
            status={status}
            updatePolicyPending={updatePolicyPending}
          />
        </div>
        {updatePolicySuccess ? (
          <p
            role="status"
            className="mt-3 text-sm text-[var(--app-success-text)]"
          >
            {copy.policySaved}
          </p>
        ) : null}
        {hasError ? (
          <p className="mt-3 text-sm text-[var(--app-danger-text)]">
            {copy.failure}
          </p>
        ) : null}
      </div>
    </details>
  );
}
