import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import { useWebSocketStore } from './websocket'

export interface SignalResponse {
  id: number | null
  timestamp: string
  strategy_id: string
  symbol: string
  direction: string
  target_weight: number
  price: number | null
  asset_class: string
  isNew?: boolean
}

export const useSignalsStore = defineStore('signals', () => {
  const signals = ref<SignalResponse[]>([])
  const loading = ref(false)
  let wsListenerActive = false

  async function fetchSignals(limit = 50, offset = 0) {
    loading.value = true
    try {
      const { data } = await client.get('/signals', { params: { limit, offset } })
      signals.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchLatest(limit = 10) {
    const { data } = await client.get('/signals/latest', { params: { limit } })
    return data as SignalResponse[]
  }

  function startListening() {
    if (wsListenerActive) return
    wsListenerActive = true
    const ws = useWebSocketStore()
    ws.on('SignalEvent', (data: Record<string, any>) => {
      const signal: SignalResponse = {
        id: null,
        timestamp: data.timestamp ?? new Date().toISOString(),
        strategy_id: data.strategy_id ?? '',
        symbol: data.symbol ?? '',
        direction: data.direction ?? '',
        target_weight: data.target_weight ?? 0,
        price: data.price ?? null,
        asset_class: data.asset_class ?? 'stock',
        isNew: true,
      }
      signals.value.unshift(signal)
      // Remove 'new' badge after 10s
      setTimeout(() => {
        signal.isNew = false
      }, 10000)
    })
  }

  return { signals, loading, fetchSignals, fetchLatest, startListening }
})
