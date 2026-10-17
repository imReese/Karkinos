import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { formatPercent } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { useBacktestResultQuery } from '../ai-research-feature-boundary';
import type { ShadowResearchCandidate } from '../shadow-research-api';
import { formatCandidateOptionLabel } from '../candidate-display';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';

export function StrategyEvolutionLineage({
  candidates,
  currentCandidates,
  historicalCandidates,
  selectedCandidateId,
  onSelectCandidate,
  verifiedWinnerCandidateIds = new Set(),
  registryControl,
}: {
  candidates: ShadowResearchCandidate[];
  currentCandidates?: ShadowResearchCandidate[];
  historicalCandidates?: ShadowResearchCandidate[];
  selectedCandidateId: string | null;
  onSelectCandidate: (candidateId: string) => void;
  verifiedWinnerCandidateIds?: Set<string>;
  registryControl?: React.ReactNode;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const copy = SHADOW_RESEARCH_COPY[zh ? 'zh' : 'en'];

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const [indicator, setIndicator] = useState<{
    x: number;
    width: number;
    visible: boolean;
  }>({ x: 0, width: 0, visible: false });

  if (!candidates || candidates.length === 0) {
    return null;
  }

  // Find the selected candidate or default to first
  const activeCandidate = useMemo(() => {
    return (
      candidates.find((c) => c.candidate_id === selectedCandidateId) ??
      candidates[0]
    );
  }, [candidates, selectedCandidateId]);

  // Group candidates that belong to the same lineage run as the active candidate
  const runCandidates = useMemo(() => {
    return candidates.filter((c) => c.run_id === activeCandidate?.run_id);
  }, [candidates, activeCandidate?.run_id]);

  const lineageChain = useMemo(() => {
    // 1. Trace connected lineage tree via parent_candidate_id (both backwards to root and forwards to latest child)
    let root: ShadowResearchCandidate | undefined = activeCandidate;
    const visitedUp = new Set<string>();
    while (root && !visitedUp.has(root.candidate_id)) {
      visitedUp.add(root.candidate_id);
      const parentId: string | null | undefined =
        root.comparison?.iteration_lineage?.parent_candidate_id;
      const parent: ShadowResearchCandidate | undefined = parentId
        ? candidates.find((c) => c.candidate_id === parentId)
        : undefined;
      if (!parent) break;
      root = parent;
    }

    if (root) {
      const chain: ShadowResearchCandidate[] = [];
      let curr: ShadowResearchCandidate | undefined = root;
      const visitedDown = new Set<string>();
      while (curr && !visitedDown.has(curr.candidate_id)) {
        visitedDown.add(curr.candidate_id);
        chain.push(curr);
        const next: ShadowResearchCandidate | undefined = candidates.find(
          (c) =>
            c.comparison?.iteration_lineage?.parent_candidate_id ===
            curr!.candidate_id,
        );
        curr = next;
      }
      if (chain.length > 1) {
        return chain;
      }
    }

    // 2. Fallback: if run has multiple candidates, sort by iteration_number
    if (runCandidates.length > 1) {
      return [...runCandidates].sort(
        (a, b) =>
          (a.comparison?.iteration_lineage?.iteration_number ?? 0) -
          (b.comparison?.iteration_lineage?.iteration_number ?? 0),
      );
    }

    // 3. Fallback: group candidates by run_id to find the run with the longest evolutionary sequence
    const runGroups = new Map<string, ShadowResearchCandidate[]>();
    for (const c of candidates) {
      if (!runGroups.has(c.run_id)) {
        runGroups.set(c.run_id, []);
      }
      runGroups.get(c.run_id)!.push(c);
    }

    let bestRun: ShadowResearchCandidate[] = [];
    for (const group of runGroups.values()) {
      if (group.length > bestRun.length) {
        bestRun = group;
      }
    }

    if (bestRun.length > 1) {
      return [...bestRun].sort(
        (a, b) =>
          (a.comparison?.iteration_lineage?.iteration_number ?? 0) -
          (b.comparison?.iteration_lineage?.iteration_number ?? 0),
      );
    }

    return candidates.slice(0, 5);
  }, [runCandidates, activeCandidate, candidates]);

  const totalIterations = Math.max(
    activeCandidate?.comparison?.iteration_lineage?.total_iterations ?? 0,
    lineageChain.length,
    5,
  );

  const updateIndicator = useCallback(() => {
    if (!selectedCandidateId) {
      setIndicator((prev) =>
        prev.visible ? { x: 0, width: 0, visible: false } : prev,
      );
      return;
    }
    const targetEl = cardRefs.current.get(selectedCandidateId);
    const container = scrollContainerRef.current;
    if (targetEl && container) {
      const x = targetEl.offsetLeft ?? 0;
      const width = targetEl.offsetWidth || targetEl.clientWidth || 220;
      setIndicator((prev) => {
        if (prev.visible && prev.x === x && prev.width === width) {
          return prev;
        }
        return { x, width, visible: true };
      });
    }
  }, [selectedCandidateId]);

  useEffect(() => {
    updateIndicator();
  }, [updateIndicator]);

  useEffect(() => {
    if (selectedCandidateId) {
      const targetEl = cardRefs.current.get(selectedCandidateId);
      if (
        targetEl &&
        typeof targetEl.scrollIntoView === 'function' &&
        targetEl.offsetParent !== null
      ) {
        targetEl.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest',
          inline: 'nearest',
        });
      }
    }
  }, [selectedCandidateId]);

  useEffect(() => {
    const handleResize = () => updateIndicator();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [updateIndicator]);

  return (
    <section
      aria-label={zh ? '策略演化代际链路' : 'Strategy evolution lineage'}
      className="app-dsh-panel relative space-y-3 p-4 shadow-sm"
      data-testid="strategy-evolution-lineage"
    >
      <div className="app-dsh-light-strip" />
      <div className="app-dsh-ambient-glow" />

      <div className="relative z-10 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--app-divider)] pb-2.5">
        <div className="flex items-center gap-2">
          <span className="app-dsh-pulse-beacon size-2 rounded-full bg-[var(--app-accent)] shadow-[0_0_8px_var(--app-accent)]" />
          <h4 className="font-sans text-sm font-semibold tracking-tight text-[var(--app-text)]">
            {zh ? '多代际演进阶梯' : 'Multi-Gen Evolution Stepper'}
          </h4>
          <span className="app-type-micro rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-0.5 font-mono text-[var(--app-text-tertiary)]">
            {zh
              ? `${lineageChain.length}/${totalIterations} 轮演化`
              : `${lineageChain.length}/${totalIterations} rounds`}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="shrink-0 app-type-micro font-sans font-medium uppercase tracking-wider text-[var(--app-text-tertiary)]">
            {zh ? '候选版本' : 'Registry'}:
          </span>
          {registryControl ?? (
            <label className="inline-flex items-center">
              <span className="sr-only">{copy.currentCandidates}</span>
              <select
                aria-label={copy.currentCandidates}
                className="h-7 max-w-[180px] sm:max-w-[240px] truncate rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-0.5 text-xs font-mono font-medium text-[var(--app-text)] shadow-sm transition-colors focus:border-[var(--app-accent)] focus:outline-none"
                data-testid="shadow-research-current-registry"
                onChange={(event) => onSelectCandidate(event.target.value)}
                value={selectedCandidateId ?? ''}
              >
                {currentCandidates && currentCandidates.length ? (
                  <optgroup label={copy.currentCandidates}>
                    {currentCandidates.map((c) => (
                      <option value={c.candidate_id} key={c.candidate_id}>
                        {formatCandidateOptionLabel(c, zh)}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {historicalCandidates && historicalCandidates.length ? (
                  <optgroup label={copy.candidateHistory}>
                    {historicalCandidates.map((c) => (
                      <option value={c.candidate_id} key={c.candidate_id}>
                        {formatCandidateOptionLabel(c, zh)}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </select>
            </label>
          )}
          <span className="inline-flex items-center gap-1 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-0.5 font-mono text-xs tabular-nums text-[var(--app-text-secondary)]">
            {candidates.length} {zh ? '策略总数' : 'total'}
          </span>
        </div>
      </div>

      <div
        ref={scrollContainerRef}
        className="relative z-10 flex min-w-0 items-stretch gap-3 overflow-x-auto pb-1 pt-0.5 focus-visible:outline-none"
      >
        {indicator.visible ? (
          <div
            data-testid="strategy-lineage-sliding-indicator"
            aria-hidden="true"
            className="app-lineage-sliding-pill"
            style={{
              transform: `translate3d(${indicator.x}px, 0, 0)`,
              width: `${indicator.width}px`,
            }}
          />
        ) : null}
        {lineageChain.map((candidate, index) => {
          const isSelected = candidate.candidate_id === selectedCandidateId;
          const isWinner = verifiedWinnerCandidateIds.has(
            candidate.candidate_id,
          );
          const prevCandidate = index > 0 ? lineageChain[index - 1] : null;

          return (
            <LineageCard
              key={candidate.candidate_id}
              candidate={candidate}
              index={index}
              indicatorVisible={indicator.visible}
              isSelected={isSelected}
              isWinner={isWinner}
              onSelectCandidate={onSelectCandidate}
              prevCandidate={prevCandidate}
              setCardRef={(el) => {
                if (el) cardRefs.current.set(candidate.candidate_id, el);
                else cardRefs.current.delete(candidate.candidate_id);
              }}
              totalIterations={totalIterations}
              zh={zh}
            />
          );
        })}

        {/* Next Generation Queued Beacon */}
        {(() => {
          const nextGenNumber = lineageChain.length + 1;
          const prevGenNumber = lineageChain.length;
          return (
            <div
              className="group relative z-10 flex min-w-[210px] max-w-[250px] shrink-0 flex-col justify-between rounded-[var(--app-radius-control)] border border-dashed border-[color-mix(in_srgb,var(--app-accent)_40%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-surface-raised)_60%,transparent)] p-3 text-left transition-colors"
              title={
                zh
                  ? `Gen ${nextGenNumber} 计划在今晚低谷期（21:00后）由 DeepSeek V4.1 Flash 执行下一轮因式变异与探索`
                  : `Gen ${nextGenNumber} scheduled to be explored by DeepSeek V4.1 Flash during off-peak window`
              }
            >
              <div>
                <div className="flex items-center justify-between gap-1.5">
                  <span className="app-type-micro inline-flex items-center gap-1.5 font-mono font-bold text-[var(--app-text-tertiary)]">
                    <span className="size-1.5 rounded-full bg-[var(--app-accent)] opacity-60" />
                    Gen {nextGenNumber}
                    <span className="font-normal text-[var(--app-text-tertiary)]">
                      /{Math.max(totalIterations, nextGenNumber)}
                    </span>
                  </span>
                  <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-accent)_40%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] px-1.5 py-0.2 font-sans font-semibold text-[var(--app-accent)]">
                    {zh ? '今晚待启动' : 'Queued'}
                  </span>
                </div>

                <div className="mt-2 text-xs font-semibold leading-snug text-[var(--app-text)] font-sans">
                  {zh
                    ? 'DeepSeek V4.1 Flash 待命中'
                    : 'DeepSeek V4.1 Flash Scheduled'}
                </div>
                <p className="mt-1 app-type-micro text-[var(--app-text-tertiary)] line-clamp-2 leading-relaxed font-sans">
                  {zh
                    ? `将在低谷调度窗口根据 Gen ${prevGenNumber} 评议启动下一轮探索。`
                    : `Will evolve based on Gen ${prevGenNumber} critique during off-peak window.`}
                </p>
              </div>

              <div className="mt-3 flex items-center justify-between border-t border-[var(--app-divider)] pt-2 app-type-micro text-[var(--app-text-tertiary)]">
                <span className="font-sans">
                  {zh ? '执行模型: ' : 'Engine: '}
                  <span className="font-mono font-semibold text-[var(--app-accent)]">
                    DeepSeek V4.1 Flash
                  </span>
                </span>
                <span className="font-mono text-xs opacity-60">
                  Standby &rarr;
                </span>
              </div>
            </div>
          );
        })()}
      </div>
    </section>
  );
}

type LineageMetrics = {
  sharpe: number;
  total_return: number;
  max_drawdown: number;
};

function extractCandidateMetrics(
  candidate: ShadowResearchCandidate | null | undefined,
  reportMetrics:
    { sharpe: number; total_return: number; max_drawdown: number } | undefined,
): LineageMetrics | null {
  if (candidate?.comparison?.candidate) {
    return {
      sharpe: candidate.comparison.candidate.sharpe,
      total_return: candidate.comparison.candidate.total_return,
      max_drawdown: candidate.comparison.candidate.max_drawdown,
    };
  }
  if (reportMetrics) {
    return {
      sharpe: reportMetrics.sharpe,
      total_return: reportMetrics.total_return,
      max_drawdown: reportMetrics.max_drawdown,
    };
  }
  return null;
}

function LineageCard({
  candidate,
  index,
  totalIterations,
  isSelected,
  isWinner,
  prevCandidate,
  indicatorVisible,
  onSelectCandidate,
  setCardRef,
  zh,
}: {
  candidate: ShadowResearchCandidate;
  index: number;
  totalIterations: number;
  isSelected: boolean;
  isWinner: boolean;
  prevCandidate: ShadowResearchCandidate | null;
  indicatorVisible: boolean;
  onSelectCandidate: (candidateId: string) => void;
  setCardRef: (el: HTMLButtonElement | null) => void;
  zh: boolean;
}) {
  const sourceResultId =
    typeof candidate.candidate_result_id === 'number' &&
    Number.isSafeInteger(candidate.candidate_result_id) &&
    candidate.candidate_result_id > 0
      ? candidate.candidate_result_id
      : null;
  const sourceQuery = useBacktestResultQuery(
    !candidate.comparison?.candidate ? sourceResultId : null,
  );

  const prevResultId =
    typeof prevCandidate?.candidate_result_id === 'number' &&
    Number.isSafeInteger(prevCandidate.candidate_result_id) &&
    prevCandidate.candidate_result_id > 0
      ? prevCandidate.candidate_result_id
      : null;
  const prevQuery = useBacktestResultQuery(
    !prevCandidate?.comparison?.candidate ? prevResultId : null,
  );

  const metrics = extractCandidateMetrics(candidate, sourceQuery.data?.metrics);
  const prevMetrics = extractCandidateMetrics(
    prevCandidate,
    prevQuery.data?.metrics,
  );

  const lineage = candidate.comparison?.iteration_lineage;
  const iterationNum = lineage?.iteration_number ?? index + 1;

  // Compute delta vs previous generation
  const sharpeDelta =
    metrics && prevMetrics ? metrics.sharpe - prevMetrics.sharpe : null;
  const returnDelta =
    metrics && prevMetrics
      ? metrics.total_return - prevMetrics.total_return
      : null;

  const isProfitable = (metrics?.total_return ?? 0) >= 0;

  return (
    <button
      ref={setCardRef}
      type="button"
      data-testid={`lineage-card-gen-${iterationNum}`}
      onClick={() => onSelectCandidate(candidate.candidate_id)}
      className={`group relative z-10 flex min-w-[210px] max-w-[260px] flex-1 shrink-0 flex-col justify-between rounded-[var(--app-radius-control)] border p-3 text-left transition-colors ${
        isSelected
          ? indicatorVisible
            ? 'border-transparent bg-[color-mix(in_srgb,var(--app-accent)_10%,var(--app-surface-raised))] shadow-sm'
            : 'border-[var(--app-accent)] bg-[color-mix(in_srgb,var(--app-accent)_10%,var(--app-surface-raised))] shadow-md'
          : 'border-[var(--app-border)] bg-[var(--app-surface-raised)] hover:bg-[var(--app-surface-overlay)]'
      }`}
      title={
        candidate.comparison?.economic_hypothesis ||
        candidate.draft_id ||
        candidate.candidate_id
      }
    >
      <div>
        <div className="flex items-center justify-between gap-1.5">
          <span className="app-type-micro inline-flex items-center gap-1.5 font-mono font-bold text-[var(--app-text)]">
            <span
              className={`size-1.5 rounded-full transition-colors ${
                isSelected
                  ? 'bg-[var(--app-accent)] shadow-[0_0_8px_var(--app-accent)]'
                  : 'bg-[var(--app-text-tertiary)]'
              }`}
            />
            Gen {iterationNum}
            <span className="font-normal text-[var(--app-text-tertiary)]">
              /{totalIterations}
            </span>
          </span>
          {isWinner ? (
            <span
              className={`app-type-micro rounded-full border px-1.5 py-0.2 font-sans font-semibold ${
                isProfitable
                  ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                  : 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
              }`}
            >
              {zh ? '当日优选' : 'Top Pick'}
            </span>
          ) : null}
        </div>

        <div className="mt-2 line-clamp-2 font-sans text-xs font-medium leading-relaxed text-[var(--app-text-secondary)] group-hover:text-[var(--app-text)] transition-colors">
          {candidate.comparison?.economic_hypothesis || candidate.draft_id}
        </div>
      </div>

      <div className="mt-3 border-t border-[var(--app-divider)] pt-2">
        <div className="grid grid-cols-2 gap-2 font-mono tabular-nums">
          <div>
            <span className="app-type-micro block font-sans font-medium uppercase tracking-wider text-[var(--app-text-tertiary)]">
              {zh ? '夏普' : 'Sharpe'}
            </span>
            <div className="mt-0.5 flex items-baseline gap-1">
              <span className="text-xs font-bold font-mono tabular-nums text-[var(--app-text)]">
                {metrics ? metrics.sharpe.toFixed(2) : '—'}
              </span>
              {sharpeDelta !== null && Math.abs(sharpeDelta) >= 0.01 ? (
                <span
                  className={`font-mono app-type-micro font-semibold tabular-nums ${
                    sharpeDelta > 0
                      ? 'text-[var(--app-pnl-positive)]'
                      : 'text-[var(--app-pnl-negative)]'
                  }`}
                >
                  {sharpeDelta > 0
                    ? `+${sharpeDelta.toFixed(2)}`
                    : sharpeDelta.toFixed(2)}
                </span>
              ) : null}
            </div>
          </div>
          <div>
            <span className="app-type-micro block font-sans font-medium uppercase tracking-wider text-[var(--app-text-tertiary)]">
              {zh ? '总收益' : 'Return'}
            </span>
            <div className="mt-0.5 flex items-baseline gap-1">
              <span
                className={`text-xs font-bold font-mono tabular-nums ${
                  metrics && metrics.total_return > 0
                    ? 'text-[var(--app-pnl-positive)]'
                    : metrics && metrics.total_return < 0
                      ? 'text-[var(--app-pnl-negative)]'
                      : 'text-[var(--app-text)]'
                }`}
              >
                {metrics ? formatPercent(metrics.total_return) : '—'}
              </span>
              {returnDelta !== null && Math.abs(returnDelta) >= 0.001 ? (
                <span
                  className={`font-mono app-type-micro font-semibold tabular-nums ${
                    returnDelta > 0
                      ? 'text-[var(--app-pnl-positive)]'
                      : 'text-[var(--app-pnl-negative)]'
                  }`}
                >
                  {returnDelta > 0
                    ? `+${formatPercent(returnDelta)}`
                    : formatPercent(returnDelta)}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="mt-2.5 flex items-center justify-between app-type-micro text-[var(--app-text-tertiary)]">
          <span>
            <span className="font-sans font-medium">
              {zh ? '最大回撤' : 'MaxDD'}:
            </span>{' '}
            <span className="font-mono app-type-micro font-semibold tabular-nums text-[var(--app-text-secondary)]">
              {metrics ? formatPercent(Math.abs(metrics.max_drawdown)) : '—'}
            </span>
          </span>
          {isSelected ? (
            <span className="app-type-micro flex items-center gap-1 font-sans font-medium text-[var(--app-accent)]">
              <span className="size-1 rounded-full bg-[var(--app-accent)]" />
              {zh ? '正在审阅' : 'Selected'}
            </span>
          ) : (
            <span className="app-type-micro font-sans text-[var(--app-text-tertiary)] transition-colors group-hover:text-[var(--app-text-secondary)]">
              {zh ? '点击查看' : 'Inspect'} &rarr;
            </span>
          )}
        </div>
      </div>
    </button>
  );
}
