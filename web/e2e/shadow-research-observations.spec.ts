import { expect, test } from '@playwright/test';
import type { PublicationPolicyStatus } from '../src/features/ai-research/publication-policy-api';
import {
  publicationPolicyBinding,
  disabledPublicationPolicyStatus,
} from '../test-fixtures/publication-policy';

import {
  candidateSourceReport,
  researchStatus,
  savedObservation,
  savedPaperBook,
} from '../test-fixtures/shadow-observations';

for (const width of [390, 1280]) {
  test(`standing publication grant previews, renews and revokes at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    const path = '/api/ai/strategy-research/automatic-publication-policy';
    // An existing grant exercises the actual compare-and-swap renewal contract.
    let state: PublicationPolicyStatus = {
      ...disabledPublicationPolicyStatus,
      status: 'active',
      policy: {
        ...publicationPolicyBinding,
        policy_id: 'ai_recommendation_publication',
        generation: 'synthetic-existing-generation',
        enabled: true,
      },
    };
    const writes: Record<string, unknown>[] = [];
    let previewRejected = true;
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === `${path}/preview` && request.method() === 'POST') {
        expect(
          request.postDataJSON().account_scope_fingerprint,
        ).toBeUndefined();
        await route.fulfill({
          json: {
            proposed_binding: previewRejected ? null : publicationPolicyBinding,
            preview_blockers: previewRejected
              ? ['publication_preview_stock_fee_envelope_missing']
              : [],
            binding_source: null,
          },
        });
      } else if (pathname === path && request.method() === 'PUT') {
        const body = request.postDataJSON();
        writes.push(body);
        expect(body.expected_generation).toBe(state.policy.generation);
        if (body.enabled) {
          expect(body.deployment_scope_fingerprint).toBe(
            publicationPolicyBinding.deployment_scope_fingerprint,
          );
          expect(body.human_review).toBeUndefined();
          state = {
            ...state,
            policy: {
              ...state.policy,
              generation: 'synthetic-renewed-generation',
            },
          };
        } else {
          state = {
            ...disabledPublicationPolicyStatus,
            policy: {
              enabled: false,
              generation: 'synthetic-revoked-generation',
            },
          };
        }
        await route.fulfill({ json: state });
      } else if (pathname === path && request.method() === 'GET') {
        await route.fulfill({ json: state });
      } else if (
        pathname === '/api/ai/strategy-research/shadow-automation' &&
        request.method() === 'GET'
      ) {
        await route.fulfill({ json: researchStatus(false) });
      } else {
        await route.fulfill({
          status: 503,
          json: { detail: 'synthetic_unavailable' },
        });
      }
    });
    await page.goto('/ai-research');
    const panel = page.getByTestId('automatic-publication-policy');
    await expect(panel).toContainText('Current grant: active');
    await expect(panel).toContainText(
      'No per-candidate confirmation is required',
    );
    await panel.getByText('Configure and verify publication bounds').click();
    await expect(panel.getByLabel('Allocation scope')).toHaveValue(
      publicationPolicyBinding.allocation_scope,
    );
    await panel
      .getByRole('button', { name: 'Verify authorization bounds' })
      .click();
    await expect(panel).toContainText(
      'publication_preview_stock_fee_envelope_missing',
    );
    await expect(
      panel.getByRole('button', { name: 'Enable automatic publication' }),
    ).toHaveCount(0);
    expect(writes).toHaveLength(0);
    previewRejected = false;
    await panel
      .getByRole('button', { name: 'Verify authorization bounds' })
      .click();
    const enable = panel.getByRole('button', {
      name: 'Enable automatic publication',
    });
    await expect(enable).toBeDisabled();
    await panel
      .getByRole('checkbox', {
        name: /I authorize automatic account recommendation publication/,
      })
      .check();
    await enable.click();
    await expect.poll(() => writes.length).toBe(1);
    await expect(
      panel.getByRole('button', { name: 'Enable automatic publication' }),
    ).toHaveCount(0);
    await panel
      .getByRole('button', {
        name: 'Revoke grant and suspend its recommendation sources',
      })
      .click();
    await expect(panel).toContainText('Current grant: disabled');
    expect(writes).toHaveLength(2);
    expect(writes.map((body) => body.enabled)).toEqual([true, false]);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath(`publication-grant-${width}.png`),
    });
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
  });

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
    const createdBook = {
      ...savedPaperBook(),
      observation_id: created.id,
    };
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
        } else if (
          request.method() === 'POST' &&
          url.pathname ===
            '/api/research-observations/new-observation/paper-book'
        ) {
          expect(request.postDataJSON().initial_cash).toBe('100000');
          await route.fulfill({ status: 200, json: createdBook });
        } else if (
          request.method() === 'PUT' &&
          url.pathname ===
            '/api/research-observations/new-observation/automation'
        ) {
          expect(request.postDataJSON()).toMatchObject({
            enabled: true,
            paper_settlement_enabled: true,
            dataset_preparation_enabled: true,
          });
          created.automation = {
            observation_id: created.id,
            enabled: true,
            paper_settlement_enabled: true,
            dataset_preparation_enabled: true,
            generation: 'synthetic-browser-generation',
            status: 'ready',
            last_checked_at: null,
            last_attempt_at: null,
            last_blocker: null,
            dataset_id: null,
            decision_session: null,
          };
          await route.fulfill({ status: 200, json: {} });
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
      else if (
        url.pathname === '/api/research-observations/new-observation/paper-book'
      )
        payload = createdBook;
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
    const start = evidence.getByRole('button', {
      name: 'Freeze and start forward paper',
      exact: true,
    });
    await expect(start).toBeDisabled();
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
      .getByRole('checkbox', {
        name: /Authorize data preparation, target publication and settlement/,
      })
      .check();
    await expect(start).toBeEnabled();
    await start.click();
    await expect(
      evidence.getByLabel('Saved observations for this report'),
    ).toHaveValue('new-observation');
    await expect(evidence).toContainText('Publishing enabled · new-obse');
    await expect.poll(() => writes.length).toBe(3);
    expect(writes[0]).toMatchObject({
      path: 'POST /api/research-observations',
      body: { source_backtest_result_id: 8 },
    });
    expect(writes.map((write) => write.path)).toEqual([
      'POST /api/research-observations',
      'POST /api/research-observations/new-observation/paper-book',
      'PUT /api/research-observations/new-observation/automation',
    ]);
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
    expect(writes).toHaveLength(3);
  });
}
