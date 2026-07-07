import { useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import {
  formatPublicEvidenceReference,
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  formatInstrumentDisplayLabel,
  type InstrumentDisplayRecord,
} from '../../../shared/instrument-display';
import {
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  formatLedgerOrderSideLabel,
  type LedgerExecutionDetailLabels,
  type PublicLedgerEntry,
} from '../../../shared/ledger-format';
import { KillSwitchPanel } from './kill-switch-panel';
import {
  useOperationsTodayQuery,
  useReviewPaperShadowRunMutation,
  type OperationsTodayResponse,
  type PaperShadowRunReviewResponse,
} from '../../operations/api';
import {
  useConfirmManualOrderMutation,
  useDailyShadowRunMutation,
  useFillFactsQuery,
  useManualExecutionRecordMutation,
  useManualExecutionPreviewMutation,
  useManualTicketExportMutation,
  useManualOrdersQuery,
  useOrderFactsQuery,
  useRejectManualOrderMutation,
  type FillFact,
  type ControlledBridgeGateSummary,
  type ManualExecutionRecordResponse,
  type ManualExecutionPreviewRequest,
  type ManualExecutionPreviewResponse,
  type ManualTicketOperatorForm,
  type ManualTicketExportResponse,
  type ManualOrder,
  type ManualOrderStatus,
  type OrderFact,
} from '../api';
import { usePositionsQuery } from '../../portfolio/api';

type SideFilter = 'all' | 'buy' | 'sell';
type InstrumentNameLookup = Map<string, string>;
type PaperShadowRunSummary = OperationsTodayResponse['paper_shadow'];
type PaperShadowReviewQueueItem = NonNullable<
  PaperShadowRunSummary['review_queue']
>[number];

const STATUS_OPTIONS: ManualOrderStatus[] = [
  'all',
  'pending_confirm',
  'confirmed',
  'rejected',
  'canceled',
];

function statusLabel(
  status: string,
  labels: ReturnType<typeof useCopy>['trading']['page'],
  locale?: Locale,
) {
  if (status === 'pending_confirm') {
    return labels.statusPendingConfirm;
  }
  if (status === 'confirmed') {
    return labels.statusConfirmed;
  }
  if (status === 'rejected') {
    return labels.statusRejected;
  }
  if (status === 'canceled') {
    return labels.statusCanceled;
  }
  return locale ? formatPublicStatus(status, locale) : status;
}

function getLatestOrderTimestamp(orders: ManualOrder[]) {
  const latest = orders
    .map((order) => order.updated_at || order.created_at || order.timestamp)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => right - left)[0];

  return latest ? new Date(latest).toISOString() : null;
}

function paperShadowRunNeedsReview(run: PaperShadowRunSummary | null) {
  if (!run?.run_id) {
    return false;
  }
  if (run.review_status === 'accepted_for_manual_confirmation') {
    return false;
  }
  return (
    ['diverged', 'review_required'].includes(run.status) ||
    ['resolve_shadow_divergence', 'review_shadow_divergence'].includes(
      run.next_manual_review_step,
    )
  );
}

function paperShadowAcceptedReviewEvidenceItems(
  review: PaperShadowRunReviewResponse | null,
  run: PaperShadowRunSummary | null,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          reviewedBy: '复核人',
          reviewedAt: '复核时间',
          reviewSafety: '复核安全边界',
          noBrokerSubmission: '不提交券商订单',
          noLedgerMutation: '不修改生产账本',
        }
      : {
          reviewedBy: 'Reviewed by',
          reviewedAt: 'Reviewed at',
          reviewSafety: 'Review safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const reviewer = review?.reviewer ?? run?.reviewer;
  const reviewedAt = review?.reviewed_at ?? run?.reviewed_at;
  const safetyItems = [
    (review?.does_not_submit_broker_order ??
    run?.divergence_summary?.does_not_submit_broker_order)
      ? labels.noBrokerSubmission
      : '',
    (review?.does_not_mutate_production_ledger ??
    run?.divergence_summary?.does_not_mutate_production_ledger)
      ? labels.noLedgerMutation
      : '',
  ].filter(Boolean);

  return [
    reviewer ? `${labels.reviewedBy}: ${reviewer}` : '',
    reviewedAt ? `${labels.reviewedAt}: ${formatTimestamp(reviewedAt)}` : '',
    safetyItems.length
      ? `${labels.reviewSafety}: ${safetyItems.join(' · ')}`
      : '',
  ].filter(Boolean);
}

function paperShadowNextStepLabel(
  value: string | null | undefined,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    none: { en: 'No additional action', zh: '无需额外处理' },
    review_shadow_divergence: {
      en: 'Review paper/shadow divergence evidence',
      zh: '复核 paper/shadow 偏差证据',
    },
    resolve_shadow_divergence: {
      en: 'Resolve paper/shadow divergence before approval',
      zh: '批准前处理 paper/shadow 偏差',
    },
    review_manual_confirmation: {
      en: 'Review manual order confirmation',
      zh: '复核人工下单确认',
    },
    run_paper_shadow_daily: {
      en: 'Run paper/shadow simulation before manual confirmation',
      zh: '人工确认前先运行 paper/shadow 模拟',
    },
    wait_for_paper_shadow_run: {
      en: 'Paper/shadow simulation is running; wait for completion',
      zh: 'Paper/shadow 模拟正在运行，等待完成',
    },
    inspect_failed_run: {
      en: 'Inspect failed paper/shadow run before approval',
      zh: '批准前检查失败的 paper/shadow 运行',
    },
  };
  const key = value || 'none';
  return labels[key]?.[locale] ?? formatPublicStatus(key, locale);
}

function numericPaperShadowValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function latestPaperShadowRunEvidenceItems(
  run: PaperShadowRunSummary,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          run: 'Run',
          status: '状态',
          orderIntents: '订单意图',
          simOrders: '模拟订单',
          simFills: '模拟成交',
          next: '下一步',
          evidenceRefs: '证据引用',
          divergedOrders: '偏差订单',
          slippage: '模拟滑点',
          noBrokerSubmission: '不提交券商订单',
          noLedgerMutation: '不修改生产账本',
        }
      : {
          run: 'Run',
          status: 'Status',
          orderIntents: 'Order intents',
          simOrders: 'Sim orders',
          simFills: 'Sim fills',
          next: 'Next',
          evidenceRefs: 'Evidence refs',
          divergedOrders: 'Diverged orders',
          slippage: 'Sim slippage',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const summary = run.divergence_summary;
  const divergedRefs = (
    summary?.execution_comparison?.diverged_order_refs ?? []
  )
    .slice(0, 2)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const evidenceRefs = selectPaperShadowRunEvidenceRefs(run.evidence_refs ?? [])
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const reviewQueueItems = latestPaperShadowReviewQueueEvidenceItems(
    run,
    locale,
  );
  const slippage = numericPaperShadowValue(
    summary?.cost_summary?.simulated_slippage_cost,
  );
  return [
    `${labels.run}: ${run.run_id ?? '--'}`,
    `${labels.status}: ${formatPublicStatus(run.status, locale)}`,
    `${labels.orderIntents}: ${run.order_intent_count}`,
    `${labels.simOrders}: ${run.simulated_order_count}`,
    `${labels.simFills}: ${run.simulated_fill_count}`,
    `${labels.next}: ${paperShadowNextStepLabel(
      run.next_manual_review_step,
      locale,
    )}`,
    divergedRefs.length
      ? `${labels.divergedOrders}: ${divergedRefs.join(
          locale === 'zh' ? '；' : '; ',
        )}`
      : '',
    evidenceRefs.length
      ? `${labels.evidenceRefs}: ${evidenceRefs.join(
          locale === 'zh' ? '；' : '; ',
        )}`
      : '',
    ...reviewQueueItems,
    slippage !== null ? `${labels.slippage}: ${formatCurrency(slippage)}` : '',
    summary?.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    summary?.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);
}

