import { useState } from 'react';

import {
  ControlledActionZone,
  EvidenceState,
  StatusBadge,
} from '../../../shared/ui/workbench';
import type { CiticSourceIntake } from '../api';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode } from './account-truth-review-format';

export function CiticSourceIntakeHistory({
  intakes,
  isError,
  isPending,
  locale,
  onRevokeQueryWindow,
  revokePending,
}: {
  intakes: CiticSourceIntake[];
  isError: boolean;
  isPending: boolean;
  locale: 'en' | 'zh';
  onRevokeQueryWindow: (intake: CiticSourceIntake) => Promise<void>;
  revokePending: boolean;
}) {
  const text = labels[locale];
  const [revokeIntentId, setRevokeIntentId] = useState<string | null>(null);
  if (isPending) {
    return (
      <EvidenceState className="mt-4" kind="loading" title={text.loading} />
    );
  }
  if (isError) {
    return (
      <EvidenceState
        className="mt-4"
        kind="error"
        title={text.citicIntakeFailed}
      />
    );
  }
  return (
    <details className="mt-4 border-y border-[var(--app-divider)] py-3">
      <summary className="app-button-ghost flex min-h-10 cursor-pointer items-center justify-between rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        <span>{text.citicIntakeHistory}</span>
        <span className="tabular-nums">{intakes.length}</span>
      </summary>
      {intakes.length === 0 ? (
        <p className="mt-2 px-2.5 text-xs text-[var(--app-text-secondary)]">
          {text.citicNoIntakes}
        </p>
      ) : (
        <div className="mt-2 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {intakes.map((intake) => (
            <div
              className="grid gap-1 px-3 py-2.5 text-xs"
              key={intake.intake_id}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <span className="font-semibold text-[var(--app-text)]">
                  {intake.review_status === 'rejected'
                    ? text.citicRejectionSaved
                    : text.citicIntakeSaved}
                </span>
                <StatusBadge
                  tone={
                    intake.review_status === 'rejected' ? 'danger' : 'warning'
                  }
                >
                  {formatCode(intake.review_status, locale, 'status')}
                </StatusBadge>
              </div>
              <div className="app-type-micro break-all font-mono text-[var(--app-text-tertiary)]">
                SHA-256 {intake.file_fingerprint}
              </div>
              <div className="app-type-micro text-[var(--app-text-secondary)]">
                {text.validRows}: {intake.valid_row_count} · {text.invalidRows}:{' '}
                {intake.invalid_row_count} · {text.citicRecognizedEvents}:{' '}
                {intake.recognized_event_count}
                {intake.recognized_non_financial_activity_count > 0
                  ? ` · ${text.citicRecognizedNonFinancialActivities}: ${intake.recognized_non_financial_activity_count}`
                  : ''}
              </div>
              {intake.query_window_review ? (
                <div className="mt-1 border-t border-[var(--app-divider)] pt-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="app-type-micro text-[var(--app-text-secondary)]">
                      {text.citicQueryWindowLabel}:{' '}
                      {intake.query_window_review.query_start_date} —{' '}
                      {intake.query_window_review.query_end_date}
                    </div>
                    <StatusBadge
                      tone={
                        intake.query_window_review.effective_status === 'active'
                          ? 'info'
                          : 'neutral'
                      }
                    >
                      {intake.query_window_review.effective_status === 'active'
                        ? text.citicQueryWindowActive
                        : text.citicQueryWindowRevoked}
                    </StatusBadge>
                  </div>
                  {intake.source_scope_review ? (
                    <div className="mt-2 flex flex-wrap items-start justify-between gap-2 border-t border-[var(--app-divider)] pt-2">
                      <div className="app-type-micro text-[var(--app-text-secondary)]">
                        {text.citicSourceScopeLabel}:{' '}
                        {intake.source_scope_review.account_alias} ·{' '}
                        {intake.source_scope_review.account_type} ·{' '}
                        {intake.source_scope_review.market_scopes.join(', ')} ·{' '}
                        {intake.source_scope_review.asset_classes.join(', ')} ·{' '}
                        {intake.source_scope_review.account_value_band ||
                          'unverified'}
                      </div>
                      <StatusBadge
                        tone={
                          intake.source_scope_review.effective_status ===
                          'active'
                            ? 'info'
                            : 'neutral'
                        }
                      >
                        {intake.source_scope_review.effective_status ===
                        'active'
                          ? text.citicQueryWindowActive
                          : text.citicQueryWindowRevoked}
                      </StatusBadge>
                    </div>
                  ) : null}
                  <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                    {text.citicQueryWindowStillBlocked}
                  </p>
                  {intake.query_window_review.effective_status === 'active' &&
                  revokeIntentId !== intake.intake_id ? (
                    <button
                      className="app-button-ghost mt-2 min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={revokePending}
                      type="button"
                      onClick={() => setRevokeIntentId(intake.intake_id)}
                    >
                      {text.citicQueryWindowRevoke}
                    </button>
                  ) : null}
                  {revokeIntentId === intake.intake_id ? (
                    <ControlledActionZone
                      className="mt-2"
                      description={text.citicQueryWindowRevokeBody}
                      evidence={intake.query_window_review.review_fingerprint}
                      layout="stack"
                      title={text.citicQueryWindowRevokeConfirm}
                      tone="danger"
                    >
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={revokePending}
                          type="button"
                          onClick={async () => {
                            await onRevokeQueryWindow(intake);
                            setRevokeIntentId(null);
                          }}
                        >
                          {revokePending
                            ? text.citicQueryWindowRevoking
                            : text.citicQueryWindowRevokeConfirmAction}
                        </button>
                        <button
                          className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={revokePending}
                          type="button"
                          onClick={() => setRevokeIntentId(null)}
                        >
                          {text.citicCancelAction}
                        </button>
                      </div>
                    </ControlledActionZone>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}
