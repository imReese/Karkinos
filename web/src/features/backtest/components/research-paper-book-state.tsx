import type { ReactNode } from 'react';

import { formatCurrency, formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { paperBookCopy, paperAttemptReason } from '../copy-paper-book';
import type { ResearchPaperBook } from '../paper-book-contracts';
import { BacktestEffectiveCostsView } from './backtest-cost-evidence-panel';

const money = (value: string) => formatCurrency(Number(value));

function Table({
  title,
  headers,
  children,
}: {
  title: string;
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div
      className="min-w-0 overflow-x-auto"
      role="region"
      aria-label={title}
      tabIndex={0}
    >
      <table className="w-full text-left text-xs tabular-nums">
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr>
            {headers.map((label) => (
              <th
                className="whitespace-nowrap border-b border-[var(--app-divider)] px-3 py-2 font-medium"
                key={label}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_tr]:border-b [&_tr]:border-[var(--app-divider)]">
          {children}
        </tbody>
      </table>
    </div>
  );
}

export function ResearchPaperBookState({ book }: { book: ResearchPaperBook }) {
  const { locale } = usePreferences();
  const labels = paperBookCopy[locale];
  const positions = Object.entries(book.state.positions);
  return (
    <section className="min-w-0 space-y-4" aria-label={labels.snapshot}>
      <div>
        <h4 className="text-sm font-semibold">{labels.snapshot}</h4>
        <p className="mt-1 text-xs font-medium" data-testid="paper-book-as-of">
          {labels.asOf}: {book.last_settled_session ?? labels.notSettled}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          [labels.equity, book.state.equity],
          [labels.cash, book.state.cash],
          [labels.receivable, book.state.dividend_receivable],
          [labels.income, book.state.dividend_income],
        ].map(([label, value]) => (
          <div className="min-w-0" key={label}>
            <dt className="app-muted text-xs leading-5">{label}</dt>
            <dd className="break-words text-base font-semibold tabular-nums">
              {money(value)}
            </dd>
          </div>
        ))}
      </dl>
      <div className="min-w-0 space-y-2">
        <h4 className="text-xs font-semibold">{labels.positions}</h4>
        {!positions.length ? (
          <p className="app-muted text-xs">{labels.noPositions}</p>
        ) : (
          <div className="space-y-3">
            {positions.map(([symbol, position]) => (
              <div
                className="border-t border-[var(--app-divider)] pt-3"
                key={symbol}
              >
                <p className="font-mono text-sm font-semibold">{symbol}</p>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-3">
                  {[
                    [labels.quantity, position.quantity],
                    [
                      labels.available,
                      `${position.available_qty} / ${position.frozen_qty} / ${position.unlisted_qty}`,
                    ],
                    [labels.marketValue, money(position.market_value)],
                    [labels.averageCost, position.avg_cost],
                    [
                      labels.pnl,
                      `${money(position.realized_pnl)} / ${money(position.unrealized_pnl)}`,
                    ],
                    [labels.fees, money(position.commission_paid)],
                  ].map(([label, value]) => (
                    <div className="min-w-0" key={label}>
                      <dt className="app-muted leading-5">{label}</dt>
                      <dd className="break-words tabular-nums">{value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        )}
      </div>
      <details className="min-w-0" data-testid="paper-book-fills">
        <summary className="cursor-pointer text-xs font-semibold">
          {labels.fills} · {book.fills.length}
        </summary>
        <div className="mt-2">
          {!book.fills.length ? (
            <p className="app-muted text-xs">{labels.noFills}</p>
          ) : (
            <Table
              title={labels.fills}
              headers={[
                labels.session,
                labels.symbol,
                labels.side,
                labels.quantity,
                labels.price,
                labels.fee,
                labels.slippage,
                labels.publication,
              ]}
            >
              {book.fills.map((fill) => (
                <tr key={fill.fill_id}>
                  <td className="whitespace-nowrap">{fill.session}</td>
                  <td>{fill.symbol}</td>
                  <td>
                    {fill.side === 'buy'
                      ? labels.buy
                      : fill.side === 'sell'
                        ? labels.sell
                        : fill.side}
                  </td>
                  <td>{fill.fill_quantity}</td>
                  <td>{fill.fill_price}</td>
                  <td>{money(fill.commission)}</td>
                  <td>{money(fill.slippage)}</td>
                  <td className="min-w-36 break-all font-mono">
                    {fill.publication_id}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </details>
      <details className="min-w-0" data-testid="paper-book-attempts">
        <summary className="cursor-pointer text-xs font-semibold">
          {labels.attempts} · {book.attempts.length}
        </summary>
        <div className="mt-2">
          {!book.attempts.length ? (
            <p className="app-muted text-xs">{labels.noAttempts}</p>
          ) : (
            <Table
              title={labels.attempts}
              headers={[
                labels.session,
                labels.symbol,
                labels.status,
                labels.reason,
                labels.publication,
              ]}
            >
              {book.attempts.map((attempt, index) => (
                <tr
                  key={`${attempt.publication_id}:${attempt.symbol}:${attempt.session}:${index}`}
                >
                  <td className="whitespace-nowrap">{attempt.session}</td>
                  <td>{attempt.symbol}</td>
                  <td>
                    {labels.statuses[
                      attempt.status as keyof typeof labels.statuses
                    ] ?? attempt.status}
                  </td>
                  <td className="min-w-40 break-words">
                    {paperAttemptReason(attempt.reason, locale) ? (
                      <p>{paperAttemptReason(attempt.reason, locale)}</p>
                    ) : null}
                    {attempt.reason ?? '—'}
                  </td>
                  <td className="min-w-36 break-all font-mono">
                    {attempt.publication_id}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </details>
      {book.steps.length ? (
        <details className="min-w-0" data-testid="paper-book-history">
          <summary className="cursor-pointer text-xs font-semibold">
            {labels.history} · {book.steps.length}
          </summary>
          <Table
            title={labels.history}
            headers={[labels.session, labels.equity, labels.cash, 'Dataset']}
          >
            {book.steps.map((step) => (
              <tr key={step.session}>
                <td className="whitespace-nowrap">
                  {step.session}
                  <span className="app-muted block">
                    {formatTimestamp(step.settled_at)}
                  </span>
                </td>
                <td>{money(step.projection.equity)}</td>
                <td>{money(step.projection.cash)}</td>
                <td className="min-w-48 break-all font-mono">
                  {step.dataset_id}
                  {step.projection.corporate_actions.length ? (
                    <details className="mt-2">
                      <summary className="cursor-pointer">
                        {labels.corporateActions}
                      </summary>
                      <pre className="whitespace-pre-wrap break-all">
                        {JSON.stringify(
                          step.projection.corporate_actions,
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  ) : null}
                </td>
              </tr>
            ))}
          </Table>
        </details>
      ) : null}
      <details className="min-w-0 text-xs">
        <summary className="cursor-pointer font-semibold">
          {labels.provenance}
        </summary>
        <div className="mt-2 space-y-2 leading-5">
          <p>
            {labels.started}: {formatTimestamp(book.started_at)} ·{' '}
            {labels.evaluationStart}: {book.evaluation_start}
          </p>
          <p>
            {labels.initialCash}: {money(book.initial_cash)}
          </p>
          <p className="break-all font-mono">{book.id}</p>
          <BacktestEffectiveCostsView
            costs={book.policy.cost_assumptions}
            recordedLabel={labels.frozenCosts}
          />
          <p className="break-all font-mono">
            {book.policy.corporate_action_mode}
          </p>
          <p className="font-semibold">{labels.limitations}</p>
          <ul className="list-disc space-y-1 pl-4">
            {book.limitations.map((limit, index) => (
              <li key={index}>{limit}</li>
            ))}
          </ul>
        </div>
      </details>
    </section>
  );
}
