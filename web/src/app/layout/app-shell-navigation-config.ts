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
    key: 'workspace',
    label: { en: 'Workspace', zh: '工作台' },
    items: [{ to: OVERVIEW_ROUTE, key: 'overview', icon: OverviewNavIcon }],
  },
  {
    key: 'invest',
    label: { en: 'Invest', zh: '投资' },
    items: [
      { to: '/portfolio', key: 'portfolio', icon: PortfolioNavIcon },
      { to: '/market', key: 'market', icon: MarketNavIcon },
    ],
  },
  {
    key: 'research',
    label: { en: 'Research', zh: '研究' },
    items: [
      { to: '/backtest', key: 'backtest', icon: BacktestNavIcon },
      { to: '/ai-research', key: 'aiResearch', icon: AiResearchNavIcon },
    ],
  },
  {
    key: 'act',
    label: { en: 'Act', zh: '行动' },
    items: [
      { to: '/decision', key: 'decision', icon: DecisionNavIcon },
      { to: '/trading', key: 'trading', icon: TradingNavIcon },
    ],
  },
  {
    key: 'control',
    label: { en: 'Control', zh: '控制' },
    items: [
      { to: '/risk', key: 'risk', icon: RiskNavIcon },
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
  NAVIGATION_GROUPS[3].items[0],
] as const;

export function isNavigationItemActive(pathname: string, target: string) {
  return pathname === target || pathname.startsWith(target + '/');
}
