<template>
  <div class="portfolio">
    <!-- Overview metrics -->
    <div class="card mb-4">
      <div class="overview-grid">
        <div class="overview-item">
          <div class="ov-label">总权益</div>
          <div class="ov-value font-mono">¥{{ formatMoney(snapshot?.total_equity ?? 0) }}</div>
        </div>
        <div class="overview-item">
          <div class="ov-label">现金</div>
          <div class="ov-value font-mono text-cash">¥{{ formatMoney(snapshot?.cash ?? 0) }}</div>
        </div>
        <div class="overview-item">
          <div class="ov-label">持仓市值</div>
          <div class="ov-value font-mono">¥{{ formatMoney(holdingsValue) }}</div>
        </div>
        <div class="overview-item">
          <div class="ov-label">累计入金</div>
          <div class="ov-value font-mono">¥{{ formatMoney(snapshot?.total_deposits ?? 0) }}</div>
        </div>
      </div>
      <div class="pnl-row" v-if="snapshot && snapshot.total_deposits > 0">
        <span class="text-muted">累计盈亏</span>
        <span :class="pnlAmount >= 0 ? 'text-green' : 'text-red'" class="font-mono pnl-value">
          {{ pnlAmount >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pnlAmount)) }}
          ({{ pnlAmount >= 0 ? '+' : '' }}{{ (pnlPercent * 100).toFixed(2) }}%)
        </span>
      </div>
    </div>

    <!-- Allocation section -->
    <div class="card mb-4">
      <div class="card-title">资产配置</div>
      <AllocationBar :data="allocationBarData" />
      <div class="toggle-row">
        <button :class="{ active: viewMode === 'grouped' }" @click="viewMode = 'grouped'">按类别</button>
        <button :class="{ active: viewMode === 'detailed' }" @click="viewMode = 'detailed'">按标的</button>
      </div>
      <AllocationPie :data="allocationPieData" />
      <!-- Grouped breakdown -->
      <div v-if="viewMode === 'grouped' && snapshot?.allocation_grouped" class="group-breakdown">
        <div v-for="g in snapshot.allocation_grouped" :key="g.asset_class" class="group-item">
          <div class="group-color" :style="{ background: getGroupColor(g.asset_class) }"></div>
          <span class="group-name">{{ g.name }}</span>
          <span class="group-value font-mono">¥{{ formatMoney(g.value) }}</span>
          <span class="group-weight">{{ (g.weight * 100).toFixed(1) }}%</span>
        </div>
      </div>
    </div>

    <!-- Positions table -->
    <div class="card mb-4">
      <div class="card-title">持仓明细</div>
      <div class="table-wrap">
        <table v-if="snapshot && snapshot.positions.length > 0">
          <thead>
            <tr>
              <th>标的</th>
              <th>持仓</th>
              <th>可用</th>
              <th>冻结</th>
              <th>均价</th>
              <th>市值</th>
              <th>浮动盈亏</th>
              <th>已实现</th>
              <th>佣金</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pos in snapshot?.positions" :key="pos.symbol">
              <td class="font-mono">{{ pos.symbol }}</td>
              <td class="font-mono">{{ pos.quantity }}</td>
              <td class="font-mono">{{ pos.available_qty }}</td>
              <td class="font-mono">{{ pos.frozen_qty }}</td>
              <td class="font-mono">{{ pos.avg_cost.toFixed(2) }}</td>
              <td class="font-mono">{{ pos.market_value.toFixed(2) }}</td>
              <td class="font-mono" :class="pos.unrealized_pnl >= 0 ? 'text-green' : 'text-red'">
                {{ pos.unrealized_pnl >= 0 ? '+' : '' }}{{ pos.unrealized_pnl.toFixed(2) }}
              </td>
              <td class="font-mono" :class="pos.realized_pnl >= 0 ? 'text-green' : 'text-red'">
                {{ pos.realized_pnl >= 0 ? '+' : '' }}{{ pos.realized_pnl.toFixed(2) }}
              </td>
              <td class="font-mono text-muted">{{ pos.commission_paid.toFixed(2) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="text-muted empty-text">暂无持仓</div>
      </div>
    </div>

    <!-- FAB for cash flow -->
    <div class="fab-single">
      <button class="fab" @click="drawerOpen = true" title="资金流水">
        <Wallet :size="22" />
      </button>
    </div>

    <CashFlowDrawer :open="drawerOpen" @close="drawerOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { usePortfolioStore } from '../stores/portfolio'
import AllocationPie from '../components/AllocationPie.vue'
import AllocationBar from '../components/AllocationBar.vue'
import CashFlowDrawer from '../components/CashFlowDrawer.vue'
import { Wallet } from 'lucide-vue-next'

const portfolioStore = usePortfolioStore()
const snapshot = computed(() => portfolioStore.snapshot)
const viewMode = ref<'grouped' | 'detailed'>('grouped')
const drawerOpen = ref(false)

const holdingsValue = computed(() => (snapshot.value?.total_equity ?? 0) - (snapshot.value?.cash ?? 0))

const allocationPieData = computed(() => {
  if (!snapshot.value) return []
  if (viewMode.value === 'grouped' && snapshot.value.allocation_grouped?.length) {
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

const GROUP_COLORS: Record<string, string> = {
  cash: '#38bdf8',
  stock: '#6366f1',
  etf: '#8b5cf6',
  gold: '#f59e0b',
  bond: '#22c55e',
}

function getGroupColor(ac: string): string {
  return GROUP_COLORS[ac] || '#71717a'
}

onMounted(() => {
  portfolioStore.fetchPortfolio()
  portfolioStore.fetchCashFlows()
})
</script>

<style scoped>
.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.overview-item {
  padding: 12px;
  background: var(--bg-input);
  border-radius: 8px;
}

.ov-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.ov-value {
  font-size: 18px;
  font-weight: 600;
}

.pnl-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding: 10px 12px;
  background: var(--bg-input);
  border-radius: 8px;
  font-size: 14px;
}

.pnl-value {
  font-size: 15px;
  font-weight: 600;
}

.toggle-row {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  background: var(--bg-input);
  border-radius: 8px;
  padding: 3px;
  width: fit-content;
}

.toggle-row button {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  transition: all 0.15s;
}

.toggle-row button.active {
  background: var(--bg-card);
  color: var(--text-primary);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.group-breakdown {
  margin-top: 16px;
}

.group-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.group-item:last-child {
  border-bottom: none;
}

.group-color {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}

.group-name {
  flex: 1;
  font-weight: 500;
}

.group-value {
  font-size: 13px;
}

.group-weight {
  font-size: 12px;
  color: var(--text-muted);
  min-width: 50px;
  text-align: right;
}

.empty-text {
  text-align: center;
  padding: 24px 0;
  font-size: 13px;
}

/* FAB */
.fab-single {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 200;
}

.fab {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: var(--primary);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
  transition: transform 0.15s;
}

.fab:hover {
  transform: scale(1.05);
}

@media (max-width: 768px) {
  .overview-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
