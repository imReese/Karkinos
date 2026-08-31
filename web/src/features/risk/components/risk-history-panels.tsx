import type { ReactNode } from 'react';

import { formatQuantity } from '../../../shared/format';
import { formatInstrumentDisplayLabelFromNameMap } from '../../../shared/instrument-display';
import {
  formatLedgerExplainabilityDetail,
  formatLedgerExplainabilityTitle,
} from '../../../shared/ledger-format';
import type { Locale } from '../../../shared/preferences/context';
import {
  EvidenceState,
  MetricStrip,
  Timeline,
} from '../../../shared/ui/workbench';
import {
  formatRiskAuditTimestamp,
  formatRiskCurrency,
  getRiskEventCategoryLabel,
  getRiskEventKindLabel,
  getRiskImpactSourceLabel,
} from '../model/risk-presentation';
import type { RiskPageController } from '../model/use-risk-page-controller';
import type { ExplainabilityResponse } from '../risk-feature-boundary';
import { RiskHistoryPager } from './risk-history-pager';

type Copy = RiskPageController['copy'];

export function RiskBridgePanel({
  items,
  title,
  emptyLabel,
  copy,
}: {
  items: ExplainabilityResponse['equity_bridge'];
  title: string;
  emptyLabel: string;
  copy: Copy;
}) {
  return (
    <section
      id="risk-history-panel-bridge"
      role="tabpanel"
      aria-labelledby="risk-history-tab-bridge"
      className="space-y-3"
      data-testid="risk-equity-bridge-section"
    >
      <h2 className="app-kicker app-type-overline">{title}</h2>
      {items.length > 0 ? (
        <MetricStrip
          ariaLabel={title}
          items={items.map((item) => {
            const label =
              copy.explainability.equityBridgeLabels[
                item.key as keyof typeof copy.explainability.equityBridgeLabels
              ] ?? item.label;
            const isPnlMetric =
              item.key === 'realized' || item.key === 'unrealized';
            return {
              id: item.key,
              label,
              value: formatRiskCurrency(item.value),
              tone:
                isPnlMetric && item.value > 0
                  ? ('pnl-positive' as const)
                  : isPnlMetric && item.value < 0
                    ? ('pnl-negative' as const)
                    : ('neutral' as const),
            };
          })}
        />
      ) : (
        <EvidenceState kind="empty" title={emptyLabel} />
      )}
    </section>
  );
}

