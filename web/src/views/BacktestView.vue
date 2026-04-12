<template>
  <div class="backtest">
    <!-- Error banner -->
    <div v-if="backtestStore.error" class="error-banner">
      <span>{{ backtestStore.error }}</span>
      <button class="error-close" @click="backtestStore.clearError()">&times;</button>
    </div>

    <!-- Tab switch -->
    <div class="tabs mb-4">
      <button class="tab" :class="{ active: mode === 'single' }" @click="mode = 'single'">单策略回测</button>
      <button class="tab" :class="{ active: mode === 'compare' }" @click="mode = 'compare'">策略对比</button>
    </div>

    <!-- ==================== Single Strategy Mode ==================== -->
    <template v-if="mode === 'single'">
      <div class="grid grid-2 mb-4">
        <div class="card">
          <div class="card-title">回测配置</div>

          <!-- Symbol selector -->
          <div class="form-group">
            <label>标的列表</label>
            <div v-for="(asset, idx) in assets" :key="idx" class="asset-row">
              <input type="text" v-model="asset.symbol" placeholder="代码" class="asset-input" />
              <select v-model="asset.asset_class" class="asset-select">
                <option value="stock">股票</option>
                <option value="etf">ETF</option>
                <option value="gold">黄金</option>
                <option value="bond">债券</option>
              </select>
              <button class="btn btn-sm btn-danger" @click="assets.splice(idx, 1)" v-if="assets.length > 1">&times;</button>
            </div>
            <button class="btn btn-sm btn-secondary mt-4" @click="assets.push({ symbol: '', asset_class: 'stock' })">+ 添加标的</button>
          </div>

          <!-- Strategy selector -->
          <div class="form-group">
            <label>策略</label>
            <select v-model="form.strategy" @change="onStrategyChange">
              <option v-for="s in strategies" :key="s.name" :value="s.name">{{ s.description || s.name }}</option>
            </select>
          </div>

          <!-- Dynamic strategy params -->
          <div v-for="p in currentParams" :key="p.name" class="form-group">
            <label>{{ paramLabel(p.name) }}</label>
            <input
              :type="p.type === 'int' || p.type === 'float' ? 'number' : 'text'"
              :step="p.type === 'float' ? '0.1' : undefined"
              v-model.number="strategyParams[p.name]"
            />
          </div>

          <div class="grid grid-2">
            <div class="form-group">
              <label>开始日期</label>
              <input type="date" v-model="form.start_date" />
            </div>
            <div class="form-group">
              <label>结束日期</label>
              <input type="date" v-model="form.end_date" />
            </div>
          </div>
          <div class="form-group">
            <label>初始资金</label>
            <input type="number" v-model.number="form.initial_cash" />
          </div>
          <button class="btn btn-primary mt-4" @click="runBacktest" :disabled="backtestStore.running">
            {{ backtestStore.running ? '运行中...' : '运行回测' }}
          </button>
        </div>

        <div class="card" v-if="backtestStore.currentResult">
          <div class="card-title">回测指标</div>
          <div class="metrics-grid">
            <div class="metric-item" v-for="m in metricsDisplay" :key="m.label">
              <div class="metric-label">{{ m.label }}</div>
              <div class="metric-value" :class="m.class">{{ m.value }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="card" v-if="backtestStore.currentResult && backtestStore.currentResult.equity_curve.length > 0">
        <div class="card-title">权益曲线</div>
        <EquityCurve :data="backtestStore.currentResult.equity_curve" />
      </div>
    </template>

    <!-- ==================== Compare Mode ==================== -->
    <template v-if="mode === 'compare'">
      <div class="grid grid-2 mb-4">
        <div class="card">
          <div class="card-title">对比配置</div>

          <!-- Symbol selector -->
          <div class="form-group">
            <label>标的列表</label>
            <div v-for="(asset, idx) in compareAssets" :key="idx" class="asset-row">
              <input type="text" v-model="asset.symbol" placeholder="代码" class="asset-input" />
              <select v-model="asset.asset_class" class="asset-select">
                <option value="stock">股票</option>
                <option value="etf">ETF</option>
                <option value="gold">黄金</option>
                <option value="bond">债券</option>
              </select>
              <button class="btn btn-sm btn-danger" @click="compareAssets.splice(idx, 1)" v-if="compareAssets.length > 1">&times;</button>
            </div>
            <button class="btn btn-sm btn-secondary mt-4" @click="compareAssets.push({ symbol: '', asset_class: 'stock' })">+ 添加标的</button>
          </div>

          <div class="grid grid-2">
            <div class="form-group">
              <label>开始日期</label>
              <input type="date" v-model="compareForm.start_date" />
            </div>
            <div class="form-group">
              <label>结束日期</label>
              <input type="date" v-model="compareForm.end_date" />
            </div>
          </div>
          <div class="form-group">
            <label>初始资金</label>
            <input type="number" v-model.number="compareForm.initial_cash" />
          </div>
          <button class="btn btn-primary mt-4" @click="runCompare" :disabled="backtestStore.comparing">
            {{ backtestStore.comparing ? '对比中...' : '运行对比' }}
          </button>
        </div>

        <!-- Compare results table -->
        <div class="card" v-if="backtestStore.compareResults.length > 0">
          <div class="card-title">策略指标对比</div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>策略</th>
                  <th>总收益%</th>
                  <th>年化%</th>
                  <th>Sharpe</th>
                  <th>最大回撤%</th>
                  <th>胜率</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in backtestStore.compareResults" :key="r.strategy">
                  <td>{{ r.description || r.strategy }}</td>
                  <td :class="r.metrics.total_return >= 0 ? 'text-green' : 'text-red'">
                    {{ (r.metrics.total_return * 100).toFixed(2) }}%
                  </td>
                  <td :class="r.metrics.annual_return >= 0 ? 'text-green' : 'text-red'">
                    {{ (r.metrics.annual_return * 100).toFixed(2) }}%
                  </td>
                  <td>{{ r.metrics.sharpe.toFixed(2) }}</td>
                  <td class="text-red">{{ (r.metrics.max_drawdown * 100).toFixed(2) }}%</td>
                  <td>{{ (r.metrics.win_rate * 100).toFixed(1) }}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Overlaid equity curves -->
      <div class="card" v-if="backtestStore.compareResults.length > 0">
        <div class="card-title">权益曲线对比</div>
        <EquityCurve :series="compareSeries" />
      </div>
    </template>

    <!-- History backtest results list -->
    <div class="card mt-4" v-if="backtestStore.results.length > 0">
      <div class="card-title">历史回测结果</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>策略</th>
              <th>收益率</th>
              <th>Sharpe</th>
              <th>最大回撤</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in backtestStore.results" :key="r.id">
              <td class="text-muted">{{ r.created_at?.slice(0, 10) || '-' }}</td>
              <td>{{ r.strategy }}</td>
              <td :class="r.total_return >= 0 ? 'text-green' : 'text-red'">
                {{ (r.total_return * 100).toFixed(2) }}%
              </td>
              <td>{{ r.sharpe.toFixed(2) }}</td>
              <td class="text-red">{{ (r.max_drawdown * 100).toFixed(2) }}%</td>
              <td><button class="btn btn-sm btn-secondary" @click="backtestStore.fetchResult(r.id)">查看</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { useBacktestStore, type BacktestRequest, type StrategyInfo, type CompareRequest } from '../stores/backtest'
import EquityCurve from '../components/EquityCurve.vue'

const backtestStore = useBacktestStore()

const mode = ref<'single' | 'compare'>('single')

// Default dates
const yesterday = new Date()
yesterday.setDate(yesterday.getDate() - 1)
const oneYearAgo = new Date(yesterday)
oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1)

