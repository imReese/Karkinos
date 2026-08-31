import {
  useControlledBrokerWriteReleaseApprovalChallengeMutation,
  useControlledBrokerWriteReleaseRevocationMutation,
  useControlledBrokerWriteReleaseRevocationPreviewMutation,
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

export function RevocationReview({
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
  revoke,
  onRevokeRelease,
}: {
  locale: Locale;
  preview: ReturnType<
    typeof useControlledBrokerWriteReleaseRevocationPreviewMutation
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
  revoke: ReturnType<typeof useControlledBrokerWriteReleaseRevocationMutation>;
  onRevokeRelease: () => void;
}) {
  return (
    <>
      {preview.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(preview.error)}
        </div>
      ) : null}
      {preview.data ? (
        <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger-border)_72%,transparent)] p-3 text-xs">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <span className="truncate" title={preview.data.release_evidence_id}>
              {shortenedIdentity(preview.data.release_evidence_id)}
            </span>
            <span className="app-chip">
              {formatPublicStatus(preview.data.status, locale)}
            </span>
          </div>
          {preview.data.blockers.length ? (
            <ul className="app-muted mt-2 grid gap-1 pl-5">
              {preview.data.blockers.map((blocker) => (
                <li className="list-disc break-words" key={blocker}>
                  {formatPublicOperationalNote(blocker, locale)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {preview.data?.ready ? (
        <OfflineSignatureSteps
          locale={locale}
          action="revoke_controlled_broker_write_release"
          artifactType="controlled_broker_write_release_revocation"
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
                ? '我确认永久撤销这一精确 release；它不会恢复，也不会提交、撤销或查询任何券商订单。'
                : 'I confirm permanently revoking this exact release. It cannot resume and will not submit, cancel, or query any broker order.'}
            </span>
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
            disabled={!acknowledged || revoke.isPending}
            onClick={onRevokeRelease}
          >
            {revoke.isPending
              ? locale === 'zh'
                ? '撤销中'
                : 'Revoking'
              : locale === 'zh'
                ? '永久撤销该 release 一次'
                : 'Permanently revoke this release once'}
          </button>
        </div>
      ) : null}

      {revoke.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(revoke.error)}
        </div>
      ) : null}
      {revoke.data ? (
        <div
          className="mt-2 break-words text-xs text-[var(--app-success-text)]"
          role="status"
        >
          {locale === 'zh' ? '已永久撤销：' : 'Permanently revoked: '}
          {shortenedIdentity(revoke.data.release_evidence_id)}
        </div>
      ) : null}
    </>
  );
}
