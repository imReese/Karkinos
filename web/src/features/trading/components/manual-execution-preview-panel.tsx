import type {
  ManualExecutionPreviewResponse,
  ManualExecutionRecordResponse,
} from '../api';
import { useCopy } from '../../../shared/i18n/context';
import {
  ControlledBridgeGateSummaryBlock,
  flagText,
  manualExecutionGateRows,
  PreviewMetric,
} from './manual-ticket-model';

export function ManualExecutionPreviewPanel({
  executionPreview,
  executionRecord,
  recordPending,
  recordError,
  onRecordExecution,
}: {
  executionPreview: ManualExecutionPreviewResponse | null;
  executionRecord: ManualExecutionRecordResponse | null;
  recordPending: boolean;
  recordError: string;
  onRecordExecution: (preview: ManualExecutionPreviewResponse) => Promise<void>;
}) {
  const labels = useCopy().trading.page;
  const executionPreviewResult = executionPreview;
  const preview = executionPreview?.execution_preview ?? null;
  const ledgerDraft = executionPreview?.ledger_entry_draft ?? null;
  const executionPositionCost = executionPreview?.position_cost_preview ?? null;
  if (!preview || !ledgerDraft || !executionPreviewResult) {
    return null;
  }
  const gateSummary =
    executionPreview.validation?.required_gate_summary ??
    executionRecord?.validation?.required_gate_summary ??
    null;
  const gateRows = manualExecutionGateRows(gateSummary);
  const previewSafetyValue = (key: string) => {
    const value = executionPreview.safety?.[key];
    return typeof value === 'boolean' ? value : undefined;
  };
  const previewSafetyRows = [
    {
      key: 'broker_submission_enabled',
      value: previewSafetyValue('broker_submission_enabled'),
    },
    {
      key: 'submitted_to_broker',
      value:
        previewSafetyValue('submitted_to_broker') ??
        executionPreview.submitted_to_broker,
    },
    {
      key: 'requires_human_broker_entry',
      value: previewSafetyValue('requires_human_broker_entry'),
    },
    {
      key: 'requires_operator_save',
      value:
        previewSafetyValue('requires_operator_save') ??
        ledgerDraft.requires_operator_save,
    },
    {
      key: 'does_not_mutate_oms',
      value: previewSafetyValue('does_not_mutate_oms'),
    },
    {
      key: 'does_not_mutate_production_ledger',
      value:
        previewSafetyValue('does_not_mutate_production_ledger') ??
        executionPreview.does_not_mutate_production_ledger,
    },
  ].filter((row) => typeof row.value === 'boolean');
  const record = executionRecord;
  const handleRecordExecution = () => {
    if (!executionPreview.preview_fingerprint) {
      return;
    }
    void onRecordExecution(executionPreview);
  };

  return (
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
              label={labels.manualExecutionCurrentQuantity}
              value={executionPositionCost.current_quantity}
            />
            <PreviewMetric
              label={labels.manualExecutionCurrentAvgCost}
              value={executionPositionCost.current_avg_cost}
            />
            <PreviewMetric
              label={labels.manualExecutionCurrentMarketValue}
              value={executionPositionCost.current_market_value}
            />
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
          {previewSafetyRows.map((row) => (
            <div
              className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]"
              key={row.key}
            >
              {flagText(row.key, row.value)}
            </div>
          ))}
        </div>
      </div>
      {gateRows.length ? (
        <ControlledBridgeGateSummaryBlock
          gateRows={gateRows}
          gateSummary={gateSummary}
          title={labels.manualExecutionGateSummary}
        />
      ) : null}
      {executionPreviewResult.limitations?.length ? (
        <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
          <div className="app-muted text-xs">
            {labels.manualExecutionLimitations}
          </div>
          <ul className="mt-2 grid gap-1 text-sm text-[var(--app-soft)]">
            {executionPreviewResult.limitations.map((limitation) => (
              <li className="break-words" key={limitation}>
                {limitation}
              </li>
            ))}
          </ul>
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
                {flagText('submitted_to_broker', record.submitted_to_broker)}
              </div>
              <div className="mt-1 break-words font-mono text-xs text-[var(--app-soft)]">
                {flagText('does_not_mutate_oms', record.does_not_mutate_oms)}
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
          {record.limitations?.length ? (
            <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
              <div className="app-muted text-xs">
                {labels.manualExecutionLimitations}
              </div>
              <ul className="mt-2 grid gap-1 text-sm text-[var(--app-soft)]">
                {record.limitations.map((limitation) => (
                  <li className="break-words" key={limitation}>
                    {limitation}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
