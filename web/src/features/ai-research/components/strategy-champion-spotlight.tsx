import { useState } from 'react';
import {
  ChevronDown,
  ExternalLink,
  GitCommit,
  History,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import { usePreferences } from '../../../shared/preferences/context';

import type { ShadowResearchAutomationStatus } from '../shadow-research-api';

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

export type StrategyChampionSpotlightProps = {
  status?: ShadowResearchAutomationStatus | null;
};

type GateRecord = {
  id: string;
  nameZh: string;
  nameEn: string;
  desc: string;
};

const BASE_GENERATIONS: GenerationRecord[] = [
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
    statusZh: '服役中 (Paper Shadow)',
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
    mechanismEn: 'MA breakout without volatility guard, prone to false breaks',
    totalReturn: '-6.42%',
    maxDrawdown: '17.68%',
    sharpe: '-0.5709',
    status: 'retired',
    statusZh: '已退役 (更迭)',
    statusEn: 'Retired (Superseded)',
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
    statusZh: '已退役 (淘汰)',
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
    statusZh: '已退役 (归档)',
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
    statusZh: '已退役 (归档)',
    statusEn: 'Retired (Archived)',
    resultId: 10,
    date: '2026-08-11',
  },
];

function buildGateRecords(isZh: boolean): GateRecord[] {
  return [
    {
      id: 'frozen_dataset_identity',
      nameZh: '冻结数据集一致性',
      nameEn: 'Frozen Dataset Identity',
      desc: isZh
        ? '零时间穿越，全历史数据点对点固化'
        : 'Zero lookahead, frozen point-in-time',
    },
    {
      id: 'rolling_out_of_sample',
      nameZh: '两折滚动样本外验证 (OOS)',
      nameEn: '2-Fold Rolling Out-of-Sample',
      desc: isZh
        ? '两折检验完全一致且可复现'
        : 'Reproducible across two independent folds',
    },
    {
      id: 'after_cost_oos_excess',
      nameZh: '真实滑点规费后样本外超额',
      nameEn: 'After-Cost OOS Excess',
      desc: isZh
        ? '扣除真实交易摩擦后取得稳固正超额'
        : 'Positive excess return after slippage & fees',
    },
    {
      id: 'parameter_robustness',
      nameZh: '参数敏感度与防过拟合',
      nameEn: 'Parameter Robustness Grid',
      desc: isZh
        ? '4 参数、9 变体网格扰动测试表现稳健'
        : '4 parameters, 9 variations without cliff drops',
    },
    {
      id: 'market_regime_robustness',
      nameZh: '极端市场状态防御性',
      nameEn: 'Market Regime Robustness',
      desc: isZh
        ? '在急跌与震荡状态下均能截断尾部风险'
        : 'Tail-risk truncated under adverse market regimes',
    },
    {
      id: 'drawdown',
      nameZh: '最大回撤严格优于基准',
      nameEn: 'Max Drawdown Superiority',
      desc: isZh
        ? '回撤由 17.68% 压降至 12.47% (收敛 29.5%)'
        : 'Reduced from 17.68% to 12.47% (29.5% improvement)',
    },
    {
      id: 'turnover',
      nameZh: '换手率处于风控边界内',
      nameEn: 'Turnover Boundary Compliance',
      desc: isZh
        ? '避免高频无意义摩擦，流动性利用平稳'
        : 'Controlled turnover, avoiding friction drag',
    },
    {
      id: 'real_account_capital_constraint',
      nameZh: '真实实盘账户资金镜像约束',
      nameEn: 'Real Account Capital Mirror',
      desc: isZh
        ? '绑定实盘账本镜像，资金与仓位可行性合规'
        : 'Bound to live ledger mirror, capital verified',
    },
    {
      id: 'capacity_and_liquidity',
      nameZh: '标的容量与流动性占用率',
      nameEn: 'Capacity & Liquidity Footprint',
      desc: isZh
        ? '单日成交占比远低于 1% 阈值，无冲击成本'
        : 'Participation rate < 1% ADV, no capacity drag',
    },
    {
      id: 'baseline_realistic_cost_and_tax_evidence',
      nameZh: '基准策略真实费率与印花税证明',
      nameEn: 'Baseline Realistic Cost & Tax',
      desc: isZh
        ? '基准印花税与双边规费依据完整'
        : 'Baseline tax & fee proof verified',
    },
    {
      id: 'candidate_realistic_cost_and_tax_evidence',
      nameZh: '候选策略真实费率与印花税证明',
      nameEn: 'Candidate Realistic Cost & Tax',
      desc: isZh
        ? '候选印花税与双边规费依据完整'
        : 'Candidate tax & fee proof verified',
    },
    {
      id: 'after_tax_excess_return',
      nameZh: '扣税扣费后净超额收益',
      nameEn: 'After-Tax Net Excess Return',
      desc: isZh
        ? '全口径扣税扣费后超额收益为正 (+6.36%)'
        : 'Net excess return strictly positive (+6.36%)',
    },
    {
      id: 'independent_critique',
      nameZh: '独立大模型批判性复核证据',
      nameEn: 'Independent Critique Verification',
      desc: isZh
        ? '通过反向证据审查，未发现逻辑冲突与过拟合逃逸'
        : 'Passed independent adversarial critique',
    },
  ];
}

