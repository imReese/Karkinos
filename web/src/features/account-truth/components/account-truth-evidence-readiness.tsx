import { useEffect, useState, type FormEvent } from 'react';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatPublicEvidenceReference } from '../../../shared/public-labels';
import { EvidenceState, StatusBadge } from '../../../shared/ui/workbench';
import {
  hashAccountTruthAccountReference,
  useRecordEvidenceScopeReviewMutation,
  useRevokeEvidenceScopeReviewMutation,
  type AccountTruthEvidenceReadiness,
} from '../api';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode, statusTone } from './account-truth-review-format';
import { ReasonList } from './account-truth-reconciliation-review';

const accountTruthReadinessEvidenceLabels = {
  en: {
    account_truth_import: 'Account Truth import',
    account_truth_evidence_scope: 'Reviewed evidence scope',
    account_truth_score: 'Account Truth score',
    evidence_fingerprint: 'Evidence fingerprint',
    cash_status: 'Cash component',
    position_status: 'Position component',
    fee_status: 'Fee and tax component',
    cost_basis_status: 'Cost-basis component',
    ledger_coverage: 'Freshness and ledger coverage',
    latest: 'Overall gate',
  },
  zh: {
    account_truth_import: '账户事实导入',
    account_truth_evidence_scope: '已复核证据范围',
    account_truth_score: '账户事实评分',
    evidence_fingerprint: '证据指纹',
    cash_status: '现金分项',
    position_status: '持仓分项',
    fee_status: '费用与税费分项',
    cost_basis_status: '成本基础分项',
    ledger_coverage: '新鲜度与账本覆盖',
    latest: '整体门禁',
  },
} as const;

function formatAccountTruthReadinessEvidenceReference(
  value: string | null,
  locale: 'en' | 'zh',
  missingLabel: string,
) {
  if (!value) {
    return missingLabel;
  }
  const [referenceType, ...identityParts] = value.split(':');
  const identity = identityParts.join(':').trim();
  const typeLabels = accountTruthReadinessEvidenceLabels[locale];
  if (referenceType === 'account_truth_score' && identity) {
    const componentLabel =
      typeLabels[identity as keyof typeof typeLabels] ?? identity;
    return `${typeLabels.account_truth_score} · ${componentLabel}`;
  }
  if (
    (referenceType === 'account_truth_import' ||
      referenceType === 'account_truth_evidence_scope') &&
    identity
  ) {
    return `${typeLabels[referenceType]} · ${identity}`;
  }
  if (referenceType === 'sha256' && identity) {
    return `${typeLabels.evidence_fingerprint} · sha256:${identity}`;
  }
  return formatPublicEvidenceReference(value, locale);
}

const accountTruthEvidenceIntakeActions = new Set([
  'import_and_reconcile_broker_evidence',
  'provide_cash_snapshot',
  'provide_position_snapshot',
  'provide_itemized_settlement_or_cash_flow',
  'provide_position_cost_basis_evidence',
  'refresh_broker_evidence_covering_latest_ledger',
  'provide_citic_account_truth_evidence_or_reject_source',
  'review_citic_source_query_windows',
]);

const accountTruthEvidenceScopeActions = new Set([
  'record_reviewed_account_truth_evidence_scope',
  'bind_account_truth_evidence_to_reviewed_account_scope',
  'record_reviewed_account_truth_coverage_window',
  'review_account_truth_asset_scope_completeness',
]);

const accountTruthReconciliationActions = new Set([
  'resolve_account_truth_blockers',
]);

function accountTruthReadinessActionTarget(
  action: string,
  hasCanonicalImport: boolean,
) {
  if (accountTruthEvidenceIntakeActions.has(action)) {
    return 'account-truth-import-tools';
  }
  if (accountTruthEvidenceScopeActions.has(action)) {
    return hasCanonicalImport
      ? 'account-truth-evidence-scope-review'
      : 'account-truth-import-tools';
  }
  if (accountTruthReconciliationActions.has(action)) {
    return 'account-truth-review-workspace';
  }
  return null;
}

export function openAccountTruthReadinessTarget(targetId: string) {
  const target = document.getElementById(targetId);
  if (target instanceof HTMLDetailsElement) {
    target.open = true;
  }
}