function latestPaperShadowReviewQueueEvidenceItems(
  run: PaperShadowRunSummary,
  locale: Locale,
) {
  const item = run.review_queue?.[0];
  if (!item) {
    return [];
  }

  const labels =
    locale === 'zh'
      ? {
          reviewQueue: '复核队列',
          reason: '原因',
          omsPath: 'OMS 路径',
          latestTransition: '最新状态变更',
          reviewSafety: '复核安全边界',
          noBrokerSubmission: '不提交券商订单',
          noLedgerMutation: '不修改生产账本',
        }
      : {
          reviewQueue: 'Review queue',
          reason: 'Reason',
          omsPath: 'OMS path',
          latestTransition: 'Latest transition',
          reviewSafety: 'Review safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const target = item.symbol ?? item.order_id ?? item.review_id;
  const statusPath = paperShadowOmsStatusPath(item.oms_status_path, locale);
  const latestTransition = latestOmsTransitionEvidenceRef(
    item.oms_transition_refs ?? [],
  );
  const safetyItems = [
    item.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    item.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);

  return [
    `${labels.reviewQueue}: ${target} · ${paperShadowNextStepLabel(
      item.required_action,
      locale,
    )}`,
    item.reason ? `${labels.reason}: ${item.reason}` : '',
    statusPath ? `${labels.omsPath}: ${statusPath}` : '',
    latestTransition
      ? `${labels.latestTransition}: ${formatPublicEvidenceReference(
          latestTransition,
          locale,
        )}`
      : '',
    safetyItems.length
      ? `${labels.reviewSafety}: ${safetyItems.join(
          locale === 'zh' ? ' · ' : ' · ',
        )}`
      : '',
  ].filter(Boolean);
}

function paperShadowOmsStatusPath(
  values: PaperShadowReviewQueueItem['oms_status_path'],
  locale: Locale,
) {
  if (!values?.length) {
    return null;
  }
  return values
    .map((value) => paperShadowOmsStatusLabel(value, locale))
    .join(locale === 'zh' ? ' → ' : ' → ');
}

function paperShadowOmsStatusLabel(value: string, locale: Locale) {
  const labels: Record<string, Record<Locale, string>> = {
    accepted: { en: 'Accepted', zh: '已接受模拟' },
    cancelled: { en: 'Cancelled', zh: '已取消' },
    canceled: { en: 'Cancelled', zh: '已取消' },
    expired: { en: 'Expired', zh: '已过期' },
    filled: { en: 'Filled', zh: '已成交' },
    partially_filled: { en: 'Partially Filled', zh: '部分成交' },
    reconciled: { en: 'Reconciled', zh: '已对账' },
    rejected: { en: 'Rejected', zh: '已拒绝' },
    staged: { en: 'Staged', zh: '已暂存' },
    submitted: { en: 'Submitted', zh: '已提交模拟' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function selectPaperShadowRunEvidenceRefs(refs: string[]) {
  const selected: string[] = [];
  const seen = new Set<string>();
  const add = (ref: string | undefined) => {
    if (ref && !seen.has(ref) && selected.length < 3) {
      selected.push(ref);
      seen.add(ref);
    }
  };

  add(
    refs.find((ref) => /^(?:paper_shadow_order|paper_order|order):/.test(ref)),
  );
  add(refs.find((ref) => /^(?:paper_shadow_fill|paper_fill|fill):/.test(ref)));
  add(latestOmsTransitionEvidenceRef(refs));

  for (const ref of refs) {
    add(ref);
  }

  return selected;
}

function latestOmsTransitionEvidenceRef(refs: string[]) {
  return refs
    .filter((ref) => ref.startsWith('oms_transition:'))
    .reduce<string | undefined>((latest, ref) => {
      if (!latest) {
        return ref;
      }
      return omsTransitionSequence(ref) >= omsTransitionSequence(latest)
        ? ref
        : latest;
    }, undefined);
}

function omsTransitionSequence(ref: string) {
  const sequence = Number(ref.split(':')[2]);
  return Number.isFinite(sequence) ? sequence : -1;
}

function parsePayload(value: string): Record<string, string | null> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === 'object'
      ? (parsed as Record<string, string | null>)
      : null;
  } catch {
    return null;
  }
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function instrumentDisplayLabel(
  instrument: InstrumentDisplayRecord | string,
  instrumentNames: InstrumentNameLookup,
) {
  const record =
    typeof instrument === 'string' ? { symbol: instrument } : instrument;
  return formatInstrumentDisplayLabel({
    ...record,
    display_name:
      record.display_name ??
      record.name ??
      instrumentNames.get(record.symbol ?? '') ??
      null,
  });
}

function sideLabel(side: string, locale: Locale = 'en') {
  return formatLedgerOrderSideLabel(side, locale);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function parseJsonObject(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function parseFillMetadata(fill: FillFact) {
  if (isRecord(fill.metadata)) {
    return fill.metadata;
  }
  if (typeof fill.metadata === 'string') {
    return parseJsonObject(fill.metadata) ?? {};
  }
  return parseJsonObject(fill.metadata_json) ?? {};
}

function finiteMetadataNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function firstFiniteNumber(...values: unknown[]) {
  for (const value of values) {
    const numeric = finiteMetadataNumber(value);
    if (numeric !== null) {
      return numeric;
    }
  }
  return null;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }
  return null;
}

function feeBreakdownFromMetadata(
  value: unknown,
): PublicLedgerEntry['fee_breakdown'] {
  return isRecord(value)
    ? (value as Record<string, number | string | null | undefined>)
    : null;
}

function fillToLedgerEntry(
  fill: FillFact,
  instrumentNames: InstrumentNameLookup,
): PublicLedgerEntry {
  const metadata = parseFillMetadata(fill);
  const quantity = firstFiniteNumber(fill.fill_quantity, metadata.quantity);
  const price = firstFiniteNumber(fill.fill_price, metadata.price);
  const grossAmount = firstFiniteNumber(
    fill.gross_amount,
    metadata.gross_amount,
    quantity !== null && price !== null ? quantity * price : null,
  );
  const normalizedSide = fill.side.trim().toLowerCase();
  const entryType = normalizedSide === 'sell' ? 'trade_sell' : 'trade_buy';

  return {
    id: fill.id,
    entry_type: entryType,
    timestamp: fill.timestamp,
    amount: grossAmount,
    symbol: fill.symbol,
    display_name:
      fill.display_name ??
      fill.name ??
      instrumentNames.get(fill.symbol) ??
      instrumentNames.get(fill.symbol.toLowerCase()) ??
      null,
    direction: normalizedSide || null,
    quantity,
    price,
    commission: firstFiniteNumber(fill.commission, metadata.commission),
    gross_amount: grossAmount,
    net_cash_impact: firstFiniteNumber(
      fill.net_cash_impact,
      metadata.net_cash_impact,
    ),
    fee_breakdown:
      fill.fee_breakdown ?? feeBreakdownFromMetadata(metadata.fee_breakdown),
    fee_rule_id: firstString(fill.fee_rule_id, metadata.fee_rule_id),
    fee_rule_version: firstString(
      fill.fee_rule_version,
      metadata.fee_rule_version,
    ),
    asset_class: firstString(fill.asset_class, metadata.asset_class) ?? 'stock',
    note: firstString(metadata.note),
    source: firstString(fill.source, metadata.source),
    source_ref: firstString(fill.source_ref, metadata.source_ref),
    created_at: null,
  };
}

function orderToLedgerEntry(
  order: OrderFact,
  instrumentNames: InstrumentNameLookup,
): PublicLedgerEntry {
  const quantity = finiteMetadataNumber(order.quantity);
  const price = finiteMetadataNumber(order.price);
  const normalizedSide = order.side.trim().toLowerCase();
  const entryType = normalizedSide === 'sell' ? 'trade_sell' : 'trade_buy';
  const grossAmount =
    quantity !== null && price !== null ? quantity * price : null;

  return {
    id: order.id,
    entry_type: entryType,
    timestamp: order.timestamp,
    amount: grossAmount,
    symbol: order.symbol,
    display_name:
      order.display_name ??
      order.name ??
      instrumentNames.get(order.symbol) ??
      instrumentNames.get(order.symbol.toLowerCase()) ??
      null,
    direction: normalizedSide || null,
    quantity,
    price,
    commission: null,
    gross_amount: null,
    net_cash_impact: null,
    fee_breakdown: null,
    fee_rule_id: null,
    fee_rule_version: null,
    asset_class: order.asset_class ?? 'stock',
    note: order.note ?? null,
    source: order.source ?? null,
    source_ref: order.source_ref ?? null,
    created_at: order.created_at ?? null,
  };
}

function formatOrderFactTitle(
  order: OrderFact,
  locale: Locale,
  instrumentNames: InstrumentNameLookup,
) {
  const entry = orderToLedgerEntry(order, instrumentNames);
  const action = sideLabel(order.side, locale);
  const instrument = formatLedgerInstrumentLabel(entry);
  return instrument ? `${action} ${instrument}` : action;
}

function formatOrderFactDetail(
  order: OrderFact,
  labels: ReturnType<typeof useCopy>['trading']['page'],
  detailLabels: LedgerExecutionDetailLabels,
  locale: Locale,
  instrumentNames: InstrumentNameLookup,
) {
  const entry = orderToLedgerEntry(order, instrumentNames);
  const structuredDetails = formatLedgerExecutionDetailLines(
    entry,
    detailLabels,
    locale,
  ).map((detail) => `${detail.label} ${detail.value}`);
  structuredDetails.push(
    `${labels.statusFilter} ${statusLabel(order.status, labels, locale)}`,
  );
  return structuredDetails.join(' · ');
}

function formatFillDetail(
  fill: FillFact,
  labels: ReturnType<typeof useCopy>['trading']['page'],
  detailLabels: LedgerExecutionDetailLabels,
  locale: Locale,
  instrumentNames: InstrumentNameLookup,
) {
  const structuredDetails = formatLedgerExecutionDetailLines(
    fillToLedgerEntry(fill, instrumentNames),
    detailLabels,
    locale,
  ).map((detail) => `${detail.label} ${detail.value}`);

  if (structuredDetails.length > 0) {
    return structuredDetails.join(' · ');
  }

  return `${formatQuantity(fill.fill_quantity)} @ ${formatPrice(
    fill.fill_price,
  )} · ${labels.commission} ${formatCurrency(fill.commission)}`;
}

export function TradingPage() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.trading.page;
  const orderLabels = copy.trading.orders;
  const [status, setStatus] = useState<ManualOrderStatus>('pending_confirm');
  const [symbolFilter, setSymbolFilter] = useState('');
  const [sideFilter, setSideFilter] = useState<SideFilter>('all');
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>(
    {},
  );
  const [rowError, setRowError] = useState('');
  const [confirmingRejectId, setConfirmingRejectId] = useState<string | null>(
    null,
  );
  const [exportingOrderId, setExportingOrderId] = useState<string | null>(null);

  const orders = useManualOrdersQuery(status);
  const allOrders = useManualOrdersQuery('all');
  const orderFacts = useOrderFactsQuery();
  const fillFacts = useFillFactsQuery();
  const positions = usePositionsQuery();
  const operationsToday = useOperationsTodayQuery();
  const shadowRun = useDailyShadowRunMutation();
  const reviewShadowRun = useReviewPaperShadowRunMutation();
  const confirmOrder = useConfirmManualOrderMutation();
  const rejectOrder = useRejectManualOrderMutation();
  const manualTicketExport = useManualTicketExportMutation();
  const manualExecutionPreview = useManualExecutionPreviewMutation();
  const manualExecutionRecord = useManualExecutionRecordMutation();
  const allOrderRows = allOrders.data ?? [];
  const rows = useMemo(() => {
    const normalizedSymbol = symbolFilter.trim().toLowerCase();
    return (orders.data ?? []).filter((order) => {
      const symbolMatches = normalizedSymbol
        ? order.symbol.toLowerCase().includes(normalizedSymbol)
        : true;
      const sideMatches =
        sideFilter === 'all' ? true : order.side.toLowerCase() === sideFilter;
      return symbolMatches && sideMatches;
    });
  }, [orders.data, sideFilter, symbolFilter]);

  const completedOrders = useMemo(
    () =>
      allOrderRows.filter((order) =>
        ['confirmed', 'rejected', 'canceled'].includes(order.status),
      ),
    [allOrderRows],
  );
  const counts = useMemo(
    () => ({
      pending: allOrderRows.filter(
        (order) => order.status === 'pending_confirm',
      ).length,
      confirmed: allOrderRows.filter((order) => order.status === 'confirmed')
        .length,
      rejected: allOrderRows.filter((order) => order.status === 'rejected')
        .length,
      canceled: allOrderRows.filter((order) => order.status === 'canceled')
        .length,
    }),
    [allOrderRows],
  );
  const latestTimestamp = getLatestOrderTimestamp(allOrderRows);
  const manualExecutionPreviewResult =
    manualTicketExport.data?.order_id === manualExecutionPreview.data?.order_id
      ? (manualExecutionPreview.data ?? null)
      : null;
  const manualExecutionRecordResult =
    manualTicketExport.data?.order_id === manualExecutionRecord.data?.order_id
      ? (manualExecutionRecord.data ?? null)
      : null;
  const instrumentNames = useMemo(
    () =>
      new Map(
        (positions.data ?? []).map((position) => [
          position.symbol,
          position.display_name ?? position.name ?? position.symbol,
        ]),
      ),
    [positions.data],
  );
  const busy = confirmOrder.isPending || rejectOrder.isPending;
  const paperShadowRun = operationsToday.data?.paper_shadow ?? null;

  const handleConfirm = async (orderId: string) => {
    setRowError('');
    setConfirmingRejectId(null);
    try {
      await confirmOrder.mutateAsync({ orderId });
    } catch {
      // Mutation error state renders the inline alert.
    }
  };

  const handleReject = async (orderId: string) => {
    const reason = (rejectReasons[orderId] ?? '').trim();
    if (!reason) {
      setRowError(orderLabels.rejectReasonRequired);
      setConfirmingRejectId(orderId);
      return;
    }
    if (confirmingRejectId !== orderId) {
      setRowError('');
      setConfirmingRejectId(orderId);
      return;
    }
    setRowError('');
    try {
      await rejectOrder.mutateAsync({ orderId, reason });
      setConfirmingRejectId(null);
      setRejectReasons((current) => {
        const next = { ...current };
        delete next[orderId];
        return next;
      });
    } catch (error) {
      // Mutation error state renders the inline alert.
    }
  };

  const handleExportTicket = async (orderId: string) => {
    setRowError('');
    setConfirmingRejectId(null);
    setExportingOrderId(orderId);
    try {
      await manualTicketExport.mutateAsync({ orderId });
    } catch {
      // Mutation error state renders the inline alert.
    } finally {
      setExportingOrderId(null);
    }
  };

  const handlePreviewManualExecution = async (
    orderId: string,
    values: ManualExecutionPreviewRequest,
  ) => {
    setRowError('');
    setConfirmingRejectId(null);
    try {
      await manualExecutionPreview.mutateAsync({ orderId, ...values });
    } catch {
      // Mutation error state renders inside the manual ticket panel.
    }
  };

  const handleRecordManualExecution = async (
    orderId: string,
    preview: ManualExecutionPreviewResponse,
  ) => {
    const fingerprint = preview.preview_fingerprint;
    if (!fingerprint) {
      return;
    }
    const execution = preview.execution_preview;
    setRowError('');
    setConfirmingRejectId(null);
    try {
      await manualExecutionRecord.mutateAsync({
        orderId,
        fill_price: execution.fill_price,
        quantity: execution.quantity,
        fee: execution.fee,
        tax: execution.tax,
        transfer_fee: execution.transfer_fee,
        preview_fingerprint: fingerprint,
      });
    } catch {
      // Mutation error state renders inside the manual ticket panel.
    }
  };

  const handleAcceptSimulationReview = async () => {
    if (!paperShadowRun?.run_id) {
      return;
    }
    setRowError('');
    setConfirmingRejectId(null);
    try {
      await reviewShadowRun.mutateAsync({ runId: paperShadowRun.run_id });
    } catch {
      // Mutation error state renders inside the execution audit panel.
    }
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <header className="app-page-header pb-1">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.kicker}</div>
            <h1 className="app-page-title mt-2">{labels.title}</h1>
          </div>
          <p className="app-page-subtitle sm:max-w-xl sm:text-right">
            {labels.subtitle}
          </p>
        </div>
      </header>

      <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[2rem] p-1.5">
        <div className="app-terminal-inner flex min-w-0 flex-wrap items-center gap-2 p-4 sm:p-5">
          <div className="app-product-mark mr-2">{labels.operatingMode}</div>
          <span className="rounded-full border border-[color-mix(in_srgb,var(--app-success)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-success)]">
            {labels.manualDefault}
          </span>
          <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-soft)]">
            {labels.brokerBridgeDisabled}
          </span>
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <StatusTile label={labels.pending} value={String(counts.pending)} />
        <StatusTile label={labels.confirmed} value={String(counts.confirmed)} />
        <StatusTile label={labels.rejected} value={String(counts.rejected)} />
        <StatusTile label={labels.canceled} value={String(counts.canceled)} />
        <StatusTile
          label={labels.lastUpdated}
          value={formatTimestamp(latestTimestamp)}
        />
      </div>

      <KillSwitchPanel />

      <ExecutionAuditPanel
        orders={orderFacts.data ?? []}
        fills={fillFacts.data ?? []}
        loading={orderFacts.isLoading || fillFacts.isLoading}
        error={orderFacts.isError || fillFacts.isError}
        instrumentNames={instrumentNames}
        shadowRunPending={shadowRun.isPending}
        shadowRunResult={shadowRun.data ?? null}
        paperShadowRun={paperShadowRun}
        reviewPending={reviewShadowRun.isPending}
        reviewResult={reviewShadowRun.data ?? null}
        reviewError={
          reviewShadowRun.isError ? getErrorMessage(reviewShadowRun.error) : ''
        }
        onRunShadowReview={() => void shadowRun.mutate()}
        onAcceptSimulationReview={() => void handleAcceptSimulationReview()}
      />

      <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
        <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
          <div className="flex min-w-0 flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div className="min-w-0">
              <div className="app-product-mark">{labels.filterTitle}</div>
              <h2 className="app-card-title mt-1.5">{labels.ordersTitle}</h2>
              <p className="app-muted mt-2 break-words text-sm">
                {labels.filteredCount(rows.length)}
              </p>
            </div>
            <div className="grid min-w-0 w-full gap-3 sm:grid-cols-3 xl:max-w-[680px]">
              <label className="grid gap-2 text-sm font-medium">
                {labels.statusFilter}
                <select
                  className="app-field rounded-2xl px-4 py-3 text-sm"
                  value={status}
                  onChange={(event) =>
                    setStatus(event.target.value as ManualOrderStatus)
                  }
                  aria-label={labels.statusFilter}
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option === 'all'
                        ? labels.allStatuses
                        : statusLabel(option, labels, locale)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium">
                {labels.symbolFilter}
                <input
                  name="trading-symbol-filter"
                  autoComplete="off"
                  className="app-field rounded-2xl px-4 py-3 text-sm"
                  value={symbolFilter}
                  onChange={(event) => setSymbolFilter(event.target.value)}
                  placeholder={labels.symbolPlaceholder}
                  aria-label={labels.symbolFilter}
                />
              </label>
              <label className="grid gap-2 text-sm font-medium">
                {labels.sideFilter}
                <select
                  className="app-field rounded-2xl px-4 py-3 text-sm"
                  value={sideFilter}
                  onChange={(event) =>
                    setSideFilter(event.target.value as SideFilter)
                  }
                  aria-label={labels.sideFilter}
                >
                  <option value="all">{labels.allSides}</option>
                  <option value="buy">{labels.buy}</option>
                  <option value="sell">{labels.sell}</option>
                </select>
              </label>
            </div>
          </div>

          <OrderQueue
            orders={rows}
            loading={orders.isLoading}
            error={orders.isError}
            busy={busy}
            rejectReasons={rejectReasons}
            confirmingRejectId={confirmingRejectId}
            onConfirm={handleConfirm}
            onReject={handleReject}
            onExportTicket={handleExportTicket}
            exportingOrderId={exportingOrderId}
            onRejectReasonChange={(orderId, value) =>
              setRejectReasons((current) => ({ ...current, [orderId]: value }))
            }
            instrumentNames={instrumentNames}
          />

          <ManualTicketExportPanel
            result={manualTicketExport.data ?? null}
            executionPreview={manualExecutionPreviewResult}
            executionRecord={manualExecutionRecordResult}
            previewPending={manualExecutionPreview.isPending}
            previewError={
              manualExecutionPreview.isError
                ? getErrorMessage(manualExecutionPreview.error)
                : ''
            }
            recordPending={manualExecutionRecord.isPending}
            recordError={
              manualExecutionRecord.isError
                ? getErrorMessage(manualExecutionRecord.error)
                : ''
            }
            onPreviewExecution={handlePreviewManualExecution}
            onRecordExecution={handleRecordManualExecution}
          />

          {rowError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {rowError}
            </div>
          ) : null}
          {confirmOrder.isError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {getErrorMessage(confirmOrder.error)}
            </div>
          ) : null}
          {rejectOrder.isError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {getErrorMessage(rejectOrder.error)}
            </div>
          ) : null}
          {manualTicketExport.isError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {getErrorMessage(manualTicketExport.error)}
            </div>
          ) : null}
        </div>
      </section>

      <section className="app-terminal-panel rounded-[28px] p-[1px]">
        <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
          <div>
            <div className="app-product-mark">{labels.historyKicker}</div>
            <h2 className="app-card-title mt-1.5">{labels.historyTitle}</h2>
            <p className="app-muted mt-2 text-sm">{labels.historyDetail}</p>
          </div>
          {completedOrders.length === 0 ? (
            <div className="mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
              {labels.noHistory}
            </div>
          ) : (
            <div className="mt-5 grid gap-2">
              {completedOrders.slice(0, 8).map((order) => (
                <AuditRow
                  key={order.order_id}
                  order={order}
                  instrumentNames={instrumentNames}
                />
              ))}
            </div>
          )}
        </div>
      </section>
    </section>
  );
}

