import type { KeyboardEvent } from 'react';

import {
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import {
  formatLedgerActivitySummary,
  formatLedgerExecutionDetailLines,
  formatLedgerPublicNote,
} from '../../../shared/ledger-format';
import { usePreferences } from '../../../shared/preferences/context';
import {
  EvidenceLoadingLayout as WorkbenchEvidenceLoadingLayout,
  EvidenceState as WorkbenchEvidenceState,
  WorkspaceHeader as WorkbenchWorkspaceHeader,
} from '../../../shared/ui/workbench';
import type { LedgerEntry } from '../portfolio-feature-boundary';
import {
  HOLDING_DETAIL_TABS,
  nextHoldingDetailTab,
  type DetailMetric,
  type HoldingDetailTab,
} from './holding-detail-model-values';

export function HoldingDetailStateView({
  symbol,
  state,
}: {
  symbol: string;
  state: 'loading' | 'error' | 'not-found';
}) {
  const copy = useCopy();
  const labels = copy.portfolio.detail;
  return (
    <section className="space-y-5 sm:space-y-6">
      <div data-testid="holding-detail-header">
        <WorkbenchWorkspaceHeader
          eyebrow={labels.kicker}
          title={labels.title(symbol)}
          description={labels.subtitle}
          actions={
            <a
              href="/portfolio"
              className="app-button-secondary app-type-compact inline-flex min-h-11 items-center rounded-[var(--app-radius-control)] px-3 py-2 font-semibold"
              aria-label={labels.returnToPortfolio}
            >
              {labels.backToPortfolio}
            </a>
          }
        />
      </div>
      {state === 'loading' ? (
        <WorkbenchEvidenceLoadingLayout
          title={copy.states.loading}
          description={labels.loading}
          metricCount={4}
          rowCount={4}
        />
      ) : (
        <StatusPanel
          title={state === 'error' ? copy.states.error : labels.notFoundTitle}
          detail={state === 'error' ? labels.error : labels.notFoundDetail}
          kind={state === 'error' ? 'error' : 'empty'}
        />
      )}
    </section>
  );
}

export function HoldingDetailTabs({
  activeTab,
  labels,
  onTabChange,
}: {
  activeTab: HoldingDetailTab;
  labels: Record<HoldingDetailTab, string>;
  onTabChange: (tab: HoldingDetailTab) => void;
}) {
  const handleKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    tab: HoldingDetailTab,
  ) => {
    const nextTab = nextHoldingDetailTab(tab, event.key);
    if (!nextTab) {
      return;
    }
    event.preventDefault();
    onTabChange(nextTab);
    event.currentTarget.parentElement
      ?.querySelector<HTMLButtonElement>(`#holding-tab-${nextTab}`)
      ?.focus();
  };
  const copy = useCopy().portfolio.detail;
  return (
    <div className="min-w-0">
      <div
        className="app-type-micro mb-1.5 text-right font-medium text-[var(--app-text-tertiary)] sm:hidden"
        data-testid="holding-tabs-scroll-hint"
        id="holding-tabs-scroll-hint"
      >
        {copy.tabScrollHint}
      </div>
      <div
        role="tablist"
        aria-label={copy.tabListLabel}
        aria-describedby="holding-tabs-scroll-hint"
        data-testid="holding-detail-tabs"
        className="app-horizontal-scroll-cue flex min-w-0 gap-1 overflow-x-auto border-b border-[var(--app-divider)] pb-px"
      >
        {HOLDING_DETAIL_TABS.map((tab) => {
          const selected = activeTab === tab;
          return (
            <button
              key={tab}
              id={`holding-tab-${tab}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`holding-panel-${tab}`}
              tabIndex={selected ? 0 : -1}
              className={`min-h-10 shrink-0 border-b-2 px-3 py-2 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                selected
                  ? 'border-[var(--app-accent)] text-[var(--app-text)]'
                  : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
              }`}
              onClick={() => onTabChange(tab)}
              onKeyDown={(event) => handleKeyDown(event, tab)}
            >
              {labels[tab]}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function MetricGrid({
  metrics,
  testId,
  metricTestId,
}: {
  metrics: DetailMetric[];
  testId?: string;
  metricTestId?: string;
}) {
  return (
    <dl
      data-testid={testId}
      className="mt-3 grid min-w-0 grid-cols-1 border-y border-[var(--app-divider)] sm:grid-cols-2 xl:grid-cols-3"
    >
      {metrics.map((metric) => (
        <div
          key={metric.label}
          data-testid={metricTestId}
          className="min-w-0 border-b border-[var(--app-divider)] px-3 py-2.5 sm:border-r sm:[&:nth-child(2n)]:border-r-0 xl:[&:nth-child(2n)]:border-r xl:[&:nth-child(3n)]:border-r-0"
        >
          <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
            {metric.label}
          </dt>
          <dd
            className={`mt-0.5 break-words text-sm font-semibold tabular-nums ${
              metric.tone === 'pnl-positive'
                ? 'text-[var(--app-pnl-positive)]'
                : metric.tone === 'pnl-negative'
                  ? 'text-[var(--app-pnl-negative)]'
                  : metric.tone === 'warning'
                    ? 'text-[var(--app-warning-text)]'
                    : 'text-[var(--app-text)]'
            }`}
          >
            {metric.value}
          </dd>
          {metric.detail ? (
            <div className="app-type-micro mt-0.5 text-[var(--app-text-tertiary)]">
              {metric.detail}
            </div>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

export function InfoRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'pnl-positive' | 'pnl-negative' | 'warning';
}) {
  return (
    <div
      data-testid="holding-info-row"
      className="grid min-w-0 grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-start gap-3 border-b border-[var(--app-divider)] pb-2 text-sm last:border-b-0 last:pb-0"
    >
      <span className="min-w-0 break-words text-[var(--app-text-secondary)]">
        {label}
      </span>
      <span
        data-testid="holding-info-row-value"
        className={`min-w-0 break-words text-right font-mono font-semibold tabular-nums ${
          tone === 'pnl-positive'
            ? 'text-[var(--app-pnl-positive)]'
            : tone === 'pnl-negative'
              ? 'text-[var(--app-pnl-negative)]'
              : tone === 'warning'
                ? 'text-[var(--app-warning-text)]'
                : 'text-[var(--app-text)]'
        }`}
      >
        {value}
      </span>
    </div>
  );
}

export function LedgerTrace({
  entries,
  loading,
}: {
  entries: LedgerEntry[];
  loading: boolean;
}) {
  const copy = useCopy();
  const labels = copy.portfolio.detail;
  const detailLabels = copy.activity.feed.detailFields;
  const { locale } = usePreferences();
  if (loading) {
    return <div className="app-muted mt-5 text-sm">{labels.loading}</div>;
  }
  if (entries.length === 0) {
    return (
      <div className="mt-4 border-y border-dashed border-[var(--app-divider)] px-3 py-4 text-sm text-[var(--app-text-secondary)]">
        {labels.noLedger}
      </div>
    );
  }
  return (
    <div
      data-testid="holding-ledger-scroll"
      className="mt-4 min-w-0 max-w-full overflow-x-auto overscroll-x-contain pb-2 [scrollbar-gutter:stable]"
    >
      <table
        data-testid="holding-ledger-table"
        className="app-data-table w-full min-w-[760px] text-left text-sm"
      >
        <thead className="app-kicker app-type-overline">
          <tr>
            <th className="px-4 py-3">{labels.entryType}</th>
            <th className="px-4 py-3">{labels.quantity}</th>
            <th className="px-4 py-3 text-right">{labels.price}</th>
            <th className="px-4 py-3 text-right">{labels.amount}</th>
            <th className="px-4 py-3">{labels.note}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const activitySummary = formatLedgerActivitySummary(entry, locale);
            const publicNote = formatLedgerPublicNote(entry, locale) ?? '--';
            const detailLines = formatLedgerExecutionDetailLines(
              entry,
              detailLabels,
              locale,
            );
            return (
              <tr key={entry.id}>
                <td className="px-4 py-3.5">
                  <div className="font-semibold">{activitySummary.label}</div>
                  <div className="app-muted mt-1 text-xs tabular-nums">
                    {formatTimestamp(entry.timestamp)}
                  </div>
                  <div className="app-muted mt-1 text-xs">
                    {activitySummary.cashImpactLabel}
                  </div>
                </td>
                <td className="px-4 py-3.5 font-mono tabular-nums">
                  {formatQuantity(entry.quantity)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                  {formatPrice(entry.price)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                  <div>{activitySummary.amount}</div>
                  {detailLines.length > 0 ? (
                    <div className="app-muted mt-1 flex flex-col items-end gap-0.5 text-xs">
                      {detailLines.map((detail) => (
                        <span key={detail.label}>
                          {detail.label} {detail.value}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </td>
                <td className="max-w-[280px] px-4 py-3.5 text-[var(--app-muted)]">
                  <span
                    className="line-clamp-2 break-words focus:line-clamp-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                    data-testid="holding-ledger-note"
                    tabIndex={0}
                    title={publicNote}
                  >
                    {publicNote}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ActionLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      data-testid="holding-related-action-link"
      className="app-button-secondary inline-flex min-h-10 min-w-0 items-center break-words rounded-[var(--app-radius-control)] px-3 py-2 text-center text-sm font-semibold"
      aria-label={label}
    >
      {label}
    </a>
  );
}

export function StatusPanel({
  title,
  detail,
  kind,
}: {
  title: string;
  detail: string;
  kind: 'loading' | 'empty' | 'error';
}) {
  return (
    <WorkbenchEvidenceState kind={kind} title={title} description={detail} />
  );
}
