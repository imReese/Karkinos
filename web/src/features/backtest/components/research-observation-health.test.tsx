import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';

import { PreferencesContext } from '../../../shared/preferences/context';
import type {
  ObservationHealthDecision,
  ResearchObservation,
} from '../observation-contracts';
import { ResearchObservationHealth } from './research-observation-health';

const observation: ResearchObservation = {
  id: 'observation-1',
  source_backtest_result_id: 1,
  lifecycle: 'active',
  version: 1,
  started_at: '2026-09-15T08:00:00Z',
  last_blocker: null,
  source: {
    strategy_kind: 'dual_ma',
    start_date: '2026-09-01',
    dataset_id: 'source-dataset',
    source_code_verified: false,
    source_historical_pit_verified: false,
  },
  universe: [{ symbol: '600001', instrument_type: 'stock' }],
  policy: {
    horizon_sessions: 1,
    max_symbol_weight: '0.25',
    max_gross_weight: '1',
    health_policy: {
      mode: 'pause_on_breach',
      window_intervals: 4,
      minimum_eligible_intervals: 3,
      minimum_mean_relative_price_response: '-0.015',
    },
  },
  publications: [],
  outcomes: [],
};
const decision: ObservationHealthDecision = {
  policy_id: 'karkinos.research.forward_price_health.v1',
  status: 'insufficient_evidence',
  action: 'none',
  evaluated_at: '2026-09-23T08:00:00Z',
  market_as_of: '2026-09-23',
  data_available: true,
  counts: {
    scheduled_matured: 4,
    pending: 1,
    missing_matured: 0,
    zero_exposure: 1,
    corporate_action_excluded: 1,
    unresolved: 0,
    eligible: 2,
  },
  mean_relative_price_response: null,
  threshold: '-0.015',
  selected_publication_ids: ['publication-1', 'publication-3'],
  input_fingerprint: 'sha256:saved-input',
  source_fingerprint: 'sha256:saved-source',
  code_fingerprint: 'sha256:saved-code',
  policy_fingerprint: 'sha256:saved-policy',
  blockers: [],
  limitations: ['Synthetic saved measurement limitation'],
  return_basis: 'unadjusted_price_only',
};

function mount(
  overrides: Partial<ObservationHealthDecision>,
  lifecycle: ResearchObservation['lifecycle'] = 'active',
  locale: 'en' | 'zh' = 'en',
) {
  return render(
    <PreferencesContext.Provider
      value={{
        locale,
        setLocale: () => {},
        theme: 'dark',
        setTheme: () => {},
        resolvedTheme: 'dark',
      }}
    >
      <ResearchObservationHealth
        observation={{
          ...observation,
          lifecycle,
          health_decision: { ...decision, ...overrides },
        }}
      />
    </PreferencesContext.Provider>,
  );
}

test('insufficient eligible intervals remain unavailable rather than a zero performance response', () => {
  mount({});
  expect(screen.getByRole('status')).toHaveTextContent(
    'Too few eligible intervals',
  );
  const mean = screen.getByText(
    'Mean relative price response (decimal)',
  ).parentElement!;
  expect(within(mean).getByText('Unavailable')).toBeVisible();
  expect(
    screen.getByText('Eligible intervals').parentElement,
  ).toHaveTextContent('2');
  expect(
    screen.getByText('Corporate-action exclusions').parentElement,
  ).toHaveTextContent('1');
  expect(screen.getByText(/no lifecycle change/)).toBeVisible();
  expect(screen.getByText(/More eligible matured intervals/)).toBeVisible();
  expect(screen.getByText(/100% equal-weight allocation/)).toBeVisible();
  expect(screen.getByText(/not NAV or proof of alpha decay/)).toBeVisible();
});

test('unavailable evidence is distinct from a performance breach and preserves saved blocker details', () => {
  mount({
    status: 'unavailable',
    data_available: false,
    counts: { ...decision.counts, missing_matured: 1, unresolved: 1 },
    blockers: ['health_matured_outcomes_missing'],
  });
  expect(screen.getByRole('status')).toHaveTextContent(
    'Health evidence unavailable',
  );
  expect(
    screen.getByText(/does not establish strategy deterioration/),
  ).toBeVisible();
  expect(screen.getByText(/no lifecycle change/)).toBeVisible();
  const detail = screen
    .getByText('Saved health evidence details')
    .closest('details')!;
  detail.open = true;
  expect(screen.getByText('health_matured_outcomes_missing')).toBeVisible();
  expect(screen.getByText('sha256:saved-input')).toBeVisible();
  expect(screen.getByText('sha256:saved-policy')).toBeVisible();
  expect(screen.queryByText('Configured threshold breached')).toBeNull();
});

test('renders a persisted rule pause and its exact measured decimal without requesting automatic resume', () => {
  mount(
    {
      status: 'threshold_breached',
      action: 'pause_observation',
      mean_relative_price_response: '-0.01500001',
      counts: { ...decision.counts, eligible: 3, zero_exposure: 0 },
    },
    'paused',
  );
  expect(screen.getByRole('status')).toHaveTextContent(
    'Configured threshold breached',
  );
  expect(screen.getByText('-0.01500001')).toBeVisible();
  expect(screen.getByText(/saved rule paused new publications/)).toBeVisible();
  expect(screen.queryByRole('button')).toBeNull();
});

test('Chinese copy distinguishes waiting and uses the same decimal metric and benchmark boundary', () => {
  mount({ status: 'waiting' }, 'active', 'zh');
  expect(screen.getByRole('status')).toHaveTextContent('等待观察区间到期');
  expect(screen.getByText(/100% 等权配置/)).toBeVisible();
  expect(screen.getByText(/不是净值/)).toBeVisible();
});
