import { expect, test } from '@playwright/test';

import type { BacktestReport } from '../src/features/backtest/api-contracts';
import type { ResearchObservation } from '../src/features/backtest/observation-contracts';
import type { ResearchPaperBook } from '../src/features/backtest/paper-book-contracts';
import {
  createdBook,
  settledBook,
  pausedBook,
  markedBook,
} from '../test-fixtures/research-paper-book';

const sourceId =
  'sha256:77e7be40523ed869932a2083d366e455d7909031d52ccc0458b6111398a56a1b';
const firstId = settledBook.steps[0].dataset_id;
const secondId = markedBook.steps[1].dataset_id;
const identity = createdBook.observation_id;
const report: BacktestReport = {
  id: 201,
  created_at: '2026-09-18T07:00:00Z',
  config: {
    strategy: 'dual_ma',
    start_date: '2026-09-14',
    end_date: '2026-09-18',
    initial_cash: 100000,
    dataset_id: sourceId,
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
  test(`independent book creates, settles, reloads and marks paused holdings at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    const observation: ResearchObservation = {
      id: identity,
      source_backtest_result_id: 201,
      lifecycle: 'active',
      version: 0,
      started_at: '2026-09-18T07:59:00Z',
      last_blocker: null,
      source: {
        strategy_kind: 'dual_ma',
        start_date: '2026-09-14',
        dataset_id: sourceId,
        source_code_verified: false,
        source_historical_pit_verified: false,
      },
      universe: [{ symbol: '600000', instrument_type: 'stock' }],
      policy: {
        horizon_sessions: 1,
        max_symbol_weight: '0.25',
        max_gross_weight: '1',
      },
      publications: [],
      outcomes: [],
      automation: {
        observation_id: identity,
        enabled: true,
        generation: '11111111-1111-4111-8111-111111111111',
        status: 'ready',
        last_checked_at: null,
        last_attempt_at: null,
        last_blocker: null,
        dataset_id: null,
        decision_session: null,
      },
    };
    let book: ResearchPaperBook | null = null;
    let rejected = false;
    const writes: string[] = [];
    const unexpectedWrites: string[] = [];
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      const method = request.method();
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
          datasets: [sourceId, firstId, secondId].map((id, index) => {
            const endDate = ['2026-09-18', '2026-09-21', '2026-09-22'][index];
            return {
              dataset_id: id,
              start_date: '2026-09-14',
              end_date: endDate,
              instruments: observation.universe,
              cross_source_verified: true,
              point_in_time_verified: false,
              corporate_action_evidence: {
                status: 'observed',
                oldest_captured_at: `${endDate}T07:05:00Z`,
              },
            };
          }),
        };
      else if (path === '/api/research-observations') payload = [observation];
      else if (path === `/api/research-observations/${identity}`)
        payload = observation;
      else if (
        path === `/api/research-observations/${identity}/advance` &&
        method === 'POST'
      ) {
        expect(book).not.toBeNull();
        const afterPause = book!.lifecycle === 'paused';
        writes.push(
          afterPause ? 'publish_after_pause' : 'publish_after_creation',
        );
        observation.version++;
        observation.publications.push({
          id: afterPause
            ? 'publication-after-pause'
            : settledBook.fills[0].publication_id,
          published_at: afterPause
            ? '2026-09-21T08:00:01Z'
            : '2026-09-18T08:00:01Z',
          decision_session: afterPause ? '2026-09-21' : '2026-09-18',
          dataset_id: afterPause ? firstId : sourceId,
          payload: {
            forecasts: [
              { symbol: '600000', instrument_type: 'stock', action: 'enter' },
            ],
            previous_target_weights: { '600000': afterPause ? '0.25' : '0' },
            target_weights: { '600000': '0.25' },
            rebalance_weight_deltas: { '600000': afterPause ? '0' : '0.25' },
            risk_decision: { status: 'allowed', reasons: [] },
            reference_session: afterPause ? '2026-09-22' : '2026-09-21',
            end_session: afterPause ? '2026-09-23' : '2026-09-22',
            horizon_sessions: 1,
          },
        });
        payload = { id: identity, version: observation.version };
      } else if (path === `/api/research-observations/${identity}/paper-book`) {
        if (method === 'POST') {
          expect(request.postDataJSON()).toMatchObject({
            initial_cash: '100000',
            cost_assumptions: {
              stock_commission_rate: 0,
              stock_min_commission: 5,
              slippage_bps: 0,
            },
          });
          expect(observation.publications).toHaveLength(0);
          writes.push('create');
          book = structuredClone(createdBook);
        }
        payload = book;
      } else if (
        path === `/api/research-observations/${identity}/paper-book/settle` &&
        method === 'POST'
      ) {
        const command = request.postDataJSON();
        expect(command.expected_version).toBe(book!.version);
        if (book!.version === 0) {
          expect(command.dataset_id).toBe(firstId);
          expect(observation.publications).toHaveLength(1);
          writes.push('settle');
          book = structuredClone(settledBook);
        } else if (!rejected) {
          writes.push('blocked');
          rejected = true;
          await route.fulfill({
            status: 422,
            json: { detail: 'paper_book_settled_prefix_conflict' },
          });
          return;
        } else {
          expect(book!.lifecycle).toBe('paused');
          expect(command.dataset_id).toBe(secondId);
          expect(observation.publications).toHaveLength(2);
          writes.push('mark_paused');
          book = structuredClone(markedBook);
        }
        payload = book;
      } else if (
        path === `/api/research-observations/${identity}/paper-book/pause` &&
        method === 'POST'
      ) {
        expect(request.postDataJSON().expected_version).toBe(1);
        writes.push('pause');
        book = structuredClone(pausedBook);
        payload = book;
      } else {
        if (method !== 'GET') unexpectedWrites.push(`${method} ${path}`);
        await route.fulfill({
          status: 503,
          json: { detail: 'synthetic_fixture_not_available' },
        });
        return;
      }
      await route.fulfill({ status: 200, json: payload });
    });
    async function openPanels() {
      if (width < 1280)
        await page.getByRole('tab', { name: 'Results and evidence' }).click();
      await expect(page.getByTestId('backtest-result-panel')).toBeVisible();
      const observations = page.getByTestId('research-observations-panel');
      await expect(observations).toBeVisible();
      if ((await observations.getAttribute('open')) === null)
        await observations.locator(':scope > summary').click();
      await expect(observations).toHaveAttribute('open', '');
      const paperBook = page.getByTestId('research-paper-book-panel');
      await expect(paperBook).toBeVisible();
      if ((await paperBook.getAttribute('open')) === null)
        await paperBook.locator(':scope > summary').click();
      await expect(paperBook).toHaveAttribute('open', '');
    }
    await page.goto('/backtest');
    await openPanels();
    const panel = page.getByTestId('research-paper-book-panel');
    await expect(
      panel.getByRole('button', { name: 'Create independent paper book' }),
    ).toBeDisabled();
    expect(writes).toEqual([]);
    await panel.getByLabel('Initial simulated cash (CNY)').fill('100000');
    await panel.getByText('Trading cost assumptions', { exact: true }).click();
    await panel.getByLabel('Cost model').selectOption('custom');
    await panel.getByLabel('Stock commission (bps)').fill('0');
    await panel.getByLabel('Stock minimum commission (CNY)').fill('5');
    await panel.getByLabel('Slippage per fill (bps)').fill('0');
    await panel
      .getByText('Independent paper book', { exact: true })
      .evaluate((node) => node.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`paper-create-${width}.png`),
    });
    await panel
      .getByText('Trading cost assumptions', { exact: true })
      .evaluate((node) => node.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`paper-costs-${width}.png`),
    });
    await panel
      .getByRole('button', { name: 'Create independent paper book' })
      .click();
    await expect(panel.getByTestId('paper-book-as-of')).toContainText(
      'Not settled; initial cash only',
    );
    const observations = page.getByTestId('research-observations-panel');
    const targetDataset = observations.getByRole('combobox', {
      name: 'Verified dataset for this observation',
      exact: true,
    });
    await targetDataset.selectOption(sourceId);
    await observations
      .getByRole('button', { name: 'Publish targets and measure outcomes' })
      .click();
    await expect(
      observations.getByText('Decision session · 2026-09-18'),
    ).toBeVisible();
    const dataset = panel.getByRole('combobox', {
      name: 'Formal Dataset for paper settlement',
      exact: true,
    });
    await dataset.selectOption(firstId);
    await panel
      .getByRole('button', { name: 'Settle paper book manually' })
      .click();
    await expect(panel.getByTestId('paper-book-as-of')).toContainText(
      '2026-09-21',
    );
    const snapshot = panel.getByRole('region', { name: 'Saved book snapshot' });
    await expect(
      snapshot.getByRole('definition').filter({ hasText: '¥99,994.75' }),
    ).toBeVisible();
    await expect(
      snapshot.getByRole('definition').filter({ hasText: '¥74,994.75' }),
    ).toBeVisible();
    await snapshot.getByTestId('paper-book-fills').locator('summary').click();
    await expect(
      snapshot
        .getByTestId('paper-book-fills')
        .getByText('¥5.25', { exact: true }),
    ).toBeVisible();
    await snapshot.evaluate((node) => node.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`paper-settled-${width}.png`),
    });
    await panel
      .getByRole('button', { name: 'Stop accepting new targets' })
      .click();
    await expect(panel.getByTestId('paper-book-lifecycle')).toContainText(
      'New target intake stopped',
    );
    await targetDataset.selectOption(firstId);
    await observations
      .getByRole('button', { name: 'Publish targets and measure outcomes' })
      .click();
    await expect(
      observations.getByText('Decision session · 2026-09-21'),
    ).toBeVisible();
    await dataset.selectOption(secondId);
    await panel
      .getByRole('button', { name: 'Settle paper book manually' })
      .click();
    await expect(panel.getByRole('alert')).toContainText(
      'previously settled accounting',
    );
    await expect(
      snapshot.getByRole('definition').filter({ hasText: '¥99,994.75' }),
    ).toBeVisible();
    await expect(
      panel.getByRole('button', { name: 'Settle paper book manually' }),
    ).toBeDisabled();
    await panel
      .getByRole('alert')
      .evaluate((node) => node.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`paper-blocked-${width}.png`),
    });
    await panel.getByRole('button', { name: 'Refresh paper book' }).click();
    await panel
      .getByRole('button', { name: 'Settle paper book manually' })
      .click();
    await expect(
      snapshot.getByRole('definition').filter({ hasText: '¥102,494.75' }),
    ).toBeVisible();
    await expect(panel.getByTestId('paper-book-as-of')).toContainText(
      '2026-09-22',
    );
    expect(book!.fills).toEqual(settledBook.fills);
    expect(book!.state.positions['600000'].quantity).toBe('2500');
    expect(observation.lifecycle).toBe('active');
    await page.reload();
    await openPanels();
    await expect(panel.getByTestId('paper-book-lifecycle')).toContainText(
      'New target intake stopped',
    );
    await expect(
      snapshot.getByRole('definition').filter({ hasText: '¥102,494.75' }),
    ).toBeVisible();
    await expect(
      panel.getByRole('button', { name: 'Stop accepting new targets' }),
    ).toBeDisabled();
    await expect(
      panel.getByRole('button', { name: /resume|automatic/i }),
    ).toHaveCount(0);
    await panel
      .getByTestId('paper-book-lifecycle')
      .evaluate((node) => node.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`paper-paused-controls-${width}.png`),
    });
    await snapshot.getByTestId('paper-book-fills').locator('summary').click();
    await snapshot
      .getByTestId('paper-book-attempts')
      .locator('summary')
      .click();
    await snapshot.evaluate((node) => node.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`paper-paused-${width}.png`),
    });
    expect(writes).toEqual([
      'create',
      'publish_after_creation',
      'settle',
      'pause',
      'publish_after_pause',
      'blocked',
      'mark_paused',
    ]);
    expect(unexpectedWrites).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
