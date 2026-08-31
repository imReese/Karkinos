import {
  useControlledBrokerWriteReleaseApprovalChallengeMutation,
  useOperatorApprovalVerificationMutation,
} from '../api';
import {
  mutationError,
  shortenedIdentity,
  type Locale,
  type TrustedSignerIdentity,
} from './contracts';

export function OfflineSignatureSteps({
  locale,
  action,
  artifactType,
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
}: {
  locale: Locale;
  action:
    | 'issue_controlled_broker_write_release'
    | 'revoke_controlled_broker_write_release';
  artifactType:
    | 'controlled_broker_write_release_dossier'
    | 'controlled_broker_write_release_revocation';
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
}) {
  return (
    <div className="mt-3 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] pt-3">
      {identities.length === 0 ? (
        <div className="app-error-text text-xs">
          {locale === 'zh'
            ? '没有启用的可信离线签名身份；mutation 保持关闭。'
            : 'No enabled trusted offline signer identity is configured; mutation remains closed.'}
        </div>
      ) : (
        <>
          <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '可信签名身份' : 'Trusted signer identity'}
            <select
              aria-label={
                locale === 'zh'
                  ? '选择可信签名身份'
                  : 'Select trusted signer identity'
              }
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              value={effectiveKeyId}
              onChange={(event) => onIdentityChange(event.target.value)}
            >
              {identities.map((identity) => (
                <option key={identity.key_id} value={identity.key_id}>
                  {identity.operator_id} · {identity.key_id}
                </option>
              ))}
            </select>
          </label>
          {selectedIdentity ? (
            <div className="app-muted mt-2 truncate text-xs">
              key fingerprint:{' '}
              {shortenedIdentity(selectedIdentity.public_key_fingerprint)}
            </div>
          ) : null}
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
            disabled={!selectedIdentity || challenge.isPending}
            onClick={onCreateChallenge}
          >
            {challenge.isPending
              ? locale === 'zh'
                ? '创建中'
                : 'Creating'
              : locale === 'zh'
                ? '创建 3 分钟离线签名 challenge'
                : 'Create 3-minute offline signing challenge'}
          </button>
        </>
      )}

      {challenge.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(challenge.error)}
        </div>
      ) : null}
      {challenge.data ? (
        <div className="mt-3 min-w-0">
          <div className="app-muted text-xs leading-5">
            {locale === 'zh'
              ? `使用 scripts/broker/operator_signer.py，expected action 为 ${action}，artifact type 为 ${artifactType}。只粘贴 payload；私钥不得进入 Karkinos。`
              : `Use scripts/broker/operator_signer.py with expected action ${action} and artifact type ${artifactType}. Paste only the payload; the private key must never enter Karkinos.`}
          </div>
          <textarea
            aria-label={
              locale === 'zh' ? '离线签名 payload' : 'Offline signing payload'
            }
            className="app-field mt-2 min-h-20 w-full rounded-xl px-3 py-2 font-mono text-xs"
            readOnly
            value={challenge.data.signing_payload_base64}
          />
          <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '离线签名 Base64' : 'Offline signature Base64'}
            <textarea
              aria-label={
                locale === 'zh' ? '离线签名 Base64' : 'Offline signature Base64'
              }
              className="app-field min-h-20 w-full rounded-xl px-3 py-2 font-mono text-xs"
              value={signature}
              onChange={(event) => onSignatureChange(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!signature.trim() || verification.isPending}
            onClick={onVerifySignature}
          >
            {verification.isPending
              ? locale === 'zh'
                ? '验证中'
                : 'Verifying'
              : locale === 'zh'
                ? '验证离线签名'
                : 'Verify offline signature'}
          </button>
        </div>
      ) : null}

      {verification.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(verification.error)}
        </div>
      ) : null}
      {verification.data ? (
        <div
          className="mt-2 text-xs text-[var(--app-success-text)]"
          role="status"
        >
          {locale === 'zh'
            ? '可信身份验证通过：'
            : 'Trusted identity verified: '}
          {verification.data.operator_id}
        </div>
      ) : null}
    </div>
  );
}
