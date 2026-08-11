import { expect, test } from '@playwright/test';

const accountTruthAcceptanceViewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 834, height: 1112 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];

test('critical human-review surfaces load from the product runtime', async ({
  page,
}) => {
  test.setTimeout(60_000);
  const surfaces = [
    { path: '/decision', heading: /Decision platform|决策平台/ },
    { path: '/trading', heading: /Trading review|交易复核/ },
    {
      path: '/account-truth',
      heading: /Account Truth Review Center|账户事实复核中心/,
    },
  ];

  for (const surface of surfaces) {
    await page.goto(surface.path);
    await expect(page).toHaveURL(new RegExp(`${surface.path}$`));
    await expect(
      page.getByRole('heading', { name: surface.heading }),
    ).toBeVisible();
  }

  await page.goto('/account-truth');
  await expect(page.getByTestId('account-truth-review-workspace')).toBeVisible({
    timeout: 30_000,
  });
  expect(
    await page
      .locator(
        '[data-testid^="account-truth-item-"]:not([data-testid^="account-truth-item-selector-"])',
      )
      .count(),
  ).toBeLessThanOrEqual(1);

  await page.goto('/trading');
  await expect(page.getByTestId('kill-switch-panel')).toBeVisible();
  await expect(page.getByText(/Global kill switch|全局紧急停止/)).toBeVisible();
});

test('Account Truth keeps unresolved report reads local and fail closed', async ({
  page,
}) => {
  let releaseReportHistory: () => void = () => undefined;
  let markReportHistoryRequested: () => void = () => undefined;
  const reportHistoryGate = new Promise<void>((resolve) => {
    releaseReportHistory = resolve;
  });
  const reportHistoryRequested = new Promise<void>((resolve) => {
    markReportHistoryRequested = resolve;
  });
  const persistedReport = {
    import_run_id: 'browser-safety-import-run',
    schema_version: 'karkinos.account_truth.reconciliation.v1',
    status: 'mismatch',
    row_count: 1,
    validation_status: 'pass',
    source_type: 'canonical_broker_statement_csv',
    source_name: 'synthetic-browser-safety.csv',
    created_at: '2026-06-18T10:10:00+08:00',
    unresolved_count: 1,
    cash_difference: '0.00',
    fee_difference: '0.00',
    tax_difference: '0.00',
    suggested_review_actions: ['review_position_difference'],
    limitations: ['Synthetic provider-free browser fixture.'],
  };

  await page.route('**/api/account-truth/score', async (route) => {
    await route.fulfill({
      json: {
        schema_version: 'karkinos.account_truth.score.v1',
        status: 'available',
        import_run_id: persistedReport.import_run_id,
        score: 42,
        gate_status: 'blocked',
        cash_status: 'pass',
        position_status: 'mismatch',
        fee_status: 'pass',
        cost_basis_status: 'pass',
        data_freshness_status: 'fresh',
        unresolved_mismatch_count: 1,
        resolved_review_count: 0,
        required_actions: ['review_position_difference'],
        blocking_reasons: ['unresolved_position_difference'],
        limitations: ['Synthetic provider-free browser fixture.'],
      },
    });
  });

  await page.route(
    '**/api/account-truth/reconciliation-reports**',
    async (route) => {
      const requestUrl = new URL(route.request().url());
      if (requestUrl.pathname !== '/api/account-truth/reconciliation-reports') {
        await route.fulfill({
          json: {
            ...persistedReport,
            items: [
              {
                item_key: 'position:SYN001',
                category: 'position',
                status: 'mismatch',
                severity: 'mismatch',
                symbol: 'SYN001',
                display_name: 'Synthetic holding',
                broker_value: '1',
                karkinos_value: '0',
                difference: '1',
                suggested_review_action: 'review_position_difference',
                detail: 'Synthetic persisted mismatch for browser safety.',
                evidence_references: [
                  'broker_event:browser-safety-import-run:SYN001',
                ],
                latest_review: null,
              },
            ],
          },
        });
        return;
      }
      markReportHistoryRequested();
      await reportHistoryGate;
      await route.fulfill({
        json: [
          persistedReport,
          {
            ...persistedReport,
            import_run_id: 'browser-safety-earlier-import-run',
            created_at: '2026-06-17T10:10:00+08:00',
          },
        ],
      });
    },
  );

  await page.goto('/account-truth');

  await reportHistoryRequested;
  await expect(
    page.getByTestId('account-truth-review-workspace'),
  ).toBeVisible();
  await expect(page.getByTestId('account-truth-current-report')).toBeVisible();
  await expect(page.getByTestId('account-truth-reports-loading')).toHaveCount(
    0,
  );
  await expect(
    page.locator('[data-workbench-primitive="metric-strip"]'),
  ).toBeVisible();
  expect(await page.getByText('0 items', { exact: true }).count()).toBe(0);
  expect(
    await page.getByText('No reconciliation reports for this filter.').count(),
  ).toBe(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('account-truth-current-report')).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBe(0);

  releaseReportHistory();
  await expect(page.getByText(/earlier report|份较早报告/).first()).toBeVisible(
    { timeout: 15_000 },
  );
});

