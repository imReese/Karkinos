import { lazy } from 'react';
import {
  createRoute,
  createRootRoute,
  createRouter,
  Outlet,
  useRouterState,
} from '@tanstack/react-router';

const AppShell = lazy(() =>
  import('./layout/app-shell').then((module) => ({
    default: module.AppShell,
  })),
);

function RoutePending() {
  return (
    <div
      aria-busy="true"
      className="grid min-h-[50vh] w-full place-items-center px-4 py-12"
      data-testid="route-pending"
    >
      <div
        aria-live="polite"
        className="text-sm font-medium text-[var(--app-text-secondary)]"
        role="status"
      >
        Loading Karkinos…
      </div>
    </div>
  );
}

function RootLayout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });

  if (pathname === '/') {
    return <Outlet />;
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

const rootRoute = createRootRoute({
  component: RootLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
}).lazy(() =>
  import('../features/home/pages/public-home-page').then(
    (module) => module.Route,
  ),
);

const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/overview',
}).lazy(() =>
  import('../features/overview/pages/overview-page').then(
    (module) => module.Route,
  ),
);

const portfolioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/portfolio',
  validateSearch: (search: Record<string, unknown>) => ({
    assetClass:
      typeof search.assetClass === 'string' && search.assetClass.length > 0
        ? search.assetClass
        : 'all',
    pnl:
      search.pnl === 'winners' ||
      search.pnl === 'losers' ||
      search.pnl === 'all'
        ? search.pnl
        : 'all',
    q: typeof search.q === 'string' ? search.q : '',
  }),
}).lazy(() =>
  import('../features/portfolio/pages/portfolio-page').then(
    (module) => module.Route,
  ),
);

const holdingDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/portfolio/$symbol',
}).lazy(() =>
  import('../features/portfolio/pages/holding-detail-page').then(
    (module) => module.Route,
  ),
);

const activityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/activity',
}).lazy(() =>
  import('../features/activity/pages/activity-page').then(
    (module) => module.Route,
  ),
);

const riskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/risk',
}).lazy(() =>
  import('../features/risk/pages/risk-page').then((module) => module.Route),
);

const accountTruthRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/account-truth',
}).lazy(() =>
  import('../features/account-truth/pages/account-truth-page').then(
    (module) => module.Route,
  ),
);

const decisionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/decision',
}).lazy(() =>
  import('../features/decision/pages/decision-page').then(
    (module) => module.Route,
  ),
);

const operationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/operations',
}).lazy(() =>
  import('../features/operations/pages/operations-page').then(
    (module) => module.Route,
  ),
);

const marketRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/market',
}).lazy(() =>
  import('../features/market/pages/market-page').then((module) => module.Route),
);

const tradingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/trading',
}).lazy(() =>
  import('../features/trading/pages/trading-page').then(
    (module) => module.Route,
  ),
);

const backtestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/backtest',
}).lazy(() =>
  import('../features/backtest/pages/backtest-page').then(
    (module) => module.Route,
  ),
);

const aiResearchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ai-research',
}).lazy(() =>
  import('../features/ai-research/pages/ai-research-page').then(
    (module) => module.Route,
  ),
);

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
}).lazy(() =>
  import('../features/settings/pages/settings-page').then(
    (module) => module.Route,
  ),
);

const routeTree = rootRoute.addChildren([
  indexRoute,
  overviewRoute,
  portfolioRoute,
  holdingDetailRoute,
  activityRoute,
  riskRoute,
  accountTruthRoute,
  decisionRoute,
  operationsRoute,
  marketRoute,
  tradingRoute,
  backtestRoute,
  aiResearchRoute,
  settingsRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPendingComponent: RoutePending,
  defaultPendingMs: 0,
  defaultPendingMinMs: 0,
  defaultPreload: 'intent',
});

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
