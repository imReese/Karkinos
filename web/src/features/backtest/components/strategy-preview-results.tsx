import { useHoldingStrategyAttributionQuery } from '../backtest-feature-boundary';
import { formatCurrency } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicNote } from '../../../shared/public-labels';
import type {
  BacktestAttributionPreviewResponse,
  BacktestPaperShadowPreviewResponse,
} from '../api';
import {
  buildBacktestAttributionEvidenceChainItems,
  buildBacktestHoldingAttributionNextAction,
  buildBacktestHoldingAttributionReadinessItems,
  buildHoldingAttributionReviewHref,
} from './account-strategy-attribution-adapter';
import { MetadataItem } from './strategy-metadata-panel';

export function PaperShadowPreviewResult({
  result,
}: {
  result: BacktestPaperShadowPreviewResponse;
}) {
  const labels = useCopy().backtest.page;
  const fill = result.fill;
  const fillPrice = Number(fill?.fill_price ?? 0);
  const fillQuantity = fill?.fill_quantity ?? '--';
  const totalFee = Number(
    fill?.fee_breakdown?.total_fee ?? fill?.commission ?? 0,
  );
  const hasFill = result.status === 'simulated' && fill !== null;

  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <div>
          <div className="app-muted text-xs font-semibold">
            {labels.signalPreviewPaperShadowResultTitle}
          </div>
          <div className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {hasFill
              ? labels.signalPreviewPaperShadowSimulatedFill
              : labels.signalPreviewPaperShadowBlockedResult}
          </div>
        </div>
        {result.does_not_mutate_ledger ? (
          <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
            {labels.signalPreviewPaperShadowNoLedgerMutation}
          </span>
        ) : null}
      </div>
      {hasFill ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <MetadataItem
            label={labels.signalPreviewPaperShadowFill}
            value={labels.signalPreviewPaperShadowFillSummary(
              String(fillQuantity),
              formatCurrency(fillPrice),
            )}
          />
          <MetadataItem
            label={labels.signalPreviewPaperShadowFee}
            value={labels.signalPreviewPaperShadowEstimatedFee(
              formatCurrency(totalFee),
            )}
          />
        </div>
      ) : (
        <p className="app-muted mt-3 text-sm leading-6">
          {labels.signalPreviewPaperShadowBlocked}
        </p>
      )}
    </div>
  );
}

