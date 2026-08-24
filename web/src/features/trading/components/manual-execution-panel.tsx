import { type FormEvent } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import type {
  ManualExecutionPreviewRequest,
  ManualExecutionPreviewResponse,
  ManualExecutionRecordResponse,
  ManualTicketExportResponse,
} from '../api';
import { ManualExecutionPreviewPanel } from './manual-execution-preview-panel';
import {
  feeComponentInputValue,
  formDataText,
  formInputValue,
  manualTicketFormFromResult,
} from './manual-ticket-model';

export function ManualExecutionPanel({
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
  result: ManualTicketExportResponse;
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
  const operatorForm = manualTicketFormFromResult(result);
  const feeTax = operatorForm?.fee_tax_assumptions ?? null;
  const feeComponents = feeTax?.fee_components ?? {};
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

  return (
    <>
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
      <ManualExecutionPreviewPanel
        executionPreview={executionPreview}
        executionRecord={executionRecord}
        recordPending={recordPending}
        recordError={recordError}
        onRecordExecution={(preview) =>
          onRecordExecution(result.order_id, preview)
        }
      />
    </>
  );
}
