<template>
  <div class="signals-page">
    <section class="page-intro">
      <div>
        <div class="section-eyebrow">任务中心</div>
        <h1 class="page-title">待处理任务与信号历史</h1>
        <p class="page-copy">先处理当前任务，再回看策略输出和最近触发记录。</p>
      </div>
      <button class="btn btn-secondary" @click="refreshAll">刷新</button>
    </section>

    <section class="surface mb-4">
      <div class="signals-head">
        <div>
          <div class="section-eyebrow">待处理队列</div>
          <h2 class="surface-title">任务列表</h2>
        </div>
      </div>
      <div v-if="signalsStore.actionCards.length === 0" class="text-muted empty-text">暂无待处理任务</div>
      <div v-else class="task-list">
        <article v-for="task in signalsStore.actionCards" :key="task.id ?? task.timestamp" class="task-row">
          <div class="task-main">
            <div class="direction-cell">
              <SignalBadge :direction="task.direction" />
              <span class="font-mono">{{ task.symbol }}</span>
            </div>
            <div class="task-title">{{ task.title }}</div>
            <div class="task-detail">{{ task.detail }}</div>
          </div>
          <div class="task-actions">
            <span class="task-time">{{ formatTime(task.timestamp) }}</span>
            <div class="task-buttons">
              <button
                class="btn btn-secondary btn-sm"
                @click="updateTask(task.id, 'deferred')"
                :disabled="processingTaskId === task.id"
              >
                {{ processingTaskId === task.id ? '处理中...' : '稍后' }}
              </button>
              <button
                class="btn btn-secondary btn-sm"
                @click="updateTask(task.id, 'dismissed')"
                :disabled="processingTaskId === task.id"
              >
                忽略
              </button>
              <button class="btn btn-primary btn-sm" @click="openTask(task)" :disabled="processingTaskId === task.id">去执行</button>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section class="surface">
      <div class="signals-head">
        <div>
          <div class="section-eyebrow">信号历史</div>
          <h2 class="surface-title">策略输出记录</h2>
        </div>
      </div>
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
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSignalsStore, type ActionCard } from '../stores/signals'
import { useUiStore } from '../stores/ui'
import SignalBadge from '../components/SignalBadge.vue'

const signalsStore = useSignalsStore()
const uiStore = useUiStore()
const router = useRouter()
const processingTaskId = ref<number | null>(null)

function formatTime(ts: string): string {
  return ts.slice(0, 19).replace('T', ' ')
}

async function refreshAll() {
  await Promise.all([signalsStore.fetchSignals(100), signalsStore.fetchActions(20)])
  uiStore.info('任务和信号列表已刷新。', '已刷新')
}

async function updateTask(taskId: number | null, status: string) {
  if (taskId == null) return
  processingTaskId.value = taskId
  try {
    await signalsStore.updateActionStatus(taskId, status)
    const mapping: Record<string, string> = {
      deferred: '任务已稍后处理。',
      dismissed: '任务已从待处理队列移除。',
      executed: '任务已标记为已执行。',
    }
    uiStore.success(mapping[status] ?? '任务状态已更新。', '任务已更新')
  } catch {
    uiStore.error('任务状态未能更新，请稍后重试。', '更新失败')
  } finally {
    processingTaskId.value = null
  }
}

function openTask(task: ActionCard) {
  router.push({
    path: '/trade',
    query: {
      action_id: task.id?.toString() ?? '',
      symbol: task.symbol,
      direction: task.direction,
      asset_class: task.asset_class,
      price: task.price?.toString() ?? '',
    },
  })
}

onMounted(() => {
  signalsStore.fetchSignals(100)
  signalsStore.fetchActions(20)
  signalsStore.startListening()
})
</script>

<style scoped>
.signals-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.signals-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.direction-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-list {
  display: flex;
  flex-direction: column;
}

.task-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  padding: 16px 0;
  border-top: 1px solid var(--border);
}

.task-row:first-child {
  border-top: none;
  padding-top: 0;
}

.task-main {
  min-width: 0;
}

.task-title {
  margin-top: 10px;
  font-size: 18px;
  font-weight: 600;
}

.task-detail {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}

.task-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}

.task-time {
  font-size: 12px;
  color: var(--text-muted);
}

.task-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
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

@media (max-width: 768px) {
  .signals-head,
  .task-row {
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .task-actions,
  .task-buttons {
    align-items: flex-start;
    justify-content: flex-start;
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
