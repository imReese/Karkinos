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
  if (
    accounting?.schema_version !== 'karkinos.backtest_cash_dividends.v1' ||
    accounting.mode !== 'cash_dividends_gross'
  )
    return null;
  return (
    <section
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      aria-label={labels.title}
      data-testid="cash-dividend-accounting"
    >
      <h3 className="text-sm font-semibold">{labels.title}</h3>
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
      <p className="app-muted mt-3 text-xs leading-5">{labels.cashDetail}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
        {labels.limitations}
      </p>
      <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
        {labels.exDate(accounting.ex_date_execution_blocked_count)}
      </p>
    </section>
  );
}