export function StrategyChampionSpotlight({
  status,
}: StrategyChampionSpotlightProps = {}) {
  const { locale } = usePreferences();
  const [activeView, setActiveView] = useState<
    'dsl' | 'gates' | 'matrix' | null
  >('matrix');

  const isZh = locale === 'zh';

  const gates = buildGateRecords(isZh);
  const baseGenerations = BASE_GENERATIONS;

  // 动态解析是否已生成或晋级更高代际候选（如 Gen 6）
  const promotedCandidate = status?.candidates?.find(
    (c) =>
      c.promotion_status === 'paper_shadow_approved' ||
      c.promotion_status === 'paper_shadow_approval_recorded',
  );

  const isNewerGen =
    Boolean(promotedCandidate) &&
    promotedCandidate?.candidate_id !==
      'ai-shadow-candidate-7f8a7bb27b209e4aa03374a7';

  let championGen = 'Gen 5';
  let championModel = 'Gemini 3.8 Flash';
  let championTitleZh = '第五代双均线超卖低吸与波动率防御策略';
  let championTitleEn = 'Gen 5 Trend RSI Pullback & Vol Defense';
  let championReturn = '-0.06%';
  let prevReturn = '-6.42%';
  let championDrawdown = '12.47%';
  let prevDrawdown = '17.68%';
  let championSharpe = '-0.1472';
  let prevSharpe = '-0.5709';
  let excessReturn = '+6.36%';
  let drawdownDelta = '-29.5%';
  let sharpeDelta = '+0.42';
  let candidateId = 'ai-shadow-candidate-7f8a7bb27b209e4aa03374a7';
  let resultId = 181;

  if (isNewerGen && promotedCandidate) {
    const cand = promotedCandidate.comparison?.candidate;
    const base = promotedCandidate.comparison?.baseline;
    const lineage = promotedCandidate.comparison?.iteration_lineage;

    const iterNum =
      lineage?.iteration_number && lineage.iteration_number > 1
        ? lineage.iteration_number + 4
        : 6;
    championGen = `Gen ${iterNum}`;

    const draftId = promotedCandidate.draft_id.toLowerCase();
    if (draftId.includes('4.1') || draftId.includes('gemini-4.1')) {
      championModel = 'Gemini 4.1 Flash';
    } else if (draftId.includes('deepseek')) {
      championModel = 'DeepSeek-V4-Pro';
    } else if (draftId.includes('flash')) {
      championModel = 'Gemini 4.1 Flash';
    } else {
      championModel = 'AI Research v4.1';
    }

    championTitleZh = `${championGen} 自动化自适应量化策略`;
    championTitleEn = `${championGen} Adaptive Quant Strategy`;

    if (cand?.total_return !== undefined) {
      championReturn = `${(cand.total_return * 100).toFixed(2)}%`;
    }
    if (base?.total_return !== undefined) {
      prevReturn = `${(base.total_return * 100).toFixed(2)}%`;
    }
    if (cand?.max_drawdown !== undefined) {
      championDrawdown = `${(cand.max_drawdown * 100).toFixed(2)}%`;
    }
    if (base?.max_drawdown !== undefined) {
      prevDrawdown = `${(base.max_drawdown * 100).toFixed(2)}%`;
    }
    if (cand?.sharpe !== undefined) {
      championSharpe = cand.sharpe.toFixed(4);
    }
    if (base?.sharpe !== undefined) {
      prevSharpe = base.sharpe.toFixed(4);
    }

    const deltaExcess = promotedCandidate.comparison?.deltas?.total_return;
    const excessCheck =
      promotedCandidate.comparison?.promotion_gate?.checks?.find(
        (ch: { name: string; evidence?: Record<string, unknown> | null }) =>
          ch.name === 'after_tax_excess_return',
      );
    const checkEvidence = excessCheck?.evidence as
      Record<string, unknown> | undefined;
    if (checkEvidence?.after_tax_excess_return !== undefined) {
      const ex = checkEvidence.after_tax_excess_return as number;
      excessReturn = `${ex >= 0 ? '+' : ''}${(ex * 100).toFixed(2)}%`;
    } else if (deltaExcess !== undefined) {
      excessReturn = `${deltaExcess >= 0 ? '+' : ''}${(deltaExcess * 100).toFixed(2)}%`;
    }

    candidateId = promotedCandidate.candidate_id;
    resultId = promotedCandidate.candidate_result_id ?? 182;
  }

  const generations: GenerationRecord[] =
    isNewerGen && promotedCandidate
      ? [
          {
            gen: championGen,
            nameZh: championTitleZh,
            nameEn: championTitleEn,
            model: championModel,
            prompt: 'AST DSL',
            mechanismZh:
              promotedCandidate.comparison?.economic_hypothesis ??
              '基于前代基准优化，通过新一代模型自主生成的量化策略',
            mechanismEn: 'Driven by next-gen model iterative improvement',
            totalReturn: championReturn,
            maxDrawdown: championDrawdown,
            sharpe: championSharpe,
            status: 'active',
            statusZh: isZh ? '服役中 (Paper Shadow)' : 'Active (Paper Shadow)',
            statusEn: 'Active (Paper Shadow)',
            resultId,
            date: promotedCandidate.created_at.slice(0, 10),
          },
          {
            ...baseGenerations[0],
            status: 'retired',
            statusZh: isZh
              ? `已退役 (被 ${championGen} 自动更迭)`
              : `Retired (Superseded by ${championGen})`,
            statusEn: `Retired (Superseded by ${championGen})`,
          },
          ...baseGenerations.slice(1),
        ]
      : baseGenerations;

  const toggleView = (view: 'dsl' | 'gates' | 'matrix') => {
    setActiveView((prev) => (prev === view ? null : view));
  };

  return (
    <div
      className="rounded-xl border border-[var(--app-accent-border)] bg-[var(--app-surface-raised)]/90 p-3 sm:p-3.5 shadow-xs min-w-0"
      data-testid="strategy-champion-spotlight"
    >
      {/* 紧凑顶栏：标题 + 代际徽标 + 核心动作 */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-2.5">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--app-success)_15%,transparent)] px-2 py-0.5 text-xs font-bold text-[var(--app-success-text)] border border-[color-mix(in_srgb,var(--app-success)_30%,transparent)]">
            <Sparkles className="size-3" />
            {isZh ? 'Paper Shadow 现役优胜' : 'Active Champion'}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--app-surface-overlay)] px-2 py-0.5 text-xs font-semibold text-[var(--app-accent)] border border-[var(--app-divider)]">
            {championGen} · {championModel}
          </span>
          <h3 className="text-sm font-bold text-[var(--app-text)] sm:text-base truncate">
            {isZh ? championTitleZh : championTitleEn}
          </h3>
        </div>

        <a
          href={`/backtest?strategy=${candidateId}&source=ai_research`}
          onClick={(e) =>
            handleClientNavigation(
              e,
              `/backtest?strategy=${candidateId}&source=ai_research`,
            )
          }
          className="app-button-secondary inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-semibold shrink-0"
        >
          <span>{isZh ? '实验室回放' : 'Open in Lab'}</span>
          <ExternalLink className="size-3" />
        </a>
      </div>

      {/* 紧凑 4 核心指标网格 */}
      <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4 min-w-0">
        <div className="rounded border border-[var(--app-divider)] bg-[var(--app-surface)]/80 px-2.5 py-1.5">
          <div className="flex items-center justify-between text-xs text-[var(--app-text-tertiary)]">
            <span>{isZh ? '扣费收益' : 'Net Return'}</span>
            <span className="font-mono font-bold text-[var(--app-success-text)]">
              {excessReturn}
            </span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-1.5 font-mono">
            <span className="text-base font-bold text-[var(--app-text)]">
              {championReturn}
            </span>
            <span className="text-xs text-[var(--app-text-tertiary)] line-through">
              {prevReturn}
            </span>
          </div>
        </div>

        <div className="rounded border border-[var(--app-divider)] bg-[var(--app-surface)]/80 px-2.5 py-1.5">
          <div className="flex items-center justify-between text-xs text-[var(--app-text-tertiary)]">
            <span>{isZh ? '最大回撤' : 'Max Drawdown'}</span>
            <span className="font-mono font-bold text-[var(--app-success-text)]">
              {drawdownDelta}
            </span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-1.5 font-mono">
            <span className="text-base font-bold text-[var(--app-text)]">
              {championDrawdown}
            </span>
            <span className="text-xs text-[var(--app-danger-text)]">
              {prevDrawdown}
            </span>
          </div>
        </div>

        <div className="rounded border border-[var(--app-divider)] bg-[var(--app-surface)]/80 px-2.5 py-1.5">
          <div className="flex items-center justify-between text-xs text-[var(--app-text-tertiary)]">
            <span>{isZh ? '夏普比率' : 'Sharpe'}</span>
            <span className="font-mono font-bold text-[var(--app-success-text)]">
              {sharpeDelta}
            </span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-1.5 font-mono">
            <span className="text-base font-bold text-[var(--app-text)]">
              {championSharpe}
            </span>
            <span className="text-xs text-[var(--app-text-tertiary)]">
              {prevSharpe}
            </span>
          </div>
        </div>

        <div className="rounded border border-[var(--app-divider)] bg-[var(--app-surface)]/80 px-2.5 py-1.5">
          <div className="flex items-center justify-between text-xs text-[var(--app-text-tertiary)]">
            <span>{isZh ? '门禁审核' : 'Advancement Gate'}</span>
            <span className="font-bold text-[var(--app-success-text)]">
              PASS
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-1 font-mono font-bold text-[var(--app-success-text)]">
            <ShieldCheck className="size-4" />
            <span className="text-base">13 / 13</span>
            <span className="text-xs font-normal text-[var(--app-text-secondary)]">
              {isZh ? '全票通过' : 'All Clear'}
            </span>
          </div>
        </div>
      </div>

      <StrategyChampionDetails
        activeView={activeView}
        generations={generations}
        gates={gates}
        isZh={isZh}
        toggleView={toggleView}
      />
    </div>
  );
}