export function RiskEventsPanel({
  items,
  allItemCount,
  page,
  pageCount,
  title,
  emptyLabel,
  locale,
  instrumentNames,
  onPageChange,
}: {
  items: ExplainabilityResponse['recent_drivers'];
  allItemCount: number;
  page: number;
  pageCount: number;
  title: string;
  emptyLabel: string;
  locale: Locale;
  instrumentNames?: Map<string, string>;
  onPageChange: (page: number) => void;
}) {
  return (
    <section
      id="risk-history-panel-events"
      role="tabpanel"
      aria-labelledby="risk-history-tab-events"
      className="min-w-0 space-y-3"
    >
      <h2 className="app-kicker app-type-overline">{title}</h2>
      {allItemCount > 0 ? (
        <ol
          className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
          data-testid="risk-recent-impact-list"
        >
          {items.map((item) => (
            <li key={`${item.title}-${item.timestamp}`} className="px-3 py-3">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0 text-sm font-semibold leading-6">
                  {formatLedgerExplainabilityTitle(
                    item,
                    locale,
                    instrumentNames,
                  )}
                </div>
                {typeof item.amount === 'number' ? (
                  <div
                    className={`shrink-0 text-right text-sm font-semibold tabular-nums ${
                      item.amount < 0
                        ? 'text-[var(--app-pnl-negative)]'
                        : item.amount > 0
                          ? 'text-[var(--app-pnl-positive)]'
                          : 'text-[var(--app-pnl-neutral)]'
                    }`}
                  >
                    {formatRiskCurrency(item.amount)}
                  </div>
                ) : null}
              </div>
              {formatLedgerExplainabilityDetail(
                item,
                locale,
                instrumentNames,
              ) ? (
                <div className="app-muted mt-1 break-words text-sm leading-6">
                  {formatLedgerExplainabilityDetail(
                    item,
                    locale,
                    instrumentNames,
                  )}
                </div>
              ) : null}
              {item.timestamp ? (
                <time className="app-kicker app-type-micro mt-2 block">
                  {formatRiskAuditTimestamp(item.timestamp)}
                </time>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <EvidenceState kind="empty" title={emptyLabel} />
      )}
      <RiskHistoryPager
        kind="events"
        page={page}
        pageCount={pageCount}
        totalItems={allItemCount}
        locale={locale}
        onPageChange={onPageChange}
      />
    </section>
  );
}

export function RiskPositionsPanel({
  items,
  title,
  emptyLabel,
  copy,
  instrumentNames,
}: {
  items: ExplainabilityResponse['positions'];
  title: string;
  emptyLabel: string;
  copy: Copy;
  instrumentNames?: Map<string, string>;
}) {
  return (
    <section
      id="risk-history-panel-positions"
      role="tabpanel"
      aria-labelledby="risk-history-tab-positions"
      className="min-w-0 space-y-3"
    >
      <h2 className="app-kicker app-type-overline">{title}</h2>
      {items.length > 0 ? (
        <ul
          className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
          data-testid="risk-position-impact-list"
        >
          {items.map((item) => (
            <li
              key={item.symbol}
              className="grid gap-1 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-4"
            >
              <div className="min-w-0 text-sm font-semibold">
                {formatInstrumentDisplayLabelFromNameMap(
                  item.symbol,
                  instrumentNames,
                )}
              </div>
              <div className="text-sm font-medium tabular-nums sm:text-right">
                {formatRiskCurrency(item.market_value)}
              </div>
              <div className="app-muted text-sm">
                {copy.explainability.quantity} {formatQuantity(item.quantity)} ·{' '}
                {copy.portfolio.table.unrealized}{' '}
                <span
                  className={
                    item.unrealized_pnl < 0
                      ? 'text-[var(--app-pnl-negative)]'
                      : item.unrealized_pnl > 0
                        ? 'text-[var(--app-pnl-positive)]'
                        : 'text-[var(--app-pnl-neutral)]'
                  }
                >
                  {formatRiskCurrency(item.unrealized_pnl)}
                </span>
              </div>
              {item.last_activity_at ? (
                <time className="app-kicker app-type-micro sm:text-right">
                  {formatRiskAuditTimestamp(item.last_activity_at)}
                </time>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EvidenceState kind="empty" title={emptyLabel} />
      )}
    </section>
  );
}

export function RiskTimelinePanel({
  items,
  allItemCount,
  page,
  pageCount,
  copy,
  locale,
  instrumentNames,
  filters,
  onPageChange,
}: {
  items: ExplainabilityResponse['timeline'];
  allItemCount: number;
  page: number;
  pageCount: number;
  copy: Copy;
  locale: Locale;
  instrumentNames?: Map<string, string>;
  filters?: ReactNode;
  onPageChange: (page: number) => void;
}) {
  return (
    <section
      id="risk-history-panel-timeline"
      role="tabpanel"
      aria-labelledby="risk-history-tab-timeline"
      className="space-y-3"
      data-testid="risk-impact-timeline-section"
    >
      <h2 className="app-kicker app-type-overline">
        {copy.explainability.timeline}
      </h2>
      {filters ? <div className="mt-4">{filters}</div> : null}
      <div
        className="border-y border-[var(--app-divider)] py-3"
        data-testid="risk-impact-timeline-scroll"
      >
        <Timeline
          ariaLabel={copy.explainability.timeline}
          emptyState={copy.explainability.timelineEmpty}
          items={items.map((point) => ({
            id: `${point.date}-${point.equity}`,
            timestamp: point.date,
            title: `${copy.explainability.equity} ${formatRiskCurrency(point.equity)}`,
            description: `${copy.explainability.netChange} ${formatRiskCurrency(point.delta)} · ${copy.explainability.externalFlow} ${formatRiskCurrency(point.external_flow)} · ${copy.explainability.marketPnl} ${formatRiskCurrency(point.market_pnl)}`,
            evidence:
              point.events.length > 0 ? (
                <ul className="divide-y divide-[var(--app-divider)] border-t border-[var(--app-divider)] font-sans normal-case">
                  {point.events.map((event) => (
                    <li
                      key={`${event.timestamp}-${event.title}`}
                      className="py-2 first:pt-2 last:pb-0"
                    >
                      <div className="text-xs font-semibold text-[var(--app-text-secondary)]">
                        {formatLedgerExplainabilityTitle(
                          event,
                          locale,
                          instrumentNames,
                        )}{' '}
                        · {getRiskEventKindLabel(copy, event.kind)} ·{' '}
                        {getRiskEventCategoryLabel(copy, event.category)} ·{' '}
                        {getRiskImpactSourceLabel(copy, event.impact_source)}
                      </div>
                      {formatLedgerExplainabilityDetail(
                        event,
                        locale,
                        instrumentNames,
                      ) ? (
                        <div className="mt-1 text-xs leading-5 text-[var(--app-text-tertiary)]">
                          {formatLedgerExplainabilityDetail(
                            event,
                            locale,
                            instrumentNames,
                          )}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : undefined,
            tone: 'neutral' as const,
          }))}
          className="pt-1"
        />
      </div>
      <RiskHistoryPager
        kind="timeline"
        page={page}
        pageCount={pageCount}
        totalItems={allItemCount}
        locale={locale}
        onPageChange={onPageChange}
      />
    </section>
  );
}
