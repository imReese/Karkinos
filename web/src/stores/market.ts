import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import { useWebSocketStore } from './websocket'

export interface MarketQuote {
  symbol: string
  price: number
  volume: number | null
  timestamp: string | null
  asset_class: string | null
  price_change?: number
}

export interface WatchlistItem {
  symbol: string
  asset_class: string
  name: string
}

export interface KlineBar {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export const useMarketStore = defineStore('market', () => {
  const watchlist = ref<WatchlistItem[]>([])
  const quotes = ref<Record<string, MarketQuote>>({})
  const loading = ref(false)
  let wsListenerActive = false

  async function fetchWatchlist() {
    loading.value = true
    try {
      const { data } = await client.get('/market/watchlist')
      watchlist.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchQuote(symbol: string) {
    const { data } = await client.get(`/market/quote/${symbol}`)
    quotes.value[symbol] = data
    return data
  }

  async function fetchAllQuotes() {
    for (const item of watchlist.value) {
      try {
        await fetchQuote(item.symbol)
      } catch {
        // ignore individual quote errors
      }
    }
  }

  async function fetchKline(symbol: string, start?: string, end?: string) {
    const params: Record<string, string> = {}
    if (start) params.start = start
    if (end) params.end = end
    const { data } = await client.get(`/market/kline/${symbol}`, { params })
    return data as KlineBar[]
  }

  function startListening() {
    if (wsListenerActive) return
    wsListenerActive = true
    const ws = useWebSocketStore()
    ws.on('MarketEvent', (data: Record<string, any>) => {
      const symbol = data.symbol
      if (!symbol) return
      const existing = quotes.value[symbol]
      const prevPrice = existing?.price
      quotes.value[symbol] = {
        symbol,
        price: parseFloat(data.close ?? data.price ?? 0),
        volume: data.volume ? parseFloat(data.volume) : null,
        timestamp: data.timestamp ?? new Date().toISOString(),
        asset_class: data.asset_class ?? existing?.asset_class ?? null,
        price_change: prevPrice ? parseFloat(data.close ?? data.price ?? 0) - prevPrice : undefined,
      }
    })
  }

  return { watchlist, quotes, loading, fetchWatchlist, fetchQuote, fetchAllQuotes, fetchKline, startListening }
})