const fmt = (d: Date) => d.toISOString().slice(0, 10)

// --- Single strategy form ---
const form = reactive<BacktestRequest>({
  start_date: fmt(oneYearAgo),
  end_date: fmt(yesterday),
  initial_cash: 1000000,
  strategy: 'dual_ma',
  short_period: 5,
  long_period: 20,
  assets: null,
})

const assets = reactive<Array<{ symbol: string; asset_class: string }>>([
  { symbol: '600519', asset_class: 'stock' },
  { symbol: '510300', asset_class: 'etf' },
])

// --- Compare form ---
const compareForm = reactive<CompareRequest>({
  start_date: '2011-06-01',
  end_date: fmt(yesterday),
  initial_cash: 100000,
  strategies: null,
  assets: null,
})

const compareAssets = reactive<Array<{ symbol: string; asset_class: string }>>([
  { symbol: '002594', asset_class: 'stock' },
])

const compareSeries = computed(() => {
  return backtestStore.compareResults.map(r => ({
    name: r.description || r.strategy,
    data: r.equity_curve,
  }))
})

const strategies = ref<StrategyInfo[]>([])
const strategyParams = reactive<Record<string, any>>({
  short_period: 5,
  long_period: 20,
})

const currentParams = computed(() => {
  const s = strategies.value.find(s => s.name === form.strategy)
  return s?.params || []
})

