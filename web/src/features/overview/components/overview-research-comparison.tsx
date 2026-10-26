import {
  formatDate,
  formatPercent,
  formatQuantity,
} from '../../../shared/format';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import type { DailyTradingPlanResponse } from '../overview-feature-boundary';

type RecommendationStrategyContext = NonNullable<
  NonNullable<
    DailyTradingPlanResponse['account_action_recommendation']
  >['strategy_context']
>[string];

type HistoricalComparison = NonNullable<
  RecommendationStrategyContext['historical_comparison']
>;

export function SavedHistoricalComparison({
  comparison,
  locale,
  testId,
}: {
  comparison: HistoricalComparison;
  locale: string;
  testId: string;
}) {
  return (
    <div className="space-y-1.5 pt-1" data-testid={testId}>
      <p className="font-semibold">
        {locale === 'zh'
          ? '历史回测对比（研究）'
          : 'Historical backtests (research)'}
      </p>
      <p className="app-type-compact">
        {formatDate(comparison.start_date)}
        {' — '}
        {formatDate(comparison.end_date)}
        {' · '}
        {comparison.instrument_count}
        {locale === 'zh' ? ' 只标的' : ' instruments'}
        {' · '}
        {formatQuantity(comparison.bar_row_count)}
        {locale === 'zh' ? ' 条行情' : ' bar rows'}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left app-type-compact tabular-nums">
          <thead>
            <tr className="text-[var(--app-text-tertiary)]">
              <th scope="col" className="py-1 pr-3">
                {locale === 'zh' ? '真实回测' : 'Saved result'}
              </th>
              <th scope="col" className="py-1 pr-3">
                {locale === 'zh' ? '净收益' : 'Net return'}
              </th>
              <th scope="col" className="py-1 pr-3">
                {locale === 'zh' ? '年化' : 'Annualized'}
              </th>
              <th scope="col" className="py-1 pr-3">
                {locale === 'zh' ? '夏普' : 'Sharpe'}
              </th>
              <th scope="col" className="py-1">
                {locale === 'zh' ? '最大回撤' : 'Max drawdown'}
              </th>
            </tr>
          </thead>
          <tbody>
            {(
              [
                ['Gen7', comparison.baseline],
                [
                  locale === 'zh' ? '候选策略' : 'Candidate',
                  comparison.candidate,
                ],
              ] as const
            ).map(([label, result]) => (
              <tr key={result.result_id}>
                <th scope="row" className="py-1 pr-3 font-medium">
                  <a
                    href={`/backtest?id=${result.result_id}`}
                    onClick={(event) =>
                      handleClientNavigation(
                        event,
                        `/backtest?id=${result.result_id}`,
                      )
                    }
                    className="text-[var(--app-accent)] hover:underline"
                  >
                    {label} #{result.result_id}
                  </a>
                </th>
                <td className="py-1 pr-3">
                  {formatPercent(result.total_return)}
                </td>
                <td className="py-1 pr-3">
                  {formatPercent(result.annual_return)}
                </td>
                <td className="py-1 pr-3">
                  {result.sharpe == null ? '--' : result.sharpe.toFixed(2)}
                </td>
                <td className="py-1">{formatPercent(result.max_drawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="app-type-compact text-[var(--app-text-tertiary)]">
        {comparison.corporate_action_mode === 'price_only'
          ? locale === 'zh'
            ? '仅价格收益，未计现金分红。'
            : 'Price-only returns; cash distributions excluded. '
          : comparison.corporate_action_mode === 'reported_distributions_gross'
            ? locale === 'zh'
              ? '含已报告现金分红（税前）。'
              : 'Includes reported gross cash distributions. '
            : locale === 'zh'
              ? '公司行动口径未核验。'
              : 'Corporate-action basis unavailable. '}
        {comparison.point_in_time_verified === true
          ? locale === 'zh'
            ? '数据已通过历史时点核验。'
            : 'Historical point-in-time data verified. '
          : locale === 'zh'
            ? '数据未通过历史时点核验。'
            : 'Historical point-in-time data not verified. '}
        {locale === 'zh'
          ? '研究对比不代表独立最终评估通过，不改变策略准入；前向观测与人工确认仍独立。'
          : 'Research comparison does not establish independent final qualification or change promotion; forward observation and human confirmation remain separate.'}
      </p>
    </div>
  );
}

export function forwardObservationLabel(
  forward: RecommendationStrategyContext['forward'],
  locale: string,
): string {
  if (forward.status === 'not_started') {
    return locale === 'zh' ? '尚未开始' : 'Not started';
  }
  if (forward.status === 'recorded') {
    return locale === 'zh'
      ? `已有 ${forward.observation_count ?? '--'} 项记录，资格需另行核验`
      : `${forward.observation_count ?? '--'} recorded; qualification needs separate verification`;
  }
  return locale === 'zh' ? '状态不可核验' : 'Status unavailable';
}
