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

export const NAVIGATION_GROUPS = [
  {
    key: 'monitor',
    label: { en: 'Monitor', zh: '监控' },
    items: [
      { to: OVERVIEW_ROUTE, key: 'overview', icon: OverviewNavIcon },
      { to: '/portfolio', key: 'portfolio', icon: PortfolioNavIcon },
      { to: '/market', key: 'market', icon: MarketNavIcon },
    ],
  },
  {
    key: 'decide',
    label: { en: 'Decide', zh: '研判' },
    items: [
      { to: '/decision', key: 'decision', icon: DecisionNavIcon },
      { to: '/risk', key: 'risk', icon: RiskNavIcon },
      { to: '/ai-research', key: 'aiResearch', icon: AiResearchNavIcon },
      { to: '/backtest', key: 'backtest', icon: BacktestNavIcon },
    ],
  },
  {
    key: 'execute',
    label: { en: 'Execute', zh: '执行与审计' },
    items: [
      { to: '/trading', key: 'trading', icon: TradingNavIcon },
      { to: '/operations', key: 'operations', icon: OperationsNavIcon },
      { to: '/activity', key: 'activity', icon: ActivityNavIcon },
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
  NAVIGATION_GROUPS[1].items[0],
] as const;

export function isNavigationItemActive(pathname: string, target: string) {
  return pathname === target || pathname.startsWith(target + '/');
}
