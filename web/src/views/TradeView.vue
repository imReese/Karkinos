<template>
  <div class="trade-execution">
    <section class="execution-hero">
      <div class="hero-copy">
        <div class="section-eyebrow">交易执行</div>
        <h1 class="hero-title">{{ route.query.action_id ? '确认任务并记录交易' : '记录交易' }}</h1>
        <p class="hero-text">确认方向、价格和数量，再把结果回写到账户与任务状态。</p>
        <div class="hero-actions">
          <button class="btn btn-secondary" @click="goHome">返回首页</button>
          <button class="btn btn-secondary" @click="goTasks">查看任务</button>
        </div>
      </div>

      <div class="hero-figure">
        <div class="hero-badge">{{ direction === 'buy' ? '买入执行' : '卖出执行' }}</div>
        <div class="hero-symbol font-mono">{{ form.symbol || '----' }}</div>
        <div class="hero-meta">
          <span>资产类别 {{ assetLabel }}</span>
          <span v-if="form.price > 0">价格 ¥{{ form.price.toFixed(2) }}</span>
        </div>
        <div class="hero-value font-mono" v-if="form.quantity > 0 && form.price > 0">
          ¥{{ (form.quantity * form.price).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
        </div>
        <div class="hero-caption">预计成交金额</div>
      </div>
    </section>

    <div class="execution-workspace">
      <div class="workspace-main">
        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">交易录入</div>
              <h2 class="surface-title">交易参数</h2>
            </div>
          </div>

          <div class="direction-toggle">
            <button :class="{ active: direction === 'buy' }" class="dir-btn buy" @click="direction = 'buy'">
              买入
            </button>
            <button :class="{ active: direction === 'sell' }" class="dir-btn sell" @click="direction = 'sell'">
              卖出
            </button>
          </div>

          <div class="trade-form">
            <div class="grid grid-2">
              <div class="form-group">
                <label>标的代码</label>
                <input type="text" v-model="form.symbol" placeholder="如 600519" />
              </div>
              <div class="form-group">
                <label>资产类别</label>
                <select v-model="form.asset_class">
                  <option value="stock">股票</option>
                  <option value="etf">ETF</option>
                  <option value="gold">黄金</option>
                  <option value="bond">债券</option>
                </select>
              </div>
            </div>
            <div class="grid grid-3">
              <div class="form-group">
                <label>数量</label>
                <input type="number" v-model.number="form.quantity" placeholder="0" min="0" step="100" />
              </div>
              <div class="form-group">
                <label>价格</label>
                <input type="number" v-model.number="form.price" placeholder="0.00" min="0" step="0.01" />
              </div>
              <div class="form-group">
                <label>佣金</label>
                <input type="number" v-model.number="form.commission" placeholder="0.00" min="0" step="0.01" />
              </div>
            </div>
            <div class="grid grid-2">
              <div class="form-group">
                <label>日期</label>
                <input type="date" v-model="dateStr" />
              </div>
              <div class="form-group">
                <label>备注</label>
                <input type="text" v-model="form.note" placeholder="备注（可选）" />
              </div>
            </div>
          </div>
        </section>

        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">最近交易</div>
              <h2 class="surface-title">最近交易</h2>
            </div>
          </div>
          <div class="table-wrap">
            <table v-if="portfolioStore.trades.length > 0">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>标的</th>
                  <th>方向</th>
                  <th>数量</th>
                  <th>价格</th>
                  <th>佣金</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in portfolioStore.trades.slice(0, 8)" :key="t.id">
                  <td class="text-muted">{{ t.timestamp?.slice(0, 10) || '-' }}</td>
                  <td class="font-mono">{{ t.symbol }}</td>
                  <td>
                    <span class="dir-badge" :class="t.direction">
                      {{ t.direction === 'buy' ? '买入' : '卖出' }}
                    </span>
                  </td>
                  <td class="font-mono">{{ t.quantity }}</td>
                  <td class="font-mono">{{ t.price.toFixed(2) }}</td>
                  <td class="font-mono text-muted">{{ t.commission.toFixed(2) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无交易记录。</div>
          </div>
        </section>
      </div>

      <aside class="workspace-side">
        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">执行摘要</div>
              <h2 class="surface-title">执行摘要</h2>
            </div>
          </div>
          <div class="summary-list">
            <div class="summary-row">
              <span class="summary-label">方向</span>
              <span class="summary-value">{{ direction === 'buy' ? '买入' : '卖出' }}</span>
            </div>
            <div class="summary-row">
              <span class="summary-label">标的</span>
              <span class="summary-value font-mono">{{ form.symbol || '--' }}</span>
            </div>
            <div class="summary-row">
              <span class="summary-label">资产类别</span>
              <span class="summary-value">{{ assetLabel }}</span>
            </div>
            <div class="summary-row">
              <span class="summary-label">预计成交额</span>
              <span class="summary-value font-mono">
                ¥{{ (form.quantity * form.price).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
              </span>
            </div>
            <div class="summary-row" v-if="route.query.action_id">
              <span class="summary-label">任务回写</span>
              <span class="summary-value">提交后标记为已执行</span>
            </div>
          </div>
          <div class="submit-area">
            <button
              class="btn submit-btn"
              :class="direction === 'buy' ? 'btn-buy' : 'btn-sell'"
              @click="submitTrade"
              :disabled="!canSubmit || submitting"
            >
              {{ submitting ? '提交中...' : direction === 'buy' ? '确认买入' : '确认卖出' }}
            </button>
            <AppNotice
              v-if="inlineNotice"
              class="submit-notice"
              :tone="inlineNotice.tone"
              :title="inlineNotice.title"
              :message="inlineNotice.message"
              dense
            />
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppNotice from '../components/AppNotice.vue'
import { usePortfolioStore } from '../stores/portfolio'
import { useSignalsStore } from '../stores/signals'
import { useUiStore } from '../stores/ui'

const portfolioStore = usePortfolioStore()
const signalsStore = useSignalsStore()
const uiStore = useUiStore()
const route = useRoute()
const router = useRouter()

const direction = ref<'buy' | 'sell'>('buy')
const dateStr = ref(new Date().toISOString().slice(0, 10))
const submitting = ref(false)
const inlineNotice = ref<{ tone: 'success' | 'error'; title: string; message: string } | null>(null)

const form = reactive({
  symbol: '',
  quantity: 0,
  price: 0,
  commission: 0,
  asset_class: 'stock',
  note: '',
})

const canSubmit = computed(() => form.symbol.trim() && form.quantity > 0 && form.price > 0)
const assetLabel = computed(() => {
  const mapping: Record<string, string> = {
    stock: '股票',
    etf: 'ETF',
    gold: '黄金',
    bond: '债券',
  }
  return mapping[form.asset_class] ?? form.asset_class
})

function applyRoutePrefill() {
  const query = route.query
  if (typeof query.symbol === 'string' && query.symbol.trim()) {
    form.symbol = query.symbol.trim().toUpperCase()
  }
  if (query.direction === 'buy' || query.direction === 'sell') {
    direction.value = query.direction
  }
  if (typeof query.asset_class === 'string' && query.asset_class.trim()) {
    form.asset_class = query.asset_class
  }
  if (typeof query.price === 'string' && query.price.trim()) {
    const parsed = Number(query.price)
    if (!Number.isNaN(parsed) && parsed > 0) {
      form.price = parsed
    }
  }
}

async function submitTrade() {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  inlineNotice.value = null

  try {
    await portfolioStore.addTrade({
      timestamp: new Date(dateStr.value).toISOString(),
      symbol: form.symbol.trim().toUpperCase(),
      direction: direction.value,
      quantity: form.quantity,
      price: form.price,
      commission: form.commission,
      asset_class: form.asset_class,
      note: form.note,
    })
    const actionId =
      typeof route.query.action_id === 'string' ? Number(route.query.action_id) : NaN
    if (!Number.isNaN(actionId) && actionId > 0) {
      await signalsStore.updateActionStatus(actionId, 'executed')
    }
    inlineNotice.value = {
      tone: 'success',
      title: '交易已记录',
      message: '账户与任务状态已经同步更新。',
    }
    uiStore.success('交易已记录，账户与任务状态已经同步更新。', '执行成功')
    form.symbol = ''
    form.quantity = 0
    form.price = 0
    form.commission = 0
    form.note = ''
    setTimeout(() => {
      router.push('/')
    }, 700)
  } catch {
    inlineNotice.value = {
      tone: 'error',
      title: '提交失败',
      message: '请检查输入参数后重试。',
    }
    uiStore.error('交易未能提交，请检查输入参数后重试。', '执行失败')
  } finally {
    submitting.value = false
  }
}

function goHome() {
  router.push('/')
}

function goTasks() {
  router.push('/signals')
}

onMounted(() => {
  applyRoutePrefill()
  portfolioStore.fetchTrades()
})

watch(() => route.query, applyRoutePrefill)
</script>

<style scoped>
.trade-execution {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.execution-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.95fr);
  gap: 20px;
  padding: 30px;
  border-radius: 30px;
  background:
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.94), transparent 36%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(244, 247, 250, 0.88));
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: var(--shadow-card);
}

.section-eyebrow {
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.hero-title {
  max-width: none;
  font-size: clamp(22px, 2.5vw, 30px);
  line-height: 1.05;
  letter-spacing: -0.035em;
}

.hero-text {
  margin-top: 14px;
  max-width: 34ch;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 22px;
}

.hero-figure {
  padding: 22px;
  border-radius: 24px;
  background: rgba(18, 20, 25, 0.96);
  color: #f5f7fa;
}

.hero-badge {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(245, 247, 250, 0.68);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.hero-symbol {
  margin-top: 18px;
  font-size: 38px;
  line-height: 1;
}

.hero-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 12px;
  color: rgba(245, 247, 250, 0.62);
  font-size: 13px;
}

.hero-value {
  margin-top: 28px;
  font-size: 28px;
}

.hero-caption {
  margin-top: 8px;
  color: rgba(245, 247, 250, 0.52);
  font-size: 12px;
}

.execution-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.85fr);
  gap: 18px;
}

.workspace-main,
.workspace-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.surface {
  padding: 24px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.07);
  box-shadow: var(--shadow-card);
}

.surface-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.surface-title {
  font-size: 20px;
  line-height: 1.15;
  letter-spacing: -0.03em;
}

.direction-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  background: var(--bg-input);
  border-radius: var(--radius-md);
  padding: 3px;
}

