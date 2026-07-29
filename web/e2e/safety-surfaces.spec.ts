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
    timeout: 15_000,
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

test('Account Truth stays fail closed until required persisted evidence resolves', async ({
  page,
}) => {
  await page.route(
    '**/api/account-truth/reconciliation-reports**',
    async (route) => {
      const requestUrl = new URL(route.request().url());
      if (requestUrl.pathname !== '/api/account-truth/reconciliation-reports') {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({ response });
    },
  );

  await page.goto('/account-truth');

  await expect(
    page.getByRole('heading', { name: 'Loading Account Truth evidence.' }),
  ).toBeVisible();
  expect(
    await page.locator('[data-workbench-primitive="metric-strip"]').count(),
  ).toBe(0);
  expect(await page.getByText('0 items', { exact: true }).count()).toBe(0);
  expect(
    await page.getByText('No reconciliation reports for this filter.').count(),
  ).toBe(0);

  await expect(page.getByTestId('account-truth-review-workspace')).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.locator('[data-workbench-primitive="metric-strip"]'),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Loading Account Truth evidence.' }),
  ).toHaveCount(0);
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
