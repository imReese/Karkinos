import { formatTimestamp } from '../../../shared/format';
import type {
  useRunShadowResearchMutation,
  useShadowResearchAutomationQuery,
  ShadowResearchPolicyInput,
} from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { Field, NumberField, StatusMetric } from './shadow-research-view';

export const MAX_PROVIDER_CALLS = 10;
export const MAX_CANDIDATES = 5;

export function hasValidResearchDates(policy: ShadowResearchPolicyInput) {
  return (
    (!policy.research_end_date && !policy.sealed_end_date) ||
    Boolean(
      policy.research_end_date &&
      policy.sealed_end_date &&
      policy.research_end_date < policy.sealed_end_date,
    )
  );
}

function FinalEvaluationDates({
  policy,
  onChange,
  copy,
}: {
  policy: ShadowResearchPolicyInput;
  onChange: (
    dates: Pick<
      ShadowResearchPolicyInput,
      'research_end_date' | 'sealed_end_date'
    >,
  ) => void;
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
}) {
  return (
    <>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Field
          label={copy.researchEndDate}
          type="date"
          value={policy.research_end_date ?? ''}
          onChange={(value) => onChange({ research_end_date: value || null })}
        />
        <Field
          label={copy.sealedEndDate}
          type="date"
          value={policy.sealed_end_date ?? ''}
          onChange={(value) => onChange({ sealed_end_date: value || null })}
        />
      </div>
      <p className="sr-only">{copy.sealedDatesDetail}</p>
      {!hasValidResearchDates(policy) ? (
        <p role="alert" className="mt-2 text-sm text-[var(--app-danger-text)]">
          {copy.sealedDatesInvalid}
        </p>
      ) : null}
    </>
  );
}

