import { expect, test } from 'vitest';

import { copy } from './copy';

function collectStaticText(value: unknown): string[] {
  if (typeof value === 'string') {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.flatMap(collectStaticText);
  }
  if (value && typeof value === 'object') {
    return Object.values(value).flatMap(collectStaticText);
  }
  return [];
}

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

test('uses user-readable English simulation-review wording in strategy loop copy', () => {
  const backtestCopy = JSON.stringify(copy.en.backtest);

  expect(backtestCopy).toContain('simulation review');
  expect(backtestCopy).not.toContain('paper/shadow');
  expect(backtestCopy).not.toContain('Paper/shadow');
});

test('keeps static user-facing copy free of frontend and backend jargon', () => {
  const userFacingCopy = collectStaticText(copy).join('\n');

  expect(userFacingCopy).not.toMatch(/\b(?:back|front)end\b|后端|前端/iu);
});

test('keeps the primary portfolio path free of implementation jargon', () => {
  const primaryPaths = [
    {
      summary: copy.en.portfolio.summary,
      currentHoldings: copy.en.portfolio.currentHoldings,
      toolbarHelper: copy.en.portfolio.toolbar.helper,
    },
    {
      summary: copy.zh.portfolio.summary,
      currentHoldings: copy.zh.portfolio.currentHoldings,
      toolbarHelper: copy.zh.portfolio.toolbar.helper,
    },
  ];

  for (const path of primaryPaths) {
    const primaryCopy = JSON.stringify(path);

    expect(primaryCopy).not.toMatch(
      /canonical|persisted|provider|snapshot|ledger|权威|持久化|快照|账本/i,
    );
  }

  expect(copy.en.portfolio.summary.missingDetail).toContain(
    'will not calculate account totals',
  );
  expect(copy.zh.portfolio.summary.missingDetail).toContain(
    '不会用持仓表自行拼算总资产',
  );
});

test('keeps the primary overview path free of implementation jargon', () => {
  const primaryPaths = [
    {
      loading: copy.en.overview.loading,
      error: copy.en.overview.error,
      simulation: copy.en.overview.dashboard.operationsViewPaperShadow,
      dataResolution: copy.en.overview.dashboard.dataResolutionCondition,
      strategyResolution: copy.en.overview.dashboard.strategyEvidenceResolution,
      reviewLoading: copy.en.overview.dashboard.dataReviewLoading,
      reviewUnavailable: copy.en.overview.dashboard.dataReviewUnavailable,
      identityBlocked: copy.en.overview.dashboard.dataReviewIdentityBlocked,
      heatmap: copy.en.overview.dashboard.marketHeatmapUnavailableDetail,
      positions: copy.en.overview.dashboard.positionsDetail,
      curve: copy.en.overview.equityCurve.emptyHint,
    },
    {
      loading: copy.zh.overview.loading,
      error: copy.zh.overview.error,
      simulation: copy.zh.overview.dashboard.operationsViewPaperShadow,
      dataResolution: copy.zh.overview.dashboard.dataResolutionCondition,
      strategyResolution: copy.zh.overview.dashboard.strategyEvidenceResolution,
      reviewLoading: copy.zh.overview.dashboard.dataReviewLoading,
      reviewUnavailable: copy.zh.overview.dashboard.dataReviewUnavailable,
      identityBlocked: copy.zh.overview.dashboard.dataReviewIdentityBlocked,
      heatmap: copy.zh.overview.dashboard.marketHeatmapUnavailableDetail,
      positions: copy.zh.overview.dashboard.positionsDetail,
      curve: copy.zh.overview.equityCurve.emptyHint,
    },
  ];

  for (const path of primaryPaths) {
    expect(JSON.stringify(path)).not.toMatch(
      /canonical|persisted|provider|paper\/shadow|backend projection|valuation snapshot|ledger cutoff|ledger identity|持久化|后端投影|估值快照|账本截止/i,
    );
  }

  expect(copy.zh.overview.dashboard.dataResolutionCondition).not.toMatch(
    /^解除条件/u,
  );
  expect(copy.en.overview.dashboard.dataResolutionCondition).not.toMatch(
    /^Clears?/u,
  );
});
