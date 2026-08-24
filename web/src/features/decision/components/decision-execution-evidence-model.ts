import { type Locale } from '../../../shared/preferences/context';
import { formatCurrency } from '../../../shared/format';
import {
  type ExecutionReconciliationRun,
  type ExecutionReconciliationItem,
  type BrokerGatewayFillsQueryResponse,
} from '../decision-feature-boundary';
import type {
  BrokerTradeCostEvidence,
  ManualBrokerComparisonEvidence,
  ManualExecutionEvidence,
} from './decision-status-model';
import { numericCostSummaryValue, objectRecord } from './decision-status-model';

export function brokerTradeCostEvidenceForItem(
  item: ExecutionReconciliationItem | undefined,
  locale: Locale,
): BrokerTradeCostEvidence | null {
  const payload = objectRecord(item?.payload);
  const summary = objectRecord(payload?.broker_trade_cost_summary);
  if (!summary) {
    return null;
  }

  const labels =
    locale === 'zh'
      ? {
          brokerEvent: '条券商事件',
          brokerEventsUnavailable: '券商事件待复核',
          grossAmount: '成交总额',
          feeTax: '手续费 / 税费',
          transferFee: '过户费',
          netAmount: '净额',
          reviewRequired: '更新账本前需复核',
          noLedgerMutation: '不修改账本',
        }
      : {
          brokerEvent: 'broker event',
          brokerEventsUnavailable: 'Broker events need review',
          grossAmount: 'Gross amount',
          feeTax: 'Fee / tax',
          transferFee: 'Transfer fee',
          netAmount: 'Net amount',
          reviewRequired: 'Review before ledger update',
          noLedgerMutation: 'No ledger mutation',
        };
  const eventCountValue = numericCostSummaryValue(summary.event_count);
  const eventCount =
    eventCountValue === null ? 0 : Math.max(0, Math.trunc(eventCountValue));
  const grossAmount = formatCurrency(
    numericCostSummaryValue(summary.gross_amount),
  );
  const fee = formatCurrency(numericCostSummaryValue(summary.fee));
  const tax = formatCurrency(numericCostSummaryValue(summary.tax));
  const transferFee = formatCurrency(
    numericCostSummaryValue(summary.transfer_fee),
  );
  const netAmount = formatCurrency(numericCostSummaryValue(summary.net_amount));
  const items = [
    grossAmount !== '--'
      ? { label: labels.grossAmount, value: grossAmount }
      : null,
    fee !== '--' || tax !== '--'
      ? { label: labels.feeTax, value: `${fee} / ${tax}` }
      : null,
    transferFee !== '--'
      ? { label: labels.transferFee, value: transferFee }
      : null,
    netAmount !== '--' ? { label: labels.netAmount, value: netAmount } : null,
  ].filter(
    (entry): entry is { label: string; value: string } => entry !== null,
  );
  if (eventCount <= 0 && items.length === 0) {
    return null;
  }
  return {
    eventCountLabel:
      eventCount > 0
        ? countLabel(eventCount, labels.brokerEvent, 'broker events', locale)
        : labels.brokerEventsUnavailable,
    items,
    safetyLabels: [
      summary.review_required_before_ledger_update === true
        ? labels.reviewRequired
        : '',
      summary.does_not_mutate_production_ledger === true
        ? labels.noLedgerMutation
        : '',
    ].filter(Boolean),
  };
}

export function manualExecutionEvidenceForItem(
  item: ExecutionReconciliationItem | undefined,
  locale: Locale,
): ManualExecutionEvidence | null {
  const payload = objectRecord(item?.payload);
  return manualExecutionEvidenceForPayload(payload, locale);
}

