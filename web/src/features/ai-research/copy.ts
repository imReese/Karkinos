import type { Locale } from '../../shared/locale';

export const aiResearchPageCopy = {
  en: {
    kicker: 'AI research',
    title: 'Research review',
    subtitle:
      'Review cited research against saved account evidence, then record a human conclusion. Nothing here can place an order.',
    context: 'Human-started · saved evidence · advisory only',
    openStrategyLab: 'Open Strategy Lab',
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
  },
  zh: {
    kicker: 'AI 研究',
    title: '研究复核',
    subtitle:
      '依据已保存的账户证据复核研究结论，并记录人工判断；本页不能提交订单。',
    context: '人工启动 · 已保存证据 · 仅供研究',
    openStrategyLab: '打开策略实验',
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
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type AiResearchPageCopy = (typeof aiResearchPageCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    aiResearchPage: AiResearchPageCopy;
  }
}
