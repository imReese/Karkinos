import { describe, expect, test } from 'vitest';

import {
  formatLedgerActivitySummary,
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  formatLedgerPublicNote,
  formatLedgerSourceLabel,
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

  test('formats activity titles and cash-impact semantics from shared ledger data', () => {
    expect(formatLedgerActivitySummary(yutongBuy, 'en')).toMatchObject({
      label: 'Security buy',
      shortLabel: 'B',
      cashImpactLabel: 'Consumes cash',
      amount: '-CN¥5,270.00',
      tone: 'debit',
    });
    expect(
      formatLedgerActivitySummary(
        {
          ...yutongBuy,
          entry_type: 'cash_deposit',
          amount: 3000,
          net_cash_impact: 3000,
        },
        'zh',
      ),
    ).toMatchObject({
      label: '现金入金',
      shortLabel: '入',
      cashImpactLabel: '增加现金或确认回款',
      amount: '+CN¥3,000.00',
      tone: 'credit',
    });
  });

  test('formats cash interest as a first-class cash income entry', () => {
    const cashInterest: LedgerEntry = {
      id: 17,
      entry_type: 'cash_interest',
      timestamp: '2026-06-22T06:24:15+00:00',
      amount: 0.27,
      symbol: null,
      display_name: null,
      direction: null,
      quantity: null,
      price: null,
      commission: 0,
      asset_class: 'cash',
      note: '批量结息归本：现金利息 0.27 元',
      source: 'broker_statement_manual_correction',
      source_ref: 'cash-interest-20260622-batch-settlement-0.27',
      created_at: '2026-06-22T06:24:15+00:00',
    };

    expect(summarizeLedgerEntry(cashInterest)).toMatchObject({
      kind: 'cash_interest',
      cashImpact: 0.27,
      grossAmount: 0.27,
    });
    expect(formatLedgerActivitySummary(cashInterest, 'zh')).toMatchObject({
      label: '现金利息',
      shortLabel: '息',
      cashImpactLabel: '增加现金或确认回款',
      amount: '+CN¥0.27',
      tone: 'credit',
    });
    expect(formatLedgerActivitySummary(cashInterest, 'en')).toMatchObject({
      label: 'Cash interest',
      shortLabel: 'I',
      cashImpactLabel: 'Adds cash or realized proceeds',
      amount: '+CN¥0.27',
      tone: 'credit',
    });
    expect(formatLedgerPublicNote(cashInterest)).toBe(
      '批量结息归本：现金利息 0.27 元',
    );
  });

  test('localizes internal ledger source codes for public activity rows', () => {
    expect(
      formatLedgerSourceLabel('broker_statement_manual_correction', 'zh'),
    ).toBe('券商对账修正');
    expect(formatLedgerSourceLabel('portfolio_trade', 'zh')).toBe('组合交易');
    expect(
      formatLedgerSourceLabel('broker_statement_manual_correction', 'en'),
    ).toBe('Broker statement correction');
  });

  test('omits cost-basis method from public ledger execution details', () => {
    const details = formatLedgerExecutionDetailLines(
      {
        ...yutongBuy,
        gross_amount: 5270,
        net_cash_impact: -5275,
        fee_breakdown: {
          commission: 5,
        },
        cost_basis_method: 'broker_remaining_cost',
      },
      {
        amount: '金额',
        grossAmount: '成交总额',
        netCashImpact: '净现金影响',
        quantity: '份额/数量',
        price: '价格',
        fee: '手续费',
        commission: '佣金',
        stampTax: '印花税',
        transferFee: '过户费',
        otherFees: '其他费用',
        costBasis: '成本口径',
      },
      'zh',
    );

    expect(details.some((line) => line.label === '净现金影响')).toBe(false);
    expect(details.some((line) => line.value === '-CN¥5,275.00')).toBe(false);
    expect(details.some((line) => line.label === '成本口径')).toBe(false);
    expect(details.some((line) => line.value.includes('broker'))).toBe(false);
    expect(details.some((line) => line.value.includes('券商展示成本'))).toBe(
      false,
    );
  });
});
