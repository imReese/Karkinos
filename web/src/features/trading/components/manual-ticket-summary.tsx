import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { ManualTicketExportResponse } from '../api';
import {
  ControlledBridgeGateSummaryBlock,
  formValueText,
  manualExecutionGateRows,
  manualTicketExportReviewLabels,
  manualTicketFormFromResult,
  manualTicketReconciliationHandoffLabels,
  PreviewMetric,
} from './manual-ticket-model';

export function ManualTicketSummary({
  result,
}: {
  result: ManualTicketExportResponse;
}) {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  const exportReviewLabels = manualTicketExportReviewLabels(locale);
  const handoffLabels = manualTicketReconciliationHandoffLabels(locale);
  const operatorForm = manualTicketFormFromResult(result);
  const feeTax = operatorForm?.fee_tax_assumptions ?? null;
  const session = operatorForm?.trading_session_constraints ?? null;
  const cashImpact = operatorForm?.cash_impact_preview ?? null;
  const positionCost = operatorForm?.position_cost_preview ?? null;
  const visibleFields =
    operatorForm?.fields?.filter((field) => field.key !== 'account_alias') ??
    [];
  const ticketGateSummary = result.validation?.required_gate_summary ?? null;
  const ticketGateRows = manualExecutionGateRows(ticketGateSummary);

  return (
    <>
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
      <div
        className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-3"
        data-testid="manual-ticket-reconciliation-handoff"
      >
        <div className="font-semibold text-[var(--app-text)]">
          {handoffLabels.title}
        </div>
        <div className="app-muted mt-1 text-sm leading-6">
          {handoffLabels.detail}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold"
            href="/account-truth"
          >
            {handoffLabels.importEvidence}
          </a>
          <a
            className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold"
            href="/decision"
          >
            {handoffLabels.reviewReconciliation}
          </a>
        </div>
      </div>
      {ticketGateRows.length ? (
        <ControlledBridgeGateSummaryBlock
          gateRows={ticketGateRows}
          gateSummary={ticketGateSummary}
          title={labels.manualExecutionGateSummary}
        />
      ) : null}
    </>
  );
}
