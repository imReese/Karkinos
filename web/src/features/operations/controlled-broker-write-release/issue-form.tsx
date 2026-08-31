import type {
  BrokerAdapterReadinessRelease,
  ControlledBrokerWriteReleaseOwnerReviewRefs,
} from '../api';
import {
  OWNER_REVIEW_FIELDS,
  ownerReviewLabel,
  shortenedIdentity,
  type Locale,
  type OwnerReviewRefField,
} from './contracts';

export function IssueReleaseForm({
  locale,
  readonlyCandidates,
  effectiveReleaseRef,
  onReleaseRefChange,
  soakAcceptanceId,
  manifestText,
  onManifestTextChange,
  durationSeconds,
  onDurationChange,
  ownerRefs,
  onOwnerRefChange,
  previewPending,
  onLoadPreview,
  manifestError,
  previewError,
}: {
  locale: Locale;
  readonlyCandidates: BrokerAdapterReadinessRelease[];
  effectiveReleaseRef: string;
  onReleaseRefChange: (value: string) => void;
  soakAcceptanceId: string;
  manifestText: string;
  onManifestTextChange: (value: string) => void;
  durationSeconds: number;
  onDurationChange: (value: number) => void;
  ownerRefs: ControlledBrokerWriteReleaseOwnerReviewRefs;
  onOwnerRefChange: (field: OwnerReviewRefField, value: string) => void;
  previewPending: boolean;
  onLoadPreview: () => void;
  manifestError: string;
  previewError: string;
}) {
  return (
    <>
      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '只读 adapter release' : 'Read-only adapter release'}
        <select
          aria-label={
            locale === 'zh'
              ? '选择只读 adapter release'
              : 'Select read-only adapter release'
          }
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={effectiveReleaseRef}
          onChange={(event) => onReleaseRefChange(event.target.value)}
        >
          {readonlyCandidates.length === 0 ? (
            <option value="">
              {locale === 'zh'
                ? '无可用只读 release'
                : 'No eligible read-only release'}
            </option>
          ) : null}
          {readonlyCandidates.map((release) => (
            <option
              key={release.release_evidence_ref}
              value={release.release_evidence_ref}
            >
              {release.provider} · {release.account_alias} ·{' '}
              {release.release_evidence_ref}
            </option>
          ))}
        </select>
      </label>

      <div className="app-muted mt-2 break-words text-xs">
        {locale === 'zh' ? '精确 soak acceptance：' : 'Exact soak acceptance: '}
        {soakAcceptanceId
          ? shortenedIdentity(soakAcceptanceId)
          : locale === 'zh'
            ? '缺失或未通过'
            : 'missing or not accepted'}
      </div>

      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        Execution-edge manifest JSON
        <textarea
          aria-label="Execution-edge manifest JSON"
          className="app-field min-h-32 min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
          spellCheck={false}
          value={manifestText}
          onChange={(event) => onManifestTextChange(event.target.value)}
          placeholder='{"schema_version":"karkinos.broker_execution_edge_manifest.v1",…}'
        />
      </label>

      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '放行期限' : 'Release duration'}
        <select
          aria-label={
            locale === 'zh' ? '选择放行期限' : 'Select release duration'
          }
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={durationSeconds}
          onChange={(event) => onDurationChange(Number(event.target.value))}
        >
          {[1, 4, 8, 12].map((hours) => (
            <option key={hours} value={hours * 60 * 60}>
              {hours}h
            </option>
          ))}
        </select>
      </label>

      <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2">
        {OWNER_REVIEW_FIELDS.map((field) => (
          <label
            className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]"
            key={field}
          >
            {ownerReviewLabel(field, locale)}
            <input
              aria-label={ownerReviewLabel(field, locale)}
              className="app-field min-w-0 rounded-xl px-3 py-2 text-xs"
              value={ownerRefs[field]}
              onChange={(event) => onOwnerRefChange(field, event.target.value)}
              placeholder="review:…"
            />
          </label>
        ))}
      </div>

      <button
        type="button"
        className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        disabled={previewPending}
        onClick={onLoadPreview}
      >
        {previewPending
          ? locale === 'zh'
            ? '核验中'
            : 'Checking'
          : locale === 'zh'
            ? '生成只读放行预览'
            : 'Generate read-only release preview'}
      </button>

      {manifestError ? (
        <div className="app-error-text mt-2 text-xs" role="alert">
          {manifestError}
        </div>
      ) : null}
      {previewError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {previewError}
        </div>
      ) : null}
    </>
  );
}
