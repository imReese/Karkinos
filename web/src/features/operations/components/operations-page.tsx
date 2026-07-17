import { ArrowUpRight, CircleAlert, Database, ShieldCheck } from 'lucide-react';

import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  type OperationsAttentionItem,
  type OperationsStatus,
  type OperationsTodayResponse,
  useOperationsTodayQuery,
} from '../api';
import {
  operationsAttentionResolutionLabel,
  operationsNextActionLabel,
  operationsSubsystemLabel,
  operationsTargetHref,
} from '../presentation';

function formatEvidenceTime(value: string | null | undefined, locale: Locale) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(parsed);
}

function statusTone(status: OperationsStatus) {
  if (status === 'blocked') {
    return {
      border: 'border-[color-mix(in_srgb,var(--app-danger)_42%,transparent)]',
      background: 'bg-[color-mix(in_srgb,var(--app-danger)_9%,transparent)]',
      text: 'text-[var(--app-danger)]',
      dot: 'bg-[var(--app-danger)]',
    };
  }
  if (status === 'degraded' || status === 'manual_action_required') {
    return {
      border: 'border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)]',
      background: 'bg-[color-mix(in_srgb,var(--app-warning)_9%,transparent)]',
      text: 'text-[var(--app-warning)]',
      dot: 'bg-[var(--app-warning)]',
    };
  }
  if (status === 'pass' || status === 'healthy' || status === 'no_action') {
    return {
      border: 'border-[color-mix(in_srgb,var(--app-success)_36%,transparent)]',
      background: 'bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)]',
      text: 'text-[var(--app-success)]',
      dot: 'bg-[var(--app-success)]',
    };
  }
  return {
    border: 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)]',
    background: 'bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)]',
    text: 'text-[var(--app-subtext-1)]',
    dot: 'bg-[var(--app-muted)]',
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function attentionContractIsSafe(
  item: unknown,
): item is OperationsAttentionItem {
  if (!isRecord(item) || !isRecord(item.evidence)) {
    return false;
  }
  return (
    item.schema_version === 'karkinos.operations_attention_item.v1' &&
    typeof item.subsystem_id === 'string' &&
    typeof item.status === 'string' &&
    typeof item.target === 'string' &&
    typeof item.next_action === 'string' &&
    typeof item.resolution_condition === 'string' &&
    typeof item.task_fingerprint === 'string' &&
    item.task_fingerprint.startsWith('sha256:') &&
    typeof item.evidence.status === 'string' &&
    (item.evidence.observed_at === null ||
      typeof item.evidence.observed_at === 'string') &&
    item.manual_acknowledgement_clears_status === false &&
    item.read_only_projection === true &&
    item.provider_contacted === false &&
    item.database_writes_performed === false &&
    item.authorizes_execution === false
  );
}

function subsystemContractIsSafe(value: unknown) {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === 'string' &&
    typeof value.status === 'string' &&
    typeof value.target === 'string' &&
    typeof value.next_action === 'string' &&
    typeof value.detail_status === 'string' &&
    Array.isArray(value.limitations) &&
    value.limitations.every((item) => typeof item === 'string')
  );
}

function operationsProjectionIsSafe(
  value: unknown,
): value is OperationsTodayResponse {
  if (!isRecord(value) || !isRecord(value.health)) {
    return false;
  }
  const health = value.health;
  const attentionItems = value.attention_items ?? [];
  return (
    value.schema_version === 'karkinos.operations_today.v1' &&
    typeof value.generated_at === 'string' &&
    typeof value.conclusion_status === 'string' &&
    [
      'total',
      'pass',
      'degraded',
      'blocked',
      'manual_action_required',
      'skipped',
    ].every(
      (key) => typeof health[key] === 'number' && Number.isFinite(health[key]),
    ) &&
    Array.isArray(value.subsystems) &&
    value.subsystems.every(subsystemContractIsSafe) &&
    Array.isArray(attentionItems) &&
    attentionItems.every(attentionContractIsSafe)
  );
}

