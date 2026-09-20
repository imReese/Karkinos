import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatPrice,
} from '../../../shared/format';
import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { PositionPricing } from '../../../shared/portfolio-evidence/position-pricing';
import {
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
                    {model.variant === 'dashboard' ? null : (
                      <>
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
                      </>
                    )}
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
                    {model.variant === 'dashboard' ? (
                      <span className="ml-1.5 font-medium text-[var(--app-text-tertiary)]">
                        · {formatPercent(model.weightBySymbol[position.symbol])}
                      </span>
                    ) : null}
                  </div>
                  {model.variant === 'dashboard' ? null : (
                    <div className="mt-0.5 text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                      {model.showHistoryColumns
                        ? labels.realized
                        : labels.marketValue}
                    </div>
                  )}
                  {model.variant === 'dashboard' ? (
                    <>
                      <div
                        className={`mt-0.5 text-[length:var(--app-font-size-micro)] tabular-nums ${resolvePositionTone(
                          position.today_change,
                        )}`}
                      >
                        {labels.todayChange}{' '}
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

              {!model.showHistoryColumns && model.variant !== 'dashboard' ? (
                <div className="mt-3 flex min-w-0 items-center gap-2 border-t border-[var(--app-divider)] pt-2">
                  <PositionPricing position={position} locale={locale} />
                  <span className="ml-auto whitespace-nowrap text-xs tabular-nums text-[var(--app-text-secondary)]">
                    {formatPrice(position.latest_price)}
                  </span>
                </div>
              ) : null}
            </a>
          </li>
        );
      })}
    </ul>
  );
}
