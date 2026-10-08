import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { formatCurrency, formatPercent } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { ResponsiveChartFrame } from '../../../shared/ui/workbench';
import type { ResearchPaperBook } from '../paper-book-contracts';

const copy = {
  zh: {
    title: '前向净收益与基准',
    net: '模拟净收益',
    excess: '模拟净超额',
    benchmark: '等权买入持有',
    drawdown: '最大回撤',
    fees: '成交费用',
    slippage: '滑点成本',
    cash: '现金占比',
    initial: '初始资金',
    basis:
      '基准与策略在首个实际接收目标的交易日同步启动，使用相同标的、资金、限额和成本。净资产已扣成交费用与滑点；下列成本不再重复扣减。',
    priceOnly: '仅价格收益：ETF 分配覆盖未验证。',
    gross: '包含服务商报告的税前分红；历史完整覆盖及税后收益未验证。',
    waiting: '尚无已结算的前向样本。',
    missing: '当前响应未提供净绩效，请刷新确认。',
    samples: '实际目标之后的结算日',
    health: '模拟健康判断',
    states: {
      not_configured: '未配置规则',
      unavailable: '比较证据不可用',
      insufficient_evidence: '有效样本不足',
      within_rule: '在配置阈值内，继续观察',
      threshold_breached: '阈值越界，需要复核',
    },
    paused: '已停止接收新目标，继续结算已有持仓。',
    report: '检查成本、持仓及执行阻断，再决定是否另起研究。',
    attribution: '持仓损益贡献',
    contribution: '收益贡献',
    pnl: '净损益',
    residual: '未归因损益',
    cashNote:
      '现金收益按零利息建模。贡献来自模拟账本，不是因子或 alpha 因果归因。',
    record: '按日比较数据',
    session: '结算日',
    window: '评估区间',
    pauseRule: '最大回撤',
    excessRule: '最低模拟净超额',
  },
  en: {
    title: 'Forward net performance and benchmark',
    net: 'Modeled net return',
    excess: 'Modeled net excess',
    benchmark: 'Equal-weight buy and hold',
    drawdown: 'Maximum drawdown',
    fees: 'Execution fees',
    slippage: 'Slippage cost',
    cash: 'Cash weight',
    initial: 'Initial cash',
    basis:
      'Strategy and benchmark start together at the first actually accepted target session, with the same universe, cash, limits and costs. Equity already includes fees and slippage; costs below are not deducted again.',
    priceOnly: 'Price returns only: ETF distributions are unverified.',
    gross:
      'Includes provider-reported gross distributions; complete historical coverage and after-tax returns are unverified.',
    waiting: 'No settled forward samples yet.',
    missing:
      'Net performance is absent from this response. Refresh to confirm.',
    samples: 'Settled sessions after a real target',
    health: 'Modeled book health',
    states: {
      not_configured: 'No rule configured',
      unavailable: 'Comparison evidence unavailable',
      insufficient_evidence: 'Insufficient eligible samples',
      within_rule: 'Within configured thresholds; continue observation',
      threshold_breached: 'Threshold breached; review required',
    },
    paused: 'New target intake stopped; continue settling existing positions.',
    report:
      'Review costs, holdings and execution blockers before starting new research.',
    attribution: 'Position P&L contributions',
    contribution: 'Return contribution',
    pnl: 'Net P&L',
    residual: 'Unattributed P&L',
    cashNote:
      'Cash earns no modeled interest. Contributions come from simulated accounting, not causal factor or alpha attribution.',
    record: 'Daily comparison data',
    session: 'Settled session',
    window: 'Evaluation interval',
    pauseRule: 'Maximum drawdown',
    excessRule: 'Minimum modeled net excess',
  },
};

const percent = (value: string | null) =>
  formatPercent(value === null ? null : Number(value));

