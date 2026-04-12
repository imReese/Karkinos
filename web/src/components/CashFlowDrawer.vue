<template>
  <Teleport to="body">
    <div class="drawer-overlay" :class="{ open: open }" @click.self="$emit('close')">
      <div class="drawer-panel" :class="{ open: open }">
        <div class="drawer-header">
          <h3>资金流水</h3>
          <button class="drawer-close" @click="$emit('close')">&times;</button>
        </div>

        <div class="drawer-body">
          <!-- Tab switch -->
          <div class="flow-tabs">
            <button :class="{ active: flowType === 'deposit' }" @click="flowType = 'deposit'">入金</button>
            <button :class="{ active: flowType === 'withdraw' }" @click="flowType = 'withdraw'">出金</button>
          </div>

          <!-- Form -->
          <div class="flow-form">
            <div class="form-group">
              <label>金额</label>
              <input type="number" v-model.number="amount" placeholder="0.00" step="0.01" min="0" />
            </div>
            <div class="form-group">
              <label>日期</label>
              <input type="date" v-model="dateStr" />
            </div>
            <div class="form-group">
              <label>备注</label>
              <input type="text" v-model="note" placeholder="备注（可选）" />
            </div>
            <button
              class="btn btn-primary submit-btn"
              :class="{ 'btn-danger': flowType === 'withdraw' }"
              @click="submit"
              :disabled="!amount || amount <= 0"
            >
              {{ flowType === 'deposit' ? '确认入金' : '确认出金' }}
            </button>
          </div>

          <!-- History -->
          <div class="flow-history">
            <div class="history-title">历史记录</div>
            <div v-if="portfolioStore.cashFlows.length === 0" class="text-muted empty-text">暂无记录</div>
            <div v-for="f in portfolioStore.cashFlows" :key="f.id" class="flow-item">
              <div class="flow-info">
                <span class="flow-type-badge" :class="f.flow_type">
                  {{ f.flow_type === 'deposit' ? '入金' : '出金' }}
                </span>
                <span class="flow-date">{{ f.timestamp?.slice(0, 10) }}</span>
              </div>
              <div class="flow-right">
                <span class="flow-amount" :class="f.flow_type === 'deposit' ? 'text-green' : 'text-red'">
                  {{ f.flow_type === 'deposit' ? '+' : '-' }}¥{{ f.amount.toFixed(2) }}
                </span>
                <button class="btn-remove" @click="portfolioStore.deleteCashFlow(f.id)">&times;</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { usePortfolioStore } from '../stores/portfolio'

defineProps<{ open: boolean }>()
defineEmits<{ close: [] }>()

const portfolioStore = usePortfolioStore()

const flowType = ref('deposit')
const amount = ref(0)
const dateStr = ref(new Date().toISOString().slice(0, 10))
const note = ref('')

async function submit() {
  if (!amount.value || amount.value <= 0) return
  await portfolioStore.addCashFlow({
    timestamp: new Date(dateStr.value).toISOString(),
    amount: amount.value,
    flow_type: flowType.value,
    note: note.value,
  })
  amount.value = 0
  note.value = ''
}
</script>

<style scoped>
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 300;
  opacity: 0;
  visibility: hidden;
  transition: opacity var(--transition-normal), visibility var(--transition-normal);
}

.drawer-overlay.open {
  opacity: 1;
  visibility: visible;
}

.drawer-panel {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: 400px;
  max-width: 100vw;
  background: var(--bg-card);
  border-left: 1px solid var(--border);
  z-index: 301;
  transform: translateX(100%);
  transition: transform var(--transition-normal);
  display: flex;
  flex-direction: column;
}

.drawer-panel.open {
  transform: translateX(0);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px;
  border-bottom: 1px solid var(--border);
}

.drawer-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.drawer-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 24px;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  transition: color var(--transition-fast);
}

.drawer-close:hover {
  color: var(--text-primary);
}

.drawer-body {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}

.flow-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  background: var(--bg-input);
  border-radius: var(--radius-md);
  padding: 3px;
}

.flow-tabs button {
  flex: 1;
  padding: 8px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-sans);
}

.flow-tabs button.active {
  background: var(--bg-card);
  color: var(--text-primary);
}

.flow-form {
  margin-bottom: 24px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.form-group input {
  width: 100%;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
}

.flow-history {
  border-top: 1px solid var(--border);
  padding-top: 16px;
}

.history-title {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 16px;
}

.empty-text {
  text-align: center;
  padding: 32px 0;
  font-size: 13px;
}

.flow-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.flow-item:last-child {
  border-bottom: none;
}

.flow-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.flow-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-weight: 600;
}

.flow-type-badge.deposit {
  background: rgba(34, 197, 94, 0.12);
  color: var(--success);
}

.flow-type-badge.withdraw {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
}

.flow-date {
  font-size: 12px;
  color: var(--text-muted);
}

.flow-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.flow-amount {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
}

.btn-remove {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 16px;
  cursor: pointer;
  padding: 0 4px;
  opacity: 0;
  transition: opacity var(--transition-fast), color var(--transition-fast);
}

.flow-item:hover .btn-remove {
  opacity: 1;
}

.btn-remove:hover {
  color: var(--danger);
}

@media (max-width: 480px) {
  .drawer-panel {
    width: 100vw;
  }
}
</style>
