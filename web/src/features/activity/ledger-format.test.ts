import { describe, expect, test } from 'vitest';

import {
  formatLedgerActivitySummary,
  formatLedgerDashboardPresentation,
  formatLedgerEvidenceReference,
  formatLedgerExplainabilityDetail,
  formatLedgerExplainabilityTitle,
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
    expect(formatLedgerPublicNote(yutongBuy)).toBeNull();
  });

  test('keeps user-authored English notes in portfolio ledger traces', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        note: 'initial allocation',
      }),
    ).toBe('initial allocation');
  });

  test('suppresses generated trade notes that repeat structured amount fields', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        symbol: '012710',
        display_name: null,
        quantity: 204.102,
        price: 0.9799,
        commission: 0,
        asset_class: 'fund',
        note: '用户记录：华夏核心成长混合C 买入 200 元 | Auto-confirmed pending fund subscription: gross_amount=200.00 | confirmed_nav=0.979900',
      }),
    ).toBeNull();
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        note: '买入 200 股，价格 26.35，手续费 5.00',
      }),
    ).toBeNull();
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

  test('builds overview dashboard ledger presentation from shared formatter', () => {
    const presentation = formatLedgerDashboardPresentation(
      {
        ...yutongBuy,
        gross_amount: 5270,
        net_cash_impact: -5275.16,
        fee_breakdown: {
          commission: '5',
          stamp_tax: '0',
          transfer_fee: '0.16',
        },
      },
      {
        amount: 'Amount',
        grossAmount: 'Gross amount',
        netCashImpact: 'Net cash impact',
        quantity: 'Quantity',
        price: 'Price',
        fee: 'Fee',
        commission: 'Commission',
        stampTax: 'Stamp tax',
        transferFee: 'Transfer fee',
        otherFees: 'Other fees',
        costBasis: 'Cost basis',
      },
      'en',
      'Stock',
    );

    expect(presentation).toEqual({
      title: 'Buy 宇通客车 600066',
      details: [
        'Stock',
        'Gross amount CN¥5,270.00',
        'Net cash impact -CN¥5,275.16',
        'Quantity 200',
        'Price CN¥26.35',
        'Commission CN¥5.00',
        'Stamp tax CN¥0.00',
        'Transfer fee CN¥0.16',
      ],
      amount: 'CN¥5,270.00',
      publicNote: null,
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
    expect(formatLedgerPublicNote(cashInterest)).toBeNull();
  });

  test('keeps cash notes when the mentioned amount does not match the structured amount', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        entry_type: 'cash_interest',
        amount: 0.27,
        symbol: null,
        display_name: null,
        note: '结息差异 10.27 元，等待券商复核',
      }),
    ).toBe('结息差异 10.27 元，等待券商复核');
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

  test('formats broker trade evidence references with shared ledger labels', () => {
    expect(
      formatLedgerEvidenceReference(
        'broker_event:import-run-1:SYN001:trade_buy',
        'en',
      ),
    ).toBe('Broker evidence · SYN001 · Buy · import-run-1');
    expect(
      formatLedgerEvidenceReference(
        'broker_event:import-run-1:SYN001:trade_sell',
        'zh',
      ),
    ).toBe('券商证据 · SYN001 · 卖出 · import-run-1');
    expect(
      formatLedgerEvidenceReference(
        'broker_event:import-run-1:SYN001:position_snapshot',
        'en',
      ),
    ).toBe('Broker evidence · SYN001 · Position snapshot · import-run-1');
  });

  test('formats generated explainability events through shared ledger labels', () => {
    const instrumentNames = new Map([['600066', '宇通客车']]);

    expect(
      formatLedgerExplainabilityTitle(
        {
          kind: 'trade_buy',
          title: 'Bought 600066',
          detail: '数量 200 · 价格 ¥26.35 · 手续费 ¥5.00',
          symbol: '600066',
          amount: -5275,
        },
        'zh',
        instrumentNames,
      ),
    ).toBe('买入 宇通客车 600066');
    expect(
      formatLedgerExplainabilityTitle(
        {
          kind: 'trade_buy',
          title: '买入 600066',
          detail: '数量 200 · 价格 ¥26.35 · 手续费 ¥5.00',
          symbol: '600066',
          amount: -5275,
        },
        'zh',
        instrumentNames,
      ),
    ).toBe('买入 宇通客车 600066');
    expect(
      formatLedgerExplainabilityTitle(
        {
          kind: 'cash_deposit',
          title: 'cash_deposit',
          detail: 'RMB cash deposit recorded from user request',
          symbol: null,
          amount: 3000,
        },
        'en',
        instrumentNames,
      ),
    ).toBe('Cash deposit');
    expect(
      formatLedgerExplainabilityDetail(
        {
          kind: 'cash_deposit',
          title: 'cash_deposit',
          detail: 'RMB cash deposit recorded from user request',
          symbol: null,
          amount: 3000,
        },
        'zh',
        instrumentNames,
      ),
    ).toBe('金额 CN¥3,000.00');
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

    expect(details).toContainEqual({
      label: '净现金影响',
      value: '-CN¥5,275.00',
    });
    expect(details.some((line) => line.label === '成本口径')).toBe(false);
    expect(details.some((line) => line.value.includes('broker'))).toBe(false);
    expect(details.some((line) => line.value.includes('券商展示成本'))).toBe(
      false,
    );
  });

  test('omits zero stock-specific fee rows for open-end fund purchases', () => {
    const details = formatLedgerExecutionDetailLines(
      {
        id: 11,
        entry_type: 'trade_buy',
        timestamp: '2026-06-05T05:22:58+00:00',
        amount: 200,
        gross_amount: 200,
        net_cash_impact: -200,
        symbol: '012710',
        display_name: '华夏核心成长混合C',
        direction: 'buy',
        quantity: 239.808153477218,
        price: 0.834,
        commission: 0,
        fee_breakdown: {
          commission: 0,
          subscription_fee: 0,
          redemption_fee: 0,
          stamp_tax: 0,
          transfer_fee: 0,
          other_fees: 0,
        },
        asset_class: 'fund',
        note: '手工录入基金申购：华夏核心成长混合C，申购金额 200.00',
        source: 'manual',
        source_ref: 'manual-fund-012710-20260605',
        created_at: '2026-06-05T05:22:58+00:00',
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

    expect(details).toEqual([
      { label: '成交总额', value: 'CN¥200.00' },
      { label: '净现金影响', value: '-CN¥200.00' },
      { label: '份额/数量', value: '239.8082' },
      { label: '价格', value: 'CN¥0.83' },
    ]);
  });
});
