import { useMemo, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useBrokerConnectorSoakPromotionStatusQuery,
  useOperationsTodayQuery,
  useReviewPaperShadowRunMutation,
} from '../operations-boundary';
import { usePositionsQuery } from '../portfolio-boundary';
import {
  useConfirmManualOrderMutation,
  useDailyShadowRunMutation,
  useFillFactsQuery,
  useManualExecutionPreviewMutation,
  useManualExecutionRecordMutation,
  useManualOrdersQuery,
  useManualTicketExportMutation,
  useOrderFactsQuery,
  useRejectManualOrderMutation,
  type ManualExecutionPreviewRequest,
  type ManualExecutionPreviewResponse,
  type ManualOrderStatus,
} from '../api';
import {
  getLatestOrderTimestamp,
  type SideFilter,
} from './trading-execution-format';

export function useTradingPageController() {
  const orderLabels = useCopy().trading.orders;
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
  const brokerSoakPromotion = useBrokerConnectorSoakPromotionStatusQuery();
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
  const paperShadowRun = operationsToday.data?.paper_shadow ?? null;
  const brokerAdapterReadiness =
    operationsToday.data?.broker_adapter_readiness ?? null;

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
    } catch {
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

  return {
    status,
    setStatus,
    symbolFilter,
    setSymbolFilter,
    sideFilter,
    setSideFilter,
    rejectReasons,
    setRejectReasons,
    rowError,
    confirmingRejectId,
    exportingOrderId,
    orders,
    orderFacts,
    fillFacts,
    operationsToday,
    brokerSoakPromotion,
    shadowRun,
    reviewShadowRun,
    confirmOrder,
    rejectOrder,
    manualTicketExport,
    manualExecutionPreview,
    manualExecutionRecord,
    rows,
    completedOrders,
    counts,
    latestTimestamp,
    manualExecutionPreviewResult,
    manualExecutionRecordResult,
    instrumentNames,
    paperShadowRun,
    brokerAdapterReadiness,
    busy: confirmOrder.isPending || rejectOrder.isPending,
    handleConfirm,
    handleReject,
    handleExportTicket,
    handlePreviewManualExecution,
    handleRecordManualExecution,
    handleAcceptSimulationReview,
  };
}

export type TradingPageController = ReturnType<typeof useTradingPageController>;
