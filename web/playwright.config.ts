import { defineConfig, devices } from '@playwright/test';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const runtimeDataDir = mkdtempSync(join(tmpdir(), 'karkinos-playwright-'));
const runtimeEnvFile = join(runtimeDataDir, '.env');
const runtimeConfigFile = join(runtimeDataDir, 'config.json');
writeFileSync(runtimeEnvFile, '');
writeFileSync(
  runtimeConfigFile,
  JSON.stringify({
    server: { market_calendar_auto_sync: false },
    ai: { enabled: false },
    data_source: { provider: 'akshare' },
    account_truth: {
      broker_statement_collector: { enabled: false },
      citic_history_xls_directory: { enabled: false },
    },
  }),
);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
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
      'cd .. && .venv/bin/python -m server --host 127.0.0.1 --port 18080',
    url: 'http://127.0.0.1:18080/api/settings',
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      KARKINOS_DATA_DIR: runtimeDataDir,
      KARKINOS_WORKSPACE: runtimeDataDir,
      KARKINOS_ENV_FILE: runtimeEnvFile,
      KARKINOS_CONFIG_PATH: runtimeConfigFile,
      KARKINOS_DATA_SOURCE: 'akshare',
      KARKINOS_TUSHARE_TOKEN: '',
      KARKINOS_AI_ENABLED: 'false',
      KARKINOS_AI_API_KEY: '',
    },
  },
});
