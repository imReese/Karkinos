import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import { StatusBadge } from '../../../shared/ui/workbench';
import { quoteNeedsReview } from '../position-observation';
import {
  formatPositionAge,
  handlePositionLinkClick,
  holdingDetailHref,
  resolvePositionAssetClass,
  resolvePositionName,
  resolvePositionTone,
  type PositionsTableModel,
} from './positions-table-model';

type PortfolioCopy = ReturnType<typeof useCopy>;

export function PositionsTableMobileList({
  copy,
  locale,
  model,
}: {
  copy: PortfolioCopy;
  locale: Locale;
  model: PositionsTableModel;
}) {
  const labels = copy.portfolio.table;
  const detailLabels = copy.portfolio.detail;
  if (model.positions.length === 0) {
    return (
      <div className="border-y border-[var(--app-divider)] px-3 py-4 text-sm text-[var(--app-text-secondary)] md:hidden">
        {copy.portfolio.positionsEmpty}
      </div>
    );
  }

  return (
    <ul
      data-testid="positions-mobile-list"
      className="min-w-0 max-w-full divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] md:hidden"
    >
      {model.positions.map((position) => {
        const displayName = resolvePositionName(position);
        const needsReview = quoteNeedsReview(position.quote_status);
        const staleReason = formatStaleReason(
          position.stale_reason,
          copy.common.staleReasons,
        );
        return (
          <li className="min-w-0 max-w-full" key={position.symbol}>
            <a
              href={holdingDetailHref(position.symbol)}
              onClick={(event) =>
                handlePositionLinkClick(
                  event,
                  position.symbol,
                  model.onOpenPosition,
                )
              }
              data-testid={`position-mobile-row-${position.symbol}`}
              aria-label={`${labels.detailsTitle}: ${displayName} ${position.symbol}`}
              className={`app-position-mobile-row block w-full min-w-0 max-w-full px-1 text-[var(--app-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                model.variant === 'dashboard' ? 'py-2.5' : 'py-3'
              }`}
            >
              <div className="flex min-w-0 items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">
                    {displayName}
                  </div>
                  <div className="app-type-micro mt-0.5 flex min-w-0 items-center gap-1.5 text-[var(--app-text-tertiary)]">
                    <span className="shrink-0 font-mono font-medium">
                      {position.symbol}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span className="truncate">
                      {formatAssetClassLabel(
                        resolvePositionAssetClass(
                          position,
                          model.assetClassBySymbol,
                        ),
                        copy.common,
                      )}
                    </span>
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div
                    className={`text-sm font-semibold tabular-nums ${
                      model.showHistoryColumns
                        ? resolvePositionTone(position.realized_pnl)
                        : 'text-[var(--app-text)]'
                    }`}
                  >
                    {formatCurrency(
                      model.showHistoryColumns
                        ? position.realized_pnl
                        : position.market_value,
                    )}
                  </div>
                  <div className="mt-0.5 text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                    {model.showHistoryColumns
                      ? labels.realized
                      : labels.marketValue}
                  </div>
                  {model.variant === 'dashboard' ? (
                    <>
                      <div
                        className={`mt-1 text-xs font-semibold tabular-nums ${resolvePositionTone(
                          position.today_change,
                        )}`}
                      >
                        <span className="sr-only">{labels.todayChange}: </span>
                        {formatCurrency(position.today_change)}
                      </div>
                      <div
                        className={`mt-0.5 text-[length:var(--app-font-size-micro)] tabular-nums ${resolvePositionTone(
                          position.unrealized_pnl,
                        )}`}
                      >
                        {labels.unrealized}{' '}
                        {formatCurrency(position.unrealized_pnl)}
                      </div>
                    </>
                  ) : null}
                </div>
              </div>

              {model.variant !== 'dashboard' ? (
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                  {model.showHistoryColumns ? (
                    <>
                      <div className="min-w-0">
                        <dt className="text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                          {labels.closedOn}
                        </dt>
                        <dd className="mt-0.5 truncate font-mono text-xs tabular-nums text-[var(--app-text-secondary)]">
                          {formatDate(position.closed_at)}
                        </dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                          {detailLabels.commissionPaid}
                        </dt>
                        <dd className="mt-0.5 truncate text-xs tabular-nums text-[var(--app-text-secondary)]">
                          {formatCurrency(position.commission_paid)}
                        </dd>
                      </div>
                    </>
                  ) : (
                    <>
                      {model.showFullColumns ? (
                        <div className="min-w-0">
                          <dt className="text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                            {labels.weight}
                          </dt>
                          <dd className="mt-0.5 truncate text-xs font-medium tabular-nums">
                            {formatPercent(
                              model.weightBySymbol[position.symbol],
                            )}
                          </dd>
                        </div>
                      ) : null}
                      <div className="min-w-0">
                        <dt className="text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                          {labels.todayChange}
                        </dt>
                        <dd
                          className={`mt-0.5 truncate text-xs font-medium tabular-nums ${resolvePositionTone(
                            position.today_change,
                          )}`}
                        >
                          {formatCurrency(position.today_change)}
                        </dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                          {labels.unrealized}
                        </dt>
                        <dd
                          className={`mt-0.5 truncate text-xs font-medium tabular-nums ${resolvePositionTone(
                            position.unrealized_pnl,
                          )}`}
                        >
                          {formatCurrency(position.unrealized_pnl)}
                        </dd>
                      </div>
                      {model.showFullColumns ? (
                        <div className="min-w-0">
                          <dt className="text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                            {labels.realized}
                          </dt>
                          <dd
                            className={`mt-0.5 truncate text-xs font-medium tabular-nums ${resolvePositionTone(
                              position.realized_pnl,
                            )}`}
                          >
                            {formatCurrency(position.realized_pnl)}
                          </dd>
                        </div>
                      ) : null}
                    </>
                  )}
                </dl>
              ) : null}

              {!model.showHistoryColumns ? (
                <div
                  className={`flex min-w-0 items-center gap-2 ${
                    model.variant === 'dashboard'
                      ? 'mt-1.5'
                      : 'mt-3 border-t border-[var(--app-divider)] pt-2'
                  }`}
                >
                  <StatusBadge tone={needsReview ? 'warning' : 'success'}>
                    {position.quote_status
                      ? formatPublicStatus(position.quote_status, locale)
                      : '--'}
                  </StatusBadge>
                  <span className="min-w-0 truncate text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                    {formatPositionAge(position.quote_age_seconds)} ·{' '}
                    {formatTimestamp(position.quote_timestamp)}
                  </span>
                  {position.stale_reason ? (
                    <span
                      className="min-w-0 truncate text-[length:var(--app-font-size-micro)] text-[var(--app-warning-text)]"
                      title={staleReason}
                    >
                      {staleReason}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </a>
          </li>
        );
      })}
    </ul>
  );
}
