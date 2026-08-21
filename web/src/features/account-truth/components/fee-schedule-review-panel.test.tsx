import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import {
  REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
  REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
  type AccountTruthEvidenceReadiness,
  type ReviewedFeeSchedulePreview,
  type ReviewedFeeScheduleReview,
  type ReviewedFeeScheduleReviewStatus,
} from '../api';
import { FeeScheduleReviewPanel } from './fee-schedule-review-panel';

const previewFingerprint = `sha256:${'1'.repeat(64)}`;
const reviewFingerprint = `sha256:${'2'.repeat(64)}`;
const scheduleFingerprint = `sha256:${'3'.repeat(64)}`;

const readiness = {
  evidence_scope: {
    declared_coverage_window: {
      status: 'complete',
      start_date: '2026-01-01',
      end_date: '2026-12-31',
    },
  },
} as AccountTruthEvidenceReadiness;

const readyPreview: ReviewedFeeSchedulePreview = {
  schema_version: 'karkinos.account_truth.reviewed_fee_schedule_preview.v1',
  status: 'ready',
  schedule: {
    schedule_id: 'synthetic_reviewed_schedule',
    account_profile_id: 'synthetic_account',
    broker_name: 'synthetic_broker',
    stock_a_commission_rate: '0.0001',
    stock_a_min_commission: '5',
    fund_etf_commission_rate: '0.0001',
    fund_etf_min_commission: '5',
    stamp_tax_rate: '0.0005',
    transfer_fee_rate: '0.00001',
    fund_etf_transfer_fee_rate: '0',
    exchange_transfer_fee_rates: { shanghai: '0.00001' },
    other_fee_rate: '0',
    money_precision: '0.01',
    money_rounding_mode: 'half_up',
    limitations: [],
  },
  schedule_fingerprint: scheduleFingerprint,
  effective_start_date: '2026-01-01',
  effective_end_date: '2026-12-31',
  account_truth_import_run_id: 'synthetic-import',
  account_truth_source_fingerprint: `sha256:${'4'.repeat(64)}`,
  account_truth_scope_fingerprint: `sha256:${'5'.repeat(64)}`,
  account_reference_hash: `sha256:${'6'.repeat(64)}`,
  account_truth_readiness_status: 'ready',
  account_truth_promotion_status: 'clear',
  component_reconciliation: {
    status: 'pass',
    trade_count: 2,
    matched_trade_count: 2,
    side_counts: { buy: 1, sell: 1 },
    asset_class_counts: { stock: 2 },
    mismatch_counts: { fee: 0, tax: 0, transfer_fee: 0 },
    mismatch_counts_by_asset_and_side: [],
    maximum_absolute_differences: {
      fee: '0',
      tax: '0',
      transfer_fee: '0',
    },
    tolerance: '0.01',
  },
  issues: [],
  preview_fingerprint: previewFingerprint,
  persisted_broker_events_only: true,
  stores_broker_event_details: false,
  provider_contacted: false,
  authorizes_execution: false,
  changes_capital_authority: false,
};

const acceptedReview: ReviewedFeeScheduleReview = {
  review_id: 'fee_review_synthetic',
  schema_version: 'karkinos.account_truth.reviewed_fee_schedule_review.v1',
  decision: 'accepted',
  schedule: readyPreview.schedule,
  schedule_fingerprint: scheduleFingerprint,
  preview: readyPreview,
  preview_fingerprint: previewFingerprint,
  account_truth_import_run_id: readyPreview.account_truth_import_run_id,
  account_truth_source_fingerprint:
    readyPreview.account_truth_source_fingerprint,
  account_truth_scope_fingerprint: readyPreview.account_truth_scope_fingerprint,
  account_reference_hash: readyPreview.account_reference_hash,
  effective_start_date: readyPreview.effective_start_date,
  effective_end_date: readyPreview.effective_end_date,
  reviewer: 'synthetic_owner',
  review_fingerprint: reviewFingerprint,
  created_at: '2026-08-12T08:00:00+08:00',
  reused: false,
};

const missingStatus: ReviewedFeeScheduleReviewStatus = {
  status: 'missing',
  review: null,
  blockers: ['reviewed_fee_schedule_review_missing'],
  current_preview_fingerprint: null,
  authorizes_execution: false,
  changes_capital_authority: false,
};

