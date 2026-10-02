import { usePreferences } from '../../../shared/preferences/context';
import type { CashDividendAccounting } from '../corporate-action-contracts';
import { cashDividendCopy } from '../copy-cash-dividends';

export function CashDividendAccountingPanel({
  accounting,
}: {
  accounting?: CashDividendAccounting | null;
}) {
  const { locale } = usePreferences();
  const labels = cashDividendCopy[locale];
  const sharesMode =
    accounting?.schema_version === 'karkinos.backtest_cash_dividends.v2' &&
    accounting.mode === 'reported_distributions_gross';
  if (
    !accounting ||
    (!sharesMode &&
      (accounting.schema_version !== 'karkinos.backtest_cash_dividends.v1' ||
        accounting.mode !== 'cash_dividends_gross'))
  )
    return null;
  const title = sharesMode ? labels.reportedTitle : labels.title;
  return (
    <section
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      aria-label={title}
      data-testid="cash-dividend-accounting"
    >
      <h3 className="text-sm font-semibold">{title}</h3>
      <dl className="mt-3 grid gap-3 sm:grid-cols-3">
        {[
          [labels.income, accounting.gross_income],
          [labels.paid, accounting.cash_paid],
          [labels.receivable, accounting.receivable],
        ].map(([label, value]) => (
          <div
            key={label}
            className="min-w-0 border-l border-[var(--app-divider)] pl-3"
          >
            <dt className="app-muted text-xs">{label}</dt>
            <dd className="mt-1 break-words font-mono text-sm font-semibold tabular-nums">
              ¥ {value}
            </dd>
          </div>
        ))}
      </dl>
      {sharesMode ? (
        <>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            {[
              [labels.shares, accounting.share_quantity],
              [labels.unlisted, accounting.unlisted_quantity],
            ].map(([label, value]) => (
              <div
                key={label}
                className="min-w-0 border-l border-[var(--app-divider)] pl-3"
              >
                <dt className="app-muted text-xs">{label}</dt>
                <dd className="mt-1 break-words font-mono text-sm font-semibold tabular-nums">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="app-muted mt-3 text-xs leading-5">
            {labels.sharesDetail}
          </p>
          <details className="mt-3 min-w-0">
            <summary className="cursor-pointer text-xs font-semibold">
              {labels.shareRecords}
            </summary>
            <div
              className="mt-2 w-full min-w-0 max-w-full overflow-x-auto overscroll-x-contain"
              role="region"
              aria-label={labels.shareRecords}
              tabIndex={0}
            >
              <table className="w-full min-w-[860px] text-left text-xs">
                <caption className="sr-only">{labels.shareRecords}</caption>
                <thead>
                  <tr>
                    {[
                      labels.symbol,
                      labels.recordDate,
                      labels.exDateColumn,
                      labels.sharesPerShare,
                      labels.shareQuantity,
                      labels.listingDate,
                      labels.shareStatus,
                    ].map((label) => (
                      <th
                        key={label}
                        scope="col"
                        className="px-3 py-2 font-semibold"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {accounting.distributions
                    .filter((item) => Number(item.shares_per_share) > 0)
                    .map((item) => (
                      <tr
                        key={item.action_id}
                        className="border-t border-[var(--app-divider)]"
                      >
                        {[
                          item.symbol,
                          item.record_date,
                          item.ex_date,
                          item.shares_per_share,
                          item.share_quantity,
                          item.listing_date ?? labels.unknown,
                          item.shares_listed ? labels.listed : labels.notListed,
                        ].map((value, index) => (
                          <td
                            key={index}
                            className="whitespace-nowrap px-3 py-2 tabular-nums"
                          >
                            {value}
                          </td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      ) : null}
      <p className="app-muted mt-3 text-xs leading-5">{labels.cashDetail}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
        {sharesMode ? labels.reportedLimitations : labels.limitations}
      </p>
      <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
        {labels.exDate(accounting.ex_date_execution_blocked_count)}
      </p>
    </section>
  );
}