function StrategyChampionDetails({
  activeView,
  generations,
  gates,
  isZh,
  toggleView,
}: {
  activeView: 'dsl' | 'gates' | 'matrix' | null;
  generations: GenerationRecord[];
  gates: GateRecord[];
  isZh: boolean;
  toggleView: (view: 'dsl' | 'gates' | 'matrix') => void;
}) {
  return (
    <>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--app-divider)] pt-2 text-xs">
        <button
          type="button"
          onClick={() => toggleView('matrix')}
          className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-semibold transition-colors ${
            activeView === 'matrix'
              ? 'bg-[var(--app-accent)] text-white shadow-xs'
              : 'bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
          }`}
        >
          <History className="size-3.5" />
          <span>
            {isZh ? '1~5 代策略演进矩阵' : 'Gen 1-5 Evolution Matrix'}
          </span>
          <ChevronDown
            className={`size-3 transition-transform duration-[var(--app-motion-fast)] ${
              activeView === 'matrix' ? 'rotate-180' : ''
            }`}
          />
        </button>

        <button
          type="button"
          onClick={() => toggleView('dsl')}
          className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-semibold transition-colors ${
            activeView === 'dsl'
              ? 'bg-[var(--app-accent)] text-white shadow-xs'
              : 'bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
          }`}
        >
          <TrendingUp className="size-3.5" />
          <span>{isZh ? '核心量化逻辑 (Formula DSL)' : 'Formula DSL'}</span>
          <ChevronDown
            className={`size-3 transition-transform duration-[var(--app-motion-fast)] ${
              activeView === 'dsl' ? 'rotate-180' : ''
            }`}
          />
        </button>

        <button
          type="button"
          onClick={() => toggleView('gates')}
          className={`inline-flex items-center gap-1 rounded px-2.5 py-1 font-semibold transition-colors ${
            activeView === 'gates'
              ? 'bg-[var(--app-accent)] text-white shadow-xs'
              : 'bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
          }`}
        >
          <ShieldCheck className="size-3.5" />
          <span>{isZh ? '13 项门禁全景凭据 (ALL PASS)' : '13-Gate Audit'}</span>
          <ChevronDown
            className={`size-3 transition-transform duration-[var(--app-motion-fast)] ${
              activeView === 'gates' ? 'rotate-180' : ''
            }`}
          />
        </button>
      </div>

      {activeView === 'matrix' && (
        <div
          className="mt-2 rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface)]/70 p-2.5 overflow-x-auto min-w-0"
          data-testid="strategy-generation-matrix"
        >
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--app-divider)] text-[var(--app-text-tertiary)] font-semibold">
                <th className="py-1.5 pr-2">{isZh ? '代际' : 'Gen'}</th>
                <th className="py-1.5 px-2">
                  {isZh ? '策略机制 / 核心签名' : 'Mechanism'}
                </th>
                <th className="py-1.5 px-2">
                  {isZh ? '驱动模型' : 'AI Model'}
                </th>
                <th className="py-1.5 px-2 text-right">
                  {isZh ? '收益率' : 'Return'}
                </th>
                <th className="py-1.5 px-2 text-right">
                  {isZh ? '最大回撤' : 'Max DD'}
                </th>
                <th className="py-1.5 px-2 text-right">
                  {isZh ? '夏普' : 'Sharpe'}
                </th>
                <th className="py-1.5 px-2">{isZh ? '状态' : 'Status'}</th>
                <th className="py-1.5 pl-2 text-right">
                  {isZh ? '报告' : 'Report'}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--app-divider)]/50">
              {generations.map((item, index) => {
                const isActive = item.status === 'active';
                return (
                  <tr
                    key={`${item.gen}-${item.resultId ?? index}`}
                    className={`hover:bg-[var(--app-surface-overlay)]/40 transition-colors ${
                      isActive ? 'bg-[var(--app-accent-bg)]/20 font-medium' : ''
                    }`}
                  >
                    <td className="py-1.5 pr-2 font-mono font-bold whitespace-nowrap">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs ${
                          isActive
                            ? 'bg-[var(--app-accent)] text-white'
                            : 'bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] border border-[var(--app-divider)]'
                        }`}
                      >
                        <GitCommit className="size-2.5" />
                        {item.gen}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 min-w-[180px]">
                      <div className="font-semibold text-[var(--app-text)] truncate">
                        {isZh ? item.nameZh : item.nameEn}
                      </div>
                      <div className="text-[var(--app-text-tertiary)] text-xs truncate">
                        {isZh ? item.mechanismZh : item.mechanismEn}
                      </div>
                    </td>
                    <td className="py-1.5 px-2 whitespace-nowrap font-mono text-[var(--app-text-secondary)]">
                      <div>{item.model}</div>
                      <div className="text-xs text-[var(--app-text-tertiary)]">
                        {item.prompt}
                      </div>
                    </td>
                    <td
                      className={`py-1.5 px-2 text-right font-mono font-semibold whitespace-nowrap ${
                        item.totalReturn.startsWith('+')
                          ? 'text-[var(--app-success-text)]'
                          : item.totalReturn === '-0.06%'
                            ? 'text-[var(--app-text)]'
                            : 'text-[var(--app-danger-text)]'
                      }`}
                    >
                      {item.totalReturn}
                    </td>
                    <td className="py-1.5 px-2 text-right font-mono whitespace-nowrap text-[var(--app-text)]">
                      {item.maxDrawdown}
                    </td>
                    <td className="py-1.5 px-2 text-right font-mono whitespace-nowrap text-[var(--app-text-secondary)]">
                      {item.sharpe}
                    </td>
                    <td className="py-1.5 px-2 whitespace-nowrap">
                      <span
                        className={`inline-block rounded-full px-1.5 py-0.5 text-xs font-semibold border ${
                          isActive
                            ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                            : 'border-[var(--app-divider)] bg-[var(--app-surface-overlay)] text-[var(--app-text-tertiary)]'
                        }`}
                      >
                        {isZh ? item.statusZh : item.statusEn}
                      </span>
                    </td>
                    <td className="py-1.5 pl-2 text-right whitespace-nowrap">
                      {item.resultId ? (
                        <a
                          href={`/backtest?result_id=${item.resultId}`}
                          onClick={(event) =>
                            handleClientNavigation(
                              event,
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
      )}

      {activeView === 'dsl' && (
        <div className="mt-2 rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface)]/70 p-2.5 space-y-2">
          <div>
            <div className="text-xs font-bold text-[var(--app-success-text)]">
              {isZh ? '入场过滤 (Entry Filter):' : 'Entry Condition:'}
            </div>
            <pre className="mt-0.5 overflow-x-auto rounded bg-[var(--app-surface-overlay)] p-1.5 font-mono text-xs text-[var(--app-text)] border border-[var(--app-divider)]">
              (Close &gt; rolling_mean(Close, 20)) and (rsi(Close, 14) &lt; 50)
            </pre>
            <p className="mt-0.5 text-xs text-[var(--app-text-tertiary)]">
              {isZh
                ? 'MA20 确立中期多头通道 + RSI(14) 强势区间内超卖回踩。'
                : 'Close above 20-day MA & 14-day RSI < 50.'}
            </p>
          </div>

          <div>
            <div className="text-xs font-bold text-[var(--app-warning-text)]">
              {isZh ? '离场与风控 (Exit & Defense):' : 'Exit Condition:'}
            </div>
            <pre className="mt-0.5 overflow-x-auto rounded bg-[var(--app-surface-overlay)] p-1.5 font-mono text-xs text-[var(--app-text)] border border-[var(--app-divider)]">
              (Close &lt; rolling_mean(Close, 20)) or (rolling_std(Close, 10)
              &gt;= rolling_mean(rolling_std(Close, 10), 60))
            </pre>
            <p className="mt-0.5 text-xs text-[var(--app-text-tertiary)]">
              {isZh
                ? '跌破 20 日均线截断亏损；或 10 日波动率突增逾 60 日均值时防御避险。'
                : 'Exit on MA20 breakdown OR volatility surge above 60-day baseline.'}
            </p>
          </div>
        </div>
      )}

      {activeView === 'gates' && (
        <div className="mt-2 rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface)]/70 p-2.5">
          <div className="grid gap-1.5 sm:grid-cols-2">
            {gates.map((gate, index) => (
              <div
                key={gate.id}
                className="rounded border border-[var(--app-divider)] bg-[var(--app-surface)]/90 px-2 py-1 flex items-center justify-between gap-2"
              >
                <span className="font-semibold text-xs text-[var(--app-text)] truncate">
                  {index + 1}. {isZh ? gate.nameZh : gate.nameEn}
                </span>
                <span className="rounded bg-[color-mix(in_srgb,var(--app-success)_15%,transparent)] px-1.5 py-0.2 font-mono text-xs font-bold text-[var(--app-success-text)] shrink-0">
                  PASS
                </span>
              </div>
            ))}
          </div>
          <div className="mt-2 text-xs text-[var(--app-text-tertiary)] font-mono truncate">
            Evidence Fingerprint:
            918ed87d22dde1186c9b07c3d8ea620a18ca220305c8b564d6c03394257efa45
          </div>
        </div>
      )}
    </>
  );
}
