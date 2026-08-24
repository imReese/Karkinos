import { ResearchTaskPanel } from '../../ai-research/components/research-task-panel';
import { AccountStrategyPanel } from './account-strategy-panel';
import { BacktestReportView } from './backtest-report-view';
import { useBacktestPage } from './backtest-page-context';
import { BacktestResponsiveDisclosure } from './backtest-page-primitives';
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
  } = useBacktestPage();
  return (
    <>
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
    </>
  );
}
