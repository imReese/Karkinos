import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ConnectionState = 'connecting' | 'connected' | 'disconnected'

export const useWebSocketStore = defineStore('websocket', () => {
  const state = ref<ConnectionState>('disconnected')
  const lastEvent = ref<Record<string, any> | null>(null)
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  const listeners: Map<string, Set<(data: any) => void>> = new Map()

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws`

    state.value = 'connecting'
    ws = new WebSocket(url)

    ws.onopen = () => {
      state.value = 'connected'
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }

    ws.onclose = () => {
      state.value = 'disconnected'
      scheduleReconnect()
    }

    ws.onerror = () => {
      state.value = 'disconnected'
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        lastEvent.value = data
        dispatch(data)
      } catch {
        // ignore parse errors
      }
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    state.value = 'disconnected'
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, 3000)
  }

  function on(eventType: string, handler: (data: any) => void) {
    if (!listeners.has(eventType)) {
      listeners.set(eventType, new Set())
    }
    listeners.get(eventType)!.add(handler)
  }

  function off(eventType: string, handler: (data: any) => void) {
    listeners.get(eventType)?.delete(handler)
  }

  function dispatch(data: Record<string, any>) {
    const eventType = data.event_type
    if (eventType && listeners.has(eventType)) {
      listeners.get(eventType)!.forEach((handler) => handler(data))
    }
  }

  // Auto-connect
  connect()

  return { state, lastEvent, connect, disconnect, on, off }
})
