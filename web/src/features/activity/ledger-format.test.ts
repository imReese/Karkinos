import { describe, expect, test } from 'vitest';

import {
  formatLedgerActivitySummary,
  formatLedgerDashboardPresentation,
  formatLedgerEvidenceReference,
  formatLedgerExplainabilityDetail,
  formatLedgerExplainabilityTitle,
  formatLedgerFeeRuleLabel,
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  formatLedgerOrderSideLabel,
  formatLedgerPublicNote,
  formatLedgerSourceLabel,
  formatLedgerCostBasisMethodLabel,
  summarizeLedgerEntry,
} from './ledger-format';
import type { LedgerEntry } from './api';

const yutongBuy: LedgerEntry = {
  id: 15,
  entry_type: 'trade_buy',
  timestamp: '2026-01-15T03:04:56+00:00',
  amount: 3250,
  symbol: '600003',
  display_name: '示例制造',
  direction: 'buy',
  quantity: 200,
  price: 16.25,
  commission: 5,
  asset_class: 'stock',
  note: '合成测试流水：示例制造 600003 买入，按本地费率规则计费',
  source: 'manual',
  source_ref: 'manual-stock-a-20260115-100000',
  created_at: '2026-01-15T12:35:51.741832',
};

describe('ledger formatter', () => {
  test('uses DB display_name as the instrument source of truth', () => {
    expect(formatLedgerInstrumentLabel(yutongBuy)).toBe('示例制造 600003');
  });

  test('formats order sides through the shared ledger formatter', () => {
    expect(formatLedgerOrderSideLabel('buy', 'zh')).toBe('买入');
    expect(formatLedgerOrderSideLabel('sell', 'en')).toBe('Sell');
    expect(formatLedgerOrderSideLabel('broker_special_side', 'en')).toBe(
      'Status needs review',
    );
  });

  test('falls back to readable note parsing without duplicating the symbol', () => {
    expect(
      formatLedgerInstrumentLabel({ ...yutongBuy, display_name: null }),
    ).toBe('示例制造 600003');
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

  test('localizes internal note codes instead of rendering raw backend values', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: 'internal_fee_rule_missing',
        },
        'zh',
      ),
    ).toBe('待人工复核说明');
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: 'internal_fee_rule_missing',
        },
        'en',
      ),
    ).toBe('Review note');
  });

  test('suppresses generated configured-fee notes when fee evidence is structured', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        fee_breakdown: {
          commission: '5.00',
          stamp_tax: '0.000000',
          transfer_fee: '0.032500',
          other_fees: '0.000000',
          total_fee: '5.032500',
        },
        fee_rule_id: 'manual_configured_commission',
        fee_rule_version: 'account_commission_rate',
        note: '账户佣金配置：佣金率万2，最低5元',
      }),
    ).toBeNull();
  });

  test('suppresses generated trade notes that repeat structured amount fields', () => {
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        symbol: '012999',
        display_name: null,
        quantity: 204.102,
        price: 0.9799,
        commission: 0,
        asset_class: 'fund',
        note: '用户记录：示例稳健混合C 买入 200 元 | Auto-confirmed pending fund subscription: gross_amount=200.00 | confirmed_nav=0.979900',
      }),
    ).toBeNull();
    expect(
      formatLedgerPublicNote({
        ...yutongBuy,
        note: '买入 200 股，价格 16.25，手续费 5.00',
      }),
    ).toBeNull();
  });

  test('keeps user remarks while suppressing semicolon-delimited structured facts', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: '复盘观察；买入 200 股，价格 16.25，手续费 5.00',
        },
        'zh',
      ),
    ).toBe('复盘观察');
  });

  test('suppresses English generated manual-trade notes that repeat structured fields', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: 'Manual trade: 示例制造 600003 buy, quantity 200, price 16.25, commission 5.00',
        },
        'en',
      ),
    ).toBeNull();
  });

  test('keeps English user remarks while suppressing manual-trade fact segments', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: 'watchlist follow-up; Manual trade: 示例制造 600003 buy, quantity 200, price 16.25, commission 5.00',
        },
        'en',
      ),
    ).toBe('watchlist follow-up');
  });

  test('keeps multiline user remarks while suppressing generated trade facts', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: '复盘观察\n买入 200 股，价格 16.25，手续费 5.00',
        },
        'zh',
      ),
    ).toBe('复盘观察');
  });

  test('suppresses legacy manual holding notes that duplicate structured fees', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: '手工录入持仓：示例制造 600003 买入，佣金按万1.5，最低5元计收',
          fee_breakdown: {
            commission: '5.00',
            stamp_tax: '0.00',
            transfer_fee: '0.03',
            total_fee: '5.03',
          },
        },
        'zh',
      ),
    ).toBeNull();
  });

  test('suppresses legacy manual trade prefixes that duplicate structured facts', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          note: '手工录入交易-示例制造 600003 买入，数量 200，价格 16.25，手续费 5.00',
        },
        'zh',
      ),
    ).toBeNull();
  });

  test('keeps user remarks while suppressing core accounting fact note segments', () => {
    expect(
      formatLedgerPublicNote(
        {
          ...yutongBuy,
          gross_amount: 3250,
          net_cash_impact: -3255.16,
          fee_breakdown: {
            commission: '5.00',
            stamp_tax: '0.00',
            transfer_fee: '0.16',
            total_fee: '5.16',
          },
          note: '复盘观察；成本价 16.25；净现金影响 -3255.16；手续费 5.16',
        },
        'zh',
      ),
    ).toBe('复盘观察');
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
      cashImpact: -3250,
      grossAmount: 3250,
    });
  });

  test('formats activity titles and cash-impact semantics from shared ledger data', () => {
    expect(formatLedgerActivitySummary(yutongBuy, 'en')).toMatchObject({
      label: 'Security buy',
      shortLabel: 'B',
      cashImpactLabel: 'Consumes cash',
      amount: '-CN¥3,250.00',
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
      label: '资金转入',
      shortLabel: '入',
      cashImpactLabel: '现金增加',
      amount: '+CN¥3,000.00',
      tone: 'credit',
    });
  });

  test('formats cash movements as professional public ledger rows', () => {
    const cashDeposit: LedgerEntry = {
      ...yutongBuy,
      entry_type: 'cash_deposit',
      amount: 12000,
      symbol: null,
      display_name: null,
      direction: null,
      quantity: null,
      price: null,
      commission: 0,
      gross_amount: null,
      net_cash_impact: null,
      fee_breakdown: null,
      asset_class: 'cash',
      note: '手工录入现金入金：人民币 12000 元，开户时间 2026-04-27',
      source: 'manual',
    };

    expect(formatLedgerInstrumentLabel(cashDeposit)).toBe('人民币现金');
    expect(formatLedgerPublicNote(cashDeposit, 'zh')).toBeNull();
    expect(formatLedgerActivitySummary(cashDeposit, 'zh')).toMatchObject({
      label: '资金转入',
      shortLabel: '入',
      cashImpactLabel: '现金增加',
      amount: '+CN¥12,000.00',
      tone: 'credit',
    });
    expect(
      formatLedgerExecutionDetailLines(
        cashDeposit,
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
      ),
    ).toEqual([{ label: '金额', value: 'CN¥12,000.00' }]);
  });

  test('builds overview dashboard ledger presentation from shared formatter', () => {
    const presentation = formatLedgerDashboardPresentation(
      {
        ...yutongBuy,
        gross_amount: 3250,
        net_cash_impact: -3255.16,
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
      title: 'Buy 示例制造 600003',
      details: [
        'Stock',
        'Gross amount CN¥3,250.00',
        'Net cash impact -CN¥3,255.16',
        'Quantity 200',
        'Price CN¥16.25',
        'Commission CN¥5.00',
        'Stamp tax CN¥0.00',
        'Transfer fee CN¥0.16',
      ],
      amount: '-CN¥3,255.16',
      publicNote: null,
    });
  });

  test('uses signed net cash impact as dashboard primary amount when fee evidence exists', () => {
    const presentation = formatLedgerDashboardPresentation(
      {
        ...yutongBuy,
        gross_amount: 3250,
        net_cash_impact: -3255.16,
        fee_breakdown: {
          commission: '5',
          stamp_tax: '0',
          transfer_fee: '0.16',
        },
      },
      {
        amount: 'Amount',
        grossAmount: 'Gross amount',
        netCashImpact: 'Cash impact',
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

    expect(presentation.amount).toBe('-CN¥3,255.16');
    expect(presentation.details).toContain('Gross amount CN¥3,250.00');
    expect(presentation.details).toContain('Cash impact -CN¥3,255.16');
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
      label: '结息入账',
      shortLabel: '息',
      cashImpactLabel: '现金利息',
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

  test('hides zero stock-fee labels for cash interest rows', () => {
    const cashInterest: LedgerEntry = {
      ...yutongBuy,
      entry_type: 'cash_interest',
      amount: 0.27,
      symbol: null,
      display_name: null,
      direction: null,
      quantity: null,
      price: null,
      commission: 0,
      gross_amount: 0.27,
      net_cash_impact: 0.27,
      fee_breakdown: {
        commission: '0',
        stamp_tax: '0',
        transfer_fee: '0',
        other_fees: '0',
      },
      asset_class: 'cash',
      note: '批量结息归本：现金利息 0.27 元',
    };

    expect(
      formatLedgerExecutionDetailLines(
        cashInterest,
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
      ),
    ).toEqual([{ label: '金额', value: 'CN¥0.27' }]);
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
    ).toBe('对账校正');
    expect(formatLedgerSourceLabel('portfolio_trade', 'zh')).toBe('交易流水');
    expect(
      formatLedgerSourceLabel('broker_statement_manual_correction', 'en'),
    ).toBe('Reconciliation adjustment');
  });

  test('uses public fallbacks for future ledger source codes', () => {
    expect(
      formatLedgerSourceLabel('broker_statement_manual_adjustment_v2', 'zh'),
    ).toBe('账本来源待确认');
    expect(
      formatLedgerSourceLabel('broker_statement_manual_adjustment_v2', 'en'),
    ).toBe('Source needs review');
  });

  test('localizes fee-rule and cost-basis method labels through shared formatter', () => {
    expect(formatLedgerFeeRuleLabel('manual_configured_commission', 'zh')).toBe(
      '账户配置费用规则',
    );
    expect(formatLedgerFeeRuleLabel('manual_fee_input', 'en')).toBe(
      'Manual fee override',
    );
    expect(formatLedgerFeeRuleLabel('future_fee_rule_v2', 'zh')).toBe(
      '费用规则待确认',
    );
    expect(
      formatLedgerCostBasisMethodLabel('moving_average_buy_cost', 'zh'),
    ).toBe('移动平均买入成本');
    expect(
      formatLedgerCostBasisMethodLabel('broker_remaining_cost', 'en'),
    ).toBe('Broker displayed remaining cost');
    expect(formatLedgerCostBasisMethodLabel('future_cost_basis_v2', 'en')).toBe(
      'Cost basis method needs review',
    );
  });

  test('formats broker trade evidence references with shared ledger labels', () => {
    const instrumentNames = new Map([['syn001', '合成样例股票A']]);

    expect(
      formatLedgerEvidenceReference(
        'broker_event:import-run-1:SYN001:trade_buy',
        'en',
        instrumentNames,
      ),
    ).toBe('Broker evidence · 合成样例股票A SYN001 · Buy · import-run-1');
    expect(
      formatLedgerEvidenceReference(
        'broker_event:import-run-1:SYN001:trade_sell',
        'zh',
        instrumentNames,
      ),
    ).toBe('券商证据 · 合成样例股票A SYN001 · 卖出 · import-run-1');
    expect(
      formatLedgerEvidenceReference(
        'broker_event:import-run-1:SYN001:position_snapshot',
        'en',
        instrumentNames,
      ),
    ).toBe(
      'Broker evidence · 合成样例股票A SYN001 · Position snapshot · import-run-1',
    );
  });

  test('formats generated explainability events through shared ledger labels', () => {
    const instrumentNames = new Map([['600003', '示例制造']]);

    expect(
      formatLedgerExplainabilityTitle(
        {
          kind: 'trade_buy',
          title: 'Bought 600003',
          detail: '数量 200 · 价格 ¥16.25 · 手续费 ¥5.00',
          symbol: '600003',
          amount: -3255,
        },
        'zh',
        instrumentNames,
      ),
    ).toBe('买入 示例制造 600003');
    expect(
      formatLedgerExplainabilityTitle(
        {
          kind: 'trade_buy',
          title: '买入 600003',
          detail: '数量 200 · 价格 ¥16.25 · 手续费 ¥5.00',
          symbol: '600003',
          amount: -3255,
        },
        'zh',
        instrumentNames,
      ),
    ).toBe('买入 示例制造 600003');
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
        gross_amount: 3250,
        net_cash_impact: -3255,
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
      value: '-CN¥3,255.00',
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
        timestamp: '2026-01-12T05:22:58+00:00',
        amount: 200,
        gross_amount: 200,
        net_cash_impact: -200,
        symbol: '012999',
        display_name: '示例稳健混合C',
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
        note: '手工录入基金申购：示例稳健混合C，申购金额 200.00',
        source: 'manual',
        source_ref: 'manual-fund-012999-20260112',
        created_at: '2026-01-12T05:22:58+00:00',
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