const metricsDisplay = computed(() => {
  const m = backtestStore.currentResult?.metrics
  if (!m) return []
  return [
    { label: '总收益率', value: `${(m.total_return * 100).toFixed(2)}%`, class: m.total_return >= 0 ? 'text-green' : 'text-red' },
    { label: '年化收益', value: `${(m.annual_return * 100).toFixed(2)}%`, class: m.annual_return >= 0 ? 'text-green' : 'text-red' },
    { label: 'Sharpe', value: m.sharpe.toFixed(2), class: '' },
    { label: 'Sortino', value: m.sortino.toFixed(2), class: '' },
    { label: '最大回撤', value: `${(m.max_drawdown * 100).toFixed(2)}%`, class: 'text-red' },
    { label: '胜率', value: `${(m.win_rate * 100).toFixed(1)}%`, class: '' },
    { label: '天数', value: `${m.duration_days}`, class: '' },
  ]
})

const _paramLabels: Record<string, string> = {
  short_period: '短周期',
  long_period: '长周期',
  rsi_period: 'RSI 周期',
  oversold: '超卖阈值',
  overbought: '超买阈值',
  bb_period: '布林带周期',
  num_std: '标准差倍数',
  target_weights: '目标权重',
}

function paramLabel(name: string): string {
  return _paramLabels[name] || name
}

function onStrategyChange() {
  const s = strategies.value.find(s => s.name === form.strategy)
  if (s) {
    for (const p of s.params) {
      if (strategyParams[p.name] === undefined) {
        strategyParams[p.name] = p.default
      }
    }
  }
}

async function runBacktest() {
  const request: BacktestRequest = {
    ...form,
    ...strategyParams,
    assets: assets.filter(a => a.symbol.trim() !== ''),
  }
  await backtestStore.runBacktest(request)
  backtestStore.fetchResults()
}

async function runCompare() {
  const request: CompareRequest = {
    ...compareForm,
    assets: compareAssets.filter(a => a.symbol.trim() !== ''),
  }
  await backtestStore.runCompare(request)
  backtestStore.fetchResults()
}

onMounted(async () => {
  const list = await backtestStore.fetchStrategies()
  if (list) {
    strategies.value = list
    if (list.length > 0 && !list.find(s => s.name === form.strategy)) {
      form.strategy = list[0].name
    }
    onStrategyChange()
  }
  backtestStore.fetchResults()
})
</script>

<style scoped>
.error-banner {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger);
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.error-close {
  background: none;
  border: none;
  color: var(--danger);
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
}

.tabs {
  display: flex;
  gap: 4px;
  background: var(--bg-input);
  border-radius: 8px;
  padding: 4px;
}

.tab {
  flex: 1;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
}

.tab.active {
  background: var(--primary);
  color: #fff;
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.form-group input,
.form-group select {
  width: 100%;
}

.asset-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  align-items: center;
}

.asset-input {
  flex: 1;
  padding: 6px 10px;
}

.asset-select {
  width: 90px;
  padding: 6px 10px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.metric-item {
  padding: 12px;
  background: var(--bg-input);
  border-radius: 8px;
}

.metric-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
}
</style>
