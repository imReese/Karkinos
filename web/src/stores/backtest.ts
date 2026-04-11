import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export interface BacktestRequest {
  start_date: string
  end_date: string
  initial_cash: number
  strategy: string
  short_period: number
  long_period: number
  assets: Array<{ symbol: string; asset_class: string }> | null
  [key: string]: any
}

export interface BacktestMetrics {
  initial_cash: number
  final_equity: number
  total_return: number
  annual_return: number
  sharpe: number
  sortino: number
  max_drawdown: number
  win_rate: number
  duration_days: number
}

export interface EquityPoint {
  timestamp: string
  equity: number
}

export interface BacktestResponse {
  id: number
  created_at: string
  config: BacktestRequest
  metrics: BacktestMetrics
  equity_curve: EquityPoint[]
}

export interface BacktestSummary {
  id: number
  created_at: string
  strategy: string
  total_return: number
  sharpe: number
  max_drawdown: number
}

export interface StrategyParam {
  name: string
  type: string
  default: any
  description: string
}

export interface StrategyInfo {
  name: string
  description: string
  params: StrategyParam[]
}

export const useBacktestStore = defineStore('backtest', () => {
  const results = ref<BacktestSummary[]>([])
  const currentResult = ref<BacktestResponse | null>(null)
  const running = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)

  function clearError() {
    error.value = null
  }

  async function runBacktest(request: BacktestRequest) {
    running.value = true
    error.value = null
    try {
      const { data } = await client.post('/backtest/run', request)
      currentResult.value = data
      return data as BacktestResponse
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '回测运行失败'
      error.value = msg
      throw e
    } finally {
      running.value = false
    }
  }

  async function fetchResults() {
    loading.value = true
    error.value = null
    try {
      const { data } = await client.get('/backtest/results')
      results.value = data
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '获取回测结果失败'
      error.value = msg
    } finally {
      loading.value = false
    }
  }

  async function fetchResult(id: number) {
    error.value = null
    try {
      const { data } = await client.get(`/backtest/results/${id}`)
      currentResult.value = data
      return data as BacktestResponse
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '获取回测详情失败'
      error.value = msg
      throw e
    }
  }

  async function fetchStrategies() {
    error.value = null
    try {
      const { data } = await client.get('/backtest/strategies')
      return data as StrategyInfo[]
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '获取策略列表失败'
      error.value = msg
      return []
    }
  }

  return { results, currentResult, running, loading, error, clearError, runBacktest, fetchResults, fetchResult, fetchStrategies }
})
