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
  const loading = ref(false)
  const cashFlows = ref<CashFlowResponse[]>([])
  const equityCurve = ref<EquityPoint[]>([])
  const trades = ref<TradeResponse[]>([])

  async function fetchPortfolio() {
    loading.value = true
    try {
      const { data } = await client.get('/portfolio')
      snapshot.value = data
    } finally {
      loading.value = false
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
    await fetchCashFlows()
    return data as CashFlowResponse
  }

  async function deleteCashFlow(id: number) {
    await client.delete(`/portfolio/cash-flow/${id}`)
    await fetchPortfolio()
    await fetchCashFlows()
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

  async function addTrade(trade: TradeCreate) {
    const { data } = await client.post('/portfolio/trade', trade)
    await fetchPortfolio()
    await fetchTrades()
    return data as TradeResponse
  }

  async function deleteTrade(id: number) {
    await client.delete(`/portfolio/trade/${id}`)
    await fetchPortfolio()
    await fetchTrades()
  }

  return {
    snapshot, loading, cashFlows, equityCurve, trades,
    fetchPortfolio, fetchCashFlows, addCashFlow, deleteCashFlow,
    fetchEquityCurve, fetchTrades, addTrade, deleteTrade,
  }
})
