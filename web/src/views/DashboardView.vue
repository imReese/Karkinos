<template>
  <div class="dashboard">
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="section-eyebrow">账户状态</div>
        <h1 class="hero-title">账户状态</h1>
        <p class="hero-text">先确认现金、持仓和风险，再处理待执行动作。</p>
        <div class="hero-actions">
          <button class="btn btn-primary hero-action-btn" @click="openTrade">记录一笔交易</button>
          <button class="btn btn-secondary hero-action-btn" @click="openDeposit">记录入金</button>
          <button class="btn btn-secondary hero-action-btn" @click="goToSignals">查看任务</button>
        </div>
        <div class="hero-scroll" @click="scrollToActions">
          <span>继续查看今日动作</span>
          <ChevronDown :size="16" />
        </div>
        <div class="hero-notes">
          <div class="hero-note">
            <span class="hero-note-label">累计入金</span>
            <span class="hero-note-value font-mono">¥{{ formatMoney(totalDeposits) }}</span>
          </div>
          <div class="hero-note">
            <span class="hero-note-label">持仓市值</span>
            <span class="hero-note-value font-mono">¥{{ formatMoney(holdingsValue) }}</span>
          </div>
          <div class="hero-note status-note">
            <span class="hero-note-label">市场状态</span>
            <span class="hero-note-value"><LiveIndicator /></span>
          </div>
        </div>
      </div>

      <div class="hero-figure">
        <div class="hero-badge">现金占比 {{ (cashRatio * 100).toFixed(1) }}%</div>
        <div class="hero-amount font-mono">¥{{ formatMoney(totalEquity) }}</div>
        <div class="hero-caption">当前总资产</div>
        <div class="hero-performance" v-if="totalDeposits > 0">
          <span :class="pnlAmount >= 0 ? 'text-green' : 'text-red'" class="font-mono">
            {{ pnlAmount >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pnlAmount)) }}
          </span>
          <span class="hero-performance-divider">/</span>
          <span :class="pnlAmount >= 0 ? 'text-green' : 'text-red'" class="font-mono">
            {{ pnlAmount >= 0 ? '+' : '' }}{{ (pnlPercent * 100).toFixed(2) }}%
          </span>
        </div>
        <div class="hero-performance-label">相对入金表现</div>
      </div>
    </section>

    <section class="overview-strip">
      <article class="overview-tile interactive-tile" @click="openDeposit">
        <div class="overview-icon cash-icon"><Wallet :size="18" /></div>
        <div class="overview-label">可用现金</div>
        <div class="overview-value font-mono text-cash">¥{{ formatMoney(availableCash) }}</div>
      </article>
      <article class="overview-tile interactive-tile" @click="goToPortfolio">
        <div class="overview-icon position-icon"><Briefcase :size="18" /></div>
        <div class="overview-label">持仓数</div>
        <div class="overview-value">{{ positionsCount }}</div>
      </article>
      <article class="overview-tile interactive-tile" @click="goToPortfolio">
        <div class="overview-icon pnl-icon"><TrendingUp :size="18" /></div>
        <div class="overview-label">浮动盈亏</div>
        <div class="overview-value font-mono" :class="unrealizedPnl >= 0 ? 'text-green' : 'text-red'">
          {{ unrealizedPnl >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(unrealizedPnl)) }}
        </div>
      </article>
      <article class="overview-tile interactive-tile" @click="goToTrade">
        <div class="overview-icon status-icon"><Activity :size="18" /></div>
        <div class="overview-label">已实现盈亏</div>
        <div class="overview-value font-mono" :class="realizedPnl >= 0 ? 'text-green' : 'text-red'">
          {{ realizedPnl >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(realizedPnl)) }}
        </div>
      </article>
    </section>

    <div class="workspace">
      <div class="workspace-main">
        <section ref="actionSurfaceRef" class="surface action-surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">动作中心</div>
              <h2 class="surface-title">待处理任务</h2>
            </div>
            <div class="surface-meta">{{ actionCards.length }} 条待关注动作</div>
          </div>

          <div v-if="actionCards.length === 0" class="empty-state">
            <div class="empty-title">暂无待执行动作</div>
            <div class="empty-copy">当前没有需要立即确认的建议，可以继续观察市场或手工记录交易。</div>
            <div class="empty-actions">
              <button class="btn btn-primary" @click="openTrade">记录交易</button>
              <button class="btn btn-secondary" @click="goToSignals">查看信号流</button>
            </div>
          </div>

          <div v-else class="action-list">
            <article v-for="s in actionCards" :key="s.id ?? s.timestamp" class="action-row">
              <div class="action-body">
                <div class="action-topline">
                  <div class="action-symbol">
                    <SignalBadge :direction="s.direction" />
                    <span class="font-mono">{{ s.symbol }}</span>
                  </div>
                  <span v-if="s.price !== null" class="action-price font-mono">¥{{ formatMoney(s.price) }}</span>
                </div>
                <div class="action-title">{{ s.title }}</div>
                <div class="action-detail">{{ s.detail }}</div>
              </div>
              <div class="action-aside">
                <span class="action-time">{{ formatTime(s.timestamp) }}</span>
                <div class="action-controls">
                  <button class="action-btn ghost-btn" @click="markAction(s, 'deferred')" :disabled="processingActionId === s.id">
                    {{ processingActionId === s.id ? '处理中...' : '稍后' }}
                  </button>
                  <button class="action-btn ghost-btn" @click="markAction(s, 'dismissed')" :disabled="processingActionId === s.id">忽略</button>
                  <button class="action-btn" @click="openAction(s)" :disabled="processingActionId === s.id">去执行</button>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section class="surface activity-surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">最近活动</div>
              <h2 class="surface-title">交易与资金流水</h2>
            </div>
            <div class="surface-meta">{{ activities.length }} 条</div>
          </div>
          <div v-if="activities.length === 0" class="empty-state compact-empty">
            <div class="empty-copy">暂无最近活动。</div>
          </div>
          <div v-else class="activity-list">
            <article v-for="item in activities" :key="`${item.kind}-${item.timestamp}-${item.title}`" class="activity-row">
              <div class="activity-main">
                <div class="activity-title">{{ item.title }}</div>
                <div class="activity-detail">{{ item.detail }}</div>
              </div>
              <div class="activity-side">
                <span v-if="item.amount !== null" class="font-mono activity-amount">
                  ¥{{ formatMoney(Math.abs(item.amount)) }}
                </span>
                <span class="activity-time">{{ formatTime(item.timestamp) }}</span>
              </div>
            </article>
          </div>
        </section>
      </div>

      <aside class="workspace-side">
        <section class="surface side-surface">
          <div class="surface-head side-head">
            <div>
              <div class="section-eyebrow">账户概览</div>
              <h2 class="surface-title">账户状态、风险与下一步</h2>
            </div>
          </div>
          <div class="detail-list">
            <div class="detail-row">
              <span class="detail-label">总资产</span>
              <span class="detail-value font-mono">¥{{ formatMoney(totalEquity) }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">可用现金</span>
              <span class="detail-value font-mono">¥{{ formatMoney(availableCash) }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">持仓市值</span>
              <span class="detail-value font-mono">¥{{ formatMoney(holdingsValue) }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">现金占比</span>
              <span class="detail-value font-mono">{{ (cashRatio * 100).toFixed(1) }}%</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">最新动作</span>
              <span class="detail-value emphasis-text">{{ actionCards.length > 0 ? actionCards[0].title : '暂无动作' }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">建议下一步</span>
              <span class="detail-value emphasis-text">{{ actionCards.length > 0 ? '确认待执行建议' : '继续观察市场' }}</span>
            </div>
          </div>
          <div class="risk-inline" v-if="riskSummary.length > 0">
            <div v-for="item in riskSummary.slice(0, 2)" :key="item.title" class="risk-inline-item">
              <div class="risk-badge" :class="`risk-${item.level}`">{{ riskLevelLabel(item.level) }}</div>
              <div class="risk-copy">
                <div class="risk-title">{{ item.title }}</div>
                <div class="risk-detail">{{ item.detail }}</div>
              </div>
            </div>
          </div>
          <div class="panel-actions">
            <button class="btn btn-secondary" @click="goToPortfolio">查看投资组合</button>
            <button class="btn btn-secondary" @click="goToMarket">查看行情</button>
            <button class="btn btn-primary" @click="goToSignals">打开信号中心</button>
          </div>
        </section>
      </aside>
    </div>

    <div class="fab-group">
      <button class="fab" @click="fabOpen = !fabOpen">
        <Plus :size="22" />
      </button>
      <div class="fab-menu" v-if="fabOpen">
        <button class="fab-item" @click="openDeposit">
          <ArrowDownCircle :size="16" />
          <span>入金</span>
        </button>
        <button class="fab-item" @click="openWithdraw">
          <ArrowUpCircle :size="16" />
          <span>出金</span>
        </button>
        <button class="fab-item" @click="openTrade">
          <ArrowLeftRight :size="16" />
          <span>记录交易</span>
        </button>
      </div>
    </div>

    <CashFlowDrawer :open="drawerOpen" @close="drawerOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePortfolioStore } from '../stores/portfolio'
import { useSignalsStore, type ActionCard } from '../stores/signals'
import { useUiStore } from '../stores/ui'
import SignalBadge from '../components/SignalBadge.vue'
import LiveIndicator from '../components/LiveIndicator.vue'
import CashFlowDrawer from '../components/CashFlowDrawer.vue'
import { Wallet, Briefcase, TrendingUp, Activity, Plus, ArrowDownCircle, ArrowUpCircle, ArrowLeftRight, ChevronDown } from 'lucide-vue-next'

const router = useRouter()
const portfolioStore = usePortfolioStore()
const signalsStore = useSignalsStore()
const uiStore = useUiStore()

const snapshot = computed(() => portfolioStore.snapshot)
const overview = computed(() => portfolioStore.overview)
const riskSummary = computed(() => portfolioStore.riskSummary)
const activities = computed(() => portfolioStore.activities)
const actionCards = ref<ActionCard[]>([])
const fabOpen = ref(false)
const processingActionId = ref<number | null>(null)
const drawerOpen = ref(false)
const drawerFlowType = ref('deposit')
const actionSurfaceRef = ref<HTMLElement | null>(null)

const totalEquity = computed(() => overview.value?.total_equity ?? snapshot.value?.total_equity ?? 0)
const availableCash = computed(() => overview.value?.available_cash ?? snapshot.value?.cash ?? 0)
const totalDeposits = computed(() => overview.value?.total_deposits ?? snapshot.value?.total_deposits ?? 0)
const positionsCount = computed(() => overview.value?.positions_count ?? snapshot.value?.positions.length ?? 0)
const unrealizedPnl = computed(() => overview.value?.unrealized_pnl ?? 0)
const realizedPnl = computed(() => overview.value?.realized_pnl ?? 0)
const cashRatio = computed(() => overview.value?.cash_ratio ?? 0)
const holdingsValue = computed(() => Math.max(totalEquity.value - availableCash.value, 0))

const pnlAmount = computed(() => totalEquity.value - totalDeposits.value)
const pnlPercent = computed(() => {
  const d = totalDeposits.value
  return d > 0 ? pnlAmount.value / d : 0
})

function formatMoney(v: number): string {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(ts: string): string {
  return ts.slice(0, 16).replace('T', ' ')
}

function riskLevelLabel(level: string): string {
  if (level === 'high') return '高'
  if (level === 'medium') return '中'
  return '低'
}

function openDeposit() {
  drawerFlowType.value = 'deposit'
  drawerOpen.value = true
  fabOpen.value = false
}

function openWithdraw() {
  drawerFlowType.value = 'withdraw'
  drawerOpen.value = true
  fabOpen.value = false
}

function openTrade() {
  router.push('/trade')
  fabOpen.value = false
}

function goToPortfolio() {
  router.push('/portfolio')
}

function goToSignals() {
  router.push('/signals')
}

function goToMarket() {
  router.push('/market')
}

function goToTrade() {
  router.push('/trade')
}

function scrollToActions() {
  actionSurfaceRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openAction(action: ActionCard) {
  router.push({
    path: '/trade',
    query: {
      action_id: action.id?.toString() ?? '',
      symbol: action.symbol,
      direction: action.direction,
      asset_class: action.asset_class,
      price: action.price?.toString() ?? '',
    },
  })
}

async function markAction(action: ActionCard, status: 'deferred' | 'dismissed') {
  if (action.id == null) return
  processingActionId.value = action.id
  try {
    await signalsStore.updateActionStatus(action.id, status)
    actionCards.value = actionCards.value.filter((item) => item.id !== action.id)
    uiStore.success(status === 'deferred' ? '任务已稍后处理。' : '任务已从首页待处理队列移除。', '任务已更新')
  } catch {
    uiStore.error('首页任务状态未能更新，请稍后重试。', '更新失败')
  } finally {
    processingActionId.value = null
  }
}

onMounted(async () => {
  await Promise.all([
    portfolioStore.fetchPortfolio(),
    portfolioStore.fetchOverview(),
    portfolioStore.fetchRiskSummary(),
    portfolioStore.fetchActivity(),
  ])
  actionCards.value = await signalsStore.fetchActions(4)
  signalsStore.startListening()
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  min-width: 0;
}

.hero-panel {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.9fr);
  gap: 18px;
  padding: 24px 26px;
  border-radius: 30px;
  background:
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.94), transparent 36%),
    radial-gradient(circle at bottom right, rgba(222, 229, 240, 0.42), transparent 28%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(246, 247, 249, 0.9));
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 30px 60px rgba(15, 23, 42, 0.06);
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
  font-size: clamp(22px, 2.4vw, 30px);
  line-height: 1.05;
  letter-spacing: -0.035em;
  color: #111317;
}

.hero-text {
  margin-top: 12px;
  max-width: 34ch;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.hero-scroll {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: color var(--transition-fast), transform var(--transition-fast);
  width: fit-content;
}

.hero-scroll:hover {
  color: var(--text-primary);
  transform: translateY(1px);
}

.hero-scroll :deep(svg) {
  animation: bobDown 1.8s ease-in-out infinite;
}

.hero-action-btn {
  min-width: 108px;
}

.hero-notes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.hero-note {
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.hero-note-label {
  display: block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.hero-note-value {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.status-note :deep(.live-indicator) {
  justify-content: flex-start;
}

.hero-figure {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 20px;
  border-radius: 24px;
  background:
    linear-gradient(180deg, rgba(28, 31, 38, 0.96), rgba(20, 22, 28, 0.92)),
    #16181d;
  color: #f5f7fa;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.hero-badge {
  align-self: flex-start;
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(245, 247, 250, 0.68);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.hero-amount {
  margin-top: 22px;
  font-size: clamp(30px, 3.2vw, 42px);
  line-height: 1;
  letter-spacing: -0.04em;
}

.hero-caption {
  margin-top: 10px;
  color: rgba(245, 247, 250, 0.62);
  font-size: 13px;
}

.hero-performance {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 28px;
  font-size: 16px;
}

.hero-performance-divider {
  color: rgba(245, 247, 250, 0.22);
}

.hero-performance .text-green {
  color: #b7efe1;
}

.hero-performance .text-red {
  color: #ffc3bd;
}

.hero-performance-label {
  margin-top: 10px;
  font-size: 12px;
  color: rgba(245, 247, 250, 0.48);
}

.overview-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.overview-tile {
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(15, 23, 42, 0.07);
  box-shadow: var(--shadow-card);
}

.interactive-tile {
  cursor: pointer;
  transition: transform var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.interactive-tile:hover {
  transform: translateY(-2px);
  border-color: rgba(15, 23, 42, 0.14);
  box-shadow: 0 18px 34px rgba(15, 23, 42, 0.08);
}

.overview-icon {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}

.cash-icon { background: rgba(33, 106, 134, 0.12); color: var(--cash); }
.position-icon { background: rgba(154, 107, 47, 0.12); color: var(--primary); }
.pnl-icon { background: rgba(32, 116, 94, 0.12); color: var(--success); }
.status-icon { background: rgba(194, 128, 30, 0.12); color: var(--warning); }

.overview-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.overview-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.72fr);
  gap: 12px;
}

.workspace-main,
.workspace-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.surface {
  padding: 18px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.07);
  box-shadow: var(--shadow-card);
}

.surface-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.side-head {
  margin-bottom: 12px;
}

.surface-title {
  font-size: 18px;
  line-height: 1.15;
  letter-spacing: -0.03em;
  color: #111317;
}

.surface-meta {
  font-size: 12px;
  color: var(--text-muted);
  padding-top: 2px;
}

.action-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.activity-list {
  display: flex;
  flex-direction: column;
}

.activity-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
}

.activity-row:first-child {
  border-top: none;
  padding-top: 0;
}

.activity-main {
  min-width: 0;
}

.activity-title {
  color: var(--text-primary);
  font-weight: 600;
}

.activity-detail {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 12px;
}

.activity-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.activity-amount {
  color: var(--text-primary);
  font-size: 13px;
}

.action-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  padding: 14px 0;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
}

.action-row:first-child {
  border-top: none;
  padding-top: 0;
}

.action-body {
  min-width: 0;
}

.action-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.action-symbol {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  color: var(--text-primary);
}

.action-price {
  color: var(--text-secondary);
  font-size: 13px;
}

.action-title {
  margin-top: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.action-detail {
  margin-top: 4px;
  max-width: 54ch;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.action-aside {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
}

.action-controls {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.action-time {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.action-btn {
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(246, 247, 249, 0.95));
  color: var(--text-primary);
  border-radius: 999px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: transform var(--transition-fast), border-color var(--transition-fast), background var(--transition-fast);
  white-space: nowrap;
}

.action-btn:hover {
  transform: translateY(-1px);
  border-color: rgba(15, 23, 42, 0.18);
  background: rgba(248, 250, 252, 1);
}

.ghost-btn {
  background: transparent;
  box-shadow: none;
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.07);
}

.detail-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.detail-label {
  color: var(--text-muted);
  font-size: 13px;
}

.detail-value {
  color: var(--text-primary);
  font-weight: 600;
  text-align: right;
}

.emphasis-text {
  max-width: 18ch;
  line-height: 1.45;
}

.risk-inline {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.risk-inline-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 0;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
}

.risk-badge {
  min-width: 30px;
  height: 30px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}

.risk-high {
  background: rgba(185, 56, 50, 0.14);
  color: var(--danger);
}

.risk-medium {
  background: rgba(194, 128, 30, 0.16);
  color: var(--warning);
}

.risk-low {
  background: rgba(32, 116, 94, 0.14);
  color: var(--success);
}

.risk-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.risk-title {
  color: var(--text-primary);
  font-weight: 600;
}

.risk-detail {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.empty-state {
  padding: 14px 0 2px;
}

.compact-empty {
  padding: 6px 0 0;
}

.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.empty-copy {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.empty-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.dashboard > * {
  animation: riseIn 420ms ease both;
}

.dashboard > *:nth-child(2) {
  animation-delay: 50ms;
}

.dashboard > *:nth-child(3) {
  animation-delay: 90ms;
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

@keyframes bobDown {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(4px);
  }
}

.fab-group {
  position: fixed;
  bottom: 32px;
  right: 32px;
  z-index: 200;
}

.fab {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-xl);
  background: var(--primary);
  color: #fff;
  border: 1px solid rgba(154, 107, 47, 0.36);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition-normal), transform var(--transition-fast);
}

.fab:hover {
  background: var(--primary-hover);
  transform: scale(1.05);
}

.fab-menu {
  position: absolute;
  bottom: 56px;
  right: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 8px;
  min-width: 160px;
}

.fab-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: none;
  border-radius: var(--radius-md);
  background: none;
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  width: 100%;
  text-align: left;
  font-family: var(--font-sans);
  transition: background var(--transition-fast);
}

.fab-item:hover {
  background: var(--surface-hover);
}

@media (max-width: 1200px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .hero-panel {
    grid-template-columns: 1fr;
  }
}

@media (min-width: 1600px) {
  .dashboard {
    gap: 18px;
  }

  .hero-panel {
    grid-template-columns: minmax(0, 1.9fr) minmax(360px, 1.05fr);
    padding: 28px 30px;
  }

  .overview-strip {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .workspace {
    grid-template-columns: minmax(0, 1.7fr) minmax(340px, 0.78fr);
    gap: 16px;
  }
}

@media (max-width: 960px) {
  .overview-strip,
  .hero-notes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .action-row {
    grid-template-columns: 1fr;
  }

  .action-aside {
    align-items: flex-start;
  }
}

@media (max-width: 720px) {
  .dashboard {
    gap: 14px;
  }

  .hero-panel,
  .surface,
  .overview-tile {
    padding: 18px;
  }

  .hero-title {
    max-width: none;
  }

  .overview-strip,
  .hero-notes {
    grid-template-columns: 1fr;
  }

  .surface-head,
  .detail-row,
  .action-topline {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
