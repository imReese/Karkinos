<template>
  <div class="market">
    <div class="card mb-4">
      <div class="card-title">关注列表</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>标的</th>
              <th>类型</th>
              <th>最新价</th>
              <th>涨跌</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in marketStore.watchlist" :key="item.symbol">
              <td>
                <div class="symbol-cell">
                  <span class="font-mono symbol-code">{{ item.symbol }}</span>
                  <span class="text-muted symbol-name">{{ item.name }}</span>
                </div>
              </td>
              <td>
                <span class="asset-badge">{{ item.asset_class }}</span>
              </td>
              <td class="font-mono price-cell">
                {{ marketStore.quotes[item.symbol]?.price?.toFixed(2) ?? '-' }}
              </td>
              <td class="font-mono" :class="priceChangeClass(item.symbol)">
                {{ priceChangeText(item.symbol) }}
              </td>
              <td>
                <button class="btn btn-sm btn-secondary" @click="showKline(item.symbol)">K线</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="klineSymbol" class="card">
      <div class="card-title">{{ klineSymbol }} K线图</div>
      <KlineChart :data="klineData" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useMarketStore, type KlineBar } from '../stores/market'
import KlineChart from '../components/KlineChart.vue'

const marketStore = useMarketStore()
const klineSymbol = ref('')
const klineData = ref<KlineBar[]>([])
let refreshTimer: ReturnType<typeof setInterval> | null = null

async function showKline(symbol: string) {
  klineSymbol.value = symbol
  klineData.value = await marketStore.fetchKline(symbol)
}

function priceChangeClass(symbol: string): string {
  const change = marketStore.quotes[symbol]?.price_change
  if (change === undefined || change === null) return ''
  return change >= 0 ? 'text-green' : 'text-red'
}

function priceChangeText(symbol: string): string {
  const change = marketStore.quotes[symbol]?.price_change
  if (change === undefined || change === null) return '-'
  const sign = change >= 0 ? '+' : ''
  return `${sign}${change.toFixed(2)}`
}

onMounted(async () => {
  await marketStore.fetchWatchlist()
  await marketStore.fetchAllQuotes()
  marketStore.startListening()

  // Periodic refresh
  refreshTimer = setInterval(() => {
    marketStore.fetchAllQuotes()
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.symbol-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.symbol-code {
  font-weight: 500;
}

.symbol-name {
  font-size: 11px;
}

.asset-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  background: var(--primary-subtle);
  color: var(--primary);
  text-transform: uppercase;
}

.price-cell {
  font-weight: 500;
}
</style>