export function OperationsPage() {
  const copy = useCopy();
  const labels = copy.operationsPage;
  const { locale } = usePreferences();
  const operations = useOperationsTodayQuery();
  const projection = operations.data;
  const projectionIsSafe = operationsProjectionIsSafe(projection);
  const attentionItems = projectionIsSafe
    ? (projection.attention_items ?? [])
    : [];

  return (
    <section
      className="min-w-0 space-y-5 sm:space-y-6"
      data-testid="operations-page"
    >
      <header className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker">{labels.kicker}</div>
          <h1 className="app-page-title mt-2">{labels.title}</h1>
          <p className="app-muted mt-3 max-w-3xl text-sm leading-6">
            {labels.subtitle}
          </p>
        </div>
        <div
          className="flex flex-wrap gap-2"
          aria-label={labels.sourceBoundary}
        >
          {[labels.readOnly, labels.providerFree, labels.noAuthority].map(
            (label) => (
              <span
                key={label}
                className="inline-flex items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-success)]"
              >
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                {label}
              </span>
            ),
          )}
        </div>
      </header>

      {operations.isLoading && !projection ? (
        <div
          className="app-terminal-panel rounded-[2rem] p-6"
          data-testid="operations-loading"
        >
          <div className="flex items-center gap-3 text-sm text-[var(--app-soft)]">
            <Database className="h-5 w-5 animate-pulse" aria-hidden="true" />
            {labels.loading}
          </div>
        </div>
      ) : operations.isError || !projection ? (
        <div
          className="rounded-[2rem] border border-[color-mix(in_srgb,var(--app-danger)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_9%,transparent)] p-6"
          role="alert"
          data-testid="operations-error"
        >
          <div className="flex items-start gap-3">
            <CircleAlert
              className="mt-0.5 h-5 w-5 shrink-0 text-[var(--app-danger)]"
              aria-hidden="true"
            />
            <div>
              <div className="font-semibold text-[var(--app-danger)]">
                {labels.error}
              </div>
              <button
                type="button"
                className="app-button-secondary mt-4 rounded-2xl px-4 py-2 text-sm font-semibold"
                onClick={() => void operations.refetch()}
              >
                {labels.retry}
              </button>
            </div>
          </div>
        </div>
      ) : !projectionIsSafe ? (
        <div
          className="rounded-[2rem] border border-[color-mix(in_srgb,var(--app-danger)_48%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_10%,transparent)] p-6"
          role="alert"
          data-testid="operations-contract-blocked"
        >
          <div className="font-semibold text-[var(--app-danger)]">
            {labels.projectionBlocked}
          </div>
          <p className="mt-2 text-sm leading-6 text-[var(--app-soft)]">
            {labels.projectionBlockedDetail}
          </p>
        </div>
      ) : (
        <>
          <div className="app-terminal-panel rounded-[2rem] p-1.5">
            <div className="app-terminal-inner rounded-[1.65rem] p-4 sm:p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="app-kicker">{labels.subsystemHealth}</div>
                  <div className="mt-2 text-sm text-[var(--app-soft)]">
                    {labels.projectedAt}:{' '}
                    <span className="font-mono tabular-nums">
                      {formatEvidenceTime(projection.generated_at, locale) ??
                        labels.noTimestamp}
                    </span>
                  </div>
                </div>
                <div className="text-xs text-[var(--app-subtext-1)]">
                  {formatPublicStatus(projection.conclusion_status, locale)}
                </div>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
                {[
                  [labels.total, projection.health.total],
                  [labels.passed, projection.health.pass],
                  [labels.degraded, projection.health.degraded],
                  [labels.blocked, projection.health.blocked],
                  [
                    labels.manualReview,
                    projection.health.manual_action_required,
                  ],
                  [labels.skipped, projection.health.skipped],
                ].map(([label, value]) => (
                  <div
                    key={String(label)}
                    className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-3"
                  >
                    <dt className="text-[10px] font-semibold uppercase text-[var(--app-subtext-0)]">
                      {label}
                    </dt>
                    <dd className="mt-1 font-mono text-lg font-semibold tabular-nums text-[var(--app-text)]">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>

          <section aria-labelledby="operations-attention-heading">
            <div className="flex items-end justify-between gap-4">
              <div>
                <div className="app-kicker">{labels.attentionQueue}</div>
                <h2
                  id="operations-attention-heading"
                  className="app-card-title mt-1.5 text-xl"
                >
                  {labels.attentionQueue}
                </h2>
              </div>
              <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] px-3 py-1.5 font-mono text-xs tabular-nums text-[var(--app-soft)]">
                {attentionItems.length}
              </span>
            </div>

            {attentionItems.length === 0 ? (
              <div
                className="app-terminal-panel mt-4 rounded-[2rem] p-6 text-sm text-[var(--app-soft)]"
                data-testid="operations-attention-empty"
              >
                {labels.attentionEmpty}
              </div>
            ) : (
              <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
                {attentionItems.map((item) => {
                  const tone = statusTone(item.status);
                  const href = operationsTargetHref(item.target);
                  const observedAt =
                    formatEvidenceTime(item.evidence.observed_at, locale) ??
                    labels.noTimestamp;
                  return (
                    <article
                      key={item.task_fingerprint}
                      className={`min-w-0 rounded-[2rem] border p-5 ${tone.border} ${tone.background}`}
                      data-testid={`operations-attention-${item.subsystem_id}`}
                    >
                      <div className="flex min-w-0 items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span
                              className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`}
                              aria-hidden="true"
                            />
                            <h3 className="truncate font-semibold text-[var(--app-text)]">
                              {operationsSubsystemLabel(
                                item.subsystem_id,
                                locale,
                              )}
                            </h3>
                          </div>
                          <div
                            className={`mt-2 text-xs font-semibold ${tone.text}`}
                          >
                            {formatPublicStatus(item.status, locale)}
                          </div>
                        </div>
                        {href !== '/operations' ? (
                          <a
                            href={href}
                            className="app-button-secondary inline-flex shrink-0 items-center gap-1.5 rounded-2xl px-3 py-2 text-xs font-semibold"
                          >
                            {labels.openEvidence}
                            <ArrowUpRight
                              className="h-3.5 w-3.5"
                              aria-hidden="true"
                            />
                          </a>
                        ) : null}
                      </div>

                      <dl className="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-2">
                        <div>
                          <dt className="text-xs text-[var(--app-subtext-0)]">
                            {labels.evidenceStatus}
                          </dt>
                          <dd className="mt-1 text-[var(--app-soft)]">
                            {formatPublicStatus(item.evidence.status, locale)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-xs text-[var(--app-subtext-0)]">
                            {labels.observedAt}
                          </dt>
                          <dd className="mt-1 font-mono text-[var(--app-soft)] tabular-nums">
                            {observedAt}
                          </dd>
                        </div>
                        <div className="sm:col-span-2">
                          <dt className="text-xs text-[var(--app-subtext-0)]">
                            {labels.nextAction}
                          </dt>
                          <dd className="mt-1 leading-6 text-[var(--app-text)]">
                            {operationsNextActionLabel(
                              item.next_action,
                              locale,
                            )}
                          </dd>
                        </div>
                        <div className="sm:col-span-2">
                          <dt className="text-xs text-[var(--app-subtext-0)]">
                            {labels.resolution}
                          </dt>
                          <dd className="mt-1 leading-6 text-[var(--app-text)]">
                            {operationsAttentionResolutionLabel(
                              item.resolution_condition,
                              locale,
                            )}
                          </dd>
                          <div className="mt-1 text-xs leading-5 text-[var(--app-subtext-1)]">
                            {labels.viewingDoesNotClear}
                          </div>
                        </div>
                        <div className="min-w-0 sm:col-span-2">
                          <dt className="text-xs text-[var(--app-subtext-0)]">
                            {labels.fingerprint}
                          </dt>
                          <dd className="mt-1 break-all font-mono text-[11px] leading-5 text-[var(--app-subtext-1)]">
                            {item.task_fingerprint}
                          </dd>
                        </div>
                      </dl>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section aria-labelledby="operations-subsystem-heading">
            <div className="app-kicker">{labels.subsystemHealth}</div>
            <h2
              id="operations-subsystem-heading"
              className="app-card-title mt-1.5 text-xl"
            >
              {labels.subsystemHealth}
            </h2>
            <div className="mt-4 grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {projection.subsystems.map((subsystem) => {
                const tone = statusTone(subsystem.status);
                return (
                  <article
                    key={subsystem.id}
                    className={`min-w-0 rounded-[1.75rem] border p-4 ${tone.border} ${tone.background}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="truncate font-semibold text-[var(--app-text)]">
                          {operationsSubsystemLabel(subsystem.id, locale)}
                        </h3>
                        <div
                          className={`mt-1 text-xs font-semibold ${tone.text}`}
                        >
                          {formatPublicStatus(subsystem.status, locale)}
                        </div>
                      </div>
                      <span
                        className={`mt-1 h-2 w-2 shrink-0 rounded-full ${tone.dot}`}
                        aria-hidden="true"
                      />
                    </div>
                    <div className="mt-3 text-xs text-[var(--app-subtext-0)]">
                      {labels.evidenceStatus}
                    </div>
                    <div className="mt-1 text-sm text-[var(--app-soft)]">
                      {formatPublicStatus(subsystem.detail_status, locale)}
                    </div>
                    <div className="mt-3 text-xs text-[var(--app-subtext-0)]">
                      {labels.nextAction}
                    </div>
                    <div className="mt-1 text-sm leading-6 text-[var(--app-soft)]">
                      {operationsNextActionLabel(subsystem.next_action, locale)}
                    </div>
                    <div className="mt-3 text-xs text-[var(--app-subtext-0)]">
                      {labels.limitations}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-[var(--app-subtext-1)]">
                      {subsystem.limitations.length > 0
                        ? subsystem.limitations.join(' · ')
                        : labels.noLimitations}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <div className="rounded-[1.75rem] border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4 text-xs leading-6 text-[var(--app-subtext-1)]">
            {labels.sourceBoundary}
          </div>
        </>
      )}
    </section>
  );
}
