import type { BacktestRunRequest, StrategyParameterSchema } from '../api';
import type {
  PublishedDataset,
  ResearchInstrument,
  VerifiedDatasetJob,
  VerifiedDatasetRange,
} from '../dataset-api';
import { buildSingleAsset } from './backtest-page-model';

export type ResearchAsset = { symbol: string; asset_class: string };

export function buildResearchAssets(
  symbol: string,
  assetClass: string,
  additional: ResearchAsset[],
): BacktestRunRequest['assets'] {
  if (!additional.length) return buildSingleAsset(symbol, assetClass);
  return [{ symbol, asset_class: assetClass }, ...additional]
    .map((asset) => ({ ...asset, symbol: asset.symbol.trim() }))
    .sort(
      (a, b) =>
        a.asset_class.localeCompare(b.asset_class) ||
        a.symbol.localeCompare(b.symbol),
    );
}

function typedInstruments(
  assets?: ResearchAsset[],
): ResearchInstrument[] | null {
  if (
    !assets?.length ||
    assets.length > 32 ||
    assets.some(
      (asset) =>
        !/^\d{6}$/.test(asset.symbol) ||
        !['stock', 'etf'].includes(asset.asset_class),
    ) ||
    new Set(assets.map((asset) => asset.symbol)).size !== assets.length
  )
    return null;
  return assets
    .map((asset) => ({
      symbol: asset.symbol,
      instrument_type: asset.asset_class as 'stock' | 'etf',
    }))
    .sort(
      (a, b) =>
        a.instrument_type.localeCompare(b.instrument_type) ||
        a.symbol.localeCompare(b.symbol),
    );
}

export function researchUniverseError(
  assets: ResearchAsset[] | undefined,
  zh: boolean,
): string {
  return assets && assets.length > 1 && !typedInstruments(assets)
    ? zh
      ? '资产篮子须包含 2–32 个不重复的六位股票或 ETF 代码，且每个标的的类型须准确。'
      : 'Use 2–32 unique six-digit stock or ETF symbols, each with the correct type.'
    : '';
}

export function researchDatasetRange(
  assets: ResearchAsset[] | undefined,
  startDate: string,
  endDate: string,
): VerifiedDatasetRange | null {
  const instruments = typedInstruments(assets);
  if (!instruments || !startDate || !endDate || startDate > endDate)
    return null;
  return {
    ...(instruments.length === 1 ? instruments[0] : { instruments }),
    start_date: startDate,
    end_date: endDate,
  };
}

function sameInstruments(a: ResearchInstrument[], b: ResearchInstrument[]) {
  const key = (items: ResearchInstrument[]) => {
    if (
      !Array.isArray(items) ||
      items.some((item) => !item || typeof item.symbol !== 'string')
    )
      return null;
    const typed = typedInstruments(
      items.map((asset) => ({
        symbol: asset.symbol,
        asset_class: asset.instrument_type,
      })),
    );
    return typed ? JSON.stringify(typed) : null;
  };
  const left = key(a);
  return left !== null && left === key(b);
}

export function datasetMatchesResearchInputs(
  dataset: PublishedDataset | null,
  assets: ResearchAsset[] | undefined,
  startDate: string,
  endDate: string,
) {
  if (!dataset) return true;
  const instruments = typedInstruments(assets);
  return (
    !!instruments &&
    dataset.start_date === startDate &&
    dataset.end_date === endDate &&
    sameInstruments(dataset.instruments, instruments)
  );
}

export function verificationMatchesResearchInputs(
  jobs: VerifiedDatasetJob[],
  range: VerifiedDatasetRange,
) {
  const instruments = range.instruments ?? [
    { symbol: range.symbol, instrument_type: range.instrument_type },
  ];
  return jobs.every((job) =>
    job.instruments
      ? sameInstruments(job.instruments, instruments)
      : instruments.length === 1,
  );
}

export function backtestParametersValid(
  schema: StrategyParameterSchema[],
  values: Record<string, string>,
) {
  return schema.every((param) => {
    if (!['int', 'float'].includes(param.type)) return true;
    const value = values[param.name] ?? '';
    const number = Number(value);
    return (
      value.trim() !== '' &&
      Number.isFinite(number) &&
      (param.type !== 'int' || Number.isInteger(number)) &&
      (param.min == null || number >= param.min) &&
      (param.max == null || number <= param.max)
    );
  });
}
