import { useState } from 'react';

import { ResearchTaskPanel } from '../backtest-feature-boundary';
import { AccountStrategyPanel } from './account-strategy-panel';
import { BacktestReportView } from './backtest-report-view';
import { useBacktestPage } from './backtest-page-context';
import { BacktestResponsiveDisclosure } from './backtest-page-primitives';
import { FactorEvaluationPanel } from './factor-evaluation-panel';
import { StrategyEvidenceGatePanel } from './strategy-evidence-gate-panel';
import { StrategyLearningReviewPanel } from './strategy-learning-review-panel';

export function BacktestGovernancePanels() {
  const {
    accountStrategy,
    accountStrategyAssignments,
    accountStrategyAttribution,
    accountStrategyContribution,
    assignSelectedStrategy,
    assignSelectedStrategyToSymbol,
    latestReport,
    portfolioInstruments,
    promotionEvidenceOpen,
    readiness,
    researchArchiveOpen,
    researchGovernanceOpen,
    selectedStrategy,
    setPromotionEvidenceOpen,
    setResearchArchiveOpen,
    setResearchGovernanceOpen,
    strategyCatalog,
    symbol,
    updateAccountStrategy,
    updateScopedAccountStrategy,
    validation,
    labels,
    locale,
  } = useBacktestPage();
  const [factorTearSheetOpen, setFactorTearSheetOpen] = useState(false);
  const sectionTitle =
    locale === 'zh'
      ? '策略归属、样本外门禁与研究任务'
      : 'Strategy Allocation, OOS Gates & Research Tasks';
  const sectionKicker =
    locale === 'zh' ? '策略治理与证据归档' : 'Governance & Evidence Registry';

  return (
    <section className="space-y-4 pt-2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-2">
        <div>
          <div className="app-kicker">{sectionKicker}</div>
          <h2 className="text-sm font-semibold text-[var(--app-text)]">
            {sectionTitle}
          </h2>
        </div>
        <span className="app-type-micro rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2.5 py-0.5 text-[var(--app-text-tertiary)]">
          Governance &amp; Evidence
        </span>
      </div>

      <div className="space-y-3">
        <BacktestResponsiveDisclosure
          detail={
            locale === 'zh'
              ? '多标的横截面因子 Rank IC、ICIR、分位数收益单调性与最新截面排序'
              : 'Cross-sectional factor Rank IC, ICIR, quantile spread and ranking'
          }
          id="backtest-factor-evaluation"
          open={factorTearSheetOpen}
          onToggle={() => setFactorTearSheetOpen((current) => !current)}
          testId="backtest-factor-evaluation-disclosure"
          title={
            locale === 'zh'
              ? '因子体检仪与宏观 ETF 资产池'
              : 'Factor Tear Sheet & Curated Universes'
          }
        >
          <FactorEvaluationPanel />
        </BacktestResponsiveDisclosure>

        <BacktestResponsiveDisclosure
          detail={labels.researchGovernanceDetail}
          id="backtest-research-governance"
          open={researchGovernanceOpen}
          onToggle={() => setResearchGovernanceOpen((current) => !current)}
          testId="backtest-research-governance-disclosure"
          title={labels.researchGovernanceTitle}
        >
          <AccountStrategyPanel
            assignment={accountStrategy.data ?? null}
            attribution={accountStrategyAttribution.data ?? null}
            contribution={accountStrategyContribution.data ?? null}
            instruments={portfolioInstruments.data?.positions ?? []}
            scopedAssignments={accountStrategyAssignments.data ?? []}
            targetSymbol={symbol}
            selectedStrategy={selectedStrategy}
            strategyCatalog={strategyCatalog}
            loading={accountStrategy.isLoading}
            error={accountStrategy.isError}
            scopedAssignmentsLoading={accountStrategyAssignments.isLoading}
            scopedAssignmentsError={accountStrategyAssignments.isError}
            attributionLoading={accountStrategyAttribution.isLoading}
            attributionError={accountStrategyAttribution.isError}
            contributionLoading={accountStrategyContribution.isLoading}
            contributionError={accountStrategyContribution.isError}
            assigning={updateAccountStrategy.isPending}
            assigningScoped={updateScopedAccountStrategy.isPending}
            assignError={updateAccountStrategy.isError}
            assignScopedError={updateScopedAccountStrategy.isError}
            onAssignSelected={assignSelectedStrategy}
            onAssignSelectedToSymbol={assignSelectedStrategyToSymbol}
          />

          <StrategyLearningReviewPanel />
        </BacktestResponsiveDisclosure>

        <BacktestResponsiveDisclosure
          detail={labels.promotionEvidenceDetail}
          id="backtest-promotion-evidence"
          open={promotionEvidenceOpen}
          onToggle={() => setPromotionEvidenceOpen((current) => !current)}
          testId="backtest-promotion-evidence-disclosure"
          title={labels.promotionEvidenceTitle}
        >
          <StrategyEvidenceGatePanel
            strategyCatalog={strategyCatalog}
            validation={validation.data ?? null}
            readiness={readiness.data ?? null}
            loading={validation.isLoading || readiness.isLoading}
            error={validation.isError || readiness.isError}
          />
        </BacktestResponsiveDisclosure>

        <BacktestResponsiveDisclosure
          detail={labels.researchArchiveDetail}
          id="backtest-research-archive"
          open={researchArchiveOpen}
          onToggle={() => setResearchArchiveOpen((current) => !current)}
          testId="backtest-research-archive-disclosure"
          title={labels.researchArchiveTitle}
        >
          <ResearchTaskPanel
            backtestResultId={latestReport?.id ?? null}
            strategyId={accountStrategy.data?.strategy_id ?? null}
          />

          {latestReport ? <BacktestReportView /> : null}
        </BacktestResponsiveDisclosure>
      </div>
    </section>
  );
}
