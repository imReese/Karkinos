import { describe, expect, test } from 'vitest';

import type { ResearchInstrument, VerifiedDatasetJob } from '../dataset-api';
import {
  researchDatasetRange,
  verificationMatchesResearchInputs,
} from './backtest-universe';

const instruments: ResearchInstrument[] = Array.from(
  { length: 5000 },
  (_, i) => ({
    symbol: String(600000 + i),
    instrument_type: 'stock',
  }),
);
const range = {
  instruments,
  start_date: '2026-01-05',
  end_date: '2026-06-30',
};
const jobs: VerifiedDatasetJob[] = Array.from({ length: 125 }, (_, i) => ({
  job_id: `range-${i}`,
  trade_date: range.end_date,
  range_start_date: range.start_date,
  range_end_date: range.end_date,
  instruments: instruments.slice(i * 40, (i + 1) * 40),
  source_policy_id: 'verified-policy',
  status: 'succeeded',
  result_ref: `dataset-${i}`,
}));

describe('complete frozen forward inputs', () => {
  test('admits the full 5000-member seed while retaining the manual basket bound', () => {
    const assets = instruments.map((item) => ({
      symbol: item.symbol,
      asset_class: item.instrument_type,
    }));
    expect(
      researchDatasetRange(assets, range.start_date, range.end_date),
    ).toBeNull();
    expect(
      researchDatasetRange(assets, range.start_date, range.end_date, 10_000),
    ).toEqual(range);
    expect(verificationMatchesResearchInputs(jobs, range)).toBe(true);
  });

  test('rejects missing, overlapping and incorrectly typed members', () => {
    expect(verificationMatchesResearchInputs(jobs.slice(1), range)).toBe(false);
    expect(verificationMatchesResearchInputs([...jobs, jobs[0]], range)).toBe(
      false,
    );
    expect(
      verificationMatchesResearchInputs(
        [
          {
            ...jobs[0],
            instruments: [
              { ...instruments[0], instrument_type: 'etf' },
              ...instruments.slice(1, 40),
            ],
          },
          ...jobs.slice(1),
        ],
        range,
      ),
    ).toBe(false);
  });

  test('requires complete per-session coverage for original daily shards', () => {
    const daily = jobs.map(
      ({ range_start_date: _start, range_end_date: _end, ...job }) => job,
    );
    const nextDay = daily.map((job) => ({
      ...job,
      job_id: `next-${job.job_id}`,
      trade_date: '2026-06-29',
    }));
    expect(
      verificationMatchesResearchInputs([...daily, ...nextDay], range),
    ).toBe(true);
    expect(
      verificationMatchesResearchInputs([...daily, ...nextDay.slice(1)], range),
    ).toBe(false);
  });

  test('rejects mixed range identities and dates outside the selected interval', () => {
    expect(
      verificationMatchesResearchInputs(
        [{ ...jobs[0], range_start_date: '2025-12-01' }, ...jobs.slice(1)],
        range,
      ),
    ).toBe(false);
    expect(
      verificationMatchesResearchInputs(
        [{ ...jobs[0], range_end_date: undefined }, ...jobs.slice(1)],
        range,
      ),
    ).toBe(false);
    expect(verificationMatchesResearchInputs([], range)).toBe(false);
  });
});
