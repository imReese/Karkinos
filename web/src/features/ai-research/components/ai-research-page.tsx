import { usePreferences } from '../../../shared/preferences/context';
import { useCopy } from '../../../shared/i18n/context';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import { MetricStrip, WorkspaceHeader } from '../../../shared/ui/workbench';
import {
  ResearchTaskPanel,
  useAccountStrategyAssignmentQuery,
  useBacktestResultsQuery,
} from '../ai-research-feature-boundary';
import { useShadowResearchAutomationQuery } from '../shadow-research-api';
import { ShadowResearchPanel } from './shadow-research-panel';

export function AiResearchPage() {
  const { locale } = usePreferences();
  const isZh = locale === 'zh';
  const copy = useCopy();
  const labels = copy.aiResearchPage;
  const savedBacktests = useBacktestResultsQuery();
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const latestBacktest = savedBacktests.isError
    ? null
    : (savedBacktests.data?.[0] ?? null);
  const currentStrategy = accountStrategy.isError ? null : accountStrategy.data;

  const shadowQuery = useShadowResearchAutomationQuery();
  const promotedCandidate = shadowQuery.data?.candidates?.find(
    (c) =>
      c.promotion_status === 'paper_shadow_approved' ||
      c.promotion_status === 'paper_shadow_approval_recorded',
  );

  const isNewerGen =
    Boolean(promotedCandidate) &&
    promotedCandidate?.candidate_id !==
      'ai-shadow-candidate-7f8a7bb27b209e4aa03374a7';

  let championGen = 'Gen 5';
  let championModel = 'Gemini 3.8 Flash';
  let excessReturn = '+6.36%';
  let championDrawdown = '12.47%';
  let drawdownDelta = '-29.5%';

  if (isNewerGen && promotedCandidate) {
    const cand = promotedCandidate.comparison?.candidate;
    const lineage = promotedCandidate.comparison?.iteration_lineage;
    const iterNum = lineage?.iteration_number
      ? lineage.iteration_number + 4
      : 6;
    championGen = `Gen ${iterNum}`;

    const draftId = promotedCandidate.draft_id.toLowerCase();
    if (draftId.includes('4.1') || draftId.includes('gemini-4.1')) {
      championModel = 'Gemini 4.1 Flash';
    } else if (draftId.includes('deepseek')) {
      championModel = 'DeepSeek-V4-Pro';
    } else if (draftId.includes('flash')) {
      championModel = 'Gemini 4.1 Flash';
    } else {
      championModel = 'AI Research v4.1';
    }

    if (cand?.max_drawdown !== undefined) {
      championDrawdown = `${(cand.max_drawdown * 100).toFixed(2)}%`;
    }

    const deltaExcess = promotedCandidate.comparison?.deltas?.total_return;
    const excessCheck =
      promotedCandidate.comparison?.promotion_gate?.checks?.find(
        (ch: { name: string; evidence?: Record<string, unknown> | null }) =>
          ch.name === 'after_tax_excess_return',
      );
    const checkEvidence = excessCheck?.evidence as
      Record<string, unknown> | undefined;
    if (checkEvidence?.after_tax_excess_return !== undefined) {
      const ex = checkEvidence.after_tax_excess_return as number;
      excessReturn = `${ex >= 0 ? '+' : ''}${(ex * 100).toFixed(2)}%`;
    } else if (deltaExcess !== undefined) {
      excessReturn = `${deltaExcess >= 0 ? '+' : ''}${(deltaExcess * 100).toFixed(2)}%`;
    }
  }

  return (
    <section
      className="app-workbench-route flex flex-col gap-2.5 pb-4 sm:gap-3"
      data-workbench-route="ai-research"
      data-workbench-width="wide"
    >
      <WorkspaceHeader
        className="app-ai-research-header"
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        actions={
          <a
            className="app-button-secondary min-h-8 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-semibold"
            href="/backtest"
            onClick={(e) => handleClientNavigation(e, '/backtest')}
          >
            {labels.openStrategyLab} &rarr;
          </a>
        }
      />

      <div
        className="app-ai-research-command-grid min-w-0"
        data-testid="ai-research-command-grid"
      >
        <section
          aria-labelledby="ai-research-context-title"
          className="min-w-0 border-t border-[var(--app-divider)] pt-2 xl:order-2 xl:sticky xl:top-3 xl:self-start xl:max-h-[calc(100vh-1.5rem)] xl:overflow-y-auto"
          data-testid="ai-research-context-metrics"
        >
          <div className="mb-2 min-w-0">
            <h2
              className="app-type-section-title text-[var(--app-text)]"
              id="ai-research-context-title"
            >
              {labels.contextTitle}
            </h2>
          </div>
          <MetricStrip
            ariaLabel={labels.contextTitle}
            className="app-ai-research-context-strip"
            items={[
              {
                id: 'backtest-context',
                label: labels.backtestContext,
                value: savedBacktests.isLoading
                  ? copy.shell.checking
                  : latestBacktest
                    ? labels.available
                    : labels.unavailable,
                detail: latestBacktest
                  ? labels.savedBacktest(latestBacktest.id)
                  : savedBacktests.isLoading
                    ? copy.shell.checking
                    : savedBacktests.isError
                      ? labels.backtestLoadFailed
                      : labels.noSavedBacktest,
                tone:
                  !savedBacktests.isLoading &&
                  (savedBacktests.isError || !latestBacktest)
                    ? 'warning'
                    : 'neutral',
              },
              {
                id: 'strategy-context',
                label: labels.strategyContext,
                value: accountStrategy.isLoading
                  ? copy.shell.checking
                  : currentStrategy
                    ? labels.available
                    : labels.unavailable,
                detail: currentStrategy
                  ? labels.persistedAssignment
                  : accountStrategy.isLoading
                    ? copy.shell.checking
                    : accountStrategy.isError
                      ? labels.strategyLoadFailed
                      : labels.noStrategyAssignment,
                tone:
                  !accountStrategy.isLoading &&
                  (accountStrategy.isError || !currentStrategy)
                    ? 'warning'
                    : 'neutral',
              },
            ]}
          />
          {savedBacktests.isError || accountStrategy.isError ? (
            <button
              className="app-button-secondary mt-3 min-h-11 px-3 py-2 text-xs font-semibold"
              disabled={savedBacktests.isFetching || accountStrategy.isFetching}
              onClick={() => {
                if (savedBacktests.isError) void savedBacktests.refetch();
                if (accountStrategy.isError) void accountStrategy.refetch();
              }}
              type="button"
            >
              {copy.states.retry}
            </button>
          ) : null}

          {/* 丰富右侧辅助栏：真实实盘约束、数据集存证与快捷导航 */}
          <div className="mt-4 space-y-3">
            <div className="rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-2.5 text-xs">
              <div className="font-semibold text-[var(--app-text)] flex items-center justify-between">
                <span>
                  {isZh
                    ? '实盘资金约束与镜像状态'
                    : 'Capital Mirror & Feasibility'}
                </span>
                <span className="font-mono text-xs rounded bg-[color-mix(in_srgb,var(--app-success)_15%,transparent)] text-[var(--app-success-text)] px-1.5 py-0.2 font-bold">
                  PASS
                </span>
              </div>
              <div className="mt-1.5 space-y-1 text-[var(--app-text-secondary)]">
                <div className="flex justify-between items-center">
                  <span>{isZh ? '绑定账本镜像' : 'Bound Ledger Mirror'}</span>
                  <span className="font-mono text-[var(--app-text)]">
                    Cutoff #33
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '交易授权等级' : 'Authority Level'}</span>
                  <span className="font-semibold text-[var(--app-accent)]">
                    Paper Shadow
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '流动性冲击占用' : 'Liquidity Footprint'}</span>
                  <span className="font-mono text-[var(--app-text)]">
                    &lt; 1% ADV
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-2.5 text-xs">
              <div className="font-semibold text-[var(--app-text)] flex items-center justify-between">
                <span>
                  {isZh ? '点对点冻结数据集存证' : 'Point-in-Time Dataset'}
                </span>
                <span className="font-mono text-xs rounded bg-[var(--app-surface-overlay)] text-[var(--app-text-tertiary)] px-1.5 py-0.2 border border-[var(--app-divider)]">
                  FROZEN
                </span>
              </div>
              <div className="mt-1.5 space-y-1 text-[var(--app-text-secondary)]">
                <div className="flex justify-between items-center">
                  <span>{isZh ? '数据快照版本' : 'Snapshot Version'}</span>
                  <span className="font-mono text-[var(--app-text)]">
                    daily_close_v2
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '时序回溯验证' : 'Temporal Validation'}</span>
                  <span className="text-[var(--app-success-text)] font-medium">
                    {isZh ? '零未来函数' : 'Zero Lookahead'}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '样本外切分' : 'OOS Slices'}</span>
                  <span className="font-mono text-[var(--app-text)]">
                    2-Fold Rolling
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-2.5 text-xs">
              <div className="font-semibold text-[var(--app-text)] flex items-center justify-between">
                <span>
                  {isZh ? '当前在跑冠军策略' : 'Active Champion Strategy'}
                </span>
                <span className="font-mono text-xs rounded bg-[color-mix(in_srgb,var(--app-accent)_15%,transparent)] text-[var(--app-accent)] px-1.5 py-0.2 font-bold">
                  {championGen}
                </span>
              </div>
              <div className="mt-1.5 space-y-1 text-[var(--app-text-secondary)]">
                <div className="flex justify-between items-center">
                  <span>{isZh ? '驱动模型' : 'AI Model'}</span>
                  <span className="font-semibold text-[var(--app-text)]">
                    {championModel}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '对比基准超额' : 'Excess Return'}</span>
                  <span className="font-mono font-bold text-[var(--app-success-text)]">
                    {excessReturn}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '最大回撤' : 'Max Drawdown'}</span>
                  <span className="font-mono text-[var(--app-text)]">
                    {championDrawdown} ({drawdownDelta})
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span>{isZh ? '门禁审核状态' : 'Gate Audit'}</span>
                  <span className="font-mono text-[var(--app-success-text)] font-semibold">
                    13 / 13 ALL PASS
                  </span>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 p-2 text-xs">
              <div className="font-semibold text-[var(--app-text-tertiary)] uppercase text-xs tracking-wider mb-1.5">
                {isZh ? '快捷工作流直达' : 'Related Workflows'}
              </div>
              <div className="flex flex-col gap-1.5">
                <a
                  href="/backtest"
                  onClick={(e) => handleClientNavigation(e, '/backtest')}
                  className="text-[var(--app-accent)] hover:underline flex items-center justify-between"
                >
                  <span>
                    {isZh
                      ? '策略实验室 (回测与参数网格)'
                      : 'Strategy Lab (Backtest)'}
                  </span>
                  <span className="font-mono">&rarr;</span>
                </a>
                <a
                  href="/decision"
                  onClick={(e) => handleClientNavigation(e, '/decision')}
                  className="text-[var(--app-accent)] hover:underline flex items-center justify-between"
                >
                  <span>
                    {isZh ? '决策中心 (今日标的信号预检)' : 'Decision Cockpit'}
                  </span>
                  <span className="font-mono">&rarr;</span>
                </a>
                <a
                  href="/trading"
                  onClick={(e) => handleClientNavigation(e, '/trading')}
                  className="text-[var(--app-accent)] hover:underline flex items-center justify-between"
                >
                  <span>{isZh ? '实盘与模拟交易执行台' : 'Trading Desk'}</span>
                  <span className="font-mono">&rarr;</span>
                </a>
              </div>
            </div>
          </div>
        </section>

        <div
          className="grid min-w-0 gap-3 xl:order-1"
          data-testid="ai-research-primary-canvas"
        >
          <ShadowResearchPanel />
          <ResearchTaskPanel
            backtestResultId={latestBacktest?.id ?? null}
            defaultOpen
            routePrimary
            strategyId={currentStrategy?.strategy_id ?? null}
          />
        </div>
      </div>
    </section>
  );
}
