import type {
  ManualExecutionPreviewRequest,
  ManualExecutionPreviewResponse,
  ManualExecutionRecordResponse,
  ManualTicketExportResponse,
} from '../api';
import { ManualExecutionPanel } from './manual-execution-panel';
import { ManualTicketSummary } from './manual-ticket-summary';

export function ManualTicketExportPanel({
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
  if (!result) {
    return null;
  }

  return (
    <div className="mt-4 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
      <ManualTicketSummary result={result} />
      <ManualExecutionPanel
        result={result}
        executionPreview={executionPreview}
        executionRecord={executionRecord}
        previewPending={previewPending}
        previewError={previewError}
        recordPending={recordPending}
        recordError={recordError}
        onPreviewExecution={onPreviewExecution}
        onRecordExecution={onRecordExecution}
      />
    </div>
  );
}