export function ResearchPaperPerformance({
  book,
}: {
  book: ResearchPaperBook;
}) {
  const { locale } = usePreferences();
  const labels = copy[locale];
  const performance = book.performance;
  if (!performance)
    return <p className="app-muted text-xs">{labels.missing}</p>;
  const points = performance.equity_series.map((point) => ({
    session: point.session ?? labels.initial,
    net: Number(point.net_return),
    benchmark:
      point.benchmark_net_return === null
        ? null
        : Number(point.benchmark_net_return),
  }));
  return (
    <section className="min-w-0 space-y-4" aria-label={labels.title}>
      <h4 className="text-sm font-semibold">{labels.title}</h4>
      <p className="app-muted text-xs">
        {labels.window}: {performance.evaluation_start} →{' '}
        {performance.through_session ?? '—'} · {labels.samples}:{' '}
        {performance.sessions_since_first_accepted_target}
      </p>
      {performance.status === 'waiting' ? (
        <p className="app-muted text-xs">{labels.waiting}</p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              [labels.net, percent(performance.net_return)],
              [labels.excess, percent(performance.modeled_net_excess_return)],
              [labels.drawdown, percent(performance.max_drawdown)],
              [labels.cash, percent(performance.cash_weight)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="app-muted text-xs">{label}</dt>
                <dd className="text-lg font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          <ResponsiveChartFrame
            ariaLabel={labels.title}
            className="h-56 w-full"
            testId="paper-net-performance-chart"
          >
            {({ width, height }) => (
              <LineChart
                width={width}
                height={height}
                data={points}
                margin={{ top: 8, right: 12, left: 0, bottom: 8 }}
              >
                <CartesianGrid stroke="var(--app-divider)" vertical={false} />
                <XAxis
                  dataKey="session"
                  minTickGap={32}
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  tickFormatter={(value: number) => formatPercent(value)}
                  width={55}
                  tick={{ fontSize: 11 }}
                />
                <Tooltip formatter={(value) => formatPercent(Number(value))} />
                <Line
                  dataKey="net"
                  name={labels.net}
                  stroke="var(--app-accent)"
                  dot={false}
                  isAnimationActive={false}
                  strokeWidth={2}
                />
                <Line
                  dataKey="benchmark"
                  name={labels.benchmark}
                  stroke="var(--app-muted)"
                  dot={false}
                  isAnimationActive={false}
                  strokeDasharray="5 4"
                  connectNulls={false}
                />
              </LineChart>
            )}
          </ResponsiveChartFrame>
          <p className="text-xs">
            {labels.benchmark}: {percent(performance.benchmark_net_return)} ·{' '}
            {labels.fees}: {formatCurrency(Number(performance.fees_paid))} ·{' '}
            {labels.slippage}:{' '}
            {formatCurrency(Number(performance.slippage_cost))}
          </p>
          <details className="text-xs">
            <summary className="cursor-pointer">{labels.record}</summary>
            <div className="overflow-x-auto">
              <table className="mt-2 w-full text-left tabular-nums">
                <thead>
                  <tr>
                    {[labels.session, labels.net, labels.benchmark].map(
                      (label) => (
                        <th className="py-2" key={label}>
                          {label}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {performance.equity_series.map((point, index) => (
                    <tr key={index}>
                      <td className="py-1">
                        {point.session ?? labels.initial}
                      </td>
                      <td>{percent(point.net_return)}</td>
                      <td>{percent(point.benchmark_net_return)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <details className="text-xs">
            <summary className="cursor-pointer">{labels.attribution}</summary>
            <div className="mt-2 space-y-2">
              {performance.position_contributions.map((item) => (
                <p
                  className="flex flex-wrap justify-between gap-2 tabular-nums"
                  key={item.symbol}
                >
                  <span>{item.symbol}</span>
                  <span>
                    {labels.pnl}: {formatCurrency(Number(item.net_pnl))} ·{' '}
                    {labels.contribution}: {percent(item.return_contribution)}
                  </span>
                </p>
              ))}
              <p>
                {labels.residual}:{' '}
                {formatCurrency(
                  Number(performance.pnl_reconciliation_residual),
                )}
              </p>
              <p className="app-muted">{labels.cashNote}</p>
            </div>
          </details>
        </>
      )}
      <p className="app-muted text-xs leading-5">
        {labels.basis}{' '}
        {performance.return_basis === 'price_only'
          ? labels.priceOnly
          : labels.gross}
      </p>
      {book.health ? (
        <div
          className="border-t border-[var(--app-divider)] pt-3 text-xs leading-5"
          role="status"
        >
          <h5 className="font-semibold">
            {labels.health}: {labels.states[book.health.status]}
          </h5>
          {book.health.policy ? (
            <p>
              {labels.pauseRule}: {percent(book.health.policy.maximum_drawdown)}{' '}
              · {labels.excessRule}:{' '}
              {percent(book.health.policy.minimum_net_excess_return)}
            </p>
          ) : null}
          {book.health.status === 'threshold_breached' ? (
            <p>
              {book.health.action === 'pause_paper_target_acceptance'
                ? labels.paused
                : labels.report}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
