import {
  DataTable,
  EvidenceDrawer,
  EvidenceState,
  ExceptionList,
  MetricStrip,
  WorkspaceHeader,
  type ExceptionItem,
} from '../../../shared/ui/workbench';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  type OperationsAttentionItem,
  type OperationsTodayResponse,
} from '../api';
import { ControlledPerOrderPilotReadinessPanel } from '../controlled-per-order-pilot-readiness-panel';
import {
  operationsAttentionResolutionLabel,
  operationsEvidenceStatusLabel,
  operationsNextActionLabel,
  operationsSubsystemLabel,
  operationsTargetHref,
} from '../presentation';
import { exceptionTone, formatEvidenceTime } from './operations-page-model';
import {
  type OperationsPageController,
  type OperationsPageLabels,
  useOperationsPageController,
} from './use-operations-page-controller';

export function OperationsPage() {
  const controller = useOperationsPageController();
  const { labels, locale, selectedAttention, setSelectedAttentionFingerprint } =
    controller;

  return (
    <section
      className="min-w-0 space-y-5 sm:space-y-6"
      data-testid="operations-page"
    >
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        context={`${labels.readOnly} · ${labels.providerFree} · ${labels.noAuthority}`}
      />
      <OperationsPageBody controller={controller} />
      <OperationsEvidenceDrawer
        attention={selectedAttention}
        labels={labels}
        locale={locale}
        onClose={() => setSelectedAttentionFingerprint(null)}
      />
    </section>
  );
}

function OperationsPageBody({
  controller,
}: {
  controller: OperationsPageController;
}) {
  const {
    copy,
    labels,
    operations,
    projection,
    projectionIsSafe,
    safeProjection,
  } = controller;
  if (operations.isLoading && !projection) {
    return (
      <OperationsLoadingState
        labels={labels}
        loadingLabel={copy.states.loading}
      />
    );
  }
  if (operations.isError || !projection) {
    return (
      <div data-testid="operations-error">
        <EvidenceState
          kind="error"
          title={labels.error}
          description={labels.sourceBoundary}
          action={
            <button
              type="button"
              className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
              onClick={() => void operations.refetch()}
            >
              {labels.retry}
            </button>
          }
        />
      </div>
    );
  }
  if (!projectionIsSafe || !safeProjection) {
    return (
      <div data-testid="operations-contract-blocked">
        <EvidenceState
          kind="error"
          title={labels.projectionBlocked}
          description={labels.projectionBlockedDetail}
          evidence={labels.sourceBoundary}
        />
      </div>
    );
  }
  return (
    <OperationsReadyWorkspace
      controller={controller}
      projection={safeProjection}
    />
  );
}

function OperationsReadyWorkspace({
  controller,
  projection,
}: {
  controller: OperationsPageController;
  projection: OperationsTodayResponse;
}) {
  return (
    <>
      <OperationsCommandGrid controller={controller} projection={projection} />
      <OperationsSubsystemRegister
        controller={controller}
        projection={projection}
      />
      <OperationsEvidenceHistory controller={controller} />
    </>
  );
}

