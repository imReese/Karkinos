// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const OPERATIONS_ROOT = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = resolve(OPERATIONS_ROOT, '../..');
const FEATURES_ROOT = resolve(SRC_ROOT, 'features');
const API_BARREL = resolve(OPERATIONS_ROOT, 'api.ts');
const API_ROOT = resolve(OPERATIONS_ROOT, 'api');

const EXPECTED_PUBLIC_SYMBOLS = [
  'AutomationCockpitResponse',
  'AutomationCurrentPerOrderReviewCandidate',
  'AutomationCurrentPerOrderReviews',
  'BrokerAdapterReadiness',
  'BrokerAdapterReadinessRelease',
  'BrokerConnectorCapabilities',
  'BrokerConnectorHealthResponse',
  'BrokerConnectorSoakPromotionConnector',
  'BrokerConnectorSoakPromotionStatus',
  'BrokerGatewayAccountFactsResponse',
  'BrokerGatewayCapability',
  'BrokerGatewayFillsQueryResponse',
  'BrokerGatewayOrderQueryResponse',
  'BrokerGatewayStatusResponse',
  'BrokerLifecycleEvidenceHealth',
  'CiticSourceFollowUp',
  'ControlledBrokerRecoveryPreview',
  'ControlledBrokerRecoveryResult',
  'ControlledBrokerRejectionEvidenceExport',
  'ControlledBrokerRejectionEvidencePreview',
  'ControlledBrokerRejectionReview',
  'ControlledBrokerRejectionSafety',
  'ControlledBrokerWriteReleaseDossier',
  'ControlledBrokerWriteReleaseDossierRequest',
  'ControlledBrokerWriteReleaseEvidence',
  'ControlledBrokerWriteReleaseOwnerReviewRefs',
  'ControlledBrokerWriteReleaseRecord',
  'ControlledBrokerWriteReleaseRevocation',
  'ControlledBrokerWriteReleaseRevocationPreview',
  'ControlledBrokerWriteReleaseRevocationReason',
  'ControlledBrokerWriteReleaseStatus',
  'ControlledExecutionOperatorSession',
  'ControlledExecutionOperatorView',
  'ControlledLedgerCorrectionPlan',
  'ControlledLedgerCorrectionPositionState',
  'ControlledLedgerCorrectionPreview',
  'ControlledLedgerCorrectionReason',
  'ControlledLedgerCorrectionResult',
  'ControlledLedgerPostingEntry',
  'ControlledLedgerPostingPreview',
  'ControlledLedgerPostingResult',
  'ControlledOrderJourney',
  'ControlledOrderJourneyStage',
  'ControlledPerOrderPilotReadiness',
  'ControlledPerOrderPilotReadinessGate',
  'ControlledSessionRevocationPreview',
  'ControlledSessionRevocationReason',
  'ControlledSessionRevocationResult',
  'ControlledSubmissionClearanceFill',
  'ControlledSubmissionClearancePreview',
  'ControlledSubmissionClearanceResult',
  'CurrentPerOrderConfirmation',
  'CurrentPerOrderDossierCandidate',
  'CurrentPerOrderDossierCandidates',
  'CurrentPerOrderDossierPreview',
  'DailyCandidateExecutionEvidenceSummary',
  'DailyCandidateFinancialPreflight',
  'DailyCandidateRunResult',
  'DailyCandidateRuntimeStatus',
  'DailyCandidateTrial',
  'DailyCandidateTrialReview',
  'DailyStrategyOperatingConstraints',
  'ExecutionReconciliationItem',
  'ExecutionReconciliationRun',
  'ManualBrokerCancellationSafety',
  'ManualBrokerCancellationTicketExport',
  'ManualBrokerCancellationTicketPreview',
  'OperationsAttentionItem',
  'OperationsExecutionReconciliationSummary',
  'OperationsSchedulerSummary',
  'OperationsStatus',
  'OperationsSubsystem',
  'OperationsTodayResponse',
  'OperatorApprovalChallenge',
  'OperatorApprovalStatus',
  'PaperShadowCostSummary',
  'PaperShadowDivergenceSummary',
  'PaperShadowExecutionComparison',
  'PaperShadowExpectedStrategyBehavior',
  'PaperShadowManualHandoff',
  'PaperShadowMarketSymbolContext',
  'PaperShadowRealizedMarketContext',
  'PaperShadowReviewQueueItem',
  'PaperShadowRunResponse',
  'PaperShadowRunReviewResponse',
  'SignedBrokerAdapterReleaseCurrentReview',
  'SignedBrokerAdapterReleaseReviewDecision',
  'SignedBrokerAdapterReleaseReviewDossier',
  'SignedBrokerAdapterReleaseReviewDossierRequest',
  'SignedBrokerAdapterReleaseReviewListItem',
  'SignedBrokerAdapterReleaseReviewRecord',
  'SignedBrokerAdapterReleaseReviewStatus',
  'TrustedOperatorIdentity',
  'VerifiedOperatorApproval',
  'useAutomationCockpitQuery',
  'useBrokerConnectorHealthQuery',
  'useBrokerConnectorSoakPromotionStatusQuery',
  'useBrokerGatewayAccountFactsQuery',
  'useBrokerGatewayFillsQuery',
  'useBrokerGatewayOrderQuery',
  'useBrokerGatewayStatusQuery',
  'useControlledBrokerRecoveryApplyMutation',
  'useControlledBrokerRecoveryApprovalChallengeMutation',
  'useControlledBrokerRecoveryPreviewMutation',
  'useControlledBrokerRejectionEvidenceExportMutation',
  'useControlledBrokerRejectionEvidencePreviewMutation',
  'useControlledBrokerRejectionReviewMutation',
  'useControlledBrokerWriteReleaseApprovalChallengeMutation',
  'useControlledBrokerWriteReleaseDossierPreviewMutation',
  'useControlledBrokerWriteReleaseIssueMutation',
  'useControlledBrokerWriteReleaseRevocationMutation',
  'useControlledBrokerWriteReleaseRevocationPreviewMutation',
  'useControlledBrokerWriteReleasesQuery',
  'useControlledBrokerWriteReleaseStatusQuery',
  'useControlledLedgerCorrectionApplyMutation',
  'useControlledLedgerCorrectionApprovalChallengeMutation',
  'useControlledLedgerCorrectionPreviewMutation',
  'useControlledLedgerPostingApplyMutation',
  'useControlledLedgerPostingPreviewMutation',
  'useControlledSessionRevocationApprovalChallengeMutation',
  'useControlledSessionRevocationMutation',
  'useControlledSessionRevocationPreviewMutation',
  'useControlledSubmissionClearanceApplyMutation',
  'useControlledSubmissionClearanceApprovalChallengeMutation',
  'useControlledSubmissionClearancePreviewMutation',
  'useCurrentPerOrderConfirmationMutation',
  'useCurrentPerOrderDossierApprovalChallengeMutation',
  'useCurrentPerOrderDossierCandidatesQuery',
  'useCurrentPerOrderDossierPreviewMutation',
  'useDailyCandidateTrialReviewMutation',
  'useExecutionReconciliationRunDetailQuery',
  'useExecutionReconciliationRunsQuery',
  'useManualBrokerCancellationTicketExportMutation',
  'useManualBrokerCancellationTicketPreviewMutation',
  'useOperationsTodayQuery',
  'useOperatorApprovalChallengeMutation',
  'useOperatorApprovalStatusQuery',
  'useOperatorApprovalVerificationMutation',
  'useReviewPaperShadowRunMutation',
  'useRunDailyCandidateMutation',
  'useRunPaperShadowMutation',
  'useSignedBrokerAdapterReleaseReviewApprovalChallengeMutation',
  'useSignedBrokerAdapterReleaseReviewDossierPreviewMutation',
  'useSignedBrokerAdapterReleaseReviewMutation',
  'useSignedBrokerAdapterReleaseReviewsQuery',
  'useSignedBrokerAdapterReleaseReviewStatusQuery',
].sort();

