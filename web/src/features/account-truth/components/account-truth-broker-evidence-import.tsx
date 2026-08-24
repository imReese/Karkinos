import { useState, type ChangeEvent } from 'react';

import {
  ControlledActionZone,
  EvidenceIdentityDisclosure,
  EvidenceState,
  StatusBadge,
} from '../../../shared/ui/workbench';
import {
  useBrokerStatementImportMutation,
  useBrokerStatementPreviewMutation,
  type BrokerStatementCollectorStatus,
  type BrokerStatementPreview,
} from '../api';
import { CiticHistoryXlsPreviewTool } from './account-truth-citic-review';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode, statusTone } from './account-truth-review-format';

export function BrokerEvidenceImportWizard({
  locale,
  collectorStatus,
  collectorStatusIsError,
  onImported,
}: {
  locale: 'en' | 'zh';
  collectorStatus: BrokerStatementCollectorStatus | undefined;
  collectorStatusIsError: boolean;
  onImported: (importRunId: string) => void;
}) {
  const text = labels[locale];
  const [sourceName, setSourceName] = useState('local-broker-statement.csv');
  const [content, setContent] = useState('');
  const [fileMessage, setFileMessage] = useState<string | null>(null);
  const previewMutation = useBrokerStatementPreviewMutation();
  const importMutation = useBrokerStatementImportMutation();
  const preview = previewMutation.data ?? importMutation.data?.preview ?? null;
  const canSubmit = content.trim().length > 0 && sourceName.trim().length > 0;
  const previewIsBlocked = preview?.validation_status === 'blocked';

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) {
      return;
    }
    setFileMessage(null);
    setSourceName(file.name || 'local-broker-statement.csv');
    try {
      setContent(await file.text());
      previewMutation.reset();
      importMutation.reset();
    } catch {
      setFileMessage(text.noFileContent);
    }
  }

  function previewStatement() {
    if (!canSubmit) {
      setFileMessage(text.noFileContent);
      return;
    }
    setFileMessage(null);
    previewMutation.mutate({
      content,
      source_name: sourceName,
    });
  }

  function importStatement() {
    if (!canSubmit) {
      setFileMessage(text.noFileContent);
      return;
    }
    setFileMessage(null);
    importMutation.mutate(
      {
        content,
        source_name: sourceName,
      },
      {
        onSuccess: (result) => {
          onImported(result.import_run.import_run_id);
        },
      },
    );
  }

  return (
    <div className="grid gap-5">
      <CiticHistoryXlsPreviewTool locale={locale} />
      <ControlledActionZone
        title={text.importWizardTitle}
        description={text.importWizardBody}
        evidence={text.importBoundary}
        layout="stack"
        tone="info"
      >
        <div
          className="w-full min-w-0"
          data-testid="account-truth-import-wizard"
        >
          <div className="app-product-mark">{text.importWizardKicker}</div>
          <BrokerStatementCollectorCallout
            locale={locale}
            status={collectorStatus}
            isError={collectorStatusIsError}
          />
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.sourceName}
              <input
                className="min-h-10 w-full rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                value={sourceName}
                onChange={(event) => setSourceName(event.currentTarget.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.chooseFile}
              <input
                accept=".csv,text/csv,text/plain"
                className="min-h-10 w-full rounded-[var(--app-radius-control)] border border-dashed border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                type="file"
                onChange={handleFileChange}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
              {text.csvContent}
              <textarea
                className="min-h-28 w-full resize-y rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 font-mono text-xs text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                value={content}
                onChange={(event) => {
                  setContent(event.currentTarget.value);
                  previewMutation.reset();
                  importMutation.reset();
                }}
              />
            </label>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!canSubmit || previewMutation.isPending}
              type="button"
              onClick={previewStatement}
            >
              {text.previewImport}
            </button>
            <button
              className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
              disabled={
                !canSubmit ||
                previewIsBlocked ||
                importMutation.isPending ||
                previewMutation.isPending
              }
              type="button"
              onClick={importStatement}
            >
              {text.confirmImport}
            </button>
          </div>
          {fileMessage ? (
            <EvidenceState
              className="mt-3"
              kind="partial"
              title={fileMessage}
            />
          ) : null}
          {preview ? (
            <BrokerStatementPreviewPanel preview={preview} locale={locale} />
          ) : null}
          {importMutation.isSuccess ? (
            <EvidenceState
              className="mt-3"
              kind="ready"
              title={`${text.importReady}: ${importMutation.data.import_run.source_name}`}
            />
          ) : null}
          {previewMutation.isError || importMutation.isError ? (
            <EvidenceState
              className="mt-3"
              kind="error"
              title={text.importFailed}
            />
          ) : null}
        </div>
      </ControlledActionZone>
    </div>
  );
}

