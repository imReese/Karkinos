import type {
  ControlledBrokerWriteReleaseEvidence,
  ControlledBrokerWriteReleaseRevocationReason,
} from '../api';
import {
  REVOCATION_REASONS,
  revocationReasonLabel,
  type Locale,
} from './contracts';

export function RevocationForm({
  locale,
  releases,
  loading,
  error,
  effectiveReleaseId,
  selectedRelease,
  onReleaseChange,
  reason,
  onReasonChange,
  previewPending,
  onLoadPreview,
}: {
  locale: Locale;
  releases: ControlledBrokerWriteReleaseEvidence[];
  loading: boolean;
  error: string;
  effectiveReleaseId: string;
  selectedRelease: ControlledBrokerWriteReleaseEvidence | null;
  onReleaseChange: (value: string) => void;
  reason: ControlledBrokerWriteReleaseRevocationReason;
  onReasonChange: (value: ControlledBrokerWriteReleaseRevocationReason) => void;
  previewPending: boolean;
  onLoadPreview: () => void;
}) {
  if (loading) {
    return (
      <div className="app-muted mt-3 text-xs">
        {locale === 'zh' ? '读取 release…' : 'Loading releases…'}
      </div>
    );
  }
  if (error) {
    return (
      <div className="app-error-text mt-3 text-xs" role="alert">
        {error}
      </div>
    );
  }
  if (releases.length === 0) {
    return (
      <div className="app-muted mt-3 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] p-3 text-xs">
        {locale === 'zh'
          ? '尚无持久化 write release；系统保持默认关闭。'
          : 'No persisted write release exists; the system remains default closed.'}
      </div>
    );
  }
  return (
    <>
      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '选择 release' : 'Select release'}
        <select
          aria-label={
            locale === 'zh' ? '选择撤销 release' : 'Select release to revoke'
          }
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={effectiveReleaseId}
          onChange={(event) => onReleaseChange(event.target.value)}
        >
          {releases.map((release) => (
            <option
              key={release.release_evidence_id}
              value={release.release_evidence_id}
            >
              {release.provider} · {release.account_alias} · {release.status}
            </option>
          ))}
        </select>
      </label>
      {selectedRelease ? (
        <div className="app-muted mt-2 grid min-w-0 gap-1 text-xs sm:grid-cols-2">
          <div className="truncate" title={selectedRelease.gateway_id}>
            gateway: {selectedRelease.gateway_id || '—'}
          </div>
          <div>{selectedRelease.expires_at || '—'}</div>
        </div>
      ) : null}
      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '撤销原因' : 'Revocation reason'}
        <select
          aria-label={
            locale === 'zh' ? '选择撤销原因' : 'Select revocation reason'
          }
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={reason}
          onChange={(event) =>
            onReasonChange(
              event.target
                .value as ControlledBrokerWriteReleaseRevocationReason,
            )
          }
        >
          {REVOCATION_REASONS.map((value) => (
            <option key={value} value={value}>
              {revocationReasonLabel(value, locale)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
        disabled={previewPending}
        onClick={onLoadPreview}
      >
        {previewPending
          ? locale === 'zh'
            ? '生成中'
            : 'Loading'
          : locale === 'zh'
            ? '生成只读撤销预览'
            : 'Generate read-only revocation preview'}
      </button>
    </>
  );
}
