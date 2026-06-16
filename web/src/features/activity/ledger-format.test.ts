import { describe, expect, test } from 'vitest';

import {
  formatLedgerInstrumentLabel,
  formatLedgerPublicNote,
  summarizeLedgerEntry,
} from './ledger-format';
import type { LedgerEntry } from './api';

const yutongBuy: LedgerEntry = {
  id: 15,
  entry_type: 'trade_buy',
  timestamp: '2026-06-16T03:04:56+00:00',
  amount: 5270,
  symbol: '600066',
  display_name: '宇通客车',
  direction: 'buy',
  quantity: 200,
  price: 26.35,
  commission: 5,
  asset_class: 'stock',
  note: '手工录入持仓：宇通客车 600066 买入，佣金按万1.5，最低5元计收',
  source: 'manual',
  source_ref: 'manual-600066-20260616-110456',
  created_at: '2026-06-16T12:35:51.741832',
};

describe('ledger formatter', () => {
  test('uses DB display_name as the instrument source of truth', () => {
    expect(formatLedgerInstrumentLabel(yutongBuy)).toBe('宇通客车 600066');
  });

  test('falls back to readable note parsing without duplicating the symbol', () => {
    expect(
      formatLedgerInstrumentLabel({ ...yutongBuy, display_name: null }),
    ).toBe('宇通客车 600066');
  });

  test('formats public notes without technical prefixes or duplicate symbols', () => {
    expect(formatLedgerPublicNote(yutongBuy)).toBe(
      '宇通客车 买入，佣金按万1.5，最低5元计收',
    );
  });

  test('keeps user-authored English notes in portfolio ledger traces', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        note: 'initial allocation',
      }),
    ).toBe('initial allocation');
  });

  test('suppresses legacy internal cash-deposit notes', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        entry_type: 'cash_deposit',
        symbol: null,
        display_name: null,
        note: 'RMB cash deposit recorded from user request',
      }),
    ).toBeNull();
  });

  test('summarizes cash impact consistently for buy trades', () => {
    expect(summarizeLedgerEntry(yutongBuy)).toMatchObject({
      kind: 'trade_buy',
      cashImpact: -5270,
      grossAmount: 5270,
    });
  });
});