const activeStatus: ReviewedFeeScheduleReviewStatus = {
  status: 'active',
  review: acceptedReview,
  blockers: [],
  current_preview_fingerprint: previewFingerprint,
  authorizes_execution: false,
  changes_capital_authority: false,
};

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderPanel(
  initialStatus: ReviewedFeeScheduleReviewStatus,
  preview: ReviewedFeeSchedulePreview = readyPreview,
) {
  let currentStatus = initialStatus;
  const requests: Array<{ url: string; method: string; body: unknown }> = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      requests.push({ url, method, body });
      if (
        url.endsWith('/api/account-truth/fee-schedule/review') &&
        method === 'GET'
      ) {
        return jsonResponse(currentStatus);
      }
      if (url.endsWith('/api/account-truth/fee-schedule/preview')) {
        return jsonResponse(preview);
      }
      if (url.endsWith('/api/account-truth/fee-schedule/reviews/revoke')) {
        const revokedReview = {
          ...acceptedReview,
          decision: 'revoked' as const,
          reviewer: String((body as { reviewer: string }).reviewer),
        };
        currentStatus = {
          status: 'revoked',
          review: revokedReview,
          blockers: ['reviewed_fee_schedule_review_revoked'],
          current_preview_fingerprint: null,
          authorizes_execution: false,
          changes_capital_authority: false,
        };
        return jsonResponse({
          status: 'revoked',
          review: revokedReview,
          revocation_confirmation:
            REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
          authorizes_execution: false,
          changes_capital_authority: false,
        });
      }
      if (url.endsWith('/api/account-truth/fee-schedule/reviews')) {
        currentStatus = activeStatus;
        return jsonResponse({
          status: 'accepted',
          review: acceptedReview,
          approval_confirmation: REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
          authorizes_execution: false,
          changes_capital_authority: false,
        });
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <FeeScheduleReviewPanel locale="en" readiness={readiness} />
    </QueryClientProvider>,
  );
  return { requests };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test('requires an exact current preview and explicit human confirmation before acceptance', async () => {
  const user = userEvent.setup();
  const { requests } = renderPanel(missingStatus);

  expect(await screen.findByText('No reviewed fee schedule')).toBeTruthy();
  expect(
    (screen.getByTestId('fee-schedule-start-date') as HTMLInputElement).value,
  ).toBe('2026-01-01');
  await user.click(screen.getByRole('button', { name: 'Recompute preview' }));
  expect(await screen.findByText('Exact fee evidence matches')).toBeTruthy();
  expect(screen.getAllByText('2', { selector: 'dd' })).toHaveLength(2);
  expect(
    screen.getByText(/Daily-candidate fee scope: stocks only/),
  ).toBeTruthy();
  expect(screen.getByText('Stock transfer fee')).toBeTruthy();
  expect(screen.queryByText('ETF transfer fee')).toBeNull();

  const approve = screen.getByRole('button', {
    name: 'Accept reviewed fee schedule',
  });
  expect((approve as HTMLButtonElement).disabled).toBe(true);
  await user.type(screen.getByLabelText('Reviewer'), 'synthetic_owner');
  await user.type(
    screen.getByLabelText('Exact approval confirmation'),
    REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
  );
  expect((approve as HTMLButtonElement).disabled).toBe(false);
  await user.click(approve);

  await screen.findByText('Current review is active for research');
  expect(screen.getByText('Active for research')).toBeTruthy();
  expect(screen.queryByTestId('fee-schedule-preview-summary')).toBeNull();
  const approvalRequest = requests.find(
    (request) =>
      request.url.endsWith('/fee-schedule/reviews') &&
      request.method === 'POST',
  );
  expect(approvalRequest?.body).toEqual({
    effective_start_date: '2026-01-01',
    effective_end_date: '2026-12-31',
    reviewed_asset_classes: ['stock'],
    expected_preview_fingerprint: previewFingerprint,
    reviewer: 'synthetic_owner',
    confirmation: REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
  });
});

test('keeps approval unavailable when deterministic component evidence is blocked', async () => {
  const user = userEvent.setup();
  renderPanel(missingStatus, {
    ...readyPreview,
    status: 'blocked',
    component_reconciliation: {
      ...readyPreview.component_reconciliation,
      status: 'blocked',
      matched_trade_count: 1,
      mismatch_counts: { fee: 1, tax: 0, transfer_fee: 0 },
      mismatch_counts_by_asset_and_side: [
        {
          asset_class: 'etf',
          side: 'buy',
          fee: 1,
          tax: 0,
          transfer_fee: 0,
        },
      ],
    },
    issues: ['reviewed_fee_schedule_component_mismatch'],
  });

  await user.click(
    await screen.findByRole('button', { name: 'Recompute preview' }),
  );
  expect(await screen.findByText('Fee evidence remains blocked')).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Accept reviewed fee schedule' }),
  ).toBeNull();
  expect(
    screen.getByText('Reviewed fee schedule component mismatch'),
  ).toBeTruthy();
  expect(
    screen.getByTestId('fee-schedule-mismatch-breakdown').textContent,
  ).toContain('fee 1 · tax 0 · transfer 0');
});

test('revokes the exact accepted review without any order or capital action', async () => {
  const { requests } = renderPanel(activeStatus);

  expect(
    await screen.findByText('Current review is active for research'),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Reviewer'), {
    target: { value: 'revoking_owner' },
  });
  fireEvent.change(screen.getByLabelText('Exact revocation confirmation'), {
    target: { value: REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Revoke reviewed fee schedule' }),
  );

  expect(
    await screen.findByText('Review revoked. Downstream use is denied.'),
  ).toBeTruthy();
  expect(await screen.findByText('Review revoked')).toBeTruthy();
  const revokeRequest = requests.find((request) =>
    request.url.endsWith('/fee-schedule/reviews/revoke'),
  );
  expect(revokeRequest?.body).toEqual({
    expected_review_id: acceptedReview.review_id,
    expected_review_fingerprint: acceptedReview.review_fingerprint,
    reviewer: 'revoking_owner',
    confirmation: REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
  });
});
