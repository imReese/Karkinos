import type { Locale } from './locale';
import type {
  LedgerActivitySummaryTone,
  LedgerExecutionDetailLabels,
  LedgerSummaryKind,
} from './ledger-format-contracts';

export const SOURCE_LABELS: Record<Locale, Record<string, string>> = {
  en: {
    broker_statement_manual_correction: 'Reconciliation adjustment',
    manual: 'Manual entry',
    portfolio_trade: 'Portfolio trade',
    review: 'Source needs review',
    system: 'System entry',
    unknown: 'Source unknown',
  },
  zh: {
    broker_statement_manual_correction: '对账校正',
    manual: '手工录入',
    portfolio_trade: '交易流水',
    review: '账本来源待确认',
    system: '系统生成',
    unknown: '来源未知',
  },
};

export const FEE_RULE_LABELS: Record<Locale, Record<string, string>> = {
  en: {
    manual_configured_commission: 'Configured account fee rule',
    manual_fee_input: 'Manual fee override',
    review: 'Fee rule needs review',
  },
  zh: {
    manual_configured_commission: '账户配置费用规则',
    manual_fee_input: '手工费用覆盖',
    review: '费用规则待确认',
  },
};

export const COST_BASIS_METHOD_LABELS: Record<
  Locale,
  Record<string, string>
> = {
  en: {
    broker_remaining_cost: 'Broker displayed remaining cost',
    moving_average_buy_cost: 'Moving average buy cost',
    projected_from_ledger: 'Projected from local ledger',
    review: 'Cost basis method needs review',
  },
  zh: {
    broker_remaining_cost: '券商剩余持仓成本',
    moving_average_buy_cost: '移动平均买入成本',
    projected_from_ledger: '本地流水推算',
    review: '成本口径待确认',
  },
};

export const ENTRY_TYPE_LABELS: Record<
  Locale,
  Record<LedgerSummaryKind, string>
> = {
  en: {
    trade_buy: 'Buy',
    trade_sell: 'Sell',
    cash_deposit: 'Cash deposit',
    cash_withdrawal: 'Cash withdrawal',
    cash_interest: 'Cash interest',
    dividend: 'Dividend',
    manual_adjustment: 'Manual adjustment',
    other: 'Ledger movement',
  },
  zh: {
    trade_buy: '买入',
    trade_sell: '卖出',
    cash_deposit: '资金转入',
    cash_withdrawal: '资金转出',
    cash_interest: '结息入账',
    dividend: '分红',
    manual_adjustment: '手动调整',
    other: '账本变动',
  },
};

export const EXPLAINABILITY_DETAIL_LABELS: Record<
  Locale,
  LedgerExecutionDetailLabels
> = {
  en: {
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
  zh: {
    amount: '金额',
    grossAmount: '成交金额',
    netCashImpact: '现金影响',
    quantity: '数量',
    price: '价格',
    fee: '手续费',
    commission: '佣金',
    stampTax: '印花税',
    transferFee: '过户费',
    otherFees: '其他费用',
    costBasis: '成本价',
  },
};

export const ACTIVITY_LABELS: Record<
  Locale,
  Record<
    LedgerSummaryKind,
    {
      label: string;
      shortLabel: string;
      cashImpactLabel: string;
      tone: LedgerActivitySummaryTone;
    }
  >
> = {
  en: {
    trade_buy: {
      label: 'Security buy',
      shortLabel: 'B',
      cashImpactLabel: 'Consumes cash',
      tone: 'debit',
    },
    trade_sell: {
      label: 'Security sell',
      shortLabel: 'S',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    cash_deposit: {
      label: 'Cash deposit',
      shortLabel: '+',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    cash_withdrawal: {
      label: 'Cash withdrawal',
      shortLabel: '-',
      cashImpactLabel: 'Consumes cash',
      tone: 'debit',
    },
    cash_interest: {
      label: 'Cash interest',
      shortLabel: 'I',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    dividend: {
      label: 'Dividend received',
      shortLabel: 'D',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    manual_adjustment: {
      label: 'Manual adjustment',
      shortLabel: 'A',
      cashImpactLabel: 'Operator adjustment',
      tone: 'adjustment',
    },
    other: {
      label: 'Ledger entry',
      shortLabel: 'L',
      cashImpactLabel: 'Reference ledger movement',
      tone: 'neutral',
    },
  },
  zh: {
    trade_buy: {
      label: '证券买入',
      shortLabel: '买',
      cashImpactLabel: '占用现金',
      tone: 'debit',
    },
    trade_sell: {
      label: '证券卖出',
      shortLabel: '卖',
      cashImpactLabel: '成交回款',
      tone: 'credit',
    },
    cash_deposit: {
      label: '资金转入',
      shortLabel: '入',
      cashImpactLabel: '现金增加',
      tone: 'credit',
    },
    cash_withdrawal: {
      label: '资金转出',
      shortLabel: '出',
      cashImpactLabel: '现金减少',
      tone: 'debit',
    },
    cash_interest: {
      label: '结息入账',
      shortLabel: '息',
      cashImpactLabel: '现金利息',
      tone: 'credit',
    },
    dividend: {
      label: '分红入账',
      shortLabel: '息',
      cashImpactLabel: '持仓现金收入',
      tone: 'credit',
    },
    manual_adjustment: {
      label: '手工调整',
      shortLabel: '调',
      cashImpactLabel: '人工校正',
      tone: 'adjustment',
    },
    other: {
      label: '账本流水',
      shortLabel: '流',
      cashImpactLabel: '参考流水',
      tone: 'neutral',
    },
  },
};