function relativeImportTargets(path: string) {
  const source = readFileSync(path, 'utf8');
  return Array.from(
    source.matchAll(
      /\b(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/g,
    ),
    (match) => match[1],
  )
    .filter((specifier) => specifier.startsWith('.'))
    .map((specifier) => resolve(dirname(path), specifier));
}

function isInside(path: string, directory: string) {
  const pathFromDirectory = relative(directory, path);
  return (
    pathFromDirectory === '' ||
    (!pathFromDirectory.startsWith('..') && !isAbsolute(pathFromDirectory))
  );
}

function functionLineCounts(source: string) {
  const starts = Array.from(
    source.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{/gs),
  );
  return starts.map((match) => {
    const start = match.index;
    const openingBrace = source.indexOf('{', start);
    let depth = 0;
    let end = openingBrace;
    for (; end < source.length; end += 1) {
      if (source[end] === '{') depth += 1;
      if (source[end] === '}') depth -= 1;
      if (depth === 0) break;
    }
    return {
      name: match[1],
      lines: source.slice(start, end + 1).split('\n').length,
    };
  });
}

function publicSymbolsFromModule(path: string) {
  const source = readFileSync(path, 'utf8');
  const declaredSymbols = Array.from(
    source.matchAll(/^export (?:type|function) ([A-Za-z_$][\w$]*)/gm),
    (match) => match[1],
  );
  const reexportedTypeSymbols = Array.from(
    source.matchAll(
      /^export\s+type\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]\s*;/gm,
    ),
    (match) => match[1],
  ).flatMap((exports) =>
    exports
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)
      .map((entry) => entry.split(/\s+as\s+/).at(-1)),
  );
  return declaredSymbols.concat(reexportedTypeSymbols);
}