test('Account Truth preserves its evidence hierarchy across themes and acceptance viewports', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(accountTruthAcceptanceViewports[0]);
  await page.goto('/account-truth');
  await expect(page.getByTestId('account-truth-review-workspace')).toBeVisible({
    timeout: 15_000,
  });

  for (const theme of ['light', 'dark'] as const) {
    await page.evaluate((nextTheme) => {
      window.localStorage.setItem('karkinos.theme', nextTheme);
    }, theme);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await expect(
      page.getByTestId('account-truth-review-workspace'),
    ).toBeVisible({ timeout: 15_000 });

    for (const viewport of accountTruthAcceptanceViewports) {
      await page.setViewportSize(viewport);
      const geometry = await page.evaluate(() => {
        const content = document.querySelector(
          '.app-shell-content',
        ) as HTMLElement;
        const route = document.querySelector(
          '[data-workbench-route="account-truth"]',
        ) as HTMLElement;
        const header = document.querySelector(
          '[data-workbench-primitive="workspace-header"]',
        ) as HTMLElement;
        const metrics = document.querySelector(
          '[data-workbench-primitive="metric-strip"]',
        ) as HTMLElement;
        const reviewWorkspace = document.querySelector(
          '[data-testid="account-truth-review-workspace"]',
        ) as HTMLElement;
        const filterRail = reviewWorkspace.querySelector(
          '.app-account-truth-filter-rail',
        ) as HTMLElement;
        return {
          contentOverflow: content.scrollWidth - content.clientWidth,
          routeOverflow: route.scrollWidth - route.clientWidth,
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
          filterLocalOverflow: filterRail.scrollWidth - filterRail.clientWidth,
          filterScrollbarWidth: getComputedStyle(filterRail).scrollbarWidth,
          headerTop: header.getBoundingClientRect().top,
          metricsTop: metrics.getBoundingClientRect().top,
          reviewTop: reviewWorkspace.getBoundingClientRect().top,
        };
      });

      expect(geometry.documentOverflow, `${theme} ${viewport.width}`).toBe(0);
      expect(geometry.contentOverflow, `${theme} ${viewport.width}`).toBe(0);
      expect(geometry.routeOverflow, `${theme} ${viewport.width}`).toBe(0);
      expect(geometry.metricsTop, `${theme} ${viewport.width}`).toBeGreaterThan(
        geometry.headerTop,
      );
      if (viewport.width < 640) {
        expect(geometry.reviewTop, `${theme} ${viewport.width}`).toBeLessThan(
          geometry.metricsTop,
        );
      } else {
        expect(
          geometry.reviewTop,
          `${theme} ${viewport.width}`,
        ).toBeGreaterThan(geometry.metricsTop);
      }
      expect(
        geometry.filterLocalOverflow,
        `${theme} ${viewport.width}`,
      ).toBeGreaterThanOrEqual(0);
      expect(geometry.filterScrollbarWidth, `${theme} ${viewport.width}`).toBe(
        'none',
      );
    }
  }
});

test('browser-visible execution contracts start fail closed', async ({
  request,
}) => {
  const [capitalResponse, bridgeResponse, submissionResponse] =
    await Promise.all([
      request.get('/api/automation/capital-authority/status'),
      request.get('/api/automation/controlled-bridge/status'),
      request.get('/api/automation/controlled-broker-submission/status'),
    ]);

  expect(capitalResponse.ok()).toBeTruthy();
  expect(bridgeResponse.ok()).toBeTruthy();
  expect(submissionResponse.ok()).toBeTruthy();

  const capital = await capitalResponse.json();
  const bridge = await bridgeResponse.json();
  const submission = await submissionResponse.json();

  expect(capital.runtime_authority_status).toBe('disabled');
  expect(capital.execution_authority_enabled).toBe(false);
  expect(capital.broker_submission_enabled).toBe(false);
  expect(bridge.runtime_execution_authority).toBe('disabled');
  expect(bridge.broker_submission_enabled).toBe(false);
  expect(bridge.live_gateway_implemented).toBe(false);
  expect(submission.default_broker_submission_enabled).toBe(false);
  expect(submission.automatic_submission_enabled).toBe(false);
  expect(submission.strategy_direct_submission_enabled).toBe(false);
  expect(submission.recovery_resubmission_enabled).toBe(false);
  expect(submission.registered_gateway_ids).toEqual([]);
});