function BrokerStatementCollectorCallout({
  locale,
  status,
  isError,
}: {
  locale: 'en' | 'zh';
  status: BrokerStatementCollectorStatus | undefined;
  isError: boolean;
}) {
  const text = labels[locale];
  const tone = statusTone(isError ? 'error' : (status?.state ?? 'checking'));
  const body = isError
    ? text.collectorUnavailable
    : status
      ? collectorStateBody(status, locale)
      : text.collectorLoading;

  return (
    <div
      className="mt-4 border-y border-[var(--app-divider)] py-3"
      data-testid="broker-statement-collector-status"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-[var(--app-text)]">
          {text.collectorTitle}
        </span>
        <StatusBadge tone={tone}>
          {collectorStateLabel(status?.state, locale)}
        </StatusBadge>
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
        {body}
      </p>
      {status?.configured_path ? (
        <EvidenceIdentityDisclosure
          className="app-button-ghost mt-2 inline-flex min-h-10 items-center rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold text-[var(--app-text-secondary)]"
          triggerLabel={text.openEvidence}
          title={text.collectorTitle}
          description={body}
          closeLabel={text.closeEvidence}
          copyLabel={text.copyEvidence}
          copiedLabel={text.copiedEvidence}
          fields={[
            {
              label: text.collectorPath,
              value: status.configured_path,
              mono: true,
            },
            ...(status.import_run_id
              ? [
                  {
                    label: text.collectorRun,
                    value: status.import_run_id,
                    mono: true,
                  },
                ]
              : []),
          ]}
        />
      ) : null}
      <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
        {text.collectorFallback}
      </p>
    </div>
  );
}

function collectorStateLabel(
  state: BrokerStatementCollectorStatus['state'] | undefined,
  locale: 'en' | 'zh',
) {
  const values: Record<
    BrokerStatementCollectorStatus['state'],
    { en: string; zh: string }
  > = {
    disabled: { en: 'Disabled', zh: '未启用' },
    waiting_for_file: { en: 'Waiting for file', zh: '等待文件' },
    pending_stability: { en: 'Waiting for stable write', zh: '等待写入稳定' },
    imported: { en: 'Evidence staged', zh: '证据已暂存' },
    unchanged: { en: 'Up to date', zh: '已是最新' },
    blocked: { en: 'Blocked', zh: '已阻断' },
    error: { en: 'Error', zh: '异常' },
  };
  return state
    ? values[state][locale]
    : locale === 'zh'
      ? '检查中'
      : 'Checking';
}

function collectorStateBody(
  status: BrokerStatementCollectorStatus,
  locale: 'en' | 'zh',
) {
  const rows = status.row_count ?? 0;
  const values: Record<
    BrokerStatementCollectorStatus['state'],
    { en: string; zh: string }
  > = {
    disabled: {
      en: 'Disabled by startup configuration; no local file is read.',
      zh: '启动配置未启用，不会读取任何本地文件。',
    },
    waiting_for_file: {
      en: 'The configured file is absent; previous staged evidence is preserved.',
      zh: '配置文件当前不存在；此前已暂存证据仍会保留。',
    },
    pending_stability: {
      en: 'A change was detected. Collection waits for a complete stable file.',
      zh: '检测到文件变化，正在等待完整写入并保持稳定。',
    },
    imported: {
      en: `${rows} rows were staged for reconciliation review.`,
      zh: `已暂存 ${rows} 行证据，等待对账复核。`,
    },
    unchanged: {
      en: 'The fingerprint is unchanged; no duplicate run was created.',
      zh: '文件指纹未变化，没有创建重复导入批次。',
    },
    blocked: {
      en: 'Validation failed closed. No production account fact was changed.',
      zh: '校验已 fail closed，生产账户事实没有被修改。',
    },
    error: {
      en: 'The read-only collection attempt failed; no ledger action was taken.',
      zh: '只读采集失败；未执行任何账本操作。',
    },
  };
  return values[status.state][locale];
}

function BrokerStatementPreviewPanel({
  preview,
  locale,
}: {
  preview: BrokerStatementPreview;
  locale: 'en' | 'zh';
}) {
  const text = labels[locale];
  return (
    <div className="mt-4 border-y border-[var(--app-divider)] py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {text.previewReady}
          </div>
          <div className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {preview.source_name}
          </div>
        </div>
        <StatusBadge tone={statusTone(preview.validation_status)}>
          {formatCode(preview.validation_status, locale, 'status')}
        </StatusBadge>
      </div>
      <div className="mt-3 grid grid-cols-3 divide-x divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
        <Metric
          label={text.validRows}
          value={String(preview.valid_row_count)}
        />
        <Metric
          label={text.invalidRows}
          value={String(preview.invalid_row_count)}
        />
        <Metric
          label={text.duplicateRows}
          value={String(preview.duplicate_row_count)}
        />
      </div>
      {preview.errors.length > 0 ? (
        <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {preview.errors.slice(0, 3).map((error) => (
            <div
              key={`${error.row_number ?? 'file'}-${error.code}`}
              className="border-l-2 border-[var(--app-danger-indicator)] px-3 py-2 text-xs font-medium text-[var(--app-danger-text)]"
            >
              {error.row_number ? `Row ${error.row_number}: ` : ''}
              {formatCode(error.code, locale, 'code')}
            </div>
          ))}
        </div>
      ) : null}
      {preview.events_preview.length > 0 ? (
        <div className="mt-3">
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {text.eventPreview}
          </div>
          <div className="mt-2 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {preview.events_preview.slice(0, 3).map((event) => (
              <div
                key={`${event.row_number}-${event.event_id}`}
                className="grid min-w-0 gap-1 px-3 py-2 text-xs"
              >
                <div className="font-semibold text-[var(--app-text)]">
                  {formatCode(event.event_type, locale, 'code')}
                  {event.symbol ? ` · ${event.symbol}` : ''}
                </div>
                <div className="text-[var(--app-text-secondary)]">
                  {event.currency} {event.net_amount}
                  {event.cash_balance ? ` · cash ${event.cash_balance}` : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="app-type-micro truncate font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div className="mt-0.5 text-base font-semibold text-[var(--app-text)] tabular-nums">
        {value}
      </div>
    </div>
  );
}
