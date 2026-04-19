import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export interface AllocationItem {
  symbol: string
  name: string
  weight: number
  value: number
  asset_class: string
}

export interface AllocationGroup {
  asset_class: string
  name: string
  value: number
  weight: number
  items: AllocationItem[]
}

export interface PositionResponse {
  symbol: string
  quantity: number
  available_qty: number
  frozen_qty: number
  avg_cost: number
  market_value: number
  unrealized_pnl: number
  realized_pnl: number
  commission_paid: number
}

export interface PortfolioSnapshot {
  cash: number
  total_equity: number
  total_deposits: number
  positions: PositionResponse[]
  allocation: AllocationItem[]
  allocation_grouped: AllocationGroup[]
}

export interface AccountOverview {
  total_equity: number
  available_cash: number
  total_deposits: number
  positions_count: number
  unrealized_pnl: number
  realized_pnl: number
  cash_ratio: number
}

export interface RiskSummaryItem {
  kind: string
  level: string
  title: string
  detail: string
}

export interface CashFlowCreate {
  timestamp: string
  amount: number
  flow_type: string
  note: string
}

export interface CashFlowResponse {
  id: number
  timestamp: string
  amount: number
  flow_type: string
  note: string
  created_at: string
}

export interface EquityPoint {
  timestamp: string
  equity: number
}

export interface ActivityItem {
  kind: string
  title: string
  detail: string
  timestamp: string
  amount: number | null
  symbol: string | null
}

export interface TradeCreate {
  timestamp: string
  symbol: string
  direction: string
  quantity: number
  price: number
  commission: number
  asset_class: string
  note: string
}

export interface TradeResponse {
  id: number
  timestamp: string
  symbol: string
  direction: string
  quantity: number
  price: number
  commission: number
  asset_class: string
  note: string
  created_at: string
}

export const usePortfolioStore = defineStore('portfolio', () => {
  const snapshot = ref<PortfolioSnapshot | null>(null)
  const overview = ref<AccountOverview | null>(null)
  const riskSummary = ref<RiskSummaryItem[]>([])
  const loading = ref(false)
  const cashFlows = ref<CashFlowResponse[]>([])
  const equityCurve = ref<EquityPoint[]>([])
  const trades = ref<TradeResponse[]>([])
  const activities = ref<ActivityItem[]>([])

  async function fetchPortfolio() {
    loading.value = true
    try {
      const { data } = await client.get('/portfolio')
      snapshot.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchOverview() {
    try {
      const { data } = await client.get('/portfolio/overview')
      overview.value = data
    } catch {
      // ignore
    }
  }

  async function fetchRiskSummary() {
    try {
      const { data } = await client.get('/portfolio/risk-summary')
      riskSummary.value = data
    } catch {
      // ignore
    }
  }

  async function fetchCashFlows() {
    try {
      const { data } = await client.get('/portfolio/cash-flows')
      cashFlows.value = data
    } catch {
      // ignore
    }
  }

  async function addCashFlow(flow: CashFlowCreate) {
    const { data } = await client.post('/portfolio/cash-flow', flow)
    await fetchPortfolio()
    await fetchOverview()
    await fetchRiskSummary()
    await fetchCashFlows()
    await fetchActivity()
    return data as CashFlowResponse
  }

  async function deleteCashFlow(id: number) {
    await client.delete(`/portfolio/cash-flow/${id}`)
    await fetchPortfolio()
    await fetchOverview()
    await fetchRiskSummary()
    await fetchCashFlows()
    await fetchActivity()
  }

  async function fetchEquityCurve() {
    try {
      const { data } = await client.get('/portfolio/equity-curve')
      equityCurve.value = data
    } catch {
      // ignore
    }
  }

  async function fetchTrades() {
    try {
      const { data } = await client.get('/portfolio/trades')
      trades.value = data
    } catch {
      // ignore
    }
  }

  async function fetchActivity(limit = 10) {
    try {
      const { data } = await client.get('/portfolio/activity', { params: { limit } })
      activities.value = data
    } catch {
      // ignore
    }
  }

  async function addTrade(trade: TradeCreate) {
    const { data } = await client.post('/portfolio/trade', trade)
    await fetchPortfolio()
    await fetchOverview()
    await fetchRiskSummary()
    await fetchTrades()
    await fetchActivity()
    return data as TradeResponse
  }

  async function deleteTrade(id: number) {
    await client.delete(`/portfolio/trade/${id}`)
    await fetchPortfolio()
    await fetchOverview()
    await fetchRiskSummary()
    await fetchTrades()
    await fetchActivity()
  }

  return {
    snapshot, overview, riskSummary, loading, cashFlows, equityCurve, trades, activities,
    fetchPortfolio, fetchOverview, fetchRiskSummary, fetchCashFlows, addCashFlow, deleteCashFlow,
    fetchEquityCurve, fetchTrades, fetchActivity, addTrade, deleteTrade,
  }
})
