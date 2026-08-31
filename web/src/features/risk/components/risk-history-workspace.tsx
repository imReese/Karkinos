import { useState, type KeyboardEvent, type ReactNode } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { EvidenceState } from '../../../shared/ui/workbench';
import type { ExplainabilityResponse } from '../risk-feature-boundary';
import { ReturnCalendarCard } from '../risk-feature-boundary';
import {
  RiskBridgePanel,
  RiskEventsPanel,
  RiskPositionsPanel,
  RiskTimelinePanel,
} from './risk-history-panels';

type RiskHistoryView = 'bridge' | 'events' | 'positions' | 'timeline';
const RISK_HISTORY_EVENT_PAGE_SIZE = 8;
const RISK_HISTORY_TIMELINE_PAGE_SIZE = 12;

export function RiskHistoryWorkspace({
  title,
  stateLabelRecent,
  stateLabelPositions,
  emptyLabel,
  explainability,
  loading,
  instrumentNames,
  filters,
  showReturnCalendar = false,
}: {
  title: string;
  stateLabelRecent: string;
  stateLabelPositions: string;
  emptyLabel: string;
  explainability: ExplainabilityResponse | undefined;
  loading: boolean;
  instrumentNames?: Map<string, string>;
  filters?: ReactNode;
  showReturnCalendar?: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const [activeView, setActiveView] = useState<RiskHistoryView>('bridge');
  const [recentDriverPage, setRecentDriverPage] = useState(0);
  const [timelinePage, setTimelinePage] = useState(0);

  if (loading) {
    return <EvidenceState kind="loading" title={copy.states.loading} />;
  }

  const equityBridge = explainability?.equity_bridge ?? [];
  const recentDrivers = explainability?.recent_drivers ?? [];
  const positions = explainability?.positions ?? [];
  const timeline = (explainability?.timeline ?? []).slice().reverse();
  const recentDriverPageCount = Math.max(
    1,
    Math.ceil(recentDrivers.length / RISK_HISTORY_EVENT_PAGE_SIZE),
  );
  const timelinePageCount = Math.max(
    1,
    Math.ceil(timeline.length / RISK_HISTORY_TIMELINE_PAGE_SIZE),
  );
  const visibleRecentDriverPage = Math.min(
    recentDriverPage,
    recentDriverPageCount - 1,
  );
  const visibleTimelinePage = Math.min(timelinePage, timelinePageCount - 1);
  const visibleRecentDrivers = recentDrivers.slice(
    visibleRecentDriverPage * RISK_HISTORY_EVENT_PAGE_SIZE,
    (visibleRecentDriverPage + 1) * RISK_HISTORY_EVENT_PAGE_SIZE,
  );
  const visibleTimeline = timeline.slice(
    visibleTimelinePage * RISK_HISTORY_TIMELINE_PAGE_SIZE,
    (visibleTimelinePage + 1) * RISK_HISTORY_TIMELINE_PAGE_SIZE,
  );
  const historyViews = [
    { id: 'bridge', label: title, count: equityBridge.length },
    { id: 'events', label: stateLabelRecent, count: recentDrivers.length },
    { id: 'positions', label: stateLabelPositions, count: positions.length },
    {
      id: 'timeline',
      label: copy.explainability.timeline,
      count: timeline.length,
    },
  ] as const;

  function handleTabKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    activeId: RiskHistoryView,
  ) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = Array.from(
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
        '[role="tab"]',
      ) ?? [],
    );
    const currentIndex = historyViews.findIndex((view) => view.id === activeId);
    const nextIndex =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? tabs.length - 1
          : event.key === 'ArrowRight'
            ? (currentIndex + 1) % tabs.length
            : (currentIndex - 1 + tabs.length) % tabs.length;
    const nextView = historyViews[nextIndex];
    if (!nextView) return;
    setActiveView(nextView.id);
    tabs[nextIndex]?.focus();
  }

  return (
    <div className="min-w-0 space-y-4">
      <div
        role="tablist"
        aria-label={
          locale === 'zh' ? '风险历史分析视图' : 'Risk history analysis views'
        }
        className="flex max-w-full overflow-x-auto border-b border-[var(--app-divider)]"
        data-testid="risk-history-tabs"
      >
        {historyViews.map((view) => (
          <button
            key={view.id}
            id={`risk-history-tab-${view.id}`}
            type="button"
            role="tab"
            aria-selected={activeView === view.id}
            aria-controls={`risk-history-panel-${view.id}`}
            tabIndex={activeView === view.id ? 0 : -1}
            onClick={() => setActiveView(view.id)}
            onKeyDown={(event) => handleTabKeyDown(event, view.id)}
            className={`flex h-10 shrink-0 items-center gap-2 border-b-2 px-3 text-xs font-semibold transition-colors duration-[var(--app-motion-fast)] motion-reduce:transition-none ${
              activeView === view.id
                ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
            }`}
          >
            <span>{view.label}</span>
            <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
              {view.count}
            </span>
          </button>
        ))}
      </div>
      {activeView === 'bridge' ? (
        <RiskBridgePanel
          items={equityBridge}
          title={title}
          emptyLabel={emptyLabel}
          copy={copy}
        />
      ) : null}
      {activeView === 'events' ? (
        <RiskEventsPanel
          items={visibleRecentDrivers}
          allItemCount={recentDrivers.length}
          page={visibleRecentDriverPage}
          pageCount={recentDriverPageCount}
          title={stateLabelRecent}
          emptyLabel={emptyLabel}
          locale={locale}
          instrumentNames={instrumentNames}
          onPageChange={setRecentDriverPage}
        />
      ) : null}
      {activeView === 'positions' ? (
        <RiskPositionsPanel
          items={positions}
          title={stateLabelPositions}
          emptyLabel={emptyLabel}
          copy={copy}
          instrumentNames={instrumentNames}
        />
      ) : null}
      {activeView === 'timeline' ? (
        <RiskTimelinePanel
          items={visibleTimeline}
          allItemCount={timeline.length}
          page={visibleTimelinePage}
          pageCount={timelinePageCount}
          copy={copy}
          locale={locale}
          instrumentNames={instrumentNames}
          filters={filters}
          onPageChange={setTimelinePage}
        />
      ) : null}
      {activeView === 'timeline' && showReturnCalendar ? (
        <ReturnCalendarCard timeline={explainability?.timeline ?? []} />
      ) : null}
    </div>
  );
}