function ExecutionAuditPanel({
  orders,
  fills,
  loading,
  error,
  instrumentNames,
  shadowRunPending,
  shadowRunResult,
  paperShadowRun,
  reviewPending,
  reviewResult,
  reviewError,
  onRunShadowReview,
  onAcceptSimulationReview,
}: {
  orders: OrderFact[];
  fills: FillFact[];
  loading: boolean;
  error: boolean;
  instrumentNames: InstrumentNameLookup;
  shadowRunPending: boolean;
  shadowRunResult: { processed_count: number; reused_count: number } | null;
  paperShadowRun: PaperShadowRunSummary | null;
  reviewPending: boolean;
  reviewResult: PaperShadowRunReviewResponse | null;
  reviewError: string;
  onRunShadowReview: () => void;
  onAcceptSimulationReview: () => void;
}) {
  const copy = useCopy();
  const labels = copy.trading.page;
  const ledgerDetailLabels = copy.activity.feed.detailFields;
  const { locale } = usePreferences();
  const latestOrders = orders.slice(0, 4);
  const latestFills = fills.slice(0, 4);
  const needsSimulationReview = paperShadowRunNeedsReview(paperShadowRun);
  const reviewAccepted =
    reviewResult?.review_status === 'accepted_for_manual_confirmation' ||
    paperShadowRun?.review_status === 'accepted_for_manual_confirmation';
  const canRecordSimulationReview = needsSimulationReview && !reviewAccepted;
  const latestPaperShadowEvidenceItems = paperShadowRun?.run_id
    ? latestPaperShadowRunEvidenceItems(paperShadowRun, locale)
    : [];
  const acceptedReviewEvidenceItems = reviewAccepted
    ? paperShadowAcceptedReviewEvidenceItems(
        reviewResult,
        paperShadowRun,
        locale,
      )
    : [];

  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.executionAudit}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.executionAuditTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl break-words text-sm leading-6">
              {labels.executionAuditDetail}
            </p>
          </div>
          <button
            type="button"
            className="app-button-secondary shrink-0 rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={shadowRunPending}
            onClick={onRunShadowReview}
          >
            {shadowRunPending
              ? labels.runningShadowReview
              : labels.runShadowReview}
          </button>
        </div>

        {shadowRunResult ? (
          <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] px-4 py-3 text-sm text-[var(--app-success)]">
            {labels.shadowRunResult(
              shadowRunResult.processed_count,
              shadowRunResult.reused_count,
            )}
          </div>
        ) : null}

        {latestPaperShadowEvidenceItems.length > 0 ? (
          <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 text-sm">
            <div className="font-semibold text-[var(--app-text)]">
              {locale === 'zh'
                ? '最新 paper/shadow 运行'
                : 'Latest paper/shadow run'}
            </div>
            <div className="mt-2 grid min-w-0 gap-1 sm:grid-cols-2">
              {latestPaperShadowEvidenceItems.map((item) => (
                <div
                  className="min-w-0 break-words text-[var(--app-soft)]"
                  key={item}
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {needsSimulationReview || reviewAccepted ? (
          <div className="mt-3 flex min-w-0 flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_9%,transparent)] px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="font-semibold text-[var(--app-text)]">
                {reviewAccepted
                  ? labels.simulationReviewAccepted
                  : labels.simulationReviewNeedsAttention}
              </div>
              {reviewAccepted ? null : (
                <div className="app-muted mt-1 break-words">
                  {labels.simulationReviewNeedsAttentionDetail}
                </div>
              )}
              {acceptedReviewEvidenceItems.length > 0 ? (
                <div className="mt-2 grid min-w-0 gap-1 text-[var(--app-soft)]">
                  {acceptedReviewEvidenceItems.map((item) => (
                    <div className="min-w-0 break-words" key={item}>
                      {item}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
            {canRecordSimulationReview ? (
              <button
                type="button"
                className="app-button-secondary shrink-0 rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                disabled={reviewPending}
                onClick={onAcceptSimulationReview}
              >
                {reviewPending
                  ? labels.recordingSimulationReview
                  : labels.recordSimulationReview}
              </button>
            ) : null}
          </div>
        ) : null}

        {reviewError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {labels.simulationReviewFailed} {reviewError}
          </div>
        ) : null}

        {loading ? (
          <div className="app-muted mt-4 text-sm">{labels.auditLoading}</div>
        ) : error ? (
          <div className="app-error-text mt-4 text-sm">
            {labels.auditLoadFailed}
          </div>
        ) : (
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
            <AuditFactList
              title={labels.orderFacts}
              empty={labels.noOrderFacts}
              rows={latestOrders.map((order) => ({
                id: order.order_id,
                title: formatOrderFactTitle(order, locale, instrumentNames),
                detail: formatOrderFactDetail(
                  order,
                  labels,
                  ledgerDetailLabels,
                  locale,
                  instrumentNames,
                ),
                timestamp: order.timestamp,
              }))}
            />
            <AuditFactList
              title={labels.fills}
              empty={labels.noFills}
              rows={latestFills.map((fill) => ({
                id: fill.fill_id ?? fill.order_id,
                title: `${instrumentDisplayLabel(
                  fill,
                  instrumentNames,
                )} · ${sideLabel(fill.side, locale)}`,
                detail: formatFillDetail(
                  fill,
                  labels,
                  ledgerDetailLabels,
                  locale,
                  instrumentNames,
                ),
                timestamp: fill.timestamp,
              }))}
            />
          </div>
        )}
      </div>
    </section>
  );
}

function AuditFactList({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: Array<{ id: string; title: string; detail: string; timestamp: string }>;
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-4">
      <div className="app-product-mark">{title}</div>
      {rows.length === 0 ? (
        <div className="app-muted mt-3 text-sm">{empty}</div>
      ) : (
        <div className="mt-3 grid gap-2">
          {rows.map((row) => (
            <div
              key={row.id}
              className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] px-3 py-2 text-sm"
            >
              <div className="font-semibold text-[var(--app-text)]">
                {row.title}
              </div>
              <div className="app-muted mt-1 break-words text-xs">
                {row.detail}
              </div>
              <div className="app-muted mt-1 font-mono text-xs tabular-nums">
                {formatTimestamp(row.timestamp)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function manualTicketFormFromResult(
  result: ManualTicketExportResponse,
): ManualTicketOperatorForm | null {
  return (
    result.ticket.operator_form ??
    result.export.content?.operator_form ??
    manualTicketFormFromContentJson(result.export.content_json)
  );
}

function manualTicketFormFromContentJson(
  contentJson: string,
): ManualTicketOperatorForm | null {
  const parsed = parseJsonObject(contentJson);
  const form = parsed?.operator_form;
  return isRecord(form) ? (form as ManualTicketOperatorForm) : null;
}

function formValueText(value: string | number | boolean | null | undefined) {
  if (value === null || value === undefined || value === '') {
    return '--';
  }
  return String(value);
}

function formInputValue(
  value: string | number | boolean | null | undefined,
  fallback = '',
) {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  return String(value);
}

function feeComponentInputValue(
  feeComponents: Record<string, string | number | null | undefined>,
  key: string,
  fallback = '0.00',
) {
  return formInputValue(feeComponents[key], fallback);
}

function formDataText(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === 'string' ? value.trim() : '';
}

function flagText(key: string, value: boolean | null | undefined) {
  return `${key}=${value === true ? 'true' : 'false'}`;
}

function gateLabel(key: string) {
  return key.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function manualExecutionGateRows(
  summary: ControlledBridgeGateSummary | null | undefined,
) {
  const gates = summary?.gates ?? {};
  const keys = summary?.required_gates?.length
    ? summary.required_gates
    : Object.keys(gates);
  return keys
    .map((key) => {
      const gate = gates[key];
      return {
        key,
        label: gateLabel(key),
        status: gate?.status ?? '',
        evidenceRef: gate?.evidence_ref ?? '',
      };
    })
    .filter(
      (item) =>
        item.label || item.status || item.evidenceRef || item.key.trim(),
    );
}

function manualTicketExportReviewLabels(locale: Locale) {
  if (locale === 'zh') {
    return {
      fileName: '导出文件',
      mimeType: 'MIME 类型',
      schema: '导出 Schema',
      format: '导出格式',
      limitations: '导出限制',
    };
  }
  return {
    fileName: 'Export file',
    mimeType: 'MIME type',
    schema: 'Export schema',
    format: 'Export format',
    limitations: 'Export limitations',
  };
}

function PreviewMetric({
  label,
  value,
}: {
  label: string;
  value: string | number | boolean | null | undefined;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
      <div className="app-muted text-xs">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
        {formValueText(value)}
      </div>
    </div>
  );
}

function ManualTicketExportPanel({
  result,
  executionPreview,
  executionRecord,
  previewPending,
  previewError,
  recordPending,
  recordError,
  onPreviewExecution,
  onRecordExecution,
}: {
  result: ManualTicketExportResponse | null;
  executionPreview: ManualExecutionPreviewResponse | null;
  executionRecord: ManualExecutionRecordResponse | null;
  previewPending: boolean;
  previewError: string;
  recordPending: boolean;
  recordError: string;
  onPreviewExecution: (
    orderId: string,
    values: ManualExecutionPreviewRequest,
  ) => Promise<void>;
  onRecordExecution: (
    orderId: string,
    preview: ManualExecutionPreviewResponse,
  ) => Promise<void>;
}) {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  if (!result) {
    return null;
  }
  const exportReviewLabels = manualTicketExportReviewLabels(locale);
  const operatorForm = manualTicketFormFromResult(result);
  const feeTax = operatorForm?.fee_tax_assumptions ?? null;
  const session = operatorForm?.trading_session_constraints ?? null;
  const cashImpact = operatorForm?.cash_impact_preview ?? null;
  const positionCost = operatorForm?.position_cost_preview ?? null;
  const feeComponents = feeTax?.fee_components ?? {};
  const visibleFields =
    operatorForm?.fields?.filter((field) => field.key !== 'account_alias') ??
    [];
  const feeDefault = feeComponentInputValue(
    feeComponents,
    'commission',
    formInputValue(feeTax?.estimated_total_fee, '0.00'),
  );
  const taxDefault = feeComponentInputValue(feeComponents, 'stamp_tax', '0.00');
  const transferFeeDefault = feeComponentInputValue(
    feeComponents,
    'transfer_fee',
    '0.00',
  );
  const executionPreviewResult = executionPreview;
  const preview = executionPreview?.execution_preview ?? null;
  const ledgerDraft = executionPreview?.ledger_entry_draft ?? null;
  const executionPositionCost = executionPreview?.position_cost_preview ?? null;
  const gateSummary =
    executionPreview?.validation?.required_gate_summary ??
    executionRecord?.validation?.required_gate_summary ??
    null;
  const gateRows = manualExecutionGateRows(gateSummary);
  const record = executionRecord;
  const handlePreviewSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    void onPreviewExecution(result.order_id, {
      fill_price: formDataText(formData, 'fill_price'),
      quantity: formDataText(formData, 'quantity'),
      fee: formDataText(formData, 'fee'),
      tax: formDataText(formData, 'tax'),
      transfer_fee: formDataText(formData, 'transfer_fee'),
    });
  };
  const handleRecordExecution = () => {
    if (!executionPreviewResult?.preview_fingerprint) {
      return;
    }
    void onRecordExecution(result.order_id, executionPreviewResult);
  };

  return (
    <div className="mt-4 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">
            {labels.manualTicketExportTitle}
          </div>
          <div className="app-muted mt-1 text-sm">
            {labels.manualTicketExportDetail}
          </div>
        </div>
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-success)_32%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-success)]">
          {labels.manualTicketExportSafety}
        </span>
      </div>
      <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <PreviewMetric
          label={exportReviewLabels.fileName}
          value={result.export.file_name}
        />
        <PreviewMetric
          label={exportReviewLabels.mimeType}
          value={result.export.mime_type}
        />
        <PreviewMetric
          label={exportReviewLabels.schema}
          value={result.export.schema_version}
        />
        <PreviewMetric
          label={exportReviewLabels.format}
          value={result.export.format}
        />
      </div>
      {result.limitations?.length ? (
        <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
          <div className="app-muted text-xs">
            {exportReviewLabels.limitations}
          </div>
          <ul className="mt-2 grid gap-1 text-sm text-[var(--app-soft)]">
            {result.limitations.map((limitation) => (
              <li className="break-words" key={limitation}>
                {limitation}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {operatorForm ? (
        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-3">
          <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
            <div className="app-muted text-xs">
              {labels.manualTicketAccountAlias}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
              {formValueText(operatorForm.account_alias)}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
            <div className="app-muted text-xs">
              {labels.manualTicketEstimatedTotalFee}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
              {formValueText(feeTax?.estimated_total_fee)}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
            <div className="app-muted text-xs">
              {labels.manualTicketTradingSession}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
              {formValueText(session?.allowed_session)}
            </div>
          </div>
        </div>
      ) : null}
      {operatorForm ? (
        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-3">
          <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
            <div className="app-muted text-xs">
              {labels.manualTicketNetCashImpact}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
              {formValueText(cashImpact?.estimated_net_cash_impact)}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
            <div className="app-muted text-xs">
              {labels.manualTicketPositionAfter}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
              {formValueText(positionCost?.estimated_quantity_after)}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
            <div className="app-muted text-xs">
              {labels.manualTicketCostBasisMethod}
            </div>
            <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
              {formValueText(positionCost?.cost_basis_method)}
            </div>
          </div>
        </div>
      ) : null}
      {visibleFields.length ? (
        <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {visibleFields.map((field) => (
            <div
              key={field.key}
              className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_16%,transparent)] px-3 py-2"
            >
              <div className="app-muted text-xs">{field.label}</div>
              <div className="mt-1 break-words text-sm text-[var(--app-text)]">
                {formValueText(field.value)}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)]">
        <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
          <div className="app-muted text-xs">
            {labels.manualTicketExportCopyText}
          </div>
          <div className="mt-1 break-words font-mono text-sm tabular-nums text-[var(--app-text)]">
            {result.export.copy_text || result.ticket.copy_text}
          </div>
        </div>
        <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
          <div className="app-muted text-xs">
            {labels.manualTicketExportPayload}
          </div>
          <pre className="mt-1 max-h-36 min-w-0 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-[var(--app-text)]">
            {result.export.content_json}
          </pre>
        </div>
      </div>
      <form
        key={result.order_id}
        className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-3"
        onSubmit={handlePreviewSubmit}
      >
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {labels.manualExecutionPreviewTitle}
            </div>
            <div className="app-muted mt-1 text-sm">
              {labels.manualExecutionPreviewDetail}
            </div>
          </div>
          <button
            type="submit"
            disabled={previewPending}
            className="app-button-secondary shrink-0 rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          >
            {previewPending
              ? labels.previewingManualExecution
              : labels.previewManualExecution}
          </button>
        </div>
        <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="grid min-w-0 gap-2 text-xs font-medium text-[var(--app-soft)]">
            {labels.manualExecutionFillPrice}
            <input
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              name="fill_price"
              inputMode="decimal"
              defaultValue={formInputValue(result.ticket.limit_price)}
              required
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs font-medium text-[var(--app-soft)]">
            {labels.manualExecutionQuantity}
            <input
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              name="quantity"
              inputMode="decimal"
              defaultValue={formInputValue(result.ticket.quantity)}
              required
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs font-medium text-[var(--app-soft)]">
            {labels.manualExecutionFee}
            <input
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              name="fee"
              inputMode="decimal"
              defaultValue={feeDefault}
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs font-medium text-[var(--app-soft)]">
            {labels.manualExecutionTax}
            <input
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              name="tax"
              inputMode="decimal"
              defaultValue={taxDefault}
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs font-medium text-[var(--app-soft)]">
            {labels.manualExecutionTransferFee}
            <input
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              name="transfer_fee"
              inputMode="decimal"
              defaultValue={transferFeeDefault}
            />
          </label>
        </div>
      </form>
      {previewError ? (
        <div className="app-error-text mt-3 text-sm" role="alert">
          {previewError}
        </div>
      ) : null}
      {preview && ledgerDraft && executionPreviewResult ? (
        <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)] p-3">
          <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <PreviewMetric
              label={labels.manualExecutionGrossAmount}
              value={preview.gross_amount}
            />
            <PreviewMetric
              label={labels.manualExecutionFeeTax}
              value={`${preview.fee} / ${preview.tax}`}
            />
            <PreviewMetric
              label={labels.manualExecutionTransferFee}
              value={preview.transfer_fee}
            />
            <PreviewMetric
              label={labels.manualExecutionNetCashImpact}
              value={preview.net_cash_impact}
            />
          </div>
          {executionPositionCost ? (
            <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
              <div className="app-muted text-xs">
                {labels.manualExecutionPositionPreview}
              </div>
              <div className="mt-2 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <PreviewMetric
                  label={labels.manualExecutionPositionAfter}
                  value={executionPositionCost.estimated_quantity_after}
                />
                <PreviewMetric
                  label={labels.manualExecutionAvgCostAfter}
                  value={executionPositionCost.estimated_avg_cost_after}
                />
                <PreviewMetric
                  label={labels.manualTicketCostBasisMethod}
                  value={executionPositionCost.cost_basis_method}
                />
                <PreviewMetric
                  label={labels.manualExecutionPositionPreviewSource}
                  value={executionPositionCost.source}
                />
              </div>
            </div>
          ) : null}
          <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2">
            <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
              <div className="app-muted text-xs">
                {labels.manualExecutionLedgerDraft}
              </div>
              <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
                {ledgerDraft.amount}
              </div>
              <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                {flagText(
                  'requires_operator_save',
                  ledgerDraft.requires_operator_save,
                )}
              </div>
              <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                {flagText(
                  'does_not_mutate_production_ledger',
                  ledgerDraft.does_not_mutate_production_ledger,
                )}
              </div>
            </div>
            {executionPreviewResult.preview_fingerprint ? (
              <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
                <div className="app-muted text-xs">
                  {labels.manualExecutionPreviewFingerprint}
                </div>
                <div className="mt-1 break-all font-mono text-xs text-[var(--app-text)]">
                  {executionPreviewResult.preview_fingerprint}
                </div>
                {executionPreviewResult.fingerprint_scope ? (
                  <>
                    <div className="app-muted mt-2 text-xs">
                      {labels.manualExecutionFingerprintScope}
                    </div>
                    <div className="mt-1 break-words text-xs text-[var(--app-soft)]">
                      {executionPreviewResult.fingerprint_scope}
                    </div>
                  </>
                ) : null}
              </div>
            ) : null}
            <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
              <div className="app-muted text-xs">
                {labels.manualExecutionSafety}
              </div>
              <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                {flagText(
                  'submitted_to_broker',
                  executionPreviewResult.submitted_to_broker,
                )}
              </div>
              <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                {flagText(
                  'does_not_mutate_production_ledger',
                  executionPreviewResult.does_not_mutate_production_ledger,
                )}
              </div>
            </div>
          </div>
          {gateRows.length ? (
            <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
              <div className="app-muted text-xs">
                {labels.manualExecutionGateSummary}
              </div>
              <div className="mt-2 grid min-w-0 gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {gateRows.map((gate) => (
                  <div className="min-w-0" key={gate.key}>
                    <div className="break-words text-sm font-semibold text-[var(--app-text)]">
                      {gate.label}
                    </div>
                    {gate.status ? (
                      <div className="mt-0.5 break-words font-mono text-xs text-[var(--app-soft)]">
                        {gate.status}
                      </div>
                    ) : null}
                    {gate.evidenceRef ? (
                      <div className="mt-0.5 break-words font-mono text-xs text-[var(--app-soft)]">
                        {gate.evidenceRef}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              <div className="mt-2 break-words font-mono text-xs text-[var(--app-soft)]">
                {flagText(
                  'does_not_authorize_execution',
                  gateSummary?.does_not_authorize_execution,
                )}
              </div>
            </div>
          ) : null}
          {executionPreviewResult.preview_fingerprint ? (
            <div className="mt-3 flex min-w-0 flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={recordPending}
                className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                onClick={handleRecordExecution}
              >
                {recordPending
                  ? labels.recordingManualExecution
                  : labels.recordManualExecution}
              </button>
            </div>
          ) : null}
          {recordError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {recordError}
            </div>
          ) : null}
          {record ? (
            <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] px-3 py-2">
              <div className="font-semibold text-[var(--app-success)]">
                {labels.manualExecutionRecordTitle}
              </div>
              <div className="app-muted mt-1 text-sm">
                {labels.manualExecutionRecordDetail}
              </div>
              <div className="mt-2 grid min-w-0 gap-2 sm:grid-cols-2">
                <PreviewMetric
                  label={labels.manualExecutionGatewayEvent}
                  value={String(record.event_id)}
                />
                <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
                  <div className="app-muted text-xs">
                    {labels.manualExecutionRecordSafety}
                  </div>
                  <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                    {flagText(
                      'submitted_to_broker',
                      record.submitted_to_broker,
                    )}
                  </div>
                  <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                    {flagText(
                      'does_not_mutate_oms',
                      record.does_not_mutate_oms,
                    )}
                  </div>
                  <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                    {flagText(
                      'requires_operator_ledger_save',
                      record.requires_operator_ledger_save,
                    )}
                  </div>
                  <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                    {flagText(
                      'does_not_mutate_production_ledger',
                      record.does_not_mutate_production_ledger,
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-panel-strong rounded-2xl px-4 py-3 shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
        {label}
      </div>
      <div className="mt-1.5 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function OrderQueue({
  orders,
  loading,
  error,
  busy,
  rejectReasons,
  confirmingRejectId,
  onConfirm,
  onReject,
  onExportTicket,
  exportingOrderId,
  onRejectReasonChange,
  instrumentNames,
}: {
  orders: ManualOrder[];
  loading: boolean;
  error: boolean;
  busy: boolean;
  rejectReasons: Record<string, string>;
  confirmingRejectId: string | null;
  onConfirm: (orderId: string) => Promise<void>;
  onReject: (orderId: string) => Promise<void>;
  onExportTicket: (orderId: string) => Promise<void>;
  exportingOrderId: string | null;
  onRejectReasonChange: (orderId: string, value: string) => void;
  instrumentNames: InstrumentNameLookup;
}) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const pageLabels = copy.trading.page;

  if (loading) {
    return <div className="app-muted mt-5 text-sm">{labels.loading}</div>;
  }
  if (error) {
    return (
      <div className="app-error-text mt-5 text-sm">{labels.loadFailed}</div>
    );
  }
  if (orders.length === 0) {
    return (
      <div className="mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="mt-5 min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
      <table className="min-w-[1120px] table-fixed text-left text-sm">
        <thead>
          <tr className="app-kicker border-b border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] text-[11px] uppercase tracking-[0.16em]">
            <th className="w-[130px] px-3 py-3">{labels.symbol}</th>
            <th className="w-[90px] px-3 py-3">{labels.side}</th>
            <th className="w-[120px] px-3 py-3 text-right">
              {labels.quantity}
            </th>
            <th className="w-[120px] px-3 py-3 text-right">{labels.price}</th>
            <th className="w-[140px] px-3 py-3">{pageLabels.statusFilter}</th>
            <th className="w-[240px] px-3 py-3">{labels.riskHint}</th>
            <th className="w-[210px] px-3 py-3">{labels.rejectReason}</th>
            <th className="w-[180px] px-3 py-3">{labels.actions}</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.order_id}
              order={order}
              busy={busy}
              rejectReason={rejectReasons[order.order_id] ?? ''}
              confirmingReject={confirmingRejectId === order.order_id}
              onConfirm={() => onConfirm(order.order_id)}
              onReject={() => onReject(order.order_id)}
              onExportTicket={() => onExportTicket(order.order_id)}
              exportingTicket={exportingOrderId === order.order_id}
              onRejectReasonChange={(value) =>
                onRejectReasonChange(order.order_id, value)
              }
              instrumentNames={instrumentNames}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrderRow({
  order,
  busy,
  rejectReason,
  confirmingReject,
  onConfirm,
  onReject,
  onExportTicket,
  exportingTicket,
  onRejectReasonChange,
  instrumentNames,
}: {
  order: ManualOrder;
  busy: boolean;
  rejectReason: string;
  confirmingReject: boolean;
  onConfirm: () => Promise<void>;
  onReject: () => Promise<void>;
  onExportTicket: () => Promise<void>;
  exportingTicket: boolean;
  onRejectReasonChange: (value: string) => void;
  instrumentNames: InstrumentNameLookup;
}) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const pageLabels = copy.trading.page;
  const { locale } = usePreferences();
  const isPending = order.status === 'pending_confirm';
  const payload = parsePayload(order.payload_json);
  const decisionId =
    order.risk_decision_id ?? payload?.risk_decision_id ?? null;
  const intentId = order.intent_id ?? payload?.intent_id ?? null;
  const displayLabel = instrumentDisplayLabel(order, instrumentNames);
  const publicNote = formatPublicOperationalNote(order.note, locale);

  return (
    <tr className="border-b border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] align-top transition-colors hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)]">
      <td className="px-3 py-4">
        <div className="font-semibold">{displayLabel}</div>
        <div className="app-muted mt-1 text-xs">
          {formatTimestamp(order.timestamp)}
        </div>
      </td>
      <td className="px-3 py-4">
        <SideBadge side={order.side} />
      </td>
      <td className="px-3 py-4 text-right tabular-nums">
        {formatQuantity(order.quantity)}
      </td>
      <td className="px-3 py-4 text-right tabular-nums">
        {formatPrice(order.price)}
      </td>
      <td className="px-3 py-4">
        <StatusBadge status={order.status} />
      </td>
      <td className="px-3 py-4">
        <div className="space-y-1">
          <div className="font-medium">{labels.riskApproved}</div>
          <div className="app-muted break-all text-xs">
            {labels.decisionId}: {decisionId ?? '--'}
          </div>
          <div className="app-muted break-all text-xs">
            {labels.intentId}: {intentId ?? '--'}
          </div>
          {publicNote ? (
            <div className="app-muted text-xs">{publicNote}</div>
          ) : null}
        </div>
      </td>
      <td className="px-3 py-4">
        <input
          name={`reject-reason-${order.order_id}`}
          autoComplete="off"
          value={rejectReason}
          onChange={(event) => onRejectReasonChange(event.target.value)}
          placeholder={labels.rejectReasonPlaceholder}
          className="app-field w-full rounded-2xl px-4 py-2.5 text-sm"
          aria-label={`${labels.rejectReason}: ${displayLabel}`}
          disabled={!isPending}
        />
      </td>
      <td className="px-3 py-4">
        {isPending ? (
          <div className="grid gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void onConfirm()}
              className="app-button-primary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              aria-label={`${labels.confirm}: ${displayLabel}`}
            >
              {labels.confirm}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onReject()}
              className="app-button-secondary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              aria-label={`${labels.reject}: ${displayLabel}`}
            >
              {confirmingReject ? pageLabels.rejectConfirm : labels.reject}
            </button>
          </div>
        ) : order.status === 'confirmed' ? (
          <button
            type="button"
            disabled={exportingTicket}
            onClick={() => void onExportTicket()}
            className="app-button-secondary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
            aria-label={`${labels.exportTicket}: ${displayLabel}`}
          >
            {exportingTicket ? labels.exportingTicket : labels.exportTicket}
          </button>
        ) : (
          <div className="app-muted text-xs">{pageLabels.statusCheck}</div>
        )}
      </td>
    </tr>
  );
}

function SideBadge({ side }: { side: string }) {
  const copy = useCopy();
  const labels = copy.trading.page;
  const { locale } = usePreferences();
  const normalized = side.toLowerCase();
  const isBuy = normalized === 'buy';

  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        isBuy
          ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]'
          : 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]'
      }`}
    >
      {isBuy
        ? labels.buy
        : normalized === 'sell'
          ? labels.sell
          : formatPublicStatus(side, locale)}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  const warning = status === 'pending_confirm';
  const danger = status === 'rejected' || status === 'canceled';
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        warning
          ? 'bg-[var(--app-warning-bg)] text-[var(--app-warning)] ring-1 ring-[var(--app-warning-border)]'
          : danger
            ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]'
            : 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]'
      }`}
    >
      {statusLabel(status, labels, locale)}
    </span>
  );
}

function AuditRow({
  order,
  instrumentNames,
}: {
  order: ManualOrder;
  instrumentNames: InstrumentNameLookup;
}) {
  const { locale } = usePreferences();
  const labels = useCopy().trading.page;
  const displayLabel = instrumentDisplayLabel(order, instrumentNames);
  const publicNote =
    formatPublicOperationalNote(order.note, locale) ?? labels.noPublicAuditNote;
  return (
    <div className="grid gap-2 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 text-sm sm:grid-cols-[120px_90px_minmax(0,1fr)_160px] sm:items-center">
      <div className="font-semibold">{displayLabel}</div>
      <SideBadge side={order.side} />
      <div className="app-muted min-w-0 truncate text-xs">{publicNote}</div>
      <div className="text-right text-xs tabular-nums text-[var(--app-muted)]">
        {formatTimestamp(order.updated_at)}
      </div>
    </div>
  );
}