.dir-btn {
  flex: 1;
  padding: 10px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-normal);
  font-family: var(--font-sans);
}

.dir-btn.buy.active {
  background: rgba(34, 197, 94, 0.12);
  color: var(--success);
}

.dir-btn.sell.active {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
}

.trade-form {
  margin-top: 8px;
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

.form-group input,
.form-group select {
  width: 100%;
}

.summary-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.summary-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.summary-label {
  color: var(--text-muted);
  font-size: 13px;
}

.summary-value {
  color: var(--text-primary);
  font-weight: 600;
  text-align: right;
}

.submit-area {
  margin-top: 22px;
}

.submit-btn {
  width: 100%;
  min-height: 46px;
}

.submit-notice {
  margin-top: 12px;
}

.btn-buy {
  background: var(--success);
  color: #fff;
}

.btn-buy:hover:not(:disabled) {
  background: #15805d;
}

.btn-sell {
  background: var(--danger);
  color: #fff;
}

.btn-sell:hover:not(:disabled) {
  background: #b93832;
}

.dir-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
}

.dir-badge.buy {
  background: rgba(34, 197, 94, 0.12);
  color: var(--success);
}

.dir-badge.sell {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
}

.empty-state {
  padding: 22px 0;
  color: var(--text-muted);
  font-size: 14px;
}

.trade-execution > * {
  animation: riseIn 420ms ease both;
}

.trade-execution > *:nth-child(2) {
  animation-delay: 60ms;
}

@keyframes riseIn {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1100px) {
  .execution-hero,
  .execution-workspace {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .trade-execution {
    gap: 14px;
  }

  .execution-hero,
  .surface {
    padding: 18px;
  }

  .hero-meta,
  .hero-actions,
  .summary-row,
  .surface-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