function OperationsCommandGrid({
  controller,
  projection,
}: {
  controller: OperationsPageController;
  projection: OperationsTodayResponse;
}) {
  const {
    attentionItems,
    labels,
    locale,
    pilotReadiness,
    setSelectedAttentionFingerprint,
  } = controller;
  return (
    <div
      className="app-operations-command-grid min-w-0"
      data-testid="operations-command-grid"
    >
      <section
        className="min-w-0 space-y-2"
        aria-labelledby="operations-attention-heading"
        data-testid="operations-attention-queue"
      >
        <div className="flex items-baseline justify-between gap-3">
          <h2
            id="operations-attention-heading"
            className="app-type-section-title text-[var(--app-text)]"
          >
            {labels.attentionQueue}
          </h2>
          <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
            {attentionItems.length}
          </span>
        </div>
        <ExceptionList
          ariaLabel={labels.attentionQueue}
          emptyState={labels.attentionEmpty}
          density="compact"
          className="app-operations-attention-list min-w-0 [&>li>dl]:grid-cols-2 lg:[&>li>dl]:grid-cols-4"
          labels={{
            reason: labels.evidenceStatus,
            unblockCondition: labels.resolution,
            nextAction: labels.nextAction,
            evidence: labels.observedAt,
          }}
          items={attentionItems.map((item) => {
            const href = operationsTargetHref(item.target);
            return {
              id: item.task_fingerprint,
              severity: exceptionTone(item.status),
              statusLabel: formatPublicStatus(item.status, locale),
              title: operationsSubsystemLabel(item.subsystem_id, locale),
              reason: operationsEvidenceStatusLabel(
                item.evidence.status,
                locale,
              ),
              unblockCondition: (
                <span>
                  {operationsAttentionResolutionLabel(
                    item.resolution_condition,
                    locale,
                  )}{' '}
                  <span className="text-[var(--app-text-tertiary)]">
                    {labels.viewingDoesNotClear}
                  </span>
                </span>
              ),
              nextAction: (
                <span className="flex flex-wrap items-center gap-2">
                  <span>
                    {operationsNextActionLabel(item.next_action, locale)}
                  </span>
                  {href !== '/operations' ? (
                    <a
                      className="font-semibold text-[var(--app-accent)] underline decoration-transparent underline-offset-2 hover:decoration-current"
                      href={href}
                    >
                      {labels.openEvidence}
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="app-button-secondary app-type-micro px-2 py-1"
                    onClick={() =>
                      setSelectedAttentionFingerprint(item.task_fingerprint)
                    }
                  >
                    {labels.reviewDetails}
                  </button>
                </span>
              ),
              evidence:
                formatEvidenceTime(item.evidence.observed_at, locale) ??
                labels.noTimestamp,
            } satisfies ExceptionItem;
          })}
        />
      </section>

      <aside
        className="min-w-0 space-y-2"
        data-testid="operations-health-overview"
      >
        <h2 className="app-type-section-title text-[var(--app-text)]">
          {labels.healthOverview}
        </h2>
        <MetricStrip
          ariaLabel={labels.healthOverview}
          className="app-operations-health-strip"
          items={[
            {
              id: 'total',
              label: labels.total,
              value: projection.health.total,
            },
            {
              id: 'degraded',
              label: labels.degraded,
              value: projection.health.degraded,
              tone: projection.health.degraded > 0 ? 'warning' : 'neutral',
            },
            {
              id: 'blocked',
              label: labels.blocked,
              value: projection.health.blocked,
              tone: projection.health.blocked > 0 ? 'warning' : 'neutral',
            },
            {
              id: 'manual-review',
              label: labels.manualReview,
              value: projection.health.manual_action_required,
              tone:
                projection.health.manual_action_required > 0
                  ? 'warning'
                  : 'neutral',
            },
          ]}
        />
      </aside>

      <div
        className="min-w-0 xl:col-span-2"
        data-testid="operations-pilot-readiness-zone"
      >
        <ControlledPerOrderPilotReadinessPanel
          readiness={pilotReadiness}
          locale={locale}
        />
      </div>
    </div>
  );
}

function OperationsSubsystemRegister({
  controller,
  projection,
}: {
  controller: OperationsPageController;
  projection: OperationsTodayResponse;
}) {
  const { labels, subsystemColumns } = controller;
  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)] py-2"
      data-testid="operations-subsystem-register"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
        <span>{labels.subsystemRegister}</span>
        <span className="flex items-center gap-2 font-mono text-xs font-normal tabular-nums text-[var(--app-text-tertiary)]">
          {projection.subsystems.length}
          <span aria-hidden="true" className="group-open:rotate-180">
            ▾
          </span>
        </span>
      </summary>
      <div className="mt-3 min-w-0">
        <DataTable
          data={projection.subsystems}
          columns={subsystemColumns}
          caption={labels.subsystemRegister}
          emptyState={labels.attentionEmpty}
          getRowId={(row) => row.id}
          tableTestId="operations-subsystem-table"
          scrollTestId="operations-subsystem-scroll"
        />
      </div>
    </details>
  );
}

function OperationsEvidenceHistory({
  controller,
}: {
  controller: OperationsPageController;
}) {
  const { labels, locale } = controller;
  return (
    <section
      className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-4"
      aria-labelledby="operations-timeline-heading"
    >
      <div>
        <h2
          id="operations-timeline-heading"
          className="app-type-section-title text-[var(--app-text)]"
        >
          {locale === 'zh' ? '证据历史' : 'Evidence history'}
        </h2>
        <p className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
          {labels.sourceBoundary}
        </p>
      </div>
      <EvidenceState
        kind="empty"
        title={locale === 'zh' ? '暂无历史事件' : 'No history events recorded'}
        description={
          locale === 'zh'
            ? '当前只保存各子系统的最新状态，尚未形成不可变的历史记录。'
            : 'Only the latest state for each subsystem is available; no immutable history has been recorded yet.'
        }
      />
    </section>
  );
}

