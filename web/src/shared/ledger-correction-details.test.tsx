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
    amount: '--',
    cashImpactLabel: '原交易已更正，仅保留审计记录',
  });
  expect(formatLedgerPublicNote(correctionFixture, 'en')).toContain(
    'no new cash movement',
  );
  render(
    <>
      <LedgerEntryTime entry={correctionFixture} locale="zh" />
      <LedgerCorrectionDetails entry={correctionFixture} locale="zh" />
    </>,
  );
  expect(screen.getByText(/记录于/)).toHaveTextContent('02/20');
  expect(screen.getByText(/旧补偿时间/)).toHaveTextContent('02/10');
  expect(screen.getByText('重复原流水 #101')).toBeTruthy();
  expect(screen.getByText('保留流水 #102')).toBeTruthy();
  expect(screen.getByText('有授权摘要，未核验批准人／批准时间。')).toBeTruthy();
  expect(screen.getByRole('status')).toHaveTextContent(
    '重复买入从原交易日期起作废',
  );
});

test('only verified duplicate entries are voided at their original trade date', () => {
  const entry: PublicLedgerEntry = {
    ...correctionFixture.correction_evidence.related_entries[0],
    entry_fingerprint: 'original',
    correction_evidence: {
      ...correctionFixture.correction_evidence,
      accounting_effect: 'original_trade_voided',
      entry_fingerprint: 'original',
    },
  };
  expect(summarizeLedgerEntry(entry).cashImpact).toBeNull();
  expect(formatLedgerActivitySummary(entry, 'zh')).toMatchObject({
    label: '重复买入已作废',
    amount: '--',
    tone: 'neutral',
  });
  expect(formatLedgerPublicNote(entry, 'zh')).toContain('从原交易日期起排除');
  const drifted = { ...entry, entry_fingerprint: 'changed' };
  expect(summarizeLedgerEntry(drifted).cashImpact).toBe(-20);
  expect(formatLedgerActivitySummary(drifted, 'zh').label).not.toContain(
    '已作废',
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
