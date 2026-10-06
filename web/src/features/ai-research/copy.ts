import type { Locale } from '../../shared/locale';

export const aiResearchPageCopy = {
  en: {
    kicker: 'AI research',
    title: 'Research review',
    subtitle:
      'Review quantitative research hypotheses, shadow evolution, and model evidence.',
    context: 'Advisory Research',
    openStrategyLab: 'Open Strategy Backtest',
    contextTitle: 'Evidence available to new tasks',
    contextDetail: 'A task can bind only the saved account context shown here.',
    backtestContext: 'Backtest context',
    strategyContext: 'Strategy context',
    available: 'Available',
    unavailable: 'Unavailable',
    savedBacktest: (id: number) => `Saved backtest #${id}`,
    backtestLoadFailed: 'Saved reports could not be read',
    noSavedBacktest: 'No saved backtest is available',
    persistedAssignment: 'Current account assignment',
    strategyLoadFailed: 'Strategy assignment could not be read',
    noStrategyAssignment: 'No account strategy is assigned',
    tabs: {
      all: 'All Workspaces',
      shadow: 'Shadow Evolution',
      tasks: 'Research Tasks',
    },
  },
  zh: {
    kicker: 'AI 投研',
    title: '研究复核',
    subtitle: '复核量化研究假说、Shadow 策略演化与模型证据。',
    context: '投研实验',
    openStrategyLab: '打开策略回测',
    contextTitle: '新任务可用证据',
    contextDetail: '研究任务只能绑定此处展示的已保存账户上下文。',
    backtestContext: '回测上下文',
    strategyContext: '策略上下文',
    available: '可用',
    unavailable: '不可用',
    savedBacktest: (id: number) => `已保存回测 #${id}`,
    backtestLoadFailed: '无法读取已保存报告',
    noSavedBacktest: '暂无已保存回测',
    persistedAssignment: '当前账户策略绑定',
    strategyLoadFailed: '无法读取策略绑定',
    noStrategyAssignment: '尚未绑定账户策略',
    tabs: {
      all: '全部工作台',
      shadow: 'Shadow 策略演化',
      tasks: '人机投研任务',
    },
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type AiResearchPageCopy = (typeof aiResearchPageCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    aiResearchPage: AiResearchPageCopy;
  }
}
