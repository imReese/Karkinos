import { type Locale } from '../../../shared/preferences/context';
import type {
  ControlledBridgeGateSummary,
  ManualTicketExportResponse,
  ManualTicketOperatorForm,
} from '../api';
import { isRecord, parseJsonObject } from './trading-execution-format';

export function manualTicketFormFromResult(
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

export function formValueText(
  value: string | number | boolean | null | undefined,
) {
  if (value === null || value === undefined || value === '') {
    return '--';
  }
  return String(value);
}

export function formInputValue(
  value: string | number | boolean | null | undefined,
  fallback = '',
) {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  return String(value);
}

export function feeComponentInputValue(
  feeComponents: Record<string, string | number | null | undefined>,
  key: string,
  fallback = '0.00',
) {
  return formInputValue(feeComponents[key], fallback);
}

export function formDataText(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === 'string' ? value.trim() : '';
}

export function flagText(key: string, value: boolean | null | undefined) {
  return `${key}=${value === true ? 'true' : 'false'}`;
}

function gateLabel(key: string) {
  return key.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

export function manualExecutionGateRows(
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

export function manualTicketExportReviewLabels(locale: Locale) {
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

export function manualTicketReconciliationHandoffLabels(locale: Locale) {
  if (locale === 'zh') {
    return {
      title: '券商流水与执行对账交接',
      detail:
        '在券商端手工执行后，先导入券商流水作为账户事实证据，再复核执行对账。此交接不会自动写账、改变持仓或提交券商订单。',
      importEvidence: '导入券商流水',
      reviewReconciliation: '复核执行对账',
    };
  }
  return {
    title: 'Broker evidence and reconciliation handoff',
    detail:
      'After manual broker entry, import the broker statement as account-truth evidence, then review execution reconciliation. This handoff does not write the ledger, change positions, or submit broker orders.',
    importEvidence: 'Import broker statement',
    reviewReconciliation: 'Review execution reconciliation',
  };
}

export function PreviewMetric({
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
export function ControlledBridgeGateSummaryBlock({
  gateRows,
  gateSummary,
  title,
}: {
  gateRows: ReturnType<typeof manualExecutionGateRows>;
  gateSummary: ControlledBridgeGateSummary | null | undefined;
  title: string;
}) {
  return (
    <div className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] px-3 py-2">
      <div className="app-muted text-xs">{title}</div>
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
  );
}
