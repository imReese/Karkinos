import { useState } from 'react';
import {
  CheckCircle2,
  Clock,
  Loader2,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';

import { formatQuantity } from '../../../shared/format';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import {
  useExecuteEtfRotationOrdersMutation,
  type EtfRotationDashboardResponse,
} from '../overview-feature-boundary';

export function EtfRotationOverviewPanel({
  data,
}: {
  data: EtfRotationDashboardResponse;
}) {
  const [selectedPeriod, setSelectedPeriod] = useState<'5y' | 'from_2025'>(
    '5y',
  );
  const executeMutation = useExecuteEtfRotationOrdersMutation();
  const { strategy, orders, execution_status, can_execute, rebalance } = data;
  const activeStrategy = data.strategy_periods?.[selectedPeriod] ?? strategy;

  const handleExecute = () => {
    executeMutation.mutate({
      operator: 'user',
      note: '基于全球大类资产轮动模型确认一键下单',
    });
  };

  const totalBuyAmount =
    rebalance?.total_buy_amount ??
    orders.reduce((sum, o) => (o.side === 'buy' ? sum + o.amount : sum), 0);

  return (
    <div
      data-testid="etf-rotation-overview-panel"
      className="flex flex-1 min-w-0 flex-col rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/80 p-4 shadow-2xs backdrop-blur-sm"
    >
      {/* 1. Strategy Identity & Execution Status */}
      <div className="flex items-start justify-between gap-2 border-b border-[var(--app-divider)] pb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="inline-flex h-2 w-2 rounded-full bg-[var(--app-accent)] shrink-0" />
            <span className="text-xs font-bold text-[var(--app-text)] truncate">
              {strategy.strategy_name}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <span className="rounded-md border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-1.5 py-0.5 app-type-micro text-[var(--app-text-secondary)] font-medium">
              A股 + 美股Q100 + 黄金 + 债券
            </span>
          </div>
        </div>

        <div className="shrink-0">
          {execution_status === 'already_executed_today' ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-2.5 py-0.5 app-type-micro font-semibold text-[var(--app-success-text)]">
              <CheckCircle2 className="h-3 w-3" />
              今日已执行
            </span>
          ) : execution_status === 'ready_to_trade' ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--app-accent)]/30 bg-[var(--app-accent)]/10 px-2.5 py-0.5 app-type-micro font-semibold text-[var(--app-accent)]">
              <Clock className="h-3 w-3" />
              待调仓 ({orders.length})
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-2.5 py-0.5 app-type-micro font-medium text-[var(--app-text-secondary)]">
              <ShieldCheck className="h-3 w-3" />
              持仓已平衡
            </span>
          )}
        </div>
      </div>

      {/* 2. Track Record Strip with Period Toggle */}
      <div className="my-3 rounded-xl border border-[var(--app-divider)]/80 bg-[var(--app-surface-overlay)]/40 p-2.5">
        <div className="flex items-center justify-between pb-2 border-b border-[var(--app-divider)]/40 app-type-micro">
          <span className="flex items-center gap-1 font-bold text-[var(--app-text-secondary)] uppercase tracking-wider">
            <TrendingUp className="h-3 w-3 text-[var(--app-accent)]" />
            历史回测表现
          </span>
          {data.strategy_periods ? (
            <div className="flex items-center rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-0.5">
              <button
                type="button"
                onClick={() => setSelectedPeriod('5y')}
                className={`rounded px-1.5 py-0.5 app-type-micro font-medium transition-colors ${
                  selectedPeriod === '5y'
                    ? 'bg-[var(--app-accent)] text-[var(--app-text-inverse)] font-bold'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
              >
                5年全周期
              </button>
              <button
                type="button"
                onClick={() => setSelectedPeriod('from_2025')}
                className={`rounded px-1.5 py-0.5 app-type-micro font-medium transition-colors ${
                  selectedPeriod === 'from_2025'
                    ? 'bg-[var(--app-accent)] text-[var(--app-text-inverse)] font-bold'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
              >
                2025至今
              </button>
            </div>
          ) : (
            <span className="text-[var(--app-text-tertiary)]">
              基准: {activeStrategy.benchmark_return_pct.toFixed(2)}%
            </span>
          )}
        </div>

        <div className="flex items-center justify-between py-1 text-[var(--app-text-tertiary)] app-type-micro">
          <span className="truncate">{activeStrategy.backtest_range}</span>
          <span className="shrink-0">
            基准: {activeStrategy.benchmark_return_pct.toFixed(2)}%
          </span>
        </div>

        <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-2 border border-[var(--app-divider)]/30">
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              累计总收益
            </div>
            <div className="mt-0.5 font-mono font-extrabold text-[var(--app-accent)] text-sm">
              +{activeStrategy.cumulative_return_pct.toFixed(2)}%
            </div>
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              超额 +{activeStrategy.excess_return_pct.toFixed(2)}%
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-2 border border-[var(--app-divider)]/30">
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              年化复合 (CAGR)
            </div>
            <div className="mt-0.5 font-mono font-extrabold text-[var(--app-text)] text-sm">
              {activeStrategy.cagr_pct.toFixed(2)}%
            </div>
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              年化稳定复利
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-2 border border-[var(--app-divider)]/30">
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              夏普比率 (Sharpe)
            </div>
            <div className="mt-0.5 font-mono font-extrabold text-[var(--app-text)] text-sm">
              {activeStrategy.sharpe_ratio.toFixed(2)}
            </div>
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              卡玛比 {activeStrategy.calmar_ratio.toFixed(2)}
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-2 border border-[var(--app-divider)]/30">
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              最大历史回撤
            </div>
            <div className="mt-0.5 font-mono font-extrabold text-[var(--app-text)] text-sm">
              {activeStrategy.max_drawdown_pct.toFixed(2)}%
            </div>
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              {selectedPeriod === '5y' ? '基准回撤 1/4' : '超额收益稳健'}
            </div>
          </div>
        </div>
      </div>

      {/* 3. Rebalance Orders List */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between text-xs font-semibold text-[var(--app-text)] pb-1.5">
          <span>今日调仓建议 ({orders.length} 选标的)</span>
          {rebalance ? (
            <span className="app-type-micro text-[var(--app-text-tertiary)] font-normal">
              换手率: {(rebalance.turnover_ratio * 100).toFixed(1)}%
            </span>
          ) : null}
        </div>

        {orders.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--app-divider)] p-4 text-center text-xs text-[var(--app-text-secondary)]">
            当前账户资产比例完全符合最优轮动权重，今日无需调整。
          </div>
        ) : (
          <ul className="space-y-2 max-h-[16rem] overflow-y-auto overscroll-y-contain pr-1">
            {orders.map((o) => {
              const isBuy = o.side === 'buy';
              return (
                <li
                  key={`${o.symbol}-${o.side}`}
                  className="rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/90 p-2.5 shadow-2xs"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono font-bold text-xs text-[var(--app-text)]">
                        {o.symbol}
                      </span>
                      <span className="font-bold text-xs text-[var(--app-text)]">
                        {o.name}
                      </span>
                    </div>
                    <span
                      className={`inline-flex items-center rounded-md px-1.5 py-0.5 app-type-micro font-bold ${
                        isBuy
                          ? 'bg-[var(--app-accent)]/15 text-[var(--app-accent)]'
                          : 'bg-[var(--app-pnl-negative)]/15 text-[var(--app-pnl-negative)]'
                      }`}
                    >
                      {isBuy ? '买入' : '卖出'}
                    </span>
                  </div>

                  <div className="mt-2 grid grid-cols-3 gap-1 border-t border-[var(--app-divider)]/40 pt-1.5 app-type-micro font-mono text-[var(--app-text-secondary)]">
                    <div>
                      <span className="text-[var(--app-text-tertiary)] block app-type-micro">
                        委托股数
                      </span>
                      <span className="font-bold text-[var(--app-text)]">
                        {formatQuantity(o.quantity)}股
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--app-text-tertiary)] block app-type-micro">
                        参考价
                      </span>
                      <span>¥{o.price.toFixed(3)}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-[var(--app-text-tertiary)] block app-type-micro">
                        预估金额
                      </span>
                      <span className="font-bold text-[var(--app-text)]">
                        ¥
                        {o.amount.toLocaleString('zh-CN', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* 4. Footer & Action */}
      <div className="mt-3 border-t border-[var(--app-divider)] pt-3 shrink-0">
        {orders.length > 0 ? (
          <div className="space-y-1 mb-2.5">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-[var(--app-text-secondary)]">
                预计动用资金
              </span>
              <span className="font-mono font-bold text-sm text-[var(--app-text)]">
                ¥
                {totalBuyAmount.toLocaleString('zh-CN', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </span>
            </div>
            {rebalance?.total_equity ? (
              <div className="flex items-center justify-between app-type-micro text-[var(--app-text-tertiary)]">
                <span>
                  测算基准:{' '}
                  {rebalance.capital_source === 'available_cash'
                    ? '账户可用资金'
                    : '配置资金'}{' '}
                  (¥
                  {rebalance.total_equity.toLocaleString('zh-CN', {
                    minimumFractionDigits: 2,
                  })}
                  )
                </span>
                <span className="font-mono font-medium">
                  资金占用率{' '}
                  {((totalBuyAmount / rebalance.total_equity) * 100).toFixed(1)}
                  %
                </span>
              </div>
            ) : null}
          </div>
        ) : null}

        {execution_status === 'already_executed_today' ? (
          <div className="rounded-xl border border-[var(--app-success-border)] bg-[var(--app-success-bg)] p-2.5 text-xs text-[var(--app-success-text)] flex items-center justify-between">
            <span className="flex items-center gap-1.5 font-semibold">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              今日调仓已执行成功
            </span>
            <a
              href="/trading"
              onClick={(e) => handleClientNavigation(e, '/trading')}
              className="font-medium underline hover:opacity-80 shrink-0 app-type-micro"
            >
              查看明细 →
            </a>
          </div>
        ) : can_execute && orders.length > 0 ? (
          <button
            type="button"
            onClick={handleExecute}
            disabled={executeMutation.isPending}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-[var(--app-accent)] py-2.5 px-4 text-xs font-bold text-[var(--app-text-inverse)] shadow-xs hover:opacity-95 active:scale-[0.99] transition-all disabled:opacity-50"
          >
            {executeMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4" />
                <span>正在提交调仓委托…</span>
              </>
            ) : (
              <>
                <TrendingUp className="h-4 w-4" />
                <span>确认下单 (一键执行调仓)</span>
              </>
            )}
          </button>
        ) : null}

        {executeMutation.isError ? (
          <p className="mt-1.5 text-center app-type-micro text-[var(--app-warning-text)]">
            下单失败:{' '}
            {executeMutation.error instanceof Error
              ? executeMutation.error.message
              : '请重试'}
          </p>
        ) : null}
      </div>
    </div>
  );
}
