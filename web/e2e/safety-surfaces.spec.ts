import { expect, test } from '@playwright/test';

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

  await page.goto('/trading');
  await expect(page.getByTestId('kill-switch-panel')).toBeVisible();
  await expect(page.getByText(/Global kill switch|全局紧急停止/)).toBeVisible();
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
