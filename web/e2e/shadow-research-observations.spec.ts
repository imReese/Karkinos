import { expect, test } from '@playwright/test';

import {
  candidateSourceReport,
  researchStatus,
  savedObservation,
  savedPaperBook,
} from '../test-fixtures/shadow-observations';

for (const width of [390, 1280]) {
  test(`candidate starts exact-source observation and reviews paper results at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    let qualified = false;
    let started = false;
    const reportReads: string[] = [];
    const writes: { path: string; body: Record<string, unknown> }[] = [];
    const older = savedObservation('older-observation');
    older.started_at = '2026-09-17T08:00:00Z';
    older.lifecycle = 'active';
    older.last_blocker = null;
    older.policy.health_policy = null;
    older.health_decision = null;
    older.publications = [];
    older.outcomes = [];
    const created = { ...older, id: 'new-observation' };
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET') {
        writes.push({
          path: `${request.method()} ${url.pathname}`,
          body: request.postDataJSON(),
        });
        if (
          request.method() === 'POST' &&
          url.pathname === '/api/research-observations'
        ) {
          expect(request.postDataJSON().source_backtest_result_id).toBe(8);
          started = true;
          await route.fulfill({ status: 200, json: { id: created.id } });
        } else {
          await route.fulfill({
            status: 403,
            json: { detail: 'unexpected_mutation' },
          });
        }
        return;
      }
      let payload: unknown;
      if (url.pathname === '/api/ai/strategy-research/shadow-automation')
        payload = researchStatus(qualified);
      else if (url.pathname === '/api/backtest/results/8') {
        reportReads.push(url.pathname);
        payload = candidateSourceReport();
      } else if (url.pathname === '/api/research-observations') {
        expect(url.searchParams.get('source_backtest_result_id')).toBe('8');
        expect(url.searchParams.get('limit')).toBe('100');
        payload = [...(started ? [created] : []), savedObservation(), older];
      } else if (url.pathname === '/api/research-observations/new-observation')
        payload = created;
      else if (
        url.pathname ===
        '/api/research-observations/saved-observation/paper-book'
      )
        payload = savedPaperBook();
      else if (url.pathname.endsWith('/paper-book')) payload = null;
      else if (url.pathname === '/api/backtest/datasets')
        payload = { datasets: [] };
      else if (
        url.pathname === '/api/strategy-promotion/states' ||
        url.pathname === '/api/backtest/results'
      )
        payload = [];
      else {
        await route.fulfill({
          status: 503,
          json: { detail: 'synthetic_fixture_not_available' },
        });
        return;
      }
      await route.fulfill({ status: 200, json: payload });
    });
    await page.goto('/ai-research');
    const qualification = page.getByTestId('shadow-research-qualification');
    await expect(qualification).toContainText('Qualification blocked');
    const candidate = page.getByTestId('shadow-research-candidate');
    await expect(candidate).toContainText(
      'Synthetic normalized trend candidate',
    );
    expect(reportReads).toHaveLength(0);
    const evidence = candidate.getByTestId('shadow-research-observations');
    await evidence
      .getByText('Forward observation and paper results', { exact: true })
      .click();
    await expect(
      evidence
        .getByLabel('Saved observations for this report')
        .locator('option'),
    ).toHaveCount(2);
    await expect(evidence).toContainText('#8');
    await expect(evidence).toContainText(
      'do not replace independent final evaluation or account qualification',
    );
    await expect(
      evidence.getByRole('button', { name: 'Start observation', exact: true }),
    ).toBeEnabled();
    expect(writes).toEqual([]);

    const paper = evidence.getByTestId('research-paper-book-panel');
    await paper.locator(':scope > summary').click();
    await expect(paper).toContainText('Modeled net excess');
    await expect(paper).toContainText('-0.7%');
    await expect(paper).toContainText(
      'Settled sessions after a real target: 2',
    );
    await expect(paper).toContainText('ETF distributions are unverified');
    await expect(paper).toContainText('New target intake stopped');
    await paper
      .locator(':scope > summary')
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`candidate-paper-results-${width}.png`),
    });
    expect(writes).toEqual([]);

    await evidence
      .getByRole('button', { name: 'Start observation', exact: true })
      .click();
    await expect(
      evidence.getByLabel('Saved observations for this report'),
    ).toHaveValue('new-observation');
    await expect(evidence).toContainText('Publishing enabled · new-obse');
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      path: 'POST /api/research-observations',
      body: { source_backtest_result_id: 8 },
    });
    await expect(qualification).toContainText('Qualification blocked');

    qualified = true;
    await page.reload();
    await expect(qualification).toContainText(
      'qualification-winner → normalized-candidate',
    );
    const bound = qualification.getByTestId('shadow-research-observations');
    await bound
      .getByText('Forward observation and paper results', { exact: true })
      .click();
    await expect(
      bound.getByLabel('Saved observations for this report').locator('option'),
    ).toHaveCount(3);
    await expect(bound).toContainText('normalized-candidate / normalized-run');
    await expect(bound).toContainText('#8');
    await expect(
      qualification.getByRole('button', {
        name: 'Approve qualified winner for paper/shadow only',
        exact: true,
      }),
    ).toBeDisabled();
    await bound
      .locator(':scope > summary')
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`candidate-observation-start-${width}.png`),
    });
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
    expect(reportReads).toHaveLength(2);
    expect(writes).toHaveLength(1);
  });
}
