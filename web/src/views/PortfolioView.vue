<template>
  <div class="portfolio-home">
    <section class="portfolio-hero">
      <div class="hero-copy">
        <div class="section-eyebrow">投资组合</div>
        <h1 class="hero-title">持仓、现金与结构风险</h1>
        <p class="hero-text">先看组合结构，再进入明细和最近变动。</p>
        <div class="hero-actions">
          <button class="btn btn-primary" @click="goTrade">记录一笔交易</button>
          <button class="btn btn-secondary" @click="drawerOpen = true">查看资金流水</button>
          <button class="btn btn-secondary" @click="goTasks">查看任务</button>
        </div>
      </div>

      <div class="hero-figure">
        <div class="hero-kpi">
          <span class="hero-kpi-label">总权益</span>
          <span class="hero-kpi-value font-mono">¥{{ formatMoney(snapshot?.total_equity ?? 0) }}</span>
        </div>
        <div class="hero-grid">
          <div class="hero-stat">
            <span class="hero-stat-label">现金</span>
            <span class="hero-stat-value font-mono text-cash">¥{{ formatMoney(snapshot?.cash ?? 0) }}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">持仓市值</span>
            <span class="hero-stat-value font-mono">¥{{ formatMoney(holdingsValue) }}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">累计入金</span>
            <span class="hero-stat-value font-mono">¥{{ formatMoney(snapshot?.total_deposits ?? 0) }}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">持仓标的</span>
            <span class="hero-stat-value">{{ snapshot?.positions.length ?? 0 }}</span>
          </div>
        </div>
        <div class="hero-pnl" v-if="snapshot && snapshot.total_deposits > 0">
          <span class="text-muted">累计盈亏</span>
          <span :class="pnlAmount >= 0 ? 'text-green' : 'text-red'" class="font-mono">
            {{ pnlAmount >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pnlAmount)) }}
            ({{ pnlAmount >= 0 ? '+' : '' }}{{ (pnlPercent * 100).toFixed(2) }}%)
          </span>
        </div>
      </div>
    </section>

    <div class="portfolio-workspace">
      <div class="workspace-main">
        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">核心持仓</div>
              <h2 class="surface-title">核心持仓</h2>
            </div>
            <button class="btn btn-secondary btn-sm" @click="goMarket">查看行情</button>
          </div>

          <div v-if="topPositions.length === 0" class="empty-state">暂无持仓。</div>
          <div v-else class="position-grid">
            <article v-for="pos in topPositions" :key="pos.symbol" class="position-card">
              <div class="position-head">
                <span class="font-mono position-symbol">{{ pos.symbol }}</span>
                <span class="position-chip">{{ positionWeight(pos).toFixed(1) }}%</span>
              </div>
              <div class="position-value font-mono">¥{{ formatMoney(pos.market_value) }}</div>
              <div class="position-meta">
                <span>持仓 {{ pos.quantity }}</span>
                <span>成本 ¥{{ pos.avg_cost.toFixed(2) }}</span>
              </div>
              <div class="position-pnl" :class="pos.unrealized_pnl >= 0 ? 'text-green' : 'text-red'">
                {{ pos.unrealized_pnl >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pos.unrealized_pnl)) }}
              </div>
            </article>
          </div>
        </section>

        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">持仓明细</div>
              <h2 class="surface-title">持仓明细</h2>
            </div>
          </div>
          <div class="table-wrap">
            <table v-if="snapshot && snapshot.positions.length > 0">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>持仓</th>
                  <th>可用</th>
                  <th>均价</th>
                  <th>市值</th>
                  <th>浮动盈亏</th>
                  <th>已实现</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="pos in snapshot.positions" :key="pos.symbol">
                  <td class="font-mono">{{ pos.symbol }}</td>
                  <td class="font-mono">{{ pos.quantity }}</td>
                  <td class="font-mono">{{ pos.available_qty }}</td>
                  <td class="font-mono">¥{{ pos.avg_cost.toFixed(2) }}</td>
                  <td class="font-mono">¥{{ formatMoney(pos.market_value) }}</td>
                  <td class="font-mono" :class="pos.unrealized_pnl >= 0 ? 'text-green' : 'text-red'">
                    {{ pos.unrealized_pnl >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pos.unrealized_pnl)) }}
                  </td>
                  <td class="font-mono" :class="pos.realized_pnl >= 0 ? 'text-green' : 'text-red'">
                    {{ pos.realized_pnl >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(pos.realized_pnl)) }}
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无持仓。</div>
          </div>
        </section>
      </div>

      <aside class="workspace-side">
        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">结构分布</div>
              <h2 class="surface-title">资产配置</h2>
            </div>
          </div>
          <AllocationBar :data="allocationBarData" />
          <div class="toggle-row">
            <button :class="{ active: viewMode === 'grouped' }" @click="viewMode = 'grouped'">按类别</button>
            <button :class="{ active: viewMode === 'detailed' }" @click="viewMode = 'detailed'">按标的</button>
          </div>
          <AllocationPie :data="allocationPieData" />
          <div v-if="viewMode === 'grouped' && snapshot?.allocation_grouped" class="group-breakdown">
            <div v-for="g in snapshot.allocation_grouped" :key="g.asset_class" class="group-item">
              <div class="group-color" :style="{ background: getGroupColor(g.asset_class) }"></div>
              <span class="group-name">{{ g.name }}</span>
              <span class="group-value font-mono">¥{{ formatMoney(g.value) }}</span>
              <span class="group-weight">{{ (g.weight * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </section>

        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">最近活动</div>
              <h2 class="surface-title">最近变动</h2>
            </div>
          </div>
          <div v-if="activities.length === 0" class="empty-state">暂无最近活动。</div>
          <div v-else class="activity-list">
            <article v-for="item in activities.slice(0, 5)" :key="`${item.kind}-${item.timestamp}-${item.title}`" class="activity-row">
              <div>
                <div class="activity-title">{{ item.title }}</div>
                <div class="activity-detail">{{ item.detail }}</div>
              </div>
              <span class="activity-time">{{ formatTime(item.timestamp) }}</span>
            </article>
          </div>
        </section>
      </aside>
    </div>

    <CashFlowDrawer :open="drawerOpen" @close="drawerOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePortfolioStore } from '../stores/portfolio'
import AllocationPie from '../components/AllocationPie.vue'
import AllocationBar from '../components/AllocationBar.vue'
import CashFlowDrawer from '../components/CashFlowDrawer.vue'

const router = useRouter()
const portfolioStore = usePortfolioStore()
const snapshot = computed(() => portfolioStore.snapshot)
const activities = computed(() => portfolioStore.activities)
const viewMode = ref<'grouped' | 'detailed'>('grouped')
const drawerOpen = ref(false)

const holdingsValue = computed(() => (snapshot.value?.total_equity ?? 0) - (snapshot.value?.cash ?? 0))
const topPositions = computed(() =>
  [...(snapshot.value?.positions ?? [])]
    .sort((a, b) => b.market_value - a.market_value)
    .slice(0, 4)
)

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

function formatTime(ts: string): string {
  return ts.slice(0, 16).replace('T', ' ')
}

function positionWeight(pos: { market_value: number }) {
  const total = snapshot.value?.total_equity ?? 0
  return total > 0 ? (pos.market_value / total) * 100 : 0
}

const GROUP_COLORS: Record<string, string> = {
  cash: '#0f6f8f',
  stock: '#2563eb',
  etf: '#7c3aed',
  gold: '#d08700',
  bond: '#1f8a70',
}

function getGroupColor(ac: string): string {
  return GROUP_COLORS[ac] || '#94a3b8'
}

function goTrade() {
  router.push('/trade')
}

function goTasks() {
  router.push('/signals')
}

function goMarket() {
  router.push('/market')
}

onMounted(() => {
  portfolioStore.fetchPortfolio()
  portfolioStore.fetchCashFlows()
  portfolioStore.fetchActivity()
})
</script>

<style scoped>
.portfolio-home {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.portfolio-hero {
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

.hero-kpi {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hero-kpi-label,
.hero-stat-label {
  font-size: 11px;
  color: rgba(245, 247, 250, 0.6);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.hero-kpi-value {
  font-size: clamp(30px, 3.2vw, 40px);
  line-height: 1;
}

.hero-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 22px;
}

.hero-stat {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.05);
}

.hero-stat-value {
  display: block;
  margin-top: 6px;
  color: #fff;
  font-weight: 600;
}

.hero-pnl {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.portfolio-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.82fr);
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

.position-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.position-card {
  padding: 18px;
  border-radius: 18px;
  background: rgba(248, 250, 252, 0.78);
  border: 1px solid rgba(15, 23, 42, 0.06);
  transition: transform var(--transition-fast), border-color var(--transition-fast);
}

.position-card:hover {
  transform: translateY(-2px);
  border-color: rgba(15, 23, 42, 0.14);
}

.position-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.position-symbol {
  font-weight: 600;
}

.position-chip {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
}

.position-value {
  margin-top: 16px;
  font-size: 24px;
  line-height: 1;
}

.position-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-secondary);
}

.position-pnl {
  margin-top: 12px;
  font-size: 14px;
  font-weight: 600;
}

.toggle-row {
  display: flex;
  gap: 4px;
  margin: 14px 0 16px;
  background: var(--bg-input);
  border-radius: var(--radius-md);
  padding: 3px;
  width: fit-content;
}

.toggle-row button {
  padding: 8px 16px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  color: var(--text-secondary);
  font-family: var(--font-sans);
}

.toggle-row button.active {
  background: rgba(255, 255, 255, 0.92);
  color: var(--text-primary);
}

.group-breakdown {
  margin-top: 16px;
}

.group-item {
  display: flex;
  align-items: center;
  gap: 12px;
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
  min-width: 48px;
  text-align: right;
}

.activity-list {
  display: flex;
  flex-direction: column;
}

.activity-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border-top: 1px solid var(--border);
}

.activity-row:first-child {
  border-top: none;
  padding-top: 0;
}

.activity-title {
  font-weight: 600;
}

.activity-detail {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 13px;
}

.activity-time {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.empty-state {
  padding: 22px 0;
  color: var(--text-muted);
  font-size: 14px;
}

.portfolio-home > * {
  animation: riseIn 420ms ease both;
}

.portfolio-home > *:nth-child(2) {
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
  .portfolio-hero,
  .portfolio-workspace {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .portfolio-home {
    gap: 14px;
  }

  .portfolio-hero,
  .surface {
    padding: 18px;
  }

  .position-grid,
  .hero-grid {
    grid-template-columns: 1fr;
  }

  .surface-head,
  .hero-pnl,
  .activity-row,
  .position-meta {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
