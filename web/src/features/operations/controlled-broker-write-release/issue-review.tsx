import {
  useControlledBrokerWriteReleaseApprovalChallengeMutation,
  useControlledBrokerWriteReleaseDossierPreviewMutation,
  useControlledBrokerWriteReleaseIssueMutation,
  useOperatorApprovalVerificationMutation,
} from '../api';
import {
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  mutationError,
  shortenedIdentity,
  type Locale,
  type TrustedSignerIdentity,
} from './contracts';
import { OfflineSignatureSteps } from './offline-signature-steps';

export function IssueReleaseReview({
  locale,
  preview,
  identities,
  effectiveKeyId,
  selectedIdentity,
  onIdentityChange,
  challenge,
  verification,
  signature,
  onSignatureChange,
  onCreateChallenge,
  onVerifySignature,
  acknowledged,
  onAcknowledgementChange,
  issue,
  onIssueRelease,
}: {
  locale: Locale;
  preview: ReturnType<
    typeof useControlledBrokerWriteReleaseDossierPreviewMutation
  >;
  identities: TrustedSignerIdentity[];
  effectiveKeyId: string;
  selectedIdentity: TrustedSignerIdentity | null;
  onIdentityChange: (keyId: string) => void;
  challenge: ReturnType<
    typeof useControlledBrokerWriteReleaseApprovalChallengeMutation
  >;
  verification: ReturnType<typeof useOperatorApprovalVerificationMutation>;
  signature: string;
  onSignatureChange: (value: string) => void;
  onCreateChallenge: () => void;
  onVerifySignature: () => void;
  acknowledged: boolean;
  onAcknowledgementChange: (value: boolean) => void;
  issue: ReturnType<typeof useControlledBrokerWriteReleaseIssueMutation>;
  onIssueRelease: () => void;
}) {
  return (
    <>
      {preview.data ? (
        <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] p-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-[var(--app-text)]">
              {preview.data.scope.provider || '—'} ·{' '}
              {preview.data.scope.account_alias || '—'}
            </span>
            <span className="app-chip">
              {formatPublicStatus(preview.data.review_status, locale)}
            </span>
          </div>
          <div className="app-muted mt-2 grid min-w-0 gap-1 text-xs sm:grid-cols-2">
            <div className="truncate" title={preview.data.dossier_fingerprint}>
              dossier: {shortenedIdentity(preview.data.dossier_fingerprint)}
            </div>
            <div className="truncate" title={preview.data.scope.gateway_id}>
              gateway: {preview.data.scope.gateway_id || '—'}
            </div>
            <div>{preview.data.effective_at}</div>
            <div>{preview.data.expires_at}</div>
          </div>
          {preview.data.review_blockers.length ? (
            <ul className="app-muted mt-2 grid gap-1 pl-5 text-xs">
              {preview.data.review_blockers.slice(0, 8).map((blocker) => (
                <li className="list-disc break-words" key={blocker}>
                  {formatPublicOperationalNote(blocker, locale)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {preview.data?.review_ready ? (
        <OfflineSignatureSteps
          locale={locale}
          action="issue_controlled_broker_write_release"
          artifactType="controlled_broker_write_release_dossier"
          identities={identities}
          effectiveKeyId={effectiveKeyId}
          selectedIdentity={selectedIdentity}
          onIdentityChange={onIdentityChange}
          challenge={challenge}
          verification={verification}
          signature={signature}
          onSignatureChange={onSignatureChange}
          onCreateChallenge={onCreateChallenge}
          onVerifySignature={onVerifySignature}
        />
      ) : null}

      {verification.data ? (
        <div className="mt-3">
          <label className="flex items-start gap-2 text-xs leading-5 text-[var(--app-text-secondary)]">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) =>
                onAcknowledgementChange(event.target.checked)
              }
            />
            <span>
              {locale === 'zh'
                ? '我确认仅签发这一精确、会过期的 manual_each_order 能力放行；它不注册 gateway、不提交或撤销订单，也不授予资本权限。'
                : 'I confirm issuing only this exact, expiring manual_each_order capability release. It registers no gateway, submits or cancels no order, and grants no capital authority.'}
            </span>
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!acknowledged || issue.isPending}
            onClick={onIssueRelease}
          >
            {issue.isPending
              ? locale === 'zh'
                ? '记录中'
                : 'Recording'
              : locale === 'zh'
                ? '记录限时能力放行'
                : 'Record time-bounded capability release'}
          </button>
        </div>
      ) : null}

      {issue.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(issue.error)}
        </div>
      ) : null}
      {issue.data ? (
        <div
          className="mt-2 break-words text-xs text-[var(--app-success-text)]"
          role="status"
        >
          {locale === 'zh' ? '已记录：' : 'Recorded: '}
          {shortenedIdentity(issue.data.release_evidence_id)} ·{' '}
          {issue.data.expires_at}
        </div>
      ) : null}
    </>
  );
}
