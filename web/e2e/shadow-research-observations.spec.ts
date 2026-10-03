import { expect, test } from '@playwright/test';

import {
  researchStatus,
  savedObservation,
} from '../test-fixtures/shadow-observations';

for (const width of [390, 1280]) {
  test(`normalized and qualified source observations remain read-only at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    let qualified = false;
    const reads: string[] = [];
    const writes: string[] = [];
    const older = savedObservation('older-observation');
    older.started_at = '2026-09-17T08:00:00Z';
    older.lifecycle = 'active';
    older.last_blocker = null;
    older.policy.health_policy = null;
    older.health_decision = null;
    older.publications = [];
    older.outcomes = [];
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() !== 'GET') {
        writes.push(`${route.request().method()} ${url.pathname}`);
        await route.fulfill({
          status: 403,
          json: { detail: 'read_only_fixture' },
        });
        return;
      }
      let payload: unknown;
      if (url.pathname === '/api/ai/strategy-research/shadow-automation')
        payload = researchStatus(qualified);
      else if (url.pathname === '/api/research-observations') {
        expect(url.searchParams.get('source_backtest_result_id')).toBe('8');
        expect(url.searchParams.get('limit')).toBe('100');
        reads.push(url.pathname);
        payload = [savedObservation(), older];
      } else if (
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
    await expect(qualification.getByRole('button')).toHaveCount(0);
    await qualification
      .getByRole('heading', {
        name: 'Account qualification review',
        exact: true,
      })
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`observation-review-blocked-${width}.png`),
    });
    const candidate = page.getByTestId('shadow-research-candidate');
    await expect(candidate).toContainText(
      'Synthetic normalized trend candidate',
    );
    expect(reads).toHaveLength(0);
    const evidence = candidate.getByTestId('shadow-research-observations');
    await evidence
      .getByText('Supplementary forward-observation evidence', { exact: true })
      .click();
    await expect(
      evidence.getByTestId('shadow-research-observation-record'),
    ).toHaveCount(2);
    await expect(evidence).toContainText('#8');
    await expect(evidence).toContainText('100 most recently started');
    await expect(evidence).toContainText(
      'do not replace independent final evaluation or account qualification',
    );
    await expect(evidence.getByRole('button')).toHaveText([
      'Refresh saved evidence',
    ]);
    await evidence
      .locator(':scope > summary')
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`observation-review-list-${width}.png`),
    });
    const record = evidence
      .getByTestId('shadow-research-observation-record')
      .first();
    await record.locator(':scope > summary').click();
    await expect(record).toContainText('Configured threshold breached');
    await expect(record).toContainText('Measured price response · 1.0%');
    await record
      .locator(':scope > summary')
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`observation-review-health-${width}.png`),
    });
    const publication = record
      .locator('summary')
      .filter({ hasText: 'Decision session' });
    await publication.click();
    await expect(record.getByRole('table')).toContainText('600000');
    await expect(record.getByRole('button')).toHaveCount(0);
    await expect(qualification).toContainText('Qualification blocked');
    qualified = true;
    await page.reload();
    await expect(qualification).toContainText(
      'qualification-winner → normalized-candidate',
    );
    const bound = qualification.getByTestId('shadow-research-observations');
    await bound
      .getByText('Supplementary forward-observation evidence', { exact: true })
      .click();
    await expect(
      bound.getByTestId('shadow-research-observation-record'),
    ).toHaveCount(2);
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
      path: testInfo.outputPath(`observation-review-qualified-${width}.png`),
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
    expect(reads).toHaveLength(2);
    expect(writes).toEqual([]);
  });
}