export function AttributionPreviewResult({
  result,
}: {
  result: BacktestAttributionPreviewResponse;
}) {
  const copy = useCopy();
  const labels = copy.backtest.page;
  const holdingLabels = copy.portfolio.detail;
  const { locale } = usePreferences();
  const holdingAttributionSymbol =
    result.review_linkage_candidate?.symbol || result.symbol;
  const holdingAttribution = useHoldingStrategyAttributionQuery(
    holdingAttributionSymbol,
  );
  const holdingAttributionReport = holdingAttribution.data ?? null;
  const holdingAttributionReadinessItems = holdingAttributionReport
    ? buildBacktestHoldingAttributionReadinessItems(
        holdingAttributionReport,
        holdingLabels,
      )
    : [];
  const holdingAttributionReady =
    holdingAttributionReadinessItems.length > 0 &&
    holdingAttributionReadinessItems.every((item) => item.passed);
  const holdingAttributionNextAction =
    buildBacktestHoldingAttributionNextAction({
      missingItem:
        holdingAttributionReadinessItems.find((item) => !item.passed) ?? null,
      labels,
      holdingLabels,
    });
  const previewEvidence =
    result.evidence_counts.signal_preview +
    result.evidence_counts.risk_preview +
    result.evidence_counts.paper_shadow_order +
    result.evidence_counts.paper_shadow_fill;
  const productionFacts =
    result.evidence_counts.production_order +
    result.evidence_counts.production_fill;
  const attributionEvidenceChainItems =
    buildBacktestAttributionEvidenceChainItems(result, labels);
  const isReady = result.status === 'ready_for_review_linkage';

  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <div>
          <div className="app-muted text-xs font-semibold">
            {labels.signalPreviewAttributionTitle}
          </div>
          <div className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {isReady
              ? labels.signalPreviewAttributionReady
              : labels.signalPreviewAttributionIncomplete}
          </div>
        </div>
        {!result.can_attribute_pnl ? (
          <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
            {labels.signalPreviewAttributionNoPnl}
          </span>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <MetadataItem
          label={labels.signalPreviewAttributionEvidence}
          value={labels.signalPreviewAttributionEvidenceSummary(
            previewEvidence,
            productionFacts,
          )}
        />
        <MetadataItem
          label={labels.signalPreviewAttributionBoundary}
          value={labels.signalPreviewAttributionPreviewOnly}
        />
      </div>
      {!result.can_attribute_pnl && productionFacts === 0 ? (
        <div className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3">
          <div className="text-sm font-semibold text-[var(--app-warning)]">
            {labels.signalPreviewAttributionNoLinkedFillsTitle}
          </div>
          <p className="mt-1 text-sm leading-6 text-[var(--app-warning)]">
            {labels.signalPreviewAttributionNoLinkedFillsDetail}
          </p>
        </div>
      ) : null}
      {result.review_linkage_candidate ? (
        <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-accent)_28%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] px-4 py-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.signalPreviewReviewLinkageTitle}
              </div>
              <p className="app-muted mt-1 text-sm leading-5">
                {labels.signalPreviewReviewLinkageDetail}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <a
                className="inline-flex items-center rounded-full border border-[color-mix(in_srgb,var(--app-accent)_42%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_12%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-accent)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_58%,var(--app-border))] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                href={buildHoldingAttributionReviewHref(
                  result.review_linkage_candidate.symbol || result.symbol,
                )}
              >
                {labels.signalPreviewReviewHoldingAttribution}
              </a>
              {result.review_linkage_candidate.manual_confirmation_required ? (
                <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1 text-xs font-semibold text-[var(--app-warning)]">
                  {labels.signalPreviewReviewLinkageManual}
                </span>
              ) : null}
              {result.review_linkage_candidate.does_not_create_order &&
              result.review_linkage_candidate.does_not_mutate_ledger ? (
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-muted)]">
                  {labels.signalPreviewReviewLinkageNoWrite}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      <div
        className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3"
        data-testid="backtest-attribution-evidence-chain"
      >
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {labels.signalPreviewEvidenceChainTitle}
        </div>
        <p className="app-muted mt-1 text-sm leading-5">
          {labels.signalPreviewEvidenceChainDetail}
        </p>
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">
          {attributionEvidenceChainItems.map((item) => (
            <li
              key={item.key}
              className="flex min-w-0 items-center justify-between gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] px-3 py-2 text-sm"
            >
              <span className="min-w-0 break-words font-semibold text-[var(--app-text)]">
                {item.label}
              </span>
              <span
                className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${
                  item.present
                    ? 'bg-[color-mix(in_srgb,var(--app-success)_14%,transparent)] text-[var(--app-success)]'
                    : 'bg-[color-mix(in_srgb,var(--app-warning)_14%,transparent)] text-[var(--app-warning)]'
                }`}
              >
                {item.present
                  ? labels.signalPreviewEvidenceChainPresent
                  : labels.signalPreviewEvidenceChainMissing}
              </span>
            </li>
          ))}
        </ul>
      </div>
      {holdingAttributionReadinessItems.length > 0 ? (
        <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-semibold text-[var(--app-text)]">
              {labels.signalPreviewHoldingAttributionReadiness}
            </div>
            <span
              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                holdingAttributionReady
                  ? 'bg-[color-mix(in_srgb,var(--app-success)_14%,transparent)] text-[var(--app-success)]'
                  : 'bg-[color-mix(in_srgb,var(--app-warning)_14%,transparent)] text-[var(--app-warning)]'
              }`}
            >
              {holdingAttributionReady
                ? holdingLabels.strategyAttributionReviewReady
                : holdingLabels.strategyAttributionReviewIncomplete}
            </span>
          </div>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {holdingAttributionReadinessItems.map((item) => (
              <li
                key={item.key}
                className="flex min-w-0 items-center gap-2 text-sm text-[var(--app-muted)]"
              >
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    item.passed
                      ? 'bg-[var(--app-success)]'
                      : 'bg-[var(--app-warning)]'
                  }`}
                />
                <span className="min-w-0 break-words">{item.label}</span>
              </li>
            ))}
          </ul>
          {holdingAttributionNextAction ? (
            <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-accent)_24%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_8%,transparent)] p-3">
              <div className="app-product-mark">
                {holdingLabels.strategyAttributionNextActionTitle}
              </div>
              <p className="mt-2 text-sm leading-6 text-[var(--app-muted)]">
                {holdingAttributionNextAction.detail}
              </p>
              <a
                className="mt-3 inline-flex items-center rounded-full border border-[color-mix(in_srgb,var(--app-accent)_42%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_12%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-accent)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_58%,var(--app-border))] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                href={holdingAttributionNextAction.href}
              >
                {holdingAttributionNextAction.label}
              </a>
            </div>
          ) : null}
        </div>
      ) : null}
      {result.limitations.length ? (
        <div className="mt-3 grid gap-2">
          {result.limitations.map((limitation) => (
            <p
              className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
              key={limitation}
            >
              {formatPublicNote(limitation, locale)}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
