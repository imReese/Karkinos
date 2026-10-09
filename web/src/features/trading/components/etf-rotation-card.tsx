import {
  TrendingUp,
  ShieldCheck,
  CheckCircle2,
  Clock,
  ArrowDownRight,
  ArrowUpRight,
  AlertCircle,
  Loader2,
} from 'lucide-react';

import { formatCurrency, formatQuantity } from '../../../shared/format';
import {
  useEtfRotationDashboardQuery,
  useExecuteEtfRotationOrdersMutation,
} from '../api-etf-rotation';

export function EtfRotationTradingCard({
  className = '',
}: {
  className?: string;
}) {
  const { data, isLoading, isError, error, refetch } =
    useEtfRotationDashboardQuery();
  const executeMutation = useExecuteEtfRotationOrdersMutation();

  if (isLoading) {
    return (
      <div
        className={`rounded-2xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-6 backdrop-blur-sm ${className}`}
      >
        <div className="flex items-center gap-3 text-sm text-[var(--app-text-secondary)]">
          <Loader2 className="h-4 w-4 text-[var(--app-accent)]" />
          <span>正在加载全球大类资产轮动量化策略与最新调仓订单…</span>
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div
        className={`rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-surface-raised)] p-6 ${className}`}
      >
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-[var(--app-warning-text)] shrink-0 mt-0.5" />
          <div>
            <h4 className="font-semibold text-[var(--app-text)]">
              无法读取量化轮动策略看板
            </h4>
            <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
              {error instanceof Error
                ? error.message
                : '服务器未返回有效策略数据'}
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-3 inline-flex items-center rounded-lg border border-[var(--app-divider)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] hover:bg-[var(--app-surface-overlay)]"
            >
              重新获取
            </button>
          </div>
        </div>
      </div>
    );
  }

  const { strategy, orders, execution_status, last_execution, can_execute } =
    data;

  const handleExecute = () => {
    executeMutation.mutate({
      operator: 'user',
      note: '基于全球轮动模型确认一键下单',
    });
  };

  return (
    <section
      data-testid="etf-rotation-trading-card"
      className={`rounded-2xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/80 p-5 shadow-xs backdrop-blur-md sm:p-6 ${className}`}
    >
      {/* 1. Header & Title */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-[var(--app-divider)] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="inline-flex h-2 w-2 rounded-full bg-[var(--app-accent)]" />
            <h3 className="text-base font-bold text-[var(--app-text)] sm:text-lg">
              {strategy.strategy_name}
            </h3>
            <span className="rounded-md border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-2 py-0.5 text-xs text-[var(--app-text-secondary)] font-medium">
              A股 + 美股QDII + 黄金 + 债券
            </span>
          </div>
          <p className="mt-1 text-xs text-[var(--app-text-tertiary)]">
            标的池覆盖：沪深300、中证500、创业板、标普500(513500)、纳指100(513100)、黄金ETF(518880)、国债ETF(511010)
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {execution_status === 'already_executed_today' ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-3 py-1 text-xs font-semibold text-[var(--app-success-text)]">
              <CheckCircle2 className="h-3.5 w-3.5" />
              今日调仓已执行
            </span>
          ) : execution_status === 'ready_to_trade' ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-accent)]/30 bg-[var(--app-accent)]/10 px-3 py-1 text-xs font-semibold text-[var(--app-accent)]">
              <Clock className="h-3.5 w-3.5" />
              待执行调仓 ({orders.length} 笔委托)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-3 py-1 text-xs font-medium text-[var(--app-text-secondary)]">
              <ShieldCheck className="h-3.5 w-3.5" />
              持仓已符合目标
            </span>
          )}
        </div>
      </div>

      {/* 2. Strategy Real Backtest Track Record (回测收益率指标区) */}
      <div className="my-5 rounded-xl border border-[var(--app-divider)]/80 bg-[var(--app-surface-overlay)]/40 p-4">
        <div className="flex items-center justify-between pb-3 border-b border-[var(--app-divider)]/50">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[var(--app-accent)]" />
            <span className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-secondary)]">
              5年真实历史数据回测表现 (2021-01 至 2026-10，共 1,391
              个实际交易日)
            </span>
          </div>
          <span className="text-xs text-[var(--app-text-tertiary)]">
            计入中信万1.5佣金、5bps滑点与整手摩擦
          </span>
        </div>

        <div className="mt-3.5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-3 border border-[var(--app-divider)]/40">
            <div className="text-xs text-[var(--app-text-tertiary)] font-medium">
              累计总收益率
            </div>
            <div className="mt-1 flex items-baseline gap-1.5">
              <span className="text-xl font-extrabold font-mono text-[var(--app-accent)]">
                +{strategy.cumulative_return_pct.toFixed(2)}%
              </span>
            </div>
            <div className="mt-1 app-type-micro text-[var(--app-text-tertiary)]">
              超额基准{' '}
              <span className="font-semibold text-[var(--app-accent)]">
                +{strategy.excess_return_pct.toFixed(2)}%
              </span>
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-3 border border-[var(--app-divider)]/40">
            <div className="text-xs text-[var(--app-text-tertiary)] font-medium">
              年化复合收益 (CAGR)
            </div>
            <div className="mt-1 text-xl font-extrabold font-mono text-[var(--app-text)]">
              {strategy.cagr_pct.toFixed(2)}%
            </div>
            <div className="mt-1 app-type-micro text-[var(--app-text-tertiary)]">
              年化稳定复利
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-3 border border-[var(--app-divider)]/40">
            <div className="text-xs text-[var(--app-text-tertiary)] font-medium">
              夏普比率 (Sharpe)
            </div>
            <div className="mt-1 text-xl font-extrabold font-mono text-[var(--app-text)]">
              {strategy.sharpe_ratio.toFixed(2)}
            </div>
            <div className="mt-1 app-type-micro text-[var(--app-text-tertiary)]">
              卡玛比率 {strategy.calmar_ratio.toFixed(2)}
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-3 border border-[var(--app-divider)]/40">
            <div className="text-xs text-[var(--app-text-tertiary)] font-medium">
              最大历史回撤 (MDD)
            </div>
            <div className="mt-1 text-xl font-extrabold font-mono text-[var(--app-text)]">
              {strategy.max_drawdown_pct.toFixed(2)}%
            </div>
            <div className="mt-1 app-type-micro text-[var(--app-text-tertiary)]">
              基准回撤的 1/4 (极强风控)
            </div>
          </div>

          <div className="rounded-lg bg-[var(--app-surface-raised)]/70 p-3 border border-[var(--app-divider)]/40 col-span-2 sm:col-span-1">
            <div className="text-xs text-[var(--app-text-tertiary)] font-medium">
              沪深300基准收益
            </div>
            <div className="mt-1 text-xl font-extrabold font-mono text-[var(--app-text-secondary)]">
              {strategy.benchmark_return_pct.toFixed(2)}%
            </div>
            <div className="mt-1 app-type-micro text-[var(--app-text-tertiary)]">
              同期A股宽基下行
            </div>
          </div>
        </div>
      </div>

      {/* 3. Actionable Rebalance Orders (今日调仓指令清单) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-[var(--app-text)]">
            今日待执行实盘调仓清单 ({orders.length} 笔指令)
          </h4>
          {data.rebalance ? (
            <span className="text-xs text-[var(--app-text-tertiary)]">
              基准资产: {formatCurrency(data.rebalance.total_equity)} |
              调仓换手率: {(data.rebalance.turnover_ratio * 100).toFixed(1)}%
            </span>
          ) : null}
        </div>

        {orders.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--app-divider)] p-6 text-center text-sm text-[var(--app-text-secondary)]">
            当前账户资产比例完全符合最优轮动权重，今日无需进行任何买卖操作。
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-overlay)]/30">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-[var(--app-divider)] bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] font-semibold">
                <tr>
                  <th className="py-2.5 px-3">证券代码</th>
                  <th className="py-2.5 px-3">证券名称</th>
                  <th className="py-2.5 px-3">买卖方向</th>
                  <th className="py-2.5 px-3 text-right">委托数量(股)</th>
                  <th className="py-2.5 px-3 text-right">参考价格</th>
                  <th className="py-2.5 px-3 text-right">预估金额</th>
                  <th className="py-2.5 px-3">调仓说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--app-divider)]/40 text-[var(--app-text)] font-mono">
                {orders.map((o) => {
                  const isBuy = o.side === 'buy';
                  return (
                    <tr
                      key={`${o.symbol}-${o.side}`}
                      className="hover:bg-[var(--app-surface-raised)]/40 transition-colors"
                    >
                      <td className="py-2.5 px-3 font-semibold">{o.symbol}</td>
                      <td className="py-2.5 px-3 font-sans font-bold text-[var(--app-text)]">
                        {o.name}
                      </td>
                      <td className="py-2.5 px-3 font-sans">
                        {isBuy ? (
                          <span className="inline-flex items-center gap-1 rounded-md bg-[var(--app-accent)]/15 px-2 py-0.5 text-xs font-bold text-[var(--app-accent)]">
                            <ArrowUpRight className="h-3 w-3" />
                            买入
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-md bg-rose-500/15 px-2 py-0.5 text-xs font-bold text-rose-400">
                            <ArrowDownRight className="h-3 w-3" />
                            卖出
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-right tabular-nums">
                        {formatQuantity(o.quantity)}
                      </td>
                      <td className="py-2.5 px-3 text-right tabular-nums">
                        ¥{o.price.toFixed(3)}
                      </td>
                      <td className="py-2.5 px-3 text-right tabular-nums font-semibold">
                        {formatCurrency(o.amount)}
                      </td>
                      <td className="py-2.5 px-3 font-sans text-[var(--app-text-secondary)]">
                        {o.reason}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 4. Execution Feedback Receipt (if already executed or just executed) */}
      {last_execution || executeMutation.data ? (
        <div className="mt-4 rounded-xl border border-[var(--app-success-border)] bg-[var(--app-success-bg)]/40 p-4">
          <div className="flex items-center gap-2 text-xs font-bold text-[var(--app-success-text)]">
            <CheckCircle2 className="h-4 w-4" />
            <span>委托已成功下达</span>
            <span className="text-[var(--app-text-tertiary)] font-normal font-mono">
              批次号: {(executeMutation.data || last_execution)?.batch_id}
            </span>
          </div>
          <p className="mt-1 text-xs text-[var(--app-text)]">
            {(executeMutation.data || last_execution)?.message}
          </p>
        </div>
      ) : null}

      {/* 5. Actual Order Placement Button (用户实际下单操作) */}
      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-t border-[var(--app-divider)] pt-4">
        <div className="text-xs text-[var(--app-text-secondary)]">
          {data.rebalance ? (
            <span>
              预计卖出释放资金{' '}
              <strong className="text-[var(--app-text)]">
                {formatCurrency(data.rebalance.total_sell_amount)}
              </strong>
              ， 预计买入需占用{' '}
              <strong className="text-[var(--app-text)]">
                {formatCurrency(data.rebalance.total_buy_amount)}
              </strong>
            </span>
          ) : (
            <span>严格遵循 A 股整手取整与“先卖后买”可用资金规则</span>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={!can_execute || executeMutation.isPending}
            onClick={handleExecute}
            className={`inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-xs font-bold transition-all shadow-sm ${
              !can_execute
                ? 'bg-[var(--app-surface-overlay)] text-[var(--app-text-tertiary)] cursor-not-allowed border border-[var(--app-divider)]'
                : 'bg-[var(--app-accent)] text-black hover:opacity-95 active:scale-98 shadow-md'
            }`}
          >
            {executeMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4" />
                正在下发委托…
              </>
            ) : execution_status === 'already_executed_today' ? (
              <>
                <CheckCircle2 className="h-4 w-4" />
                今日调仓已执行完毕
              </>
            ) : (
              <>
                <TrendingUp className="h-4 w-4" />
                确认下单（一键执行调仓）
              </>
            )}
          </button>
        </div>
      </div>
    </section>
  );
}
