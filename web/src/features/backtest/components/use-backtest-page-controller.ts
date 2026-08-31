import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useAccountStrategyAssignmentQuery,
  useAccountStrategyAssignmentsQuery,
  useAccountStrategyAttributionQuery,
  useAccountStrategyContributionQuery,
  useBacktestAttributionPreviewMutation,
  useBacktestPaperShadowPreviewMutation,
  useBacktestResultsQuery,
  useBacktestRiskPreviewMutation,
  useBacktestStrategiesQuery,
  useRunBacktestMutation,
  useSingleInstrumentStrategyLoopAcceptanceAuditQuery,
  useStrategyPromotionReadinessQuery,
  useStrategySignalPreviewMutation,
  useStrategyValidationQuery,
  useUpdateAccountStrategyAssignmentMutation,
  useUpdateScopedAccountStrategyAssignmentMutation,
  type BacktestReport,
} from '../api';
import {
  buildParamValues,
  buildRunPayload,
  currentBacktestSearchDefaults,
  fallbackStrategies,
  isPositiveNumber,
  resultSummary,
  todayDate,
} from './backtest-page-model';
import { useBacktestPortfolioInstrumentsQuery } from './backtest-portfolio-query';

export function useBacktestPageController() {
  const copy = useCopy();
  const labels = copy.backtest.page;
  const common = copy.common;
  const { locale } = usePreferences();
  const [researchGovernanceOpen, setResearchGovernanceOpen] = useState(false);
  const [promotionEvidenceOpen, setPromotionEvidenceOpen] = useState(false);
  const [researchArchiveOpen, setResearchArchiveOpen] = useState(false);
  const [latestReport, setLatestReport] = useState<BacktestReport | null>(null);
  const accountStrategyEnabled = researchGovernanceOpen || researchArchiveOpen;
  const runBacktest = useRunBacktestMutation();
  const signalPreview = useStrategySignalPreviewMutation();
  const riskPreview = useBacktestRiskPreviewMutation();
  const paperShadowPreview = useBacktestPaperShadowPreviewMutation();
  const attributionPreview = useBacktestAttributionPreviewMutation();
  const strategies = useBacktestStrategiesQuery();
  const savedResults = useBacktestResultsQuery();
  const accountStrategy = useAccountStrategyAssignmentQuery(
    accountStrategyEnabled,
  );
  const accountStrategyAssignments = useAccountStrategyAssignmentsQuery(
    researchGovernanceOpen,
  );
  const accountStrategyAttribution = useAccountStrategyAttributionQuery(
    researchGovernanceOpen,
  );
  const accountStrategyContribution = useAccountStrategyContributionQuery(
    researchGovernanceOpen,
  );
  const portfolioInstruments = useBacktestPortfolioInstrumentsQuery(
    researchGovernanceOpen,
  );
  const updateAccountStrategy = useUpdateAccountStrategyAssignmentMutation();
  const updateScopedAccountStrategy =
    useUpdateScopedAccountStrategyAssignmentMutation();
  const validation = useStrategyValidationQuery(promotionEvidenceOpen);
  const readiness = useStrategyPromotionReadinessQuery();
  const singleInstrumentAudit =
    useSingleInstrumentStrategyLoopAcceptanceAuditQuery(latestReport !== null);
  const searchDefaults = useMemo(() => currentBacktestSearchDefaults(), []);
  const [startDate, setStartDate] = useState('2025-01-02');
  const [endDate, setEndDate] = useState(() => todayDate());
  const [initialCash, setInitialCash] = useState('100000');
  const [strategy, setStrategy] = useState(searchDefaults.strategy);
  const [parameterValues, setParameterValues] = useState<
    Record<string, string>
  >(() => buildParamValues(fallbackStrategies[0].parameter_schema));
  const [symbol, setSymbol] = useState(searchDefaults.symbol);
  const [assetClass, setAssetClass] = useState(searchDefaults.assetClass);
  const [mobileWorkspaceView, setMobileWorkspaceView] = useState<
    'setup' | 'results'
  >('setup');
  const [mobileWorkspaceTouched, setMobileWorkspaceTouched] = useState(false);
  const [advancedToolsOpen, setAdvancedToolsOpen] = useState(false);
  const [formError, setFormError] = useState('');
  const assetClassOptions = [
    { value: 'stock', label: common.assetClassStock },
    { value: 'etf', label: common.assetClassEtf },
    { value: 'fund', label: common.assetClassFund },
    { value: 'gold', label: common.assetClassGold },
    { value: 'bond', label: common.assetClassBond },
  ];

  const summary = useMemo(() => resultSummary(latestReport), [latestReport]);
  const strategyCatalog = useMemo(
    () =>
      strategies.data && strategies.data.length > 0
        ? strategies.data
        : fallbackStrategies,
    [strategies.data],
  );
  const selectedStrategy = useMemo(
    () =>
      strategyCatalog.find((item) => item.name === strategy) ??
      strategyCatalog[0],
    [strategy, strategyCatalog],
  );
  const selectedReadiness =
    readiness.data?.rows.find(
      (row) =>
        row.strategy_id === selectedStrategy.strategy_id ||
        row.strategy_id === selectedStrategy.name,
    ) ?? null;
  const parameterSchema = useMemo(
    () => selectedStrategy.parameter_schema ?? [],
    [selectedStrategy],
  );
  const selectedAssetClassLabel =
    assetClassOptions.find((option) => option.value === assetClass)?.label ??
    assetClass;
  const handoffLabels =
    searchDefaults.handoffSource === 'portfolio'
      ? {
          kicker: labels.holdingHandoffKicker,
          title: labels.holdingHandoffTitle,
          detail: labels.holdingHandoffDetail,
          badge: labels.decisionHandoffResearchOnly,
        }
      : {
          kicker: labels.decisionHandoffKicker,
          title: labels.decisionHandoffTitle,
          detail: labels.decisionHandoffDetail,
          badge: labels.decisionHandoffResearchOnly,
        };
  const runContextSourceLabel =
    searchDefaults.handoffSource === 'portfolio'
      ? labels.runContextSourcePortfolio
      : searchDefaults.hasHandoffContext
        ? labels.runContextSourceDecision
        : labels.runContextSourceManual;
  const reportAsset = latestReport?.config.assets?.[0] ?? null;
  const reportSymbol = reportAsset?.symbol ?? symbol;
  const reportAssetClass = reportAsset?.asset_class ?? assetClass;
  const reportAssetClassLabel =
    assetClassOptions.find((option) => option.value === reportAssetClass)
      ?.label ?? reportAssetClass;
  const reportStrategy =
    strategyCatalog.find(
      (item) =>
        item.name === latestReport?.config.strategy ||
        item.strategy_id === latestReport?.config.strategy,
    ) ?? selectedStrategy;

  useEffect(() => {
    setParameterValues(buildParamValues(parameterSchema));
  }, [strategy, parameterSchema]);

  useEffect(() => {
    if (!mobileWorkspaceTouched && savedResults.data?.length) {
      setMobileWorkspaceView('results');
    }
  }, [mobileWorkspaceTouched, savedResults.data]);

  const submitRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !startDate ||
      !endDate ||
      !isPositiveNumber(initialCash) ||
      parameterSchema.some((param) => {
        if (param.type !== 'int' && param.type !== 'float') {
          return false;
        }
        const value = parameterValues[param.name] ?? '';
        return !isPositiveNumber(value);
      })
    ) {
      setFormError(common.mustBePositive);
      return;
    }
    setFormError('');
    try {
      const payload = buildRunPayload({
        startDate,
        endDate,
        initialCash,
        strategy,
        parameterSchema,
        parameterValues,
        symbol,
        assetClass,
      });
      const report = await runBacktest.mutateAsync(payload);
      setLatestReport(report);
      setMobileWorkspaceTouched(true);
      setMobileWorkspaceView('results');
      signalPreview.reset();
      riskPreview.reset();
      paperShadowPreview.reset();
      attributionPreview.reset();
      const previewAsset = payload.assets?.[0];
      if (previewAsset) {
        signalPreview.mutate({
          strategy: payload.strategy,
          symbol: previewAsset.symbol,
          asset_class: previewAsset.asset_class,
          start_date: payload.start_date,
          end_date: payload.end_date,
          params: payload.params,
        });
      }
    } catch (error) {
      setFormError(
        error instanceof Error && error.message
          ? error.message
          : common.genericSubmitError,
      );
    }
  };

  const assignSelectedStrategy = async () => {
    await updateAccountStrategy.mutateAsync({
      strategy_id: selectedStrategy.name,
      status: 'research_only',
      scope: 'account',
      notes: 'Assigned from Backtest page for research review.',
    });
  };

  const assignSelectedStrategyToSymbol = async () => {
    const trimmedSymbol = symbol.trim();
    if (!trimmedSymbol) {
      return;
    }
    await updateScopedAccountStrategy.mutateAsync({
      strategy_id: selectedStrategy.name,
      status: 'research_only',
      scope: 'symbol',
      symbol: trimmedSymbol,
      asset_class: assetClass,
      notes:
        'Assigned from Backtest page for single-instrument research review.',
    });
  };
  return {
    accountStrategy,
    accountStrategyAssignments,
    accountStrategyAttribution,
    accountStrategyContribution,
    advancedToolsOpen,
    assetClass,
    assetClassOptions,
    assignSelectedStrategy,
    assignSelectedStrategyToSymbol,
    attributionPreview,
    copy,
    endDate,
    formError,
    handoffLabels,
    initialCash,
    labels,
    latestReport,
    locale,
    mobileWorkspaceView,
    paperShadowPreview,
    parameterSchema,
    parameterValues,
    portfolioInstruments,
    promotionEvidenceOpen,
    readiness,
    reportAssetClassLabel,
    reportStrategy,
    reportSymbol,
    researchArchiveOpen,
    researchGovernanceOpen,
    riskPreview,
    runBacktest,
    runContextSourceLabel,
    savedResults,
    searchDefaults,
    selectedAssetClassLabel,
    selectedReadiness,
    selectedStrategy,
    setAdvancedToolsOpen,
    setAssetClass,
    setEndDate,
    setInitialCash,
    setMobileWorkspaceTouched,
    setMobileWorkspaceView,
    setParameterValues,
    setPromotionEvidenceOpen,
    setResearchArchiveOpen,
    setResearchGovernanceOpen,
    setStartDate,
    setStrategy,
    setSymbol,
    signalPreview,
    singleInstrumentAudit,
    startDate,
    strategies,
    strategy,
    strategyCatalog,
    submitRun,
    summary,
    symbol,
    updateAccountStrategy,
    updateScopedAccountStrategy,
    validation,
  };
}
