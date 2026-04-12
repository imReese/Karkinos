<template>
  <div class="live-indicator" :class="state">
    <span class="dot"></span>
    <span class="label">{{ label }}</span>
    <span v-if="!marketOpen && state === 'connected'" class="market-badge">休市</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useWebSocketStore, type ConnectionState } from '../stores/websocket'
import client from '../api/client'

const ws = useWebSocketStore()
const marketOpen = ref(false)

const state = computed<ConnectionState>(() => ws.state)

const label = computed(() => {
  if (state.value === 'connected' && !marketOpen.value) return 'Live (休市)'
  switch (state.value) {
    case 'connected': return 'Live'
    case 'connecting': return 'Connecting...'
    default: return 'Offline'
  }
})

onMounted(async () => {
  try {
    const { data } = await client.get('/settings/live/status')
    marketOpen.value = data.market_open ?? false
  } catch {
    // ignore
  }
})
</script>

<style scoped>
.live-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

.connected .dot {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}

.connecting .dot {
  background: var(--warning);
  box-shadow: 0 0 8px var(--warning);
}

.disconnected .dot {
  background: var(--danger);
  animation: none;
}

.label {
  color: var(--text-secondary);
}

.market-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: rgba(245, 158, 11, 0.12);
  color: var(--warning);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