test('operations API keeps its compatibility surface in one thin barrel', () => {
  const barrelSource = readFileSync(API_BARREL, 'utf8');
  const publicModules = Array.from(
    barrelSource.matchAll(/^export \* from '([^']+)';$/gm),
    (match) => resolve(dirname(API_BARREL), `${match[1]}.ts`),
  );
  const nonBarrelLines = barrelSource
    .split('\n')
    .filter(Boolean)
    .filter((line) => !/^export \* from '[^']+';$/.test(line));
  const publicSymbols = publicModules.flatMap(publicSymbolsFromModule);

  expect(nonBarrelLines).toEqual([]);
  expect(new Set(publicSymbols).size).toBe(publicSymbols.length);
  expect(publicSymbols.sort()).toEqual(EXPECTED_PUBLIC_SYMBOLS);
});

test('operations API modules have zero oversized module or function debt', () => {
  const paths = [API_BARREL].concat(
    readdirSync(API_ROOT)
      .filter((name) => name.endsWith('.ts'))
      .map((name) => resolve(API_ROOT, name)),
  );
  const oversizedModules = paths
    .map((path) => ({
      path: relative(SRC_ROOT, path),
      lines: readFileSync(path, 'utf8').split('\n').length,
    }))
    .filter(({ lines }) => lines > 800);
  const oversizedFunctions = paths.flatMap((path) =>
    functionLineCounts(readFileSync(path, 'utf8'))
      .filter(({ lines }) => lines > 350)
      .map(({ name, lines }) => ({
        path: relative(SRC_ROOT, path),
        name,
        lines,
      })),
  );

  expect(oversizedModules).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
});

test('operations API modules do not depend on another feature', () => {
  const paths = [API_BARREL].concat(
    readdirSync(API_ROOT)
      .filter((name) => name.endsWith('.ts'))
      .map((name) => resolve(API_ROOT, name)),
  );
  const violations = paths.flatMap((path) =>
    relativeImportTargets(path)
      .filter(
        (target) =>
          isInside(target, FEATURES_ROOT) && !isInside(target, OPERATIONS_ROOT),
      )
      .map(
        (target) =>
          `${relative(SRC_ROOT, path)} -> ${relative(SRC_ROOT, target)}`,
      ),
  );

  expect(violations).toEqual([]);
});

test('daily operations response contracts have one shared owner', () => {
  const accountApi = readFileSync(
    resolve(FEATURES_ROOT, 'account/api.ts'),
    'utf8',
  );
  const decisionApi = readFileSync(
    resolve(FEATURES_ROOT, 'decision/api.ts'),
    'utf8',
  );

  expect(accountApi).toContain(
    "from '../../shared/contracts/daily-operations'",
  );
  expect(decisionApi).toContain(
    "from '../../shared/contracts/daily-operations'",
  );
  expect(accountApi).not.toMatch(/export type DailyOperationsSummary\s*=/);
  expect(decisionApi).not.toMatch(
    /export type DailyTradingPlanBlockerSummary\s*=/,
  );
});