function legacySourceResolutionStatusLabel(
  status: string | undefined,
  locale: 'en' | 'zh',
) {
  const labels: Record<string, { en: string; zh: string }> = {
    legacy_source_review_state_unavailable: {
      en: 'review state unavailable',
      zh: '复核状态不可用',
    },
    no_legacy_source_resolution_pending: {
      en: 'no pending legacy source',
      zh: '没有待处理历史来源',
    },
    legacy_query_window_review_required: {
      en: 'query-window review required',
      zh: '仍需查询区间复核',
    },
    legacy_source_scope_review_required: {
      en: 'source-scope review required',
      zh: '仍需来源范围复核',
    },
    legacy_attestations_complete_canonical_resolution_required: {
      en: 'legacy attestations complete; canonical resolution required',
      zh: '历史声明已完成；仍需 canonical 处理',
    },
  };
  const key = status || 'legacy_source_review_state_unavailable';
  return labels[key]?.[locale] ?? formatCode(key, locale, 'status');
}

export function EvidenceReadinessChecklist({
  locale,
  readiness,
}: {
  locale: 'en' | 'zh';
  readiness: AccountTruthEvidenceReadiness | undefined;
}) {
  const text = labels[locale];
  if (!readiness) {
    return <EvidenceState kind="error" title={text.error} />;
  }
  const scope = readiness.evidence_scope;
  const observedWindow = scope.observed_event_window;
  const observedRange =
    observedWindow.occurred_start_date && observedWindow.occurred_end_date
      ? `${observedWindow.occurred_start_date} – ${observedWindow.occurred_end_date}`
      : '--';
  const observedAssets = scope.asset_scope.observed_asset_classes.length
    ? scope.asset_scope.observed_asset_classes
        .map((assetClass) => formatAssetClassLabel(assetClass, text))
        .join(' · ')
    : text.readinessNoObservedAssets;
  const snapshotDates = [
    `${text.readinessCashSnapshotShort} ${scope.snapshot_evidence.latest_cash_snapshot_date ?? '--'}`,
    `${text.readinessPositionSnapshotShort} ${scope.snapshot_evidence.latest_position_snapshot_date ?? '--'}`,
  ].join(' · ');
  const sourceFollowUp = readiness.citic_source_follow_up;
  const queryWindowIntegrityStatus =
    sourceFollowUp?.query_window_batch_integrity_status || 'missing';
  const queryWindowGapDays = Math.max(
    0,
    sourceFollowUp?.query_window_gap_calendar_day_count ?? 0,
  );
  const queryWindowOverlapDays = Math.max(
    0,
    sourceFollowUp?.query_window_overlap_calendar_day_count ?? 0,
  );
  const sourceResolution = sourceFollowUp?.resolution;
  const legacyAttestationsComplete =
    sourceResolution?.legacy_source_attestations_complete === true;
  return (
    <section
      className="min-w-0 px-1 py-4 sm:px-4"
      data-testid="account-truth-evidence-readiness"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {text.readinessRequirements}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {text.readinessKnownSources}:{' '}
            {readiness.known_incomplete_source_count}
          </p>
          <p
            className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]"
            data-testid="account-truth-citic-query-window-integrity"
          >
            {locale === 'zh' ? '查询区间完整性' : 'Query-window integrity'}:{' '}
            {formatCode(queryWindowIntegrityStatus, locale, 'status')} ·{' '}
            {locale === 'zh' ? '缺口天数' : 'gap days'} {queryWindowGapDays} ·{' '}
            {locale === 'zh' ? '重叠天数' : 'overlap days'}{' '}
            {queryWindowOverlapDays}
          </p>
          <p
            className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]"
            data-testid="account-truth-citic-source-resolution"
          >
            {legacyAttestationsComplete
              ? locale === 'zh'
                ? `历史 XLS 声明：${sourceResolution.pending_source_count}/${sourceResolution.pending_source_count} 已复核；无需重做，但仍需单独完成 canonical Account Truth 证据或明确拒绝来源。`
                : `Historical XLS attestations: ${sourceResolution.pending_source_count}/${sourceResolution.pending_source_count} reviewed; no redo is needed, but separate canonical Account Truth evidence or explicit source rejection is still required.`
              : `${locale === 'zh' ? '历史 XLS 声明阶段' : 'Historical XLS attestation stage'}: ${legacySourceResolutionStatusLabel(
                  sourceResolution?.status,
                  locale,
                )}`}
          </p>
        </div>
        <StatusBadge tone={statusTone(readiness.status)}>
          {readiness.status === 'ready'
            ? text.readinessClear
            : formatCode(readiness.status, locale, 'status')}
        </StatusBadge>
      </div>
      <ul className="mt-4 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
        {readiness.items.map((item) => {
          const actionTarget = item.required_action
            ? accountTruthReadinessActionTarget(
                item.required_action,
                Boolean(readiness.account_truth_import_run_id),
              )
            : null;
          return (
            <li
              key={item.requirement}
              className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto] items-start gap-3 py-3"
              data-testid={`account-truth-readiness-item-${item.requirement}`}
            >
              <div className="min-w-0">
                <div className="text-xs font-semibold text-[var(--app-text)]">
                  {formatCode(item.requirement, locale, 'code')}
                </div>
                <dl className="mt-2 grid min-w-0 gap-2 text-xs sm:grid-cols-2">
                  <div className="min-w-0">
                    <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                      {text.readinessItemEvidence}
                    </dt>
                    <dd className="mt-0.5 break-all leading-5 text-[var(--app-text-secondary)]">
                      {formatAccountTruthReadinessEvidenceReference(
                        item.evidence_reference,
                        locale,
                        text.readinessItemNoEvidence,
                      )}
                    </dd>
                  </div>
                  {item.required_action ? (
                    <div className="min-w-0">
                      <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                        {text.readinessItemSafeAction}
                      </dt>
                      <dd className="mt-0.5 leading-5 text-[var(--app-text-secondary)]">
                        {actionTarget ? (
                          <a
                            aria-controls={actionTarget}
                            className="app-button-ghost inline-flex min-h-9 max-w-full items-center rounded-[var(--app-radius-control)] px-2.5 text-left text-xs font-semibold"
                            href={`#${actionTarget}`}
                            onClick={() =>
                              openAccountTruthReadinessTarget(actionTarget)
                            }
                          >
                            {formatCode(item.required_action, locale, 'code')}
                          </a>
                        ) : (
                          formatCode(item.required_action, locale, 'code')
                        )}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </div>
              <StatusBadge tone={statusTone(item.status)}>
                {formatCode(item.status, locale, 'status')}
              </StatusBadge>
            </li>
          );
        })}
      </ul>
      <section
        className="mt-5 border-l-2 border-[var(--app-warning-border)] pl-3"
        data-testid="account-truth-evidence-scope"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-xs font-semibold text-[var(--app-text)]">
              {text.readinessScopeTitle}
            </h3>
            <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
              {text.readinessScopeDetail}
            </p>
          </div>
          <StatusBadge tone={statusTone(scope.status)}>
            {formatCode(scope.status, locale, 'status')}
          </StatusBadge>
        </div>
        <dl className="mt-3 divide-y divide-[var(--app-divider)] text-xs">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
            <dt className="text-[var(--app-text-secondary)]">
              {text.readinessAccountBinding}
            </dt>
            <dd>
              <StatusBadge tone={statusTone(scope.account_binding.status)}>
                {formatCode(scope.account_binding.status, locale, 'status')}
              </StatusBadge>
            </dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
            <dt className="text-[var(--app-text-secondary)]">
              {text.readinessDeclaredWindow}
            </dt>
            <dd>
              <StatusBadge
                tone={statusTone(scope.declared_coverage_window.status)}
              >
                {formatCode(
                  scope.declared_coverage_window.status,
                  locale,
                  'status',
                )}
              </StatusBadge>
            </dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
            <dt className="min-w-0 text-[var(--app-text-secondary)]">
              <span className="block">{text.readinessObservedWindow}</span>
              <span className="mt-0.5 block text-[var(--app-text-tertiary)]">
                {observedRange} ·{' '}
                {text.readinessObservedRows(observedWindow.unique_event_count)}
              </span>
            </dt>
            <dd>
              <StatusBadge tone={statusTone(observedWindow.status)}>
                {formatCode(observedWindow.status, locale, 'status')}
              </StatusBadge>
            </dd>
          </div>
          <div
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2"
            data-testid="account-truth-evidence-scope-assets"
          >
            <dt className="min-w-0 text-[var(--app-text-secondary)]">
              <span className="block">{text.readinessObservedAssets}</span>
              <span className="mt-0.5 block text-[var(--app-text-tertiary)]">
                {observedAssets}
              </span>
            </dt>
            <dd>
              <StatusBadge tone={statusTone(scope.asset_scope.status)}>
                {formatCode(scope.asset_scope.status, locale, 'status')}
              </StatusBadge>
            </dd>
          </div>
          <div className="py-2 text-[var(--app-text-secondary)]">
            <dt>{text.readinessSnapshotDates}</dt>
            <dd className="mt-0.5 text-[var(--app-text-tertiary)]">
              {snapshotDates}
            </dd>
          </div>
        </dl>
        <EvidenceScopeReviewControl locale={locale} readiness={readiness} />
      </section>
      <ReasonList
        title={text.blockingReasons}
        values={readiness.blockers}
        locale={locale}
      />
      <ReasonList
        title={text.requiredActions}
        values={readiness.required_actions}
        locale={locale}
      />
      <div className="mt-4 border-l-2 border-[var(--app-accent-border)] pl-3">
        {readiness.next_manual_action !== 'none' ? (
          <>
            <div className="app-type-overline text-[var(--app-text-tertiary)]">
              {text.readinessNextAction}
            </div>
            <p className="mt-1 text-xs font-semibold text-[var(--app-text)]">
              {formatCode(readiness.next_manual_action, locale, 'code')}
            </p>
          </>
        ) : null}
        <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
          {text.readinessBoundary}
        </p>
      </div>
    </section>
  );
}

