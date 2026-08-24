import type {
  CiticHistoryXlsPreview,
  CiticSourceIntake,
  CiticSourceQueryWindowReview,
  CiticSourceReviewStatus,
  CiticSourceScopeReview,
} from '../api';

export type CiticHistoryXlsPreviewResult = {
  id: string;
  localFileName: string;
  localNameMonthHint: string | null;
  sourceKind: 'browser_file' | 'configured_directory';
  status: 'pending' | 'complete' | 'error';
  errorKind: 'read' | 'preview' | null;
  preview: CiticHistoryXlsPreview | null;
  intakeState: 'idle' | 'pending' | 'saved' | 'error';
  intake: CiticSourceIntake | null;
  queryWindowState: 'idle' | 'pending' | 'saved' | 'error';
  queryWindowReview: CiticSourceQueryWindowReview | null;
  sourceScopeState: 'idle' | 'pending' | 'saved' | 'error';
  sourceScopeReview: CiticSourceScopeReview | null;
};

export type CiticSourceReviewIntent = {
  resultId: string;
  reviewStatus: CiticSourceReviewStatus;
  queryStartDate: string;
  queryEndDate: string;
  queryWindowAttested: boolean;
  accountAlias: string;
  accountIdentifier: string;
  accountType: string;
  marketScopes: string;
  assetClasses: string;
  accountValueBand: string;
  businessTypes: string;
  noOtherFiltersAttested: boolean;
  completeReturnedResultsAttested: boolean;
  sourceScopeAttested: boolean;
};

export function parseCiticSourceScopeCodes(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(',')
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
    ),
  );
}
