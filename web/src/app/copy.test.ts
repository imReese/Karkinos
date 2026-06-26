import { expect, test } from 'vitest';

import { copy } from './copy';

test('keeps generic submit errors user-readable in both locales', () => {
  expect(copy.en.common.genericSubmitError).toBe(
    'Request failed. Check the form values and service status.',
  );
  expect(copy.zh.common.genericSubmitError).toBe(
    '请求失败，请检查录入内容或系统状态。',
  );

  const combined = `${copy.en.common.genericSubmitError} ${copy.zh.common.genericSubmitError}`;
  expect(combined).not.toMatch(/payload|server logs|服务日志/i);
});

test('uses one Chinese simulation-review term in strategy loop copy', () => {
  const backtestCopy = JSON.stringify(copy.zh.backtest);

  expect(backtestCopy).toContain('模拟复核');
  expect(backtestCopy).not.toContain('模拟复盘');
  expect(backtestCopy).not.toContain('模拟盘复核');
});
