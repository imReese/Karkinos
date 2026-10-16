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

export const OVERVIEW_ROUTE = '/overview';
export const MARKET_ROUTE = '/market';

export const NAVIGATION_GROUPS = [
  {
    key: 'portfolio',
    label: { en: 'Investment', zh: '投资工作台' },
    items: [
      { to: OVERVIEW_ROUTE, key: 'overview', icon: OverviewNavIcon },
      { to: '/portfolio', key: 'portfolio', icon: PortfolioNavIcon },
      { to: '/decision', key: 'decision', icon: DecisionNavIcon },
      { to: '/risk', key: 'risk', icon: RiskNavIcon },
    ],
  },
  {
    key: 'research',
    label: { en: 'Research & validation', zh: '研究与验证' },
    items: [
      { to: '/ai-research', key: 'aiResearch', icon: AiResearchNavIcon },
      { to: '/backtest', key: 'backtest', icon: BacktestNavIcon },
      { to: MARKET_ROUTE, key: 'market', icon: MarketNavIcon },
    ],
  },
  {
    key: 'execute',
    label: { en: 'Execution & records', zh: '执行与记录' },
    items: [
      { to: '/trading', key: 'trading', icon: TradingNavIcon },
      { to: '/activity', key: 'activity', icon: ActivityNavIcon },
    ],
  },
  {
    key: 'system',
    label: { en: 'System', zh: '系统' },
    items: [
      { to: '/operations', key: 'operations', icon: OperationsNavIcon },
      { to: '/settings', key: 'settings', icon: SettingsNavIcon },
    ],
  },
] as const;

export const MOBILE_PRIMARY_ITEMS = [
  NAVIGATION_GROUPS[0].items[0],
  NAVIGATION_GROUPS[1].items[0],
  NAVIGATION_GROUPS[0].items[1],
  NAVIGATION_GROUPS[0].items[2],
] as const;

export function isNavigationItemActive(pathname: string, target: string) {
  return pathname === target || pathname.startsWith(target + '/');
}
