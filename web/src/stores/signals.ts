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

export interface ActionCard {
  id: number | null
  source_signal_id?: number | null
  symbol: string
  title: string
  detail: string
  direction: string
  urgency: string
  target_weight: number
  price: number | null
  strategy_id: string
  timestamp: string
  asset_class: string
  status: string
}

export const useSignalsStore = defineStore('signals', () => {
  const signals = ref<SignalResponse[]>([])
  const actionCards = ref<ActionCard[]>([])
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

  async function fetchActions(limit = 6) {
    const { data } = await client.get('/signals/actions', { params: { limit } })
    actionCards.value = data
    return data as ActionCard[]
  }

  async function updateActionStatus(actionId: number, status: string) {
    const { data } = await client.patch(`/signals/actions/${actionId}`, { status })
    actionCards.value = actionCards.value.filter(action => action.id !== actionId)
    return data as ActionCard
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

  return {
    signals,
    actionCards,
    loading,
    fetchSignals,
    fetchLatest,
    fetchActions,
    updateActionStatus,
    startListening,
  }
})