export function ShadowResearchPolicyCard({
  copy,
  datesValid,
  draftPolicyReady,
  locale,
  onRun,
  onSavePolicy,
  persistedPolicyReady,
  policy,
  policyConfirmed,
  policyDirty,
  providerWindowEligible,
  runPending,
  runReceipt,
  setPolicy,
  setPolicyConfirmed,
  status,
  updatePolicyPending,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  datesValid: boolean;
  draftPolicyReady: boolean;
  locale: string;
  onRun: () => void;
  onSavePolicy: () => void;
  persistedPolicyReady: boolean;
  policy: ShadowResearchPolicyInput;
  policyConfirmed: boolean;
  policyDirty: boolean;
  providerWindowEligible: boolean;
  runPending: boolean;
  runReceipt: ReturnType<typeof useRunShadowResearchMutation>['data'];
  setPolicy: React.Dispatch<React.SetStateAction<ShadowResearchPolicyInput>>;
  setPolicyConfirmed: React.Dispatch<React.SetStateAction<boolean>>;
  status: ReturnType<typeof useShadowResearchAutomationQuery>['data'];
  updatePolicyPending: boolean;
}) {
  return (
    <fieldset
      disabled={updatePolicyPending || runPending}
      className="mt-5 min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh' ? '自动研究设置' : 'Recurring research settings'}
          </h3>
        </div>
        <span
          className={`app-type-micro inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-semibold ${
            status?.policy.enabled
              ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
              : 'border-[var(--app-divider)] text-[var(--app-text-tertiary)]'
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              status?.policy.enabled
                ? 'bg-[var(--app-success-text)]'
                : 'bg-[var(--app-text-tertiary)]'
            }`}
          />
          {copy.savedPolicy} ·{' '}
          {status?.policy.enabled ? copy.enabled : copy.disabled}
        </span>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <label className="min-w-0 text-xs font-semibold text-[var(--app-text)]">
          {copy.question}
          <textarea
            className="app-input mt-2 min-h-24 w-full resize-y"
            onChange={(event) =>
              setPolicy((current) => ({
                ...current,
                research_question: event.target.value,
              }))
            }
            value={policy.research_question}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <Field
            label={copy.operator}
            onChange={(value) =>
              setPolicy((current) => ({ ...current, updated_by: value }))
            }
            value={policy.updated_by}
          />
          <Field
            label={copy.closeTime}
            onChange={(value) =>
              setPolicy((current) => ({
                ...current,
                after_close_time: value,
              }))
            }
            type="time"
            value={policy.after_close_time}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <NumberField
          label={copy.calls}
          max={MAX_PROVIDER_CALLS}
          min={2}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              max_provider_calls_per_market_date: value,
              max_candidates_per_run: Math.min(
                current.max_candidates_per_run,
                Math.max(1, Math.floor(value / 2)),
              ),
            }))
          }
          value={policy.max_provider_calls_per_market_date}
        />
        <StatusMetric
          detail={copy.providerLimitsRemain}
          label={copy.tokenPolicy}
          value={copy.unboundedDailyTokens}
        />
        <NumberField
          label={copy.candidates}
          max={Math.min(
            MAX_CANDIDATES,
            Math.max(
              1,
              Math.floor(policy.max_provider_calls_per_market_date / 2),
            ),
          )}
          min={1}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              max_candidates_per_run: value,
            }))
          }
          value={policy.max_candidates_per_run}
        />
      </div>

      <FinalEvaluationDates
        policy={policy}
        copy={copy}
        onChange={(dates) => {
          setPolicy((current) => ({ ...current, ...dates }));
          setPolicyConfirmed(false);
        }}
      />

      <div className="mt-4 space-y-4 border-t border-[var(--app-divider)] pt-4">
        <div>
          <label className="flex min-h-11 w-fit items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
            <input
              checked={policy.enabled}
              onChange={(event) => {
                setPolicy((current) => ({
                  ...current,
                  enabled: event.target.checked,
                }));
                setPolicyConfirmed(false);
              }}
              type="checkbox"
            />
            {copy.enableResearch}
          </label>
          <p className="text-xs leading-5 text-[var(--app-muted)]">
            {copy.policyEditDetail}
          </p>
        </div>
        {policy.enabled ? (
          <div>
            <h4 className="text-xs font-semibold text-[var(--app-text)]">
              {copy.authorizationScope}
            </h4>
            <ul className="mt-2 max-w-4xl list-disc space-y-1 pl-5 text-xs leading-5 text-[var(--app-muted)]">
              <li>{copy.scopeRounds}</li>
              <li>{copy.scopeUsage}</li>
              <li>{copy.scopeAuthority}</li>
            </ul>
          </div>
        ) : null}
        <label className="flex min-h-11 min-w-0 w-fit items-start gap-2 py-2 text-sm leading-6 text-[var(--app-text)]">
          <input
            checked={policyConfirmed}
            className="mt-1.5 shrink-0"
            onChange={(event) => setPolicyConfirmed(event.target.checked)}
            type="checkbox"
          />
          <span>{policy.enabled ? copy.confirmEnable : copy.confirmPause}</span>
        </label>
        <div className="flex flex-col gap-3 border-t border-[var(--app-divider)] pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <p
            className="max-w-xl text-xs leading-5 text-[var(--app-muted)]"
            id="shadow-policy-run-detail"
            role="status"
          >
            {policyDirty ? copy.unsavedPolicy : copy.runSavedPolicy}
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              className="app-button-primary min-h-11 px-4 py-2 text-sm font-semibold"
              disabled={
                updatePolicyPending ||
                !policyConfirmed ||
                !datesValid ||
                !policy.updated_by.trim() ||
                !policy.research_question.trim() ||
                (policy.enabled && !draftPolicyReady)
              }
              onClick={onSavePolicy}
              type="button"
            >
              {updatePolicyPending ? copy.saving : copy.save}
            </button>
            <button
              aria-describedby="shadow-policy-run-detail"
              className="app-button-secondary min-h-11 px-4 py-2 text-sm font-semibold"
              disabled={
                runPending ||
                policyDirty ||
                !status?.policy?.enabled ||
                !persistedPolicyReady ||
                !providerWindowEligible
              }
              onClick={onRun}
              type="button"
            >
              {runPending ? copy.running : copy.run}
            </button>
          </div>
        </div>
      </div>
      {runReceipt ? (
        <div
          role="status"
          className="mt-3 text-sm leading-6 text-[var(--app-muted)]"
        >
          {runReceipt.status === 'enqueued' ||
          runReceipt.status === 'already_enqueued' ? (
            <>
              <p>
                {runReceipt.status === 'enqueued'
                  ? copy.runEnqueued
                  : copy.runAlreadyEnqueued}
              </p>
              {runReceipt.available_at ? (
                <p>
                  {copy.runScheduledFor} ·{' '}
                  {formatTimestamp(runReceipt.available_at)}
                </p>
              ) : null}
              <p className="text-xs">{copy.runProviderPending}</p>
            </>
          ) : (
            <p className="text-[var(--app-warning-text)]">
              {copy.runBlocked}{' '}
              {copy.runBlockedReasons[
                runReceipt.failure_code as keyof typeof copy.runBlockedReasons
              ] ?? runReceipt.failure_code}
            </p>
          )}
        </div>
      ) : null}
      {policy.enabled && !draftPolicyReady && (
        <p className="mt-3 text-sm text-[var(--app-danger-text)]">
          {copy.fiveRoundPolicyBlocked}
        </p>
      )}
      {status?.policy.enabled && !persistedPolicyReady && draftPolicyReady && (
        <p className="mt-3 text-sm text-[var(--app-danger-text)]">
          {copy.normalizedMigrationRequired}
        </p>
      )}
    </fieldset>
  );
}
