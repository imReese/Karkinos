import { defineConfig, devices } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const runtimeDataDir = mkdtempSync(join(tmpdir(), 'karkinos-playwright-'));

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [
        ['line'],
        ['junit', { outputFile: '../reports/ci/playwright-junit.xml' }],
      ]
    : 'list',
  use: {
    baseURL: 'http://127.0.0.1:18080',
    locale: 'en-US',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command:
      'cd .. && .venv/bin/python -m server --no-live --host 127.0.0.1 --port 18080',
    url: 'http://127.0.0.1:18080/api/settings',
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      KARKINOS_DATA_DIR: runtimeDataDir,
      KARKINOS_LIVE_AUTO_START: 'false',
    },
  },
});