function OperationsLoadingState({
  labels,
  loadingLabel,
}: {
  labels: OperationsPageLabels;
  loadingLabel: string;
}) {
  return (
    <div
      aria-busy="true"
      className="min-w-0 space-y-4"
      data-testid="operations-loading"
    >
      <EvidenceState
        kind="loading"
        statusLabel={loadingLabel}
        title={labels.loading}
        description={labels.sourceBoundary}
      />
      <div className="app-operations-command-grid min-w-0">
        <section className="min-w-0 space-y-2">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {labels.attentionQueue}
          </h2>
          <EvidenceState
            kind="loading"
            title={loadingLabel}
            description={labels.viewingDoesNotClear}
          />
        </section>
        <aside className="min-w-0 space-y-2">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {labels.healthOverview}
          </h2>
          <MetricStrip
            ariaLabel={`${labels.healthOverview} · ${loadingLabel}`}
            className="app-operations-health-strip"
            items={[
              { id: 'total', label: labels.total, value: loadingLabel },
              { id: 'degraded', label: labels.degraded, value: loadingLabel },
              { id: 'blocked', label: labels.blocked, value: loadingLabel },
              {
                id: 'manual-review',
                label: labels.manualReview,
                value: loadingLabel,
              },
            ]}
          />
        </aside>
      </div>
      <section className="min-w-0 border-y border-[var(--app-divider)] py-3">
        <h2 className="app-type-section-title text-[var(--app-text)]">
          {labels.subsystemRegister}
        </h2>
        <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
          {labels.sourceBoundary}
        </p>
      </section>
    </div>
  );
}

function OperationsEvidenceDrawer({
  attention,
  labels,
  locale,
  onClose,
}: {
  attention: OperationsAttentionItem | null;
  labels: OperationsPageLabels;
  locale: Locale;
  onClose: () => void;
}) {
  return (
    <EvidenceDrawer
      open={attention !== null}
      onClose={onClose}
      title={
        attention
          ? operationsSubsystemLabel(attention.subsystem_id, locale)
          : labels.evidenceDetail
      }
      description={labels.evidenceDetailDescription}
      closeLabel={labels.closeEvidenceDetail}
    >
      {attention ? (
        <div
          className="min-w-0 space-y-5"
          data-testid="operations-evidence-detail"
        >
          <dl className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-sm">
            {[
              [labels.status, formatPublicStatus(attention.status, locale)],
              [
                labels.evidenceStatus,
                operationsEvidenceStatusLabel(
                  attention.evidence.status,
                  locale,
                ),
              ],
              [
                labels.observedAt,
                formatEvidenceTime(attention.evidence.observed_at, locale) ??
                  labels.noTimestamp,
              ],
              [
                labels.resolution,
                operationsAttentionResolutionLabel(
                  attention.resolution_condition,
                  locale,
                ),
              ],
              [
                labels.nextAction,
                operationsNextActionLabel(attention.next_action, locale),
              ],
            ].map(([label, value]) => (
              <div
                key={label}
                className="grid gap-1 py-2.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3"
              >
                <dt className="text-xs font-medium text-[var(--app-text-tertiary)]">
                  {label}
                </dt>
                <dd className="min-w-0 text-[var(--app-text)]">{value}</dd>
              </div>
            ))}
          </dl>
          <section className="min-w-0 space-y-2">
            <h3 className="app-type-subsection-title text-[var(--app-text)]">
              {labels.technicalIdentity}
            </h3>
            <div className="border-y border-[var(--app-divider)] py-3">
              <div className="text-xs font-medium text-[var(--app-text-tertiary)]">
                {labels.fingerprint}
              </div>
              <code className="mt-1 block break-all text-xs leading-5 text-[var(--app-text-secondary)]">
                {attention.task_fingerprint}
              </code>
            </div>
            <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
              {labels.sourceBoundary}
            </p>
          </section>
          {operationsTargetHref(attention.target) !== '/operations' ? (
            <a
              className="app-button-primary inline-flex px-3 py-2 text-xs"
              href={operationsTargetHref(attention.target)}
            >
              {labels.openEvidence}
            </a>
          ) : null}
        </div>
      ) : null}
    </EvidenceDrawer>
  );
}
