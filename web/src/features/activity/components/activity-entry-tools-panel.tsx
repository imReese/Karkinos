import type { RefObject } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { ControlledActionZone } from '../../../shared/ui/workbench';
import type { TradePreview } from '../api';
import { CashFlowForm, type CashFlowFormValues } from './cash-flow-form';
import { DividendForm, type DividendFormValues } from './dividend-form';
import {
  FundBatchForm,
  type FundBatchCandidate,
  type FundBatchFormValues,
} from './fund-batch-form';
import {
  ManualAdjustmentForm,
  type ManualAdjustmentFormValues,
} from './manual-adjustment-form';
import { TradeForm, type TradeFormValues } from './trade-form';

export type ActivityEntryTool =
  'trade' | 'fundBatch' | 'cashFlow' | 'dividend' | 'adjustment';

export type ActivityEntryDrafts = {
  trade?: TradeFormValues;
  fundBatch?: FundBatchFormValues;
  cashFlow?: CashFlowFormValues;
  dividend?: DividendFormValues;
  adjustment?: ManualAdjustmentFormValues;
};

export function ActivityEntryToolsPanel({
  activeEntryTool,
  entryDrafts,
  entryFormVersions,
  candidates,
  commissionSettings,
  createAdjustmentPending,
  createCashFlowPending,
  createDividendPending,
  createTradePending,
  loadingCandidates,
  onAdjustmentSubmit,
  onCashFlowSubmit,
  onDividendSubmit,
  onFundBatchSubmit,
  onSelectEntryTool,
  onTradePreviewChange,
  onTradeSubmit,
  previewError,
  previewLoading,
  tradePreview,
}: {
  activeEntryTool: ActivityEntryTool;
  entryDrafts: RefObject<ActivityEntryDrafts>;
  entryFormVersions: Partial<Record<ActivityEntryTool, number>>;
  candidates: FundBatchCandidate[];
  commissionSettings?: {
    stock_rate: number;
    stock_min_commission: number;
  };
  createAdjustmentPending: boolean;
  createCashFlowPending: boolean;
  createDividendPending: boolean;
  createTradePending: boolean;
  loadingCandidates: boolean;
  onAdjustmentSubmit: (values: ManualAdjustmentFormValues) => Promise<void>;
  onCashFlowSubmit: (values: CashFlowFormValues) => Promise<void>;
  onDividendSubmit: (values: DividendFormValues) => Promise<void>;
  onFundBatchSubmit: (values: FundBatchFormValues) => Promise<void>;
  onSelectEntryTool: (tool: ActivityEntryTool) => void;
  onTradePreviewChange: (values: TradeFormValues) => void;
  onTradeSubmit: (values: TradeFormValues) => Promise<void>;
  previewError: boolean;
  previewLoading: boolean;
  tradePreview: TradePreview | null;
}) {
  const copy = useCopy();
  const tools: Array<{ key: ActivityEntryTool; label: string }> = [
    { key: 'trade', label: copy.activity.forms.trade.title },
    { key: 'cashFlow', label: copy.activity.forms.cashFlow.title },
    { key: 'dividend', label: copy.activity.forms.dividend.title },
    { key: 'adjustment', label: copy.activity.forms.adjustment.title },
    { key: 'fundBatch', label: copy.activity.forms.fundBatch.title },
  ];

  return (
    <ControlledActionZone
      title={copy.activity.entryTools.boundaryTitle}
      description={copy.activity.entryTools.boundary}
      layout="stack"
      tone="info"
      className="min-w-0"
    >
      <div className="min-w-0 w-full">
        <div
          aria-label={copy.activity.entryTools.ariaLabel}
          className="grid min-w-0 grid-cols-2 gap-1"
          role="group"
        >
          {tools.map((tool) => {
            const isSelected = activeEntryTool === tool.key;
            return (
              <button
                key={tool.key}
                aria-pressed={isSelected}
                className={`min-h-10 min-w-0 rounded-[var(--app-radius-control)] border px-2.5 py-1.5 text-left text-xs font-semibold transition-colors xl:min-h-8 ${
                  isSelected
                    ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-hover)]'
                    : 'border-transparent bg-transparent text-[var(--app-text-tertiary)] hover:border-[var(--app-border)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)]'
                }`}
                onClick={() => onSelectEntryTool(tool.key)}
                type="button"
              >
                {tool.label}
              </button>
            );
          })}
        </div>
        <div className="mt-4 min-w-0 border-t border-[var(--app-divider)] pt-4">
          {activeEntryTool === 'trade' ? (
            <TradeForm
              key={entryFormVersions.trade ?? 0}
              initialDraft={entryDrafts.current.trade}
              onDraftSave={(values) => {
                entryDrafts.current.trade = values;
              }}
              onSubmit={onTradeSubmit}
              pending={createTradePending}
              tradePreview={tradePreview}
              previewLoading={previewLoading}
              previewError={previewError}
              onPreviewChange={onTradePreviewChange}
              commissionSettings={commissionSettings}
            />
          ) : null}
          {activeEntryTool === 'fundBatch' ? (
            <FundBatchForm
              key={entryFormVersions.fundBatch ?? 0}
              initialDraft={entryDrafts.current.fundBatch}
              onDraftSave={(values) => {
                entryDrafts.current.fundBatch = values;
              }}
              candidates={candidates}
              loadingCandidates={loadingCandidates}
              onSubmit={onFundBatchSubmit}
              pending={createTradePending}
            />
          ) : null}
          {activeEntryTool === 'cashFlow' ? (
            <CashFlowForm
              key={entryFormVersions.cashFlow ?? 0}
              initialDraft={entryDrafts.current.cashFlow}
              onDraftSave={(values) => {
                entryDrafts.current.cashFlow = values;
              }}
              onSubmit={onCashFlowSubmit}
              pending={createCashFlowPending}
            />
          ) : null}
          {activeEntryTool === 'dividend' ? (
            <DividendForm
              key={entryFormVersions.dividend ?? 0}
              initialDraft={entryDrafts.current.dividend}
              onDraftSave={(values) => {
                entryDrafts.current.dividend = values;
              }}
              onSubmit={onDividendSubmit}
              pending={createDividendPending}
            />
          ) : null}
          {activeEntryTool === 'adjustment' ? (
            <ManualAdjustmentForm
              key={entryFormVersions.adjustment ?? 0}
              initialDraft={entryDrafts.current.adjustment}
              onDraftSave={(values) => {
                entryDrafts.current.adjustment = values;
              }}
              onSubmit={onAdjustmentSubmit}
              pending={createAdjustmentPending}
            />
          ) : null}
        </div>
      </div>
    </ControlledActionZone>
  );
}