export function manualExecutionEvidenceForPayload(
  payload: Record<string, unknown> | null,
  locale: Locale,
): ManualExecutionEvidence | null {
  const summary = objectRecord(payload?.manual_execution_evidence_summary);
  if (!summary) {
    return null;
  }

  const labels =
    locale === 'zh'
      ? {
          gatewayEvent: '个网关事件',
          gatewayEventsUnavailable: '网关事件待复核',
          previewFingerprint: 'Preview fingerprint',
          fillPrice: '成交价',
          quantity: '数量',
          grossAmount: '成交总额',
          feeTax: '手续费 / 税费',
          transferFee: '过户费',
          netCashImpact: '净现金影响',
          ledgerDraft: '账本草稿',
          reviewRequired: '更新账本前需复核',
          operatorSave: '需要人工保存账本',
          noBrokerSubmission: '不提交券商订单',
          noOmsMutation: '不修改 OMS',
          noLedgerMutation: '不修改账本',
        }
      : {
          gatewayEvent: 'gateway event',
          gatewayEventsUnavailable: 'Gateway events need review',
          previewFingerprint: 'Preview fingerprint',
          fillPrice: 'Fill price',
          quantity: 'Quantity',
          grossAmount: 'Gross amount',
          feeTax: 'Fee / tax',
          transferFee: 'Transfer fee',
          netCashImpact: 'Net cash impact',
          ledgerDraft: 'Ledger draft',
          reviewRequired: 'Review before ledger update',
          operatorSave: 'Operator ledger save required',
          noBrokerSubmission: 'No broker submission',
          noOmsMutation: 'No OMS mutation',
          noLedgerMutation: 'No ledger mutation',
        };
  const eventCountValue = numericCostSummaryValue(summary.event_count);
  const eventCount =
    eventCountValue === null ? 0 : Math.max(0, Math.trunc(eventCountValue));
  const fillPrice = formatCurrency(numericCostSummaryValue(summary.fill_price));
  const grossAmount = formatCurrency(
    numericCostSummaryValue(summary.gross_amount),
  );
  const fee = formatCurrency(numericCostSummaryValue(summary.fee));
  const tax = formatCurrency(numericCostSummaryValue(summary.tax));
  const transferFee = formatCurrency(
    numericCostSummaryValue(summary.transfer_fee),
  );
  const netCashImpact = formatCurrency(
    numericCostSummaryValue(summary.net_cash_impact),
  );
  const ledgerDraft = formatCurrency(
    numericCostSummaryValue(summary.ledger_entry_amount),
  );
  const quantity =
    typeof summary.quantity === 'string' && summary.quantity.trim()
      ? summary.quantity.trim()
      : typeof summary.quantity === 'number'
        ? String(summary.quantity)
        : '';
  const fingerprint =
    typeof summary.preview_fingerprint === 'string'
      ? summary.preview_fingerprint
      : '';
  const items = [
    fillPrice !== '--' ? { label: labels.fillPrice, value: fillPrice } : null,
    quantity ? { label: labels.quantity, value: quantity } : null,
    grossAmount !== '--'
      ? { label: labels.grossAmount, value: grossAmount }
      : null,
    fee !== '--' || tax !== '--'
      ? { label: labels.feeTax, value: `${fee} / ${tax}` }
      : null,
    transferFee !== '--'
      ? { label: labels.transferFee, value: transferFee }
      : null,
    netCashImpact !== '--'
      ? { label: labels.netCashImpact, value: netCashImpact }
      : null,
    ledgerDraft !== '--'
      ? { label: labels.ledgerDraft, value: ledgerDraft }
      : null,
  ].filter(
    (entry): entry is { label: string; value: string } => entry !== null,
  );
  if (eventCount <= 0 && items.length === 0 && !fingerprint) {
    return null;
  }
  return {
    eventCountLabel:
      eventCount > 0
        ? countLabel(eventCount, labels.gatewayEvent, 'gateway events', locale)
        : labels.gatewayEventsUnavailable,
    fingerprint,
    items: fingerprint
      ? [
          {
            label: labels.previewFingerprint,
            value: fingerprint,
          },
          ...items,
        ]
      : items,
    safetyLabels: [
      summary.review_required_before_ledger_update === true
        ? labels.reviewRequired
        : '',
      summary.requires_operator_ledger_save === true ? labels.operatorSave : '',
      summary.submitted_to_broker === false ? labels.noBrokerSubmission : '',
      summary.does_not_mutate_oms === true ? labels.noOmsMutation : '',
      summary.does_not_mutate_production_ledger === true
        ? labels.noLedgerMutation
        : '',
    ].filter(Boolean),
  };
}

