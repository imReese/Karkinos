import { useEffect, useState } from 'react';

import { formatCurrency } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../../../shared/public-labels';
import type {
  BacktestAttributionPreviewResponse,
  BacktestPaperShadowPreviewRequest,
  BacktestPaperShadowPreviewResponse,
  BacktestRiskPreviewRequest,
  BacktestRiskPreviewResponse,
  StrategySignalPreviewOutput,
  StrategySignalPreviewResponse,
} from '../api';
import { MetadataItem } from './strategy-metadata-panel';
import {
  AttributionPreviewResult,
  PaperShadowPreviewResult,
} from './strategy-preview-results';
import { isPositiveNumber } from './backtest-page-model';

export function StrategySignalPreviewPanel({
  preview,
  loading,
  error,
  singleAsset,
  onRiskPreview,
  onPaperShadowPreview,
  riskPreviewResult,
  riskPreviewLoading,
  riskPreviewError,
  paperShadowPreviewResult,
  paperShadowPreviewLoading,
  paperShadowPreviewError,
  attributionPreviewResult,
  attributionPreviewLoading,
  attributionPreviewError,
}: {
  preview: StrategySignalPreviewResponse | null;
  loading: boolean;
  error: boolean;
  singleAsset: { symbol: string; asset_class: string } | null;
  onRiskPreview: (payload: BacktestRiskPreviewRequest) => void;
  onPaperShadowPreview: (payload: BacktestPaperShadowPreviewRequest) => void;
  riskPreviewResult: BacktestRiskPreviewResponse | null;
  riskPreviewLoading: boolean;
  riskPreviewError: boolean;
  paperShadowPreviewResult: BacktestPaperShadowPreviewResponse | null;
  paperShadowPreviewLoading: boolean;
  paperShadowPreviewError: boolean;
  attributionPreviewResult: BacktestAttributionPreviewResponse | null;
  attributionPreviewLoading: boolean;
  attributionPreviewError: boolean;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const output = preview?.outputs[0] ?? null;
  const [riskQuantity, setRiskQuantity] = useState('');
  const dataQuality = output?.evidence.data_quality_status ?? 'unknown';
  const datasetSnapshotId =
    preview?.dataset_snapshot_id ??
    output?.evidence.dataset_snapshot_id ??
    null;
  const datasetEvidenceLabel = datasetSnapshotId
    ? formatPublicEvidenceReference(
        `dataset_snapshot:${datasetSnapshotId}`,
        locale,
      )
    : labels.notDeclared;
  const referencePrice = output?.price ?? output?.evidence.reference_price;
  const parsedReferencePrice =
    referencePrice === null || referencePrice === undefined
      ? null
      : Number(referencePrice);
  const referencePriceText =
    parsedReferencePrice !== null && Number.isFinite(parsedReferencePrice)
      ? formatCurrency(parsedReferencePrice)
      : labels.notDeclared;
  const actionLabel = output
    ? signalPreviewActionLabel(output, locale, labels)
    : labels.notDeclared;
  const reviewGates = output?.review_gates ?? [];
  const gateRequired = output
    ? output.requires_risk_gate ||
      output.requires_account_truth_gate ||
      output.requires_paper_shadow_review ||
      output.requires_manual_review
    : false;
  const riskPreviewable =
    Boolean(output && singleAsset) &&
    (output?.action === 'buy' || output?.action === 'sell') &&
    parsedReferencePrice !== null &&
    Number.isFinite(parsedReferencePrice) &&
    parsedReferencePrice > 0;
  const paperShadowPreviewable =
    riskPreviewable && Boolean(riskPreviewResult?.passed);

  useEffect(() => {
    setRiskQuantity('');
  }, [output?.output_id]);

  const submitRiskPreview = () => {
    if (!preview || !output || !singleAsset || !riskPreviewable) {
      return;
    }
    const quantity = Number(riskQuantity);
    if (
      !Number.isFinite(quantity) ||
      quantity <= 0 ||
      parsedReferencePrice === null
    ) {
      return;
    }
    onRiskPreview({
      strategy: preview.strategy_id,
      symbol: output.symbol,
      asset_class: singleAsset.asset_class,
      action: output.action,
      quantity,
      reference_price: parsedReferencePrice,
      target_weight: output.target_weight ?? null,
      data_quality_status: dataQuality,
    });
  };
  const submitPaperShadowPreview = () => {
    if (
      !preview ||
      !output ||
      !singleAsset ||
      !paperShadowPreviewable ||
      parsedReferencePrice === null
    ) {
      return;
    }
    const quantity = Number(riskQuantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return;
    }
    onPaperShadowPreview({
      strategy: preview.strategy_id,
      symbol: output.symbol,
      asset_class: singleAsset.asset_class,
      action: output.action,
      quantity,
      reference_price: parsedReferencePrice,
      target_weight: output.target_weight ?? null,
      signal_id: output.output_id,
      dataset_snapshot_id:
        preview.dataset_snapshot_id ?? output.evidence.dataset_snapshot_id,
      risk_preview_passed: riskPreviewResult?.passed ?? false,
      risk_reasons: riskPreviewResult?.reasons ?? [],
    });
  };

  return (
    <div className="rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-4">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {labels.signalPreviewKicker}
          </div>
          <h3 className="app-type-subsection-title mt-1.5 text-[var(--app-text)]">
            {labels.signalPreviewTitle}
          </h3>
          <p className="app-muted mt-2 text-sm leading-6">
            {labels.signalPreviewDetail}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
          {labels.signalPreviewResearchOnly}
        </span>
      </div>

      {!singleAsset ? (
        <p className="app-muted mt-4 text-sm">{labels.signalPreviewSkipped}</p>
      ) : loading ? (
        <p className="app-muted mt-4 text-sm">{labels.signalPreviewLoading}</p>
      ) : error ? (
        <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
          {labels.signalPreviewUnavailable}
        </p>
      ) : output ? (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <MetadataItem
              label={labels.signalPreviewAction}
              value={actionLabel}
            />
            <MetadataItem
              label={labels.signalPreviewDataQualityLabel}
              value={formatPublicStatus(dataQuality, locale)}
            />
            <MetadataItem
              label={labels.signalPreviewBars}
              value={labels.signalPreviewBarCount(
                output.evidence.bar_count ?? 0,
              )}
            />
            <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_22%,transparent)] px-3 py-2">
              <div className="app-muted app-type-micro">
                {labels.signalPreviewReferencePriceLabel}
              </div>
              <div className="mt-1 truncate text-sm font-semibold tabular-nums">
                {labels.signalPreviewReferencePrice(referencePriceText)}
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="app-muted text-xs font-semibold">
                {labels.signalPreviewReason}
              </div>
              <p className="mt-2 text-sm leading-6 text-[var(--app-text)]">
                {signalPreviewReason(output, labels)}
              </p>
            </div>
            <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="app-muted text-xs font-semibold">
                {labels.signalPreviewDataBasis}
              </div>
              <p className="mt-2 break-words text-sm font-semibold text-[var(--app-text)]">
                {datasetEvidenceLabel}
              </p>
              <p className="app-muted mt-2 break-words text-xs leading-5">
                {labels.signalPreviewDataset}:&nbsp;
                {datasetSnapshotId ?? labels.notDeclared}
              </p>
              <p className="app-muted mt-2 text-sm leading-6">
                {labels.signalPreviewDataQuality(
                  formatPublicStatus(dataQuality, locale),
                )}
              </p>
            </div>
          </div>
          {reviewGates.length > 0 ? (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="app-muted text-xs font-semibold">
                {labels.signalPreviewReviewGates}
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
                {reviewGates.map((gate) => (
                  <div
                    key={`${gate.key}:${gate.status}`}
                    className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] px-3 py-2"
                  >
                    <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                      {signalPreviewGateLabel(gate, labels)}
                    </div>
                    <div className="app-muted mt-1 truncate text-xs">
                      {formatPublicStatus(gate.status, locale)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <RiskPreviewWorkflow
            attributionPreviewError={attributionPreviewError}
            attributionPreviewLoading={attributionPreviewLoading}
            attributionPreviewResult={attributionPreviewResult}
            onPaperShadowPreview={submitPaperShadowPreview}
            onRiskPreview={submitRiskPreview}
            paperShadowPreviewError={paperShadowPreviewError}
            paperShadowPreviewLoading={paperShadowPreviewLoading}
            paperShadowPreviewResult={paperShadowPreviewResult}
            paperShadowPreviewable={paperShadowPreviewable}
            riskPreviewError={riskPreviewError}
            riskPreviewLoading={riskPreviewLoading}
            riskPreviewResult={riskPreviewResult}
            riskPreviewable={riskPreviewable}
            riskQuantity={riskQuantity}
            setRiskQuantity={setRiskQuantity}
          />
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm font-semibold text-[var(--app-warning)]">
            {gateRequired
              ? labels.signalPreviewGateRequired
              : labels.signalPreviewNoGateRequired}
          </p>
          <p className="app-muted mt-3 text-xs leading-5">
            {labels.signalPreviewExecutionBoundary}
          </p>
        </>
      ) : (
        <p className="app-muted mt-4 text-sm">{labels.signalPreviewPending}</p>
      )}
    </div>
  );
}

function RiskPreviewWorkflow({
  attributionPreviewError,
  attributionPreviewLoading,
  attributionPreviewResult,
  onPaperShadowPreview,
  onRiskPreview,
  paperShadowPreviewError,
  paperShadowPreviewLoading,
  paperShadowPreviewResult,
  paperShadowPreviewable,
  riskPreviewError,
  riskPreviewLoading,
  riskPreviewResult,
  riskPreviewable,
  riskQuantity,
  setRiskQuantity,
}: {
  attributionPreviewError: boolean;
  attributionPreviewLoading: boolean;
  attributionPreviewResult: BacktestAttributionPreviewResponse | null;
  onPaperShadowPreview: () => void;
  onRiskPreview: () => void;
  paperShadowPreviewError: boolean;
  paperShadowPreviewLoading: boolean;
  paperShadowPreviewResult: BacktestPaperShadowPreviewResponse | null;
  paperShadowPreviewable: boolean;
  riskPreviewError: boolean;
  riskPreviewLoading: boolean;
  riskPreviewResult: BacktestRiskPreviewResponse | null;
  riskPreviewable: boolean;
  riskQuantity: string;
  setRiskQuantity: (value: string) => void;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  return (
    <>
      {riskPreviewable ? (
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
          <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <label className="grid min-w-0 flex-1 gap-2 text-sm font-medium">
              {labels.signalPreviewRiskQuantity}
              <input
                aria-label={labels.signalPreviewRiskQuantity}
                className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                min="1"
                step="1"
                type="number"
                value={riskQuantity}
                onChange={(event) => setRiskQuantity(event.target.value)}
              />
            </label>
            <button
              className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              disabled={riskPreviewLoading || !isPositiveNumber(riskQuantity)}
              onClick={onRiskPreview}
              type="button"
            >
              {riskPreviewLoading
                ? labels.signalPreviewRiskPreviewLoading
                : labels.signalPreviewRiskPreviewButton}
            </button>
          </div>
          {riskPreviewError ? (
            <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
              {labels.signalPreviewRiskPreviewUnavailable}
            </p>
          ) : riskPreviewResult ? (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="app-muted text-xs font-semibold">
                    {labels.signalPreviewRiskPreviewTitle}
                  </div>
                  <div
                    className={`mt-1 text-base font-semibold ${
                      riskPreviewResult.passed
                        ? 'text-[var(--app-pnl-positive)]'
                        : 'text-[var(--app-danger)]'
                    }`}
                  >
                    {riskPreviewResult.passed
                      ? labels.signalPreviewRiskPassed
                      : labels.signalPreviewRiskBlocked}
                  </div>
                </div>
                {riskPreviewResult.does_not_create_order ? (
                  <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
                    {labels.signalPreviewRiskNoOrder}
                  </span>
                ) : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {(riskPreviewResult.reasons.length
                  ? riskPreviewResult.reasons
                  : [riskPreviewResult.status]
                ).map((reason) => (
                  <span
                    className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-muted)]"
                    key={reason}
                  >
                    {signalPreviewRiskReasonLabel(reason, locale, labels)}
                  </span>
                ))}
              </div>
            </div>
          ) : (
            <p className="app-muted mt-3 text-sm leading-6">
              {labels.signalPreviewRiskPending}
            </p>
          )}
          {riskPreviewResult ? (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3">
              <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <div className="app-muted text-xs font-semibold">
                    {labels.signalPreviewPaperShadowNextStep}
                  </div>
                  <p className="app-muted mt-1 text-sm leading-6">
                    {paperShadowPreviewable
                      ? labels.signalPreviewPaperShadowReady
                      : labels.signalPreviewPaperShadowBlocked}
                  </p>
                </div>
                <button
                  className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={
                    paperShadowPreviewLoading || !paperShadowPreviewable
                  }
                  onClick={onPaperShadowPreview}
                  type="button"
                >
                  {paperShadowPreviewLoading
                    ? labels.signalPreviewPaperShadowLoading
                    : labels.signalPreviewPaperShadowButton}
                </button>
              </div>
              {paperShadowPreviewError ? (
                <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                  {labels.signalPreviewPaperShadowUnavailable}
                </p>
              ) : paperShadowPreviewResult ? (
                <PaperShadowPreviewResult result={paperShadowPreviewResult} />
              ) : null}
              {attributionPreviewLoading ? (
                <p className="app-muted mt-3 text-sm">
                  {labels.signalPreviewAttributionLoading}
                </p>
              ) : attributionPreviewError ? (
                <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                  {labels.signalPreviewAttributionUnavailable}
                </p>
              ) : attributionPreviewResult ? (
                <AttributionPreviewResult result={attributionPreviewResult} />
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export function signalPreviewActionLabel(
  output: StrategySignalPreviewOutput,
  locale: 'en' | 'zh',
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  if (output.action === 'buy') {
    return labels.signalPreviewActions.buy;
  }
  if (output.action === 'sell') {
    return labels.signalPreviewActions.sell;
  }
  if (output.action === 'rebalance') {
    return labels.signalPreviewActions.rebalance;
  }
  if (output.action === 'no_action') {
    return labels.signalPreviewActions.no_action;
  }
  return formatPublicStatus(output.action, locale);
}

export function signalPreviewReason(
  output: StrategySignalPreviewOutput,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  if (output.action === 'buy') {
    return labels.signalPreviewReasons.buy;
  }
  if (output.action === 'sell') {
    return labels.signalPreviewReasons.sell;
  }
  if (output.action === 'rebalance') {
    return labels.signalPreviewReasons.rebalance;
  }
  return labels.signalPreviewReasons.no_action;
}

export function signalPreviewGateLabel(
  gate: NonNullable<StrategySignalPreviewOutput['review_gates']>[number],
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  if (gate.status === 'not_required') {
    return labels.signalPreviewGateLabels.notRequired;
  }
  if (gate.key === 'data') {
    if (['blocked', 'missing', 'unavailable'].includes(gate.status)) {
      return labels.signalPreviewGateLabels.dataBlocked;
    }
    if (['pass', 'ok', 'complete', 'confirmed', 'live'].includes(gate.status)) {
      return labels.signalPreviewGateLabels.dataReady;
    }
    return labels.signalPreviewGateLabels.dataNeedsReview;
  }
  if (gate.key === 'account_truth') {
    return labels.signalPreviewGateLabels.accountTruthRequired;
  }
  if (gate.key === 'risk') {
    return labels.signalPreviewGateLabels.riskRequired;
  }
  if (gate.key === 'paper_shadow') {
    return labels.signalPreviewGateLabels.paperShadowWaiting;
  }
  if (gate.key === 'manual_review') {
    return labels.signalPreviewGateLabels.manualReviewRequired;
  }
  return labels.signalPreviewGateLabels.unknown;
}

export function signalPreviewRiskReasonLabel(
  reason: string,
  locale: 'en' | 'zh',
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  const normalized = reason.toLowerCase();
  if (normalized.includes('approved')) {
    return labels.signalPreviewRiskReasonLabels.approved;
  }
  if (normalized.includes('kill switch')) {
    return labels.signalPreviewRiskReasonLabels.killSwitch;
  }
  if (normalized.includes('data quality')) {
    return labels.signalPreviewRiskReasonLabels.dataQuality;
  }
  if (normalized.includes('cash reserve')) {
    return labels.signalPreviewRiskReasonLabels.cashReserve;
  }
  if (normalized.includes('order notional')) {
    return labels.signalPreviewRiskReasonLabels.orderNotional;
  }
  if (normalized.includes('position weight')) {
    return labels.signalPreviewRiskReasonLabels.positionWeight;
  }
  return formatPublicStatus(reason, locale);
}
