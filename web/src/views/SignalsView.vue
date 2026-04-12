<template>
  <div class="signals">
    <div class="card">
      <div class="card-title">信号历史</div>
      <div class="table-wrap">
        <table v-if="signalsStore.signals.length > 0">
          <thead>
            <tr>
              <th>时间</th>
              <th>标的</th>
              <th>方向</th>
              <th>目标权重</th>
              <th>价格</th>
              <th>策略</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in signalsStore.signals" :key="s.id ?? s.timestamp + s.symbol" class="signal-row" :class="{ 'is-new': s.isNew }">
              <td class="text-muted">{{ formatTime(s.timestamp) }}</td>
              <td class="font-mono">{{ s.symbol }}</td>
              <td>
                <div class="direction-cell">
                  <SignalBadge :direction="s.direction" />
                  <span class="new-badge" v-if="s.isNew">NEW</span>
                </div>
              </td>
              <td class="font-mono">{{ (s.target_weight * 100).toFixed(0) }}%</td>
              <td class="font-mono">{{ s.price?.toFixed(2) ?? '-' }}</td>
              <td class="text-muted">{{ s.strategy_id }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="text-muted empty-text">暂无信号记录</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useSignalsStore } from '../stores/signals'
import SignalBadge from '../components/SignalBadge.vue'

const signalsStore = useSignalsStore()

function formatTime(ts: string): string {
  return ts.slice(0, 19).replace('T', ' ')
}

onMounted(() => {
  signalsStore.fetchSignals(100)
  signalsStore.startListening()
})
</script>

<style scoped>
.direction-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.new-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--primary-subtle);
  color: var(--primary);
  font-weight: 600;
  animation: fadeIn 0.3s ease;
}

.signal-row.is-new {
  background: rgba(99, 102, 241, 0.04);
}

.empty-text {
  text-align: center;
  padding: 32px 0;
  font-size: 13px;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
