import { expect, test } from '@playwright/test';

import type { BacktestReport } from '../src/features/backtest/api-contracts';
import type { ResearchObservation } from '../src/features/backtest/observation-contracts';

const datasetId = `sha256:${'a'.repeat(64)}`;
const futureId = `sha256:${'b'.repeat(64)}`;
const identity = '11111111-1111-4111-8111-111111111111';
const report: BacktestReport = {
  id: 201,
  created_at: '2026-09-18T08:00:00Z',
  config: {
    strategy: 'dual_ma',
    start_date: '2026-09-14',
    end_date: '2026-09-18',
    initial_cash: 100000,
    dataset_id: datasetId,
    assets: [{ symbol: '600000', asset_class: 'stock' }],
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 100000,
    total_return: 0,
    annual_return: 0,
    sharpe: 0,
    sortino: 0,
    max_drawdown: 0,
    win_rate: 0,
    duration_days: 5,
  },
  equity_curve: [],
  fills: [],
};

for (const width of [390, 1280]) {
  test(`saved observation publishes, reloads, pauses and measures at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    let observation: ResearchObservation | null = null;
    const commands: string[] = [];
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      const method = route.request().method();
      let payload: unknown;
      if (path === '/api/backtest/results')
        payload = [
          {
            id: 201,
            created_at: report.created_at,
            strategy: 'dual_ma',
            total_return: 0,
            sharpe: 0,
            max_drawdown: 0,
          },
        ];
      else if (path === '/api/backtest/results/201') payload = report;
      else if (path === '/api/backtest/strategies') payload = [];
      else if (path === '/api/backtest/strategy-promotion-readiness')
        payload = { rows: [], limitations: [] };
      else if (path === '/api/backtest/datasets')
        payload = {
          tdx_configured: false,
          storage_path: '',
          busy: false,
          datasets: [datasetId, futureId].map((id) => ({
            dataset_id: id,
            start_date: '2026-09-14',
            end_date: id === datasetId ? '2026-09-18' : '2026-09-22',
            instruments: [{ symbol: '600000', instrument_type: 'stock' }],
            cross_source_verified: true,
            point_in_time_verified: false,
          })),
        };
      else if (path === '/api/research-observations' && method === 'GET') {
        expect(url.searchParams.get('source_backtest_result_id')).toBe('201');
        payload = observation ? [observation] : [];
      } else if (path === '/api/research-observations' && method === 'POST') {
        const request = route.request().postDataJSON();
        commands.push('start');
        expect(request.source_backtest_result_id).toBe(201);
        expect(request.horizon_sessions).toBe(1);
        expect(request.health_policy).toEqual({
          mode: 'observe_only',
          window_intervals: 2,
          minimum_eligible_intervals: 2,
          minimum_mean_relative_price_response: '-0.015',
        });
        observation = {
          id: identity,
          source_backtest_result_id: 201,
          lifecycle: 'active',
          version: 0,
          started_at: '2026-09-18T08:00:00Z',
          last_blocker: null,
          source: {
            strategy_kind: 'dual_ma',
            start_date: '2026-09-14',
            dataset_id: datasetId,
            source_code_verified: false,
            source_historical_pit_verified: false,
          },
          universe: [{ symbol: '600000', instrument_type: 'stock' }],
          policy: {
            horizon_sessions: 1,
            max_symbol_weight: '0.25',
            max_gross_weight: '1',
            health_policy: request.health_policy,
          },
          publications: [],
          outcomes: [],
        };
        payload = { id: identity, version: 0 };
      } else if (path === `/api/research-observations/${identity}`)
        payload = observation;
      else if (
        path === `/api/research-observations/${identity}/pause` &&
        observation
      ) {
        commands.push('pause');
        expect(route.request().postDataJSON().expected_version).toBe(
          observation.version,
        );
        observation.lifecycle = 'paused';
        observation.version++;
        payload = { id: identity, version: observation.version };
      } else if (
        path === `/api/research-observations/${identity}/advance` &&
        observation
      ) {
        const request = route.request().postDataJSON();
        expect(request.expected_version).toBe(observation.version);
        observation.version++;
        if (observation.lifecycle === 'active') {
          commands.push('publish');
          expect(request.dataset_id).toBe(datasetId);
          observation.publications.push({
            id: 'publication-1',
            decision_session: '2026-09-18',
            published_at: '2026-09-18T08:01:00Z',
            dataset_id: datasetId,
            payload: {
              forecasts: [
                { symbol: '600000', instrument_type: 'stock', action: 'enter' },
              ],
              previous_target_weights: { '600000': '0' },
              target_weights: { '600000': '0.25' },
              rebalance_weight_deltas: { '600000': '0.25' },
              risk_decision: { status: 'allowed', reasons: [] },
              reference_session: '2026-09-21',
              end_session: '2026-09-22',
              horizon_sessions: 1,
            },
          });
        } else {
          commands.push('measure');
          expect(request.dataset_id).toBe(futureId);
          observation.outcomes.push({
            publication_id: 'publication-1',
            horizon: 1,
            measured_at: '2026-09-22T08:00:00Z',
            dataset_id: futureId,
            payload: {
              status: 'measured',
              weighted_price_response: '0.025',
              return_basis: 'unadjusted_price_only',
              observations: [
                {
                  symbol: '600000',
                  target_weight: '0.25',
                  price_return: '0.1',
                  weighted_price_response: '0.025',
                },
              ],
            },
          });
        }
        observation.health_decision = {
          policy_id: 'karkinos.research.forward_price_health.v1',
          status: observation.outcomes.length
            ? 'insufficient_evidence'
            : 'waiting',
          action: 'none',
          evaluated_at: observation.outcomes.length
            ? '2026-09-22T08:00:00Z'
            : '2026-09-18T08:01:00Z',
          market_as_of: observation.outcomes.length
            ? '2026-09-22'
            : '2026-09-18',
          data_available: true,
          counts: {
            scheduled_matured: observation.outcomes.length,
            pending: observation.outcomes.length ? 0 : 1,
            missing_matured: 0,
            zero_exposure: 0,
            corporate_action_excluded: 0,
            unresolved: 0,
            eligible: observation.outcomes.length,
          },
          mean_relative_price_response: null,
          threshold: '-0.015',
          selected_publication_ids: observation.outcomes.length
            ? ['publication-1']
            : [],
          input_fingerprint: 'sha256:synthetic-health-input',
          blockers: [],
          limitations: [],
          return_basis: 'unadjusted_price_only',
        };
        payload = { id: identity, version: observation.version };
      } else {
        await route.fulfill({
          status: 503,
          json: { detail: 'synthetic_fixture_not_available' },
        });
        return;
      }
      await route.fulfill({ status: 200, json: payload });
    });
    async function openPanel() {
      if (width < 1280)
        await page.getByRole('tab', { name: 'Results and evidence' }).click();
      await page
        .getByText('Independent forward observation', { exact: true })
        .click();
    }
    await page.goto('/backtest');
    await openPanel();
    const panel = page.getByTestId('research-observations-panel');
    await panel
      .getByLabel('Outcome horizon (trading sessions)', { exact: true })
      .fill('1');
    await panel.getByLabel('Configure a forward health rule').check();
    await expect(
      panel.getByRole('button', { name: 'Start observation', exact: true }),
    ).toBeDisabled();
    await panel
      .getByLabel('Window of matured intervals', { exact: true })
      .fill('2');
    await panel
      .getByLabel('Minimum eligible intervals', { exact: true })
      .fill('2');
    await panel
      .getByLabel('Minimum mean relative price response (decimal)', {
        exact: true,
      })
      .fill('-0.015');
    await panel
      .getByText('Independent forward observation', { exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath(`observation-controls-${width}.png`),
    });
    await panel
      .getByLabel('Configure a forward health rule')
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`observation-health-settings-${width}.png`),
    });
    await panel
      .getByRole('button', { name: 'Start observation', exact: true })
      .click();
    const select = panel.getByRole('combobox', {
      name: 'Verified dataset for this observation',
      exact: true,
    });
    await expect(select).toBeVisible();
    await select.selectOption(datasetId);
    await panel
      .getByRole('button', {
        name: 'Publish targets and measure outcomes',
        exact: true,
      })
      .click();
    await expect(panel).toContainText('Awaiting future data');
    await expect(panel).toContainText('Waiting for intervals to mature');
    await page.reload();
    await openPanel();
    await expect(panel).toContainText('Awaiting future data');
    await expect(panel).toContainText('Waiting for intervals to mature');
    await panel
      .getByRole('button', { name: 'Pause new publications', exact: true })
      .click();
    await expect(
      panel.getByRole('button', {
        name: 'Pause new publications',
        exact: true,
      }),
    ).toBeDisabled();
    await select.selectOption(futureId);
    await panel
      .getByRole('button', {
        name: 'Measure existing publications',
        exact: true,
      })
      .click();
    await expect(panel).toContainText('Measured price response');
    await expect(panel).toContainText('2.5%');
    await expect(panel).toContainText('Too few eligible intervals');
    await expect(panel).toContainText('not NAV or proof of alpha decay');
    await expect(
      panel.getByRole('button', {
        name: 'Pause new publications',
        exact: true,
      }),
    ).toBeDisabled();
    await panel
      .getByRole('heading', { name: 'Forward health rule', exact: true })
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`observation-health-${width}.png`),
    });
    await panel
      .getByText('Decision session · 2026-09-18', { exact: true })
      .click();
    await expect(panel).toContainText('2026-09-21 → 2026-09-22');
    expect(commands).toEqual(['start', 'publish', 'pause', 'measure']);
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
    await panel
      .getByText('Decision session · 2026-09-18', { exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath(`observation-${width}.png`),
    });
  });
}
