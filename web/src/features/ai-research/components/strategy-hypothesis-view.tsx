import type { ReactNode } from 'react';

import type { StrategyHypothesisDraft } from '../api';
import type { StrategyHypothesisCopy } from './strategy-hypothesis-copy';

export function DraftCard({
  copy,
  draft,
  selected,
  current,
  onSelect,
}: {
  copy: StrategyHypothesisCopy;
  draft: StrategyHypothesisDraft;
  selected: boolean;
  current: boolean;
  onSelect: () => void;
}) {
  const valid = draft.validation.status === 'valid';
  return (
    <article
      className={`rounded-2xl border p-4 ${selected ? 'border-[var(--app-accent)]' : 'border-[var(--app-border)]'}`}
    >
      <label className="flex cursor-pointer items-start gap-3">
        <input
          className="mt-1"
          type="radio"
          name="strategy-draft"
          checked={selected}
          onChange={onSelect}
        />
        <span className="min-w-0">
          <span
            className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${valid ? 'bg-[var(--app-success-bg)] text-[var(--app-success)]' : 'bg-[var(--app-danger-bg)] text-[var(--app-danger)]'}`}
          >
            {valid ? copy.valid : copy.blocked}
          </span>
          <span className="mt-2 block text-sm font-semibold leading-6 text-[var(--app-text)]">
            {draft.economic_hypothesis}
          </span>
        </span>
      </label>
      <div className="mt-3 grid gap-3 text-sm">
        <TextBlock
          title={copy.parameters}
          value={JSON.stringify(draft.parameter_values)}
        />
        <TextBlock title={copy.risk} value={draft.risk_impact} />
        <TextList title={copy.limitations} items={draft.limitations} />
        <TextList
          title={copy.tests}
          items={draft.proposed_deterministic_tests}
        />
        {!valid ? (
          <TextList
            title={copy.validationErrors}
            items={draft.validation.errors}
            danger
          />
        ) : null}
        <details>
          <summary className="cursor-pointer font-semibold text-[var(--app-text)]">
            {copy.formula}
          </summary>
          <pre className="mt-2 max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-[var(--app-surface-0)] p-3 text-xs leading-5 text-[var(--app-muted)]">
            {JSON.stringify(draft.formula_ast, null, 2)}
          </pre>
        </details>
        <TextBlock
          title={copy.identity}
          value={`${draft.formula_fingerprint ?? 'blocked'} · dataset ${draft.dataset_snapshot_id} · evidence ${draft.evidence_reference_id} · context ${draft.context_snapshot_id}${current ? '' : ' · historical / not current'}`}
          mono
        />
        <TextBlock
          title={copy.providerEvidence}
          value={provenanceSummary(
            draft.provider_id,
            draft.model_id,
            draft.prompt_version,
            draft.provider_provenance,
          )}
          mono
        />
      </div>
    </article>
  );
}

export function Label({
  text,
  children,
}: {
  text: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-2 text-sm font-medium text-[var(--app-text)]">
      {text}
      {children}
    </label>
  );
}

export function Confirmation({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 rounded-2xl border border-[var(--app-warning)] bg-[var(--app-warning-bg)] p-4 text-sm leading-6 text-[var(--app-text)]">
      <input
        className="mt-1"
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

export function Identity({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-[var(--app-border)] p-3">
      <div className="app-muted text-xs">{label}</div>
      <div
        className={`mt-1 break-all text-sm font-semibold text-[var(--app-text)] ${mono ? 'font-mono text-xs' : ''}`}
      >
        {value}
      </div>
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[var(--app-border)] p-3">
      <div className="app-muted text-xs">{label}</div>
      <div className="mt-1 font-mono text-base font-semibold tabular-nums text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}

export function TextBlock({
  title,
  value,
  mono = false,
}: {
  title: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <p
      className={`break-words text-[var(--app-muted)] ${mono ? 'font-mono text-xs' : ''}`}
    >
      <strong className="text-[var(--app-text)]">{title}: </strong>
      {value}
    </p>
  );
}

export function TextList({
  title,
  items,
  danger = false,
}: {
  title: string;
  items: string[];
  danger?: boolean;
}) {
  return (
    <div
      className={
        danger ? 'text-[var(--app-danger)]' : 'text-[var(--app-muted)]'
      }
    >
      <div className="font-semibold text-[var(--app-text)]">{title}</div>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm leading-6">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function BoundaryBadge({ text }: { text: string }) {
  return (
    <span className="rounded-full border border-[var(--app-border)] px-3 py-1 text-[var(--app-muted)]">
      {text}
    </span>
  );
}

export function FailClosedMessage({ text }: { text: string }) {
  return (
    <div
      className="mt-4 rounded-2xl border border-[var(--app-danger)] bg-[var(--app-danger-bg)] p-4 text-sm text-[var(--app-danger)]"
      role="alert"
    >
      {text}
    </div>
  );
}

export function provenanceSummary(
  providerId: string | null | undefined,
  modelId: string | null | undefined,
  promptVersion: string | null | undefined,
  provenance: Record<string, unknown> | undefined,
) {
  const usage =
    provenance?.usage && typeof provenance.usage === 'object'
      ? (provenance.usage as Record<string, unknown>)
      : undefined;
  const totalTokens =
    typeof usage?.total_tokens === 'number' ? usage.total_tokens : null;
  const latency =
    typeof provenance?.latency_ms === 'number' ? provenance.latency_ms : null;
  return [
    providerId ?? 'provider unavailable',
    modelId ?? 'model unavailable',
    promptVersion ?? 'prompt unavailable',
    totalTokens === null ? 'token usage unavailable' : `${totalTokens} tokens`,
    latency === null ? 'latency unavailable' : `${latency} ms`,
  ].join(' · ');
}
