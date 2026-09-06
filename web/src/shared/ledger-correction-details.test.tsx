import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import {
  LedgerCorrectionDetails,
  LedgerEntryTime,
} from './ledger-correction-details';
import type { PublicLedgerEntry } from './ledger-format-contracts';
import { correctionFixture } from './ledger-correction-fixture';
import {
  formatLedgerActivitySummary,
  formatLedgerPublicNote,
  summarizeLedgerEntry,
} from './ledger-format';

test('correction is an adjustment, never a capital flow or return', () => {
  expect(summarizeLedgerEntry(correctionFixture).cashImpact).toBeNull();
  expect(formatLedgerActivitySummary(correctionFixture, 'zh')).toMatchObject({
    label: '历史重复记账修正',
    tone: 'adjustment',
    cashImpactLabel: '账面修正，非新增买卖、非入金',
  });
  expect(formatLedgerPublicNote(correctionFixture, 'en')).toContain(
    'not a new trade, deposit, or return',
  );
  render(
    <>
      <LedgerEntryTime entry={correctionFixture} locale="zh" />
      <LedgerCorrectionDetails entry={correctionFixture} locale="zh" />
    </>,
  );
  expect(screen.getByText(/记录于/)).toHaveTextContent('02/20');
  expect(screen.getByText(/账本生效于/)).toHaveTextContent('02/10');
  expect(screen.getByText('重复原流水 #101')).toBeTruthy();
  expect(screen.getByText('保留流水 #102')).toBeTruthy();
  expect(screen.getByText('有授权摘要，未核验批准人／批准时间。')).toBeTruthy();
  expect(screen.getByRole('status')).toHaveTextContent(
    '不代表历史收益或授权已核验',
  );
});

test.each(['missing', 'schema', 'identity', 'references'] as const)(
  'unverified %s evidence cannot produce a validated explanation',
  (problem) => {
    const entry: PublicLedgerEntry = structuredClone(correctionFixture);
    if (problem === 'schema')
      entry.correction_payload!.schema_version = 'unknown';
    if (problem === 'identity') entry.entry_fingerprint = 'changed';
    if (problem === 'missing') delete entry.correction_evidence;
    if (problem === 'references') {
      entry.correction_evidence = {
        ...entry.correction_evidence!,
        status: 'unverified',
        blockers: ['missing_reference'],
        related_entries: [],
      };
    }
    render(<LedgerCorrectionDetails entry={entry} locale="zh" />);
    expect(screen.getByRole('status')).toHaveTextContent('修正证据待核验');
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText('重复原流水 #101')).toBeNull();
  },
);