function EvidenceScopeReviewControl({
  locale,
  readiness,
}: {
  locale: 'en' | 'zh';
  readiness: AccountTruthEvidenceReadiness;
}) {
  const text = labels[locale];
  const scope = readiness.evidence_scope;
  const recordMutation = useRecordEvidenceScopeReviewMutation();
  const revokeMutation = useRevokeEvidenceScopeReviewMutation();
  const [provider, setProvider] = useState(scope.review?.provider ?? 'citic');
  const [accountAlias, setAccountAlias] = useState('');
  const [accountIdentifier, setAccountIdentifier] = useState('');
  const [coverageStartDate, setCoverageStartDate] = useState('');
  const [coverageEndDate, setCoverageEndDate] = useState('');
  const [reviewedAssets, setReviewedAssets] = useState('');
  const [attested, setAttested] = useState(false);

  useEffect(() => {
    setCoverageStartDate(scope.observed_event_window.occurred_start_date ?? '');
    setCoverageEndDate(scope.observed_event_window.occurred_end_date ?? '');
    setReviewedAssets(scope.asset_scope.observed_asset_classes.join(', '));
    setAccountIdentifier('');
    setAttested(false);
    recordMutation.reset();
    revokeMutation.reset();
  }, [scope.observed_scope_fingerprint]);

  const importRunId = readiness.account_truth_import_run_id;
  const parsedAssets = reviewedAssets
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const canRecord = Boolean(
    importRunId &&
    provider.trim() &&
    accountAlias.trim() &&
    accountIdentifier.trim() &&
    coverageStartDate &&
    coverageEndDate &&
    parsedAssets.length &&
    attested &&
    !recordMutation.isPending,
  );

  const handleRecord = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canRecord || !importRunId) return;
    try {
      const accountReferenceHash = await hashAccountTruthAccountReference(
        provider,
        accountIdentifier,
      );
      setAccountIdentifier('');
      await recordMutation.mutateAsync({
        importRunId,
        expectedObservedScopeFingerprint: scope.observed_scope_fingerprint,
        provider,
        accountAlias,
        accountReferenceHash,
        coverageStartDate,
        coverageEndDate,
        assetClasses: parsedAssets,
        fullAccountScopeAttested: true,
      });
    } catch {
      setAccountIdentifier('');
      // The mutation exposes a sanitized fail-closed state below.
    }
  };

  const inputClass =
    'min-h-10 w-full rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]';

  if (!importRunId) return null;
  if (scope.status === 'complete') {
    return (
      <div
        className="mt-4 rounded-[var(--app-radius-control)] border border-[var(--app-success-border)] bg-[var(--app-success-bg)] p-3"
        data-testid="account-truth-evidence-scope-review-complete"
        id="account-truth-evidence-scope-review"
      >
        <p className="text-xs font-semibold text-[var(--app-text)]">
          {text.scopeReviewComplete}
        </p>
        <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
          {scope.account_binding.account_alias} ·{' '}
          {scope.declared_coverage_window.start_date} –{' '}
          {scope.declared_coverage_window.end_date}
        </p>
        <p className="mt-2 text-xs leading-5 text-[var(--app-text-tertiary)]">
          {text.scopeReviewBoundary}
        </p>
        <button
          className="mt-3 min-h-10 rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] px-3 py-2 text-xs font-semibold text-[var(--app-danger)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] disabled:opacity-50"
          disabled={revokeMutation.isPending}
          type="button"
          onClick={() =>
            revokeMutation.mutate({
              importRunId,
              expectedObservedScopeFingerprint:
                scope.observed_scope_fingerprint,
            })
          }
        >
          {revokeMutation.isPending
            ? text.scopeReviewRevoking
            : text.scopeReviewRevoke}
        </button>
        {revokeMutation.isError ? (
          <p className="mt-2 text-xs text-[var(--app-danger)]">
            {text.scopeReviewFailed}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <form
      className="mt-4 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3"
      data-testid="account-truth-evidence-scope-review-form"
      id="account-truth-evidence-scope-review"
      onSubmit={handleRecord}
    >
      <h4 className="text-xs font-semibold text-[var(--app-text)]">
        {text.scopeReviewTitle}
      </h4>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {text.scopeReviewDetail}
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewProvider}
          <input
            className={inputClass}
            data-testid="account-truth-scope-provider"
            maxLength={64}
            value={provider}
            onChange={(event) => setProvider(event.currentTarget.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewAccountAlias}
          <input
            className={inputClass}
            data-testid="account-truth-scope-account-alias"
            maxLength={128}
            value={accountAlias}
            onChange={(event) => setAccountAlias(event.currentTarget.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)] sm:col-span-2">
          {text.scopeReviewAccountIdentifier}
          <input
            autoComplete="off"
            className={inputClass}
            data-testid="account-truth-scope-account-identifier"
            maxLength={256}
            type="password"
            value={accountIdentifier}
            onChange={(event) =>
              setAccountIdentifier(event.currentTarget.value)
            }
          />
          <span className="font-normal leading-5 text-[var(--app-text-tertiary)]">
            {text.scopeReviewAccountIdentifierHelp}
          </span>
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewStartDate}
          <input
            className={inputClass}
            data-testid="account-truth-scope-start-date"
            type="date"
            value={coverageStartDate}
            onChange={(event) =>
              setCoverageStartDate(event.currentTarget.value)
            }
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewEndDate}
          <input
            className={inputClass}
            data-testid="account-truth-scope-end-date"
            type="date"
            value={coverageEndDate}
            onChange={(event) => setCoverageEndDate(event.currentTarget.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)] sm:col-span-2">
          {text.scopeReviewAssets}
          <input
            className={inputClass}
            data-testid="account-truth-scope-assets"
            value={reviewedAssets}
            onChange={(event) => setReviewedAssets(event.currentTarget.value)}
          />
        </label>
      </div>
      <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--app-text-secondary)]">
        <input
          checked={attested}
          className="mt-1 size-4 shrink-0 accent-[var(--app-accent)]"
          data-testid="account-truth-scope-attestation"
          type="checkbox"
          onChange={(event) => setAttested(event.currentTarget.checked)}
        />
        <span>{text.scopeReviewAttestation}</span>
      </label>
      <button
        className="mt-3 min-h-10 rounded-[var(--app-radius-control)] bg-[var(--app-accent)] px-4 py-2 text-xs font-semibold text-[var(--app-text-inverse)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!canRecord}
        type="submit"
      >
        {recordMutation.isPending
          ? text.scopeReviewRecording
          : text.scopeReviewSubmit}
      </button>
      {recordMutation.isSuccess ? (
        <p className="mt-2 text-xs font-semibold text-[var(--app-success)]">
          {text.scopeReviewRecorded}
        </p>
      ) : null}
      {recordMutation.isError ? (
        <p className="mt-2 text-xs font-semibold text-[var(--app-danger)]">
          {text.scopeReviewFailed}
        </p>
      ) : null}
      <p className="mt-3 text-xs leading-5 text-[var(--app-text-tertiary)]">
        {text.scopeReviewBoundary}
      </p>
    </form>
  );
}