export function manualBrokerComparisonEvidenceForItem(
  item: ExecutionReconciliationItem | undefined,
  locale: Locale,
): ManualBrokerComparisonEvidence | null {
  const payload = objectRecord(item?.payload);
  const comparison = objectRecord(payload?.manual_broker_comparison);
  const comparedValues = objectRecord(comparison?.compared_values);
  const status =
    typeof comparison?.status === 'string' ? comparison.status : '';
  if (
    !comparison ||
    !comparedValues ||
    !['match', 'mismatch'].includes(status)
  ) {
    return null;
  }
  const mismatchReasons = Array.isArray(comparison?.mismatch_reasons)
    ? comparison.mismatch_reasons.filter(
        (reason): reason is string => typeof reason === 'string',
      )
    : [];
  const labels =
    locale === 'zh'
      ? {
          statusMatch: '手工与券商证据一致，仍需复核',
          statusMismatch: '手工与券商证据存在差异',
          manual: '手工记录',
          broker: '券商证据',
          reviewRequired: '更新账本前需复核',
          noAutomaticLedger: '不建议自动更新账本',
          noOmsMutation: '不修改 OMS',
          noLedgerMutation: '不修改账本',
          fields: {
            quantity: '数量',
            fill_price: '成交价',
            gross_amount: '成交总额',
            fee: '手续费',
            tax: '税费',
            transfer_fee: '过户费',
            net_amount: '净额',
          },
        }
      : {
          statusMatch:
            'Manual and broker evidence match; review still required',
          statusMismatch: 'Manual and broker evidence differ',
          manual: 'Manual record',
          broker: 'Broker evidence',
          reviewRequired: 'Review before ledger update',
          noAutomaticLedger: 'No automatic ledger recommendation',
          noOmsMutation: 'No OMS mutation',
          noLedgerMutation: 'No ledger mutation',
          fields: {
            quantity: 'Quantity',
            fill_price: 'Fill price',
            gross_amount: 'Gross amount',
            fee: 'Fee',
            tax: 'Tax',
            transfer_fee: 'Transfer fee',
            net_amount: 'Net amount',
          },
        };
  const fieldOrder = [
    'quantity',
    'fill_price',
    'gross_amount',
    'fee',
    'tax',
    'transfer_fee',
    'net_amount',
  ] as const;
  const items = fieldOrder.flatMap((field) => {
    const values = objectRecord(comparedValues[field]);
    if (!values) {
      return [];
    }
    const rawManual = values.manual;
    const rawBroker = values.broker;
    const formatValue = (value: unknown) => {
      if (field === 'quantity') {
        return String(value ?? '--');
      }
      return formatCurrency(numericCostSummaryValue(value));
    };
    return [
      {
        label: labels.fields[field],
        manualValue: `${labels.manual}: ${formatValue(rawManual)}`,
        brokerValue: `${labels.broker}: ${formatValue(rawBroker)}`,
        isMismatch: mismatchReasons.includes(
          `manual_execution_${field}_mismatch`,
        ),
      },
    ];
  });
  if (items.length === 0) {
    return null;
  }
  return {
    statusLabel:
      status === 'mismatch' ? labels.statusMismatch : labels.statusMatch,
    items,
    safetyLabels: [
      comparison.review_required_before_ledger_update === true
        ? labels.reviewRequired
        : '',
      comparison.does_not_recommend_automatic_ledger_update === true
        ? labels.noAutomaticLedger
        : '',
      comparison.does_not_mutate_oms === true ? labels.noOmsMutation : '',
      comparison.does_not_mutate_production_ledger === true
        ? labels.noLedgerMutation
        : '',
    ].filter(Boolean),
  };
}

export function countLabel(
  count: number,
  singular: string,
  plural: string,
  locale: Locale,
) {
  if (locale === 'zh') {
    return `${count} ${singular}`;
  }
  return `${count} ${count === 1 ? singular : plural}`;
}

export function stagedFillSymbolSummary(
  fills: BrokerGatewayFillsQueryResponse,
  locale: Locale,
) {
  const symbols = Array.from(
    new Set(
      fills.fills
        .map((fill) =>
          typeof fill.symbol === 'string' ? fill.symbol.trim() : '',
        )
        .filter(Boolean),
    ),
  ).slice(0, 4);
  if (symbols.length === 0) {
    return locale === 'zh' ? '暂无样本' : 'No samples';
  }
  return symbols.join(locale === 'zh' ? '、' : ', ');
}

export function stagedFillReconciliationReviewHint(
  fills: BrokerGatewayFillsQueryResponse | undefined,
  reconciliationRun: ExecutionReconciliationRun | undefined,
  locale: Locale,
) {
  const fillCount = Math.max(fills?.fill_count ?? 0, fills?.fills.length ?? 0);
  const openItemCount = reconciliationRun?.open_item_count ?? 0;
  if (fillCount <= 0 || openItemCount <= 0) {
    return null;
  }

  const fillLabel = countLabel(
    fillCount,
    locale === 'zh' ? '条暂存成交' : 'staged fill',
    'staged fills',
    locale,
  );

  return {
    title:
      locale === 'zh'
        ? '暂存成交可用于执行对账复核'
        : 'Staged fills ready for reconciliation review',
    detail:
      locale === 'zh'
        ? `${fillLabel}可先与执行对账比对，再考虑任何账本更新。`
        : `${fillLabel} can be compared with execution reconciliation before any ledger update.`,
  };
}

export function primaryExecutionReconciliationItemForRun(
  run: ExecutionReconciliationRun | undefined,
): ExecutionReconciliationItem | undefined {
  return (
    run?.items?.find(
      (item) =>
        (item.suggested_action ?? item.recommended_action ?? 'no_action') !==
        'no_action',
    ) ?? run?.items?.[0]
  );
}
