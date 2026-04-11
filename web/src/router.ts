import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('./views/DashboardView.vue') },
    { path: '/portfolio', name: 'portfolio', component: () => import('./views/PortfolioView.vue') },
    { path: '/trade', name: 'trade', component: () => import('./views/TradeView.vue') },
    { path: '/market', name: 'market', component: () => import('./views/MarketView.vue') },
    { path: '/signals', name: 'signals', component: () => import('./views/SignalsView.vue') },
    { path: '/backtest', name: 'backtest', component: () => import('./views/BacktestView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue') },
  ],
})

export default router
