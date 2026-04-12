<template>
  <div class="dashboard">
    <!-- Hero card -->
    <div class="hero-card card mb-4">
      <div class="hero-content">
        <div class="hero-label">总权益</div>
        <div class="hero-value font-mono">¥{{ formatMoney(snapshot?.total_equity ?? 0) }}</div>
        <div class="hero-pnl" v-if="snapshot && snapshot.total_deposits > 0">
          <span :class="pnlAmount >= 0 ? 'text-green' : 'text-red'" class="font-mono">
            {{ pnlAmount >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pnlAmount)) }}
          </span>
          <span :class="pnlAmount >= 0 ? 'text-green' : 'text-red'" class="font-mono pnl-pct">
            ({{ pnlAmount >= 0 ? '+' : '' }}{{ (pnlPercent * 100).toFixed(2) }}%)
          </span>
          <span class="text-muted">vs 入金</span>
        </div>
      </div>
    </div>

    <!-- 4 metric cards -->
    <div class="grid grid-4 mb-4">
      <div class="card metric-card">
        <div class="metric-icon cash-icon"><Wallet :size="18" /></div>
        <div class="metric-info">
          <div class="metric-label">现金</div>
          <div class="metric-value font-mono text-cash">¥{{ formatMoney(snapshot?.cash ?? 0) }}</div>
        </div>
      </div>
      <div class="card metric-card">
        <div class="metric-icon position-icon"><Briefcase :size="18" /></div>
        <div class="metric-info">
          <div class="metric-label">持仓数</div>
          <div class="metric-value">{{ snapshot?.positions.length ?? 0 }}</div>
        </div>
      </div>
      <div class="card metric-card">
        <div class="metric-icon pnl-icon"><TrendingUp :size="18" /></div>
        <div class="metric-info">
          <div class="metric-label">今日盈亏</div>
          <div class="metric-value font-mono text-muted">-</div>
        </div>
      </div>
      <div class="card metric-card">
        <div class="metric-icon status-icon"><Activity :size="18" /></div>
        <div class="metric-info">
          <div class="metric-label">市场状态</div>
          <div class="metric-value"><LiveIndicator /></div>
        </div>
      </div>
    </div>

    <!-- Equity curve -->
    <div class="card mb-4" v-if="equityCurveData.length > 0">
      <div class="card-title">权益曲线</div>
      <EquityCurve :data="equityCurveData" />
    </div>

    <!-- Bottom 2 columns -->
    <div class="grid grid-2">
      <!-- Latest signals -->
      <div class="card">
        <div class="card-title">最新信号</div>
        <div v-if="latestSignals.length === 0" class="text-muted empty-text">暂无信号</div>
        <div v-else class="signal-list">
          <div v-for="s in latestSignals" :key="s.id ?? s.timestamp" class="signal-item">
            <div class="signal-left">
              <SignalBadge :direction="s.direction" />
              <span class="font-mono signal-symbol">{{ s.symbol }}</span>
            </div>
            <div class="signal-right">
              <span class="font-mono">{{ (s.target_weight * 100).toFixed(0) }}%</span>
              <span class="text-muted signal-time">{{ formatTime(s.timestamp) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Allocation -->
      <div class="card">
        <div class="card-title">资产配置</div>
        <AllocationBar :data="allocationBarData" />
        <AllocationPie :data="allocationPieData" />
      </div>
    </div>

    <!-- FAB -->
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
import { usePortfolioStore, type EquityPoint } from '../stores/portfolio'
import { useSignalsStore, type SignalResponse } from '../stores/signals'
import AllocationPie from '../components/AllocationPie.vue'
import AllocationBar from '../components/AllocationBar.vue'
import SignalBadge from '../components/SignalBadge.vue'
import EquityCurve from '../components/EquityCurve.vue'
import LiveIndicator from '../components/LiveIndicator.vue'
import CashFlowDrawer from '../components/CashFlowDrawer.vue'
import { Wallet, Briefcase, TrendingUp, Activity, Plus, ArrowDownCircle, ArrowUpCircle, ArrowLeftRight } from 'lucide-vue-next'

const router = useRouter()
const portfolioStore = usePortfolioStore()
const signalsStore = useSignalsStore()

const snapshot = computed(() => portfolioStore.snapshot)
const latestSignals = ref<SignalResponse[]>([])
const fabOpen = ref(false)
const drawerOpen = ref(false)
const drawerFlowType = ref('deposit')

const equityCurveData = computed<EquityPoint[]>(() => portfolioStore.equityCurve)

const allocationPieData = computed(() => {
  if (!snapshot.value) return []
  if (snapshot.value.allocation_grouped?.length) {
    return snapshot.value.allocation_grouped.map(g => ({ name: g.name, value: g.value }))
  }
  return snapshot.value.allocation.map(a => ({ name: a.name || a.symbol, value: a.value }))
})

const allocationBarData = computed(() => {
  if (!snapshot.value) return []
  return snapshot.value.allocation.map(a => ({ name: a.name || a.symbol, weight: a.weight }))
})

const pnlAmount = computed(() => (snapshot.value?.total_equity ?? 0) - (snapshot.value?.total_deposits ?? 0))
const pnlPercent = computed(() => {
  const d = snapshot.value?.total_deposits ?? 0
  return d > 0 ? pnlAmount.value / d : 0
})

function formatMoney(v: number): string {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(ts: string): string {
  return ts.slice(0, 16).replace('T', ' ')
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

onMounted(async () => {
  await portfolioStore.fetchPortfolio()
  await portfolioStore.fetchEquityCurve()
  latestSignals.value = await signalsStore.fetchLatest(5)
  signalsStore.startListening()
})
</script>

<style scoped>
.hero-card {
  background: linear-gradient(135deg, var(--primary) 0%, #4f46e5 100%);
  border: none;
  padding: 40px;
}

.hero-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.hero-value {
  font-size: 40px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
}

.hero-pnl {
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.hero-pnl .text-green,
.hero-pnl .text-red {
  color: #fff !important;
}

.pnl-pct {
  opacity: 0.8;
}

.hero-pnl .text-muted {
  color: rgba(255, 255, 255, 0.5);
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 16px;
}

.metric-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cash-icon { background: rgba(56, 189, 248, 0.1); color: var(--cash); }
.position-icon { background: var(--primary-subtle); color: var(--primary); }
.pnl-icon { background: rgba(34, 197, 94, 0.1); color: var(--success); }
.status-icon { background: rgba(245, 158, 11, 0.1); color: var(--warning); }

.metric-info {
  flex: 1;
}

.metric-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 18px;
  font-weight: 600;
}

.signal-list {
  display: flex;
  flex-direction: column;
}

.signal-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.signal-item:last-child {
  border-bottom: none;
}

.signal-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.signal-symbol {
  font-size: 13px;
  font-weight: 500;
}

.signal-right {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.signal-time {
  font-size: 11px;
}

.empty-text {
  text-align: center;
  padding: 32px 0;
  font-size: 13px;
}

/* FAB */
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
  border: 1px solid rgba(99, 102, 241, 0.5);
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
</style>
