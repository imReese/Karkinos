import { expect, test } from 'vitest';
import { formatAssetClassLabel } from './asset-class';

const zhLabels = {
  assetClassStock: '股票',
  assetClassEtf: 'ETF',
  assetClassFund: '基金',
  assetClassGold: '黄金',
  assetClassBond: '债券',
  assetClassCash: '现金',
  assetClassIndex: '指数',
};

const enLabels = {
  assetClassStock: 'Stock',
  assetClassEtf: 'ETF',
  assetClassFund: 'Fund',
  assetClassGold: 'Gold',
  assetClassBond: 'Bond',
  assetClassCash: 'Cash',
  assetClassIndex: 'Index',
};

test('formats index asset class correctly in Chinese and English', () => {
  expect(formatAssetClassLabel('index', zhLabels)).toBe('指数');
  expect(formatAssetClassLabel('index', enLabels)).toBe('Index');
  expect(formatAssetClassLabel('INDEX', zhLabels)).toBe('指数');
});

test('falls back safely when assetClassIndex is omitted from labels', () => {
  const withoutIndexZh = { ...zhLabels };
  delete (withoutIndexZh as { assetClassIndex?: string }).assetClassIndex;
  expect(formatAssetClassLabel('index', withoutIndexZh)).toBe('指数');

  const withoutIndexEn = { ...enLabels };
  delete (withoutIndexEn as { assetClassIndex?: string }).assetClassIndex;
  expect(formatAssetClassLabel('index', withoutIndexEn)).toBe('Index');
});

test('formats other, unknown, and fund variants correctly', () => {
  expect(formatAssetClassLabel('other', zhLabels)).toBe('其他');
  expect(formatAssetClassLabel('other', enLabels)).toBe('Other');
  expect(formatAssetClassLabel('unknown', zhLabels)).toBe('未知');
  expect(formatAssetClassLabel('unknown', enLabels)).toBe('Unknown');
  expect(formatAssetClassLabel('open_end_fund', zhLabels)).toBe('基金');
  expect(formatAssetClassLabel('open-end-fund', zhLabels)).toBe('基金');
  expect(formatAssetClassLabel('convertible_bond', zhLabels)).toBe('债券');
});
