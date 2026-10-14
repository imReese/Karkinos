import { GitCommit, History } from 'lucide-react';
import { usePreferences } from '../../../shared/preferences/context';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';

type GenerationRecord = {
  gen: string;
  nameZh: string;
  nameEn: string;
  model: string;
  prompt: string;
  mechanismZh: string;
  mechanismEn: string;
  totalReturn: string;
  maxDrawdown: string;
  sharpe: string;
  status: 'active' | 'retired';
  statusZh: string;
  statusEn: string;
  resultId?: number;
  date: string;
};

export function StrategyGenerationMatrix() {
  const { locale } = usePreferences();
  const isZh = locale === 'zh';

  const generations: GenerationRecord[] = [
    {
      gen: 'Gen 5',
      nameZh: '趋势超卖低吸与波动率防御',
      nameEn: 'Trend RSI Pullback & Volatility Defense',
      model: 'Gemini 3.8 Flash',
      prompt: 'v18 / AST DSL',
      mechanismZh: 'MA20 趋势确立 + RSI(14) 强势超卖低吸 + 波动率突增离场',
      mechanismEn: 'MA20 trend + RSI(14) pullback + volatility spike exit',
      totalReturn: '-0.06%',
      maxDrawdown: '12.47%',
      sharpe: '-0.1472',
      status: 'active',
      statusZh: '现役服役中 (Paper Shadow)',
      statusEn: 'Active (Paper Shadow)',
      resultId: 181,
      date: '2026-10-13',
    },
    {
      gen: 'Gen 4',
      nameZh: '短期价格反转与均线系统',
      nameEn: 'Short-term Reversal & Moving Average',
      model: 'DeepSeek-V4-Pro',
      prompt: 'v14 ~ v17',
      mechanismZh: '价格均线突破，缺少波动率过滤，急跌行情易被假突破洗盘',
      mechanismEn:
        'MA breakout without volatility guard, prone to false breaks',
      totalReturn: '-6.42%',
      maxDrawdown: '17.68%',
      sharpe: '-0.5709',
      status: 'retired',
      statusZh: '已退役 (被 Gen 5 自动更迭)',
      statusEn: 'Retired (Superseded by Gen 5)',
      resultId: 126,
      date: '2026-09-22',
    },
    {
      gen: 'Gen 3',
      nameZh: '多因子日频选股探索',
      nameEn: 'Multi-factor Daily Selection',
      model: 'DeepSeek-V4-Pro',
      prompt: 'v14',
      mechanismZh: '引入 Shadow Research 自动化日频筛选，换手率偏高',
      mechanismEn: 'Automated daily screening with higher turnover',
      totalReturn: '-37.98%',
      maxDrawdown: '47.67%',
      sharpe: '-0.3885',
      status: 'retired',
      statusZh: '已退役 (未通过账户资格)',
      statusEn: 'Retired (Disqualified)',
      resultId: 77,
      date: '2026-09-04',
    },
    {
      gen: 'Gen 2',
      nameZh: '双均线趋势跟踪与初级风控',
      nameEn: 'Dual MA Trend & Basic Risk Control',
      model: 'DeepSeek-V4-Pro',
      prompt: 'v12 ~ v13',
      mechanismZh: '双均线金叉死叉，初步引入防过拟合与基础费率模型',
      mechanismEn: 'Dual MA crossover with initial cost model',
      totalReturn: '+3.10%',
      maxDrawdown: '14.58%',
      sharpe: '+0.0580',
      status: 'retired',
      statusZh: '已退役 (历史归档)',
      statusEn: 'Retired (Archived)',
      resultId: 26,
      date: '2026-08-21',
    },
    {
      gen: 'Gen 1',
      nameZh: '动量单指标原型验证',
      nameEn: 'Single Momentum Prototype',
      model: 'DeepSeek-V4-Pro',
      prompt: 'v5 ~ v7',
      mechanismZh: '早期动量原型，验证 Generator 与 Critique 双模型架构',
      mechanismEn: 'Early momentum prototype for dual-agent research',
      totalReturn: '-2.50%',
      maxDrawdown: '3.86%',
      sharpe: '-2.6425',
      status: 'retired',
      statusZh: '已退役 (历史归档)',
      statusEn: 'Retired (Archived)',
      resultId: 10,
      date: '2026-08-11',
    },
  ];

  return (
    <section
      className="rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-4 sm:p-5 min-w-0"
      data-testid="strategy-generation-matrix"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-3">
        <div className="flex items-center gap-2">
          <History className="size-4 text-[var(--app-accent)]" />
          <h3 className="text-base font-bold text-[var(--app-text)]">
            {isZh
              ? '量化策略代际演进矩阵 (Gen 1 ~ Gen 5)'
              : 'Strategy Generation Evolution Matrix'}
          </h3>
        </div>
        <span className="text-xs text-[var(--app-text-tertiary)]">
          {isZh
            ? '单一活跃策略权威：新代际通关自动置换老代际'
            : 'Single Active Authority: New champion supersedes prior'}
        </span>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-[var(--app-divider)] text-[var(--app-text-tertiary)] font-semibold">
              <th className="py-2.5 pr-3">{isZh ? '代际' : 'Gen'}</th>
              <th className="py-2.5 px-3">
                {isZh ? '策略名称 / 核心逻辑' : 'Strategy / Mechanism'}
              </th>
              <th className="py-2.5 px-3">{isZh ? '驱动模型' : 'AI Model'}</th>
              <th className="py-2.5 px-3 text-right">
                {isZh ? '总收益率' : 'Return'}
              </th>
              <th className="py-2.5 px-3 text-right">
                {isZh ? '最大回撤' : 'Max DD'}
              </th>
              <th className="py-2.5 px-3 text-right">
                {isZh ? '夏普' : 'Sharpe'}
              </th>
              <th className="py-2.5 px-3">
                {isZh ? '当前状态' : 'Lifecycle Status'}
              </th>
              <th className="py-2.5 pl-3 text-right">
                {isZh ? '回测报告' : 'Report'}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--app-divider)]/60 font-normal">
            {generations.map((item) => {
              const isActive = item.status === 'active';
              return (
                <tr
                  key={item.gen}
                  className={`hover:bg-[var(--app-surface-overlay)]/40 transition-colors ${
                    isActive ? 'bg-[var(--app-accent-bg)]/30 font-medium' : ''
                  }`}
                >
                  <td className="py-3 pr-3 font-mono font-bold">
                    <span
                      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ${
                        isActive
                          ? 'bg-[var(--app-accent)] text-white'
                          : 'bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] border border-[var(--app-divider)]'
                      }`}
                    >
                      <GitCommit className="size-3" />
                      {item.gen}
                    </span>
                  </td>
                  <td className="py-3 px-3 min-w-[200px]">
                    <div className="font-semibold text-[var(--app-text)]">
                      {isZh ? item.nameZh : item.nameEn}
                    </div>
                    <div className="text-[var(--app-text-tertiary)] mt-0.5 text-xs line-clamp-1">
                      {isZh ? item.mechanismZh : item.mechanismEn}
                    </div>
                  </td>
                  <td className="py-3 px-3 whitespace-nowrap font-mono text-[var(--app-text-secondary)]">
                    <div>{item.model}</div>
                    <div className="text-xs text-[var(--app-text-tertiary)]">
                      {item.prompt}
                    </div>
                  </td>
                  <td
                    className={`py-3 px-3 text-right font-mono font-semibold whitespace-nowrap ${
                      item.totalReturn.startsWith('+')
                        ? 'text-[var(--app-success-text)]'
                        : item.totalReturn === '-0.06%'
                          ? 'text-[var(--app-text)]'
                          : 'text-[var(--app-danger-text)]'
                    }`}
                  >
                    {item.totalReturn}
                  </td>
                  <td className="py-3 px-3 text-right font-mono font-semibold whitespace-nowrap text-[var(--app-text)]">
                    {item.maxDrawdown}
                  </td>
                  <td className="py-3 px-3 text-right font-mono whitespace-nowrap text-[var(--app-text-secondary)]">
                    {item.sharpe}
                  </td>
                  <td className="py-3 px-3 whitespace-nowrap">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold border ${
                        isActive
                          ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                          : 'border-[var(--app-divider)] bg-[var(--app-surface-overlay)] text-[var(--app-text-tertiary)]'
                      }`}
                    >
                      {isZh ? item.statusZh : item.statusEn}
                    </span>
                  </td>
                  <td className="py-3 pl-3 text-right whitespace-nowrap">
                    {item.resultId ? (
                      <a
                        href={`/backtest?result_id=${item.resultId}`}
                        onClick={(e) =>
                          handleClientNavigation(
                            e,
                            `/backtest?result_id=${item.resultId}`,
                          )
                        }
                        className="font-mono text-[var(--app-accent)] hover:underline font-semibold"
                      >
                        #{item.resultId}
                      </a>
                    ) : (
                      '--'
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
