import {
  ActivityNavIcon,
  AiResearchNavIcon,
  BacktestNavIcon,
  DecisionNavIcon,
  MarketNavIcon,
  OperationsNavIcon,
  OverviewNavIcon,
  PortfolioNavIcon,
  RiskNavIcon,
  SettingsNavIcon,
  TradingNavIcon,
} from './app-shell-icons';

export const NAVIGATION_GROUPS = [
  {
    key: 'portfolio',
    label: { en: 'Portfolio', zh: '组合管理' },
    items: [
      { to: '/overview', key: 'overview', icon: OverviewNavIcon },
      { to: '/portfolio', key: 'portfolio', icon: PortfolioNavIcon },
      { to: '/activity', key: 'activity', icon: ActivityNavIcon },
      { to: '/market', key: 'market', icon: MarketNavIcon },
    ],
  },
  {
    key: 'research',
    label: { en: 'Research', zh: '研究' },
    items: [
      { to: '/backtest', key: 'backtest', icon: BacktestNavIcon },
      {
        to: '/ai-research',
        key: 'aiResearch',
        icon: AiResearchNavIcon,
      },
    ],
  },
  {
    key: 'decision-risk',
    label: { en: 'Decision & Risk', zh: '决策与风控' },
    items: [
      { to: '/decision', key: 'decision', icon: DecisionNavIcon },
      { to: '/risk', key: 'risk', icon: RiskNavIcon },
    ],
  },
  {
    key: 'execution-operations',
    label: { en: 'Execution & Operations', zh: '执行与运营' },
    items: [
      { to: '/operations', key: 'operations', icon: OperationsNavIcon },
      { to: '/trading', key: 'trading', icon: TradingNavIcon },
    ],
  },
  {
    key: 'system',
    label: { en: 'System', zh: '系统' },
    items: [{ to: '/settings', key: 'settings', icon: SettingsNavIcon }],
  },
] as const;

export const MOBILE_PRIMARY_ITEMS = [
  NAVIGATION_GROUPS[0].items[0],
  NAVIGATION_GROUPS[0].items[1],
  NAVIGATION_GROUPS[2].items[0],
] as const;

export function isNavigationItemActive(pathname: string, target: string) {
  return pathname === target || pathname.startsWith(`${target}/`);
}
