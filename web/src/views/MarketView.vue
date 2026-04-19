<template>
  <div class="market-page">
    <section class="page-intro">
      <div>
        <div class="section-eyebrow">行情</div>
        <h1 class="page-title">本地快照优先的关注观察台</h1>
        <p class="page-copy">先读本地缓存，再异步刷新行情快照；在这里管理关注标的、分类筛选和持仓收益。</p>
      </div>
      <div class="intro-actions">
        <button class="btn btn-secondary" @click="refreshAll">刷新快照</button>
        <button class="btn btn-primary" @click="focusAddForm">新增关注</button>
      </div>
    </section>

    <section class="surface">
      <div class="surface-head">
        <div>
          <div class="section-eyebrow">数据源与同步</div>
          <h2 class="surface-title">数据源状态</h2>
        </div>
        <div class="surface-meta">{{ marketStatusLabel }} · {{ healthSummary }}</div>
      </div>
      <AppNotice
        :tone="marketStore.dataHealth?.refresh_policy === 'cache_only' ? 'info' : 'success'"
        :title="marketStore.dataHealth?.refresh_policy === 'cache_only' ? '当前使用本地最新快照' : '当前处于开市实时模式'"
        :message="
          marketStore.dataHealth?.refresh_policy === 'cache_only'
            ? `截至 ${latestSyncLabel}，闭市期间不重复请求 AKShare，只展示本地快照。`
            : '页面优先读取本地数据库，再由后端异步刷新并写回。'
        "
        dense
        class="sync-notice"
      />

      <div class="ops-grid">
        <div class="ops-card">
          <div class="ops-label">当前数据源</div>
          <div class="ops-inline">
            <select v-model="settings.data_source" class="ops-select">
              <option value="akshare">AKShare</option>
              <option value="tushare">Tushare</option>
            </select>
            <button class="btn btn-secondary" @click="saveDataSource" :disabled="savingSource">
              {{ savingSource ? '保存中...' : '保存数据源' }}
            </button>
          </div>
          <p class="ops-copy">数据源选择会写入全局配置，下一次行情拉取直接生效。</p>
        </div>

        <div class="ops-card" v-if="settings.data_source === 'tushare'">
          <div class="ops-label">Tushare Token</div>
          <div class="ops-inline">
            <input v-model="settings.tushare_token" type="text" placeholder="请输入或更新 Tushare Token" />
            <button class="btn btn-secondary" @click="saveDataSource" :disabled="savingSource">
              保存
            </button>
          </div>
          <p class="ops-copy">如果设置页里已经保存过，这里会显示脱敏后的值。</p>
        </div>

        <div class="ops-card">
          <div class="ops-label">最后成功快照</div>
          <div class="ops-kpi">{{ latestSyncLabel }}</div>
          <p class="ops-copy">闭市与周末会保持缓存模式；开市后才恢复异步刷新。</p>
        </div>
      </div>
    </section>

    <section class="overview-strip">
      <article class="overview-tile">
        <div class="overview-label">{{ selectedRange.label }} 关注标的</div>
        <div class="overview-value">{{ filteredWatchlist.length }}</div>
      </article>
      <article class="overview-tile">
        <div class="overview-label">持仓中</div>
        <div class="overview-value">{{ holdingCount }}</div>
      </article>
      <article class="overview-tile">
        <div class="overview-label">持仓市值</div>
        <div class="overview-value font-mono">¥{{ formatMoney(holdingMarketValue) }}</div>
      </article>
      <article class="overview-tile">
        <div class="overview-label">{{ selectedRange.label }} 实时收益</div>
        <div class="overview-value font-mono" :class="holdingUnrealizedPnl >= 0 ? 'text-green' : 'text-red'">
          {{ holdingUnrealizedPnl >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(holdingUnrealizedPnl)) }}
        </div>
      </article>
    </section>

    <div class="market-layout">
      <div class="market-main">
        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">关注列表</div>
              <h2 class="surface-title">分类与持仓状态</h2>
            </div>
          </div>

          <div class="toolbar">
            <div class="filter-tabs">
              <button
                v-for="option in assetFilters"
                :key="option.value"
                class="filter-tab"
                :class="{ active: activeFilter === option.value }"
                @click="activeFilter = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="toolbar-caption">显示 {{ filteredWatchlist.length }} / {{ marketStore.watchlist.length }} 个标的</div>
          </div>

          <div class="range-tabs">
            <button
              v-for="range in ranges"
              :key="range.value"
              class="range-tab"
              :class="{ active: selectedRangeKey === range.value }"
              @click="changeRange(range.value)"
            >
              {{ range.label }}
            </button>
          </div>

          <div v-if="filteredWatchlist.length === 0" class="empty-state">
            当前分类下没有关注标的。
          </div>
          <div v-else class="watchlist-list">
            <article
              v-for="item in filteredWatchlist"
              :key="item.symbol"
              class="watch-row"
              :class="{ active: selectedSymbol === item.symbol }"
              @click="selectSymbol(item.symbol)"
            >
              <div class="watch-head">
                <div>
                  <div class="watch-symbol font-mono">{{ item.symbol }}</div>
                  <div class="watch-name">{{ item.name || assetClassLabel(item.asset_class) }}</div>
                </div>
                <div class="watch-badges">
                  <span class="asset-badge">{{ assetClassLabel(item.asset_class) }}</span>
                  <span class="holding-badge" :class="item.is_holding ? 'is-held' : 'is-empty'">
                    {{ item.is_holding ? '持仓中' : '未持有' }}
                  </span>
                </div>
              </div>

              <div class="watch-row-price">
                <div class="watch-price font-mono">
                  {{ quoteFor(item.symbol)?.price?.toFixed(2) ?? '--' }}
                </div>
                <div class="watch-change" :class="periodReturnClass(item.symbol)">
                  {{ formatPercent(periodReturnValue(item.symbol)) }}
                </div>
              </div>

              <div class="watch-actions">
                <button class="btn btn-secondary btn-sm" @click.stop="showKline(item.symbol)">查看走势</button>
                <button class="btn btn-secondary btn-sm" @click.stop="removeItem(item.symbol)" :disabled="removingSymbol === item.symbol">
                  {{ removingSymbol === item.symbol ? '移除中...' : '移除关注' }}
                </button>
              </div>
            </article>
          </div>
        </section>

        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">明细表</div>
              <h2 class="surface-title">持仓、快照与收益</h2>
            </div>
          </div>

          <div class="table-wrap">
            <table v-if="filteredWatchlist.length > 0">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>分类</th>
                  <th>持有</th>
                  <th>最新价</th>
                  <th>数量</th>
                  <th>实时收益</th>
                  <th>{{ selectedRange.label }} 收益</th>
                  <th>快照</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in filteredWatchlist" :key="`${item.symbol}-row`">
                  <td class="font-mono">{{ item.symbol }}</td>
                  <td>{{ assetClassLabel(item.asset_class) }}</td>
                  <td>{{ item.is_holding ? '是' : '否' }}</td>
                  <td class="font-mono">{{ quoteFor(item.symbol)?.price?.toFixed(2) ?? '--' }}</td>
                  <td class="font-mono">{{ item.quantity ?? 0 }}</td>
                  <td class="font-mono" :class="(item.unrealized_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'">
                    {{ (item.unrealized_pnl ?? 0) >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(item.unrealized_pnl ?? 0)) }}
                  </td>
                  <td class="font-mono" :class="periodReturnClass(item.symbol)">
                    {{ formatPercent(periodReturnValue(item.symbol)) }}
                  </td>
                  <td>{{ formatTimestamp(item.last_snapshot_at || quoteFor(item.symbol)?.timestamp) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <aside class="market-side">
        <section class="surface detail-surface" v-if="selectedItem">
          <div class="detail-top">
            <div>
              <div class="section-eyebrow">{{ assetClassLabel(selectedItem.asset_class) }}</div>
              <h2 class="detail-title">{{ selectedItem.symbol }}</h2>
              <div class="detail-subtitle">
                {{ selectedItem.name || assetClassLabel(selectedItem.asset_class) }}
              </div>
              <div class="detail-status">
                {{ selectedRangeKey === '1d' ? '日内分钟走势' : `${selectedRange.label} 区间走势` }}
                <span>·</span>
                <span>{{ marketStatusLabel }}</span>
              </div>
            </div>
            <div class="detail-price-block">
              <div class="detail-price font-mono">{{ quoteFor(selectedItem.symbol)?.price?.toFixed(2) ?? '--' }}</div>
              <div class="detail-return" :class="selectedPeriodReturnClass">
                {{ selectedRange.label }} {{ formatPercent(selectedPeriodReturn) }}
              </div>
              <div class="detail-updated">更新于 {{ formatTimestamp(selectedItem.last_snapshot_at || quoteFor(selectedItem.symbol)?.timestamp) }}</div>
            </div>
          </div>

          <div class="range-tabs detail-range-tabs">
            <button
              v-for="range in ranges"
              :key="`detail-${range.value}`"
              class="range-tab"
              :class="{ active: selectedRangeKey === range.value }"
              @click="changeRange(range.value)"
            >
              {{ range.label }}
            </button>
          </div>

          <KlineChart :data="klineData" />

          <div class="detail-grid">
            <div class="stat-chip">
              <span class="metric-label">快照时间</span>
              <span>{{ formatTimestamp(selectedItem.last_snapshot_at || quoteFor(selectedItem.symbol)?.timestamp) }}</span>
            </div>
            <div class="stat-chip">
              <span class="metric-label">持仓数量</span>
              <span class="font-mono">{{ selectedItem.quantity ?? 0 }}</span>
            </div>
            <div class="stat-chip">
              <span class="metric-label">成本</span>
              <span class="font-mono">¥{{ selectedItem.avg_cost?.toFixed(2) ?? '--' }}</span>
            </div>
            <div class="stat-chip">
              <span class="metric-label">实时收益</span>
              <span class="font-mono" :class="(selectedItem.unrealized_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'">
                {{ (selectedItem.unrealized_pnl ?? 0) >= 0 ? '+' : '' }}¥{{ formatMoney(Math.abs(selectedItem.unrealized_pnl ?? 0)) }}
              </span>
            </div>
            <div class="stat-chip">
              <span class="metric-label">{{ selectedRange.label }} 收益</span>
              <span class="font-mono" :class="selectedPeriodReturnClass">{{ formatPercent(selectedPeriodReturn) }}</span>
            </div>
          </div>
        </section>

        <section class="surface add-surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">新增关注</div>
              <h2 class="surface-title">添加基金、股票或黄金</h2>
            </div>
          </div>
          <AppNotice
            v-if="inlineNotice"
            :tone="inlineNotice.tone"
            :title="inlineNotice.title"
            :message="inlineNotice.message"
            dense
            class="inline-notice"
          />
          <div class="form-group">
            <label>标的代码</label>
            <input ref="addInputRef" v-model="draft.symbol" type="text" placeholder="如 600519 / 510300 / Au99.99" />
          </div>
          <div class="form-group">
            <label>资产类别</label>
            <select v-model="draft.asset_class">
              <option value="stock">股票</option>
              <option value="etf">ETF / 基金</option>
              <option value="gold">黄金</option>
              <option value="bond">债券</option>
            </select>
          </div>
          <button class="btn btn-primary add-btn" @click="addItem" :disabled="addingItem">
            {{ addingItem ? '新增中...' : '新增关注' }}
          </button>
          <p class="ops-copy">新增后会立即进入本地观察列表；如果实时调度正在运行，新标的要在重启后才会纳入后台轮询。</p>
        </section>

        <section class="surface">
          <div class="surface-head">
            <div>
              <div class="section-eyebrow">收益曲线</div>
              <h2 class="surface-title">{{ selectedRange.label }} 累计收益对比</h2>
            </div>
            <div class="surface-meta">归一化到区间起点，方便比较股票、基金和黄金</div>
          </div>
          <ReturnCurveChart :series="returnCurveSeries" />
        </section>

      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import client from '../api/client'
import AppNotice from '../components/AppNotice.vue'
import KlineChart from '../components/KlineChart.vue'
import ReturnCurveChart from '../components/ReturnCurveChart.vue'
import { useMarketStore, type KlineBar } from '../stores/market'
import { usePortfolioStore } from '../stores/portfolio'
import { useUiStore } from '../stores/ui'

type FilterValue = 'all' | 'stock' | 'etf' | 'gold' | 'bond'
type RangeValue = '1d' | '1w' | '1m' | '3m' | '6m' | 'ytd' | '1y' | '2y' | '5y' | '10y' | 'all'

const marketStore = useMarketStore()
const portfolioStore = usePortfolioStore()
const uiStore = useUiStore()

const klineSymbol = ref('')
const selectedSymbol = ref('')
const klineData = ref<KlineBar[]>([])
const selectedRangeKey = ref<RangeValue>('1m')
const historicalReturns = ref<Record<string, number | null>>({})
const historicalSeries = ref<Record<string, KlineBar[]>>({})
const activeFilter = ref<FilterValue>('all')
const addingItem = ref(false)
const removingSymbol = ref('')
const savingSource = ref(false)
const addInputRef = ref<HTMLInputElement | null>(null)
const inlineNotice = ref<{ tone: 'success' | 'error' | 'info'; title: string; message: string } | null>(null)
const draft = reactive({
  symbol: '',
  asset_class: 'stock',
})
const settings = reactive({
  host: '0.0.0.0',
  port: 8000,
  live_auto_start: true,
  initial_cash: 100000,
  start_date: '2025-01-02',
  end_date: '',
  assets: [] as Array<{ symbol: string; asset_class: string }>,
  strategy: 'dual_ma',
  short_period: 5,
  long_period: 20,
  data_source: 'akshare',
  tushare_token: '',
  live_poll_interval: 60,
  notification: { type: 'console' } as Record<string, any>,
})

let refreshTimer: ReturnType<typeof setInterval> | null = null

const ranges = [
  { value: '1d', label: '1天' },
  { value: '1w', label: '1周' },
  { value: '1m', label: '1个月' },
  { value: '3m', label: '3个月' },
  { value: '6m', label: '6个月' },
  { value: 'ytd', label: '年初至今' },
  { value: '1y', label: '1年' },
  { value: '2y', label: '2年' },
  { value: '5y', label: '5年' },
  { value: '10y', label: '10年' },
  { value: 'all', label: '全部' },
] as const

const assetFilters = [
  { value: 'all', label: '全部' },
  { value: 'stock', label: '股票' },
  { value: 'etf', label: '基金 / ETF' },
  { value: 'gold', label: '黄金' },
  { value: 'bond', label: '债券' },
] as const

const selectedRange = computed(() =>
  ranges.find((range) => range.value === selectedRangeKey.value) ?? ranges[2],
)

const filteredWatchlist = computed(() =>
  marketStore.watchlist.filter((item) =>
    activeFilter.value === 'all' ? true : item.asset_class === activeFilter.value,
  ),
)

const holdingCount = computed(() => marketStore.watchlist.filter((item) => item.is_holding).length)
const holdingMarketValue = computed(() =>
  marketStore.watchlist.reduce((sum, item) => sum + (item.market_value ?? 0), 0),
)
const holdingUnrealizedPnl = computed(() =>
  marketStore.watchlist.reduce((sum, item) => sum + (item.unrealized_pnl ?? 0), 0),
)
const latestSyncLabel = computed(() => {
  const timestamps = (marketStore.dataHealth?.quotes ?? [])
    .map((item) => item.timestamp)
    .filter(Boolean) as string[]
  if (timestamps.length === 0) return '暂无本地快照'
  return formatTimestamp([...timestamps].sort()[timestamps.length - 1] ?? null)
})
const healthSummary = computed(() => {
  const available = (marketStore.dataHealth?.quotes ?? []).filter((item) => item.timestamp).length
  return `${available} / ${marketStore.watchlist.length} 个标的已有本地快照`
})
const marketStatusLabel = computed(() =>
  marketStore.dataHealth?.refresh_policy === 'cache_only' ? '休市缓存模式' : '开市实时模式',
)
const selectedItem = computed(
  () => marketStore.watchlist.find((item) => item.symbol === selectedSymbol.value) ?? null,
)

const returnCurveSeries = computed(() =>
  filteredWatchlist.value
    .map((item) => {
      const bars = historicalSeries.value[buildHistoryKey(item.symbol, selectedRangeKey.value)] ?? []
      if (bars.length < 2) return null
      const base = bars[0]?.close ?? 0
      if (!base) return null
      return {
        name: item.symbol,
        points: bars.map((bar) => ({
          timestamp: bar.timestamp,
          value: (bar.close - base) / base,
        })),
      }
    })
    .filter(Boolean) as Array<{ name: string; points: Array<{ timestamp: string; value: number }> }>,
)

function quoteFor(symbol: string) {
  return marketStore.quotes[symbol]
}

function assetClassLabel(assetClass: string) {
  const mapping: Record<string, string> = {
    stock: '股票',
    etf: '基金',
    gold: '黄金',
    bond: '债券',
  }
  return mapping[assetClass] ?? assetClass
}

function formatMoney(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(2)}%`
}

function formatTimestamp(ts: string | null | undefined) {
  if (!ts) return '暂无'
  return ts.slice(0, 19).replace('T', ' ')
}

function getHistoricalReturn(data: KlineBar[]) {
  if (data.length < 2) return null
  const firstClose = data[0]?.close ?? 0
  const lastClose = data[data.length - 1]?.close ?? 0
  if (!firstClose) return null
  return (lastClose - firstClose) / firstClose
}

function buildRangeStart(range: RangeValue) {
  const now = new Date()
  const start = new Date(now)
  switch (range) {
    case '1d':
      start.setDate(start.getDate() - 3)
      return start.toISOString().slice(0, 10)
    case '1w':
      start.setDate(start.getDate() - 10)
      return start.toISOString().slice(0, 10)
    case '1m':
      start.setMonth(start.getMonth() - 1)
      return start.toISOString().slice(0, 10)
    case '3m':
      start.setMonth(start.getMonth() - 3)
      return start.toISOString().slice(0, 10)
    case '6m':
      start.setMonth(start.getMonth() - 6)
      return start.toISOString().slice(0, 10)
    case 'ytd':
      return `${now.getFullYear()}-01-01`
    case '1y':
      start.setFullYear(start.getFullYear() - 1)
      return start.toISOString().slice(0, 10)
    case '2y':
      start.setFullYear(start.getFullYear() - 2)
      return start.toISOString().slice(0, 10)
    case '5y':
      start.setFullYear(start.getFullYear() - 5)
      return start.toISOString().slice(0, 10)
    case '10y':
      start.setFullYear(start.getFullYear() - 10)
      return start.toISOString().slice(0, 10)
    case 'all':
      return undefined
  }
}

function buildRangeEnd() {
  return new Date().toISOString().slice(0, 10)
}

function resolveInterval(symbol: string) {
  const item = marketStore.watchlist.find((candidate) => candidate.symbol === symbol)
  if (selectedRangeKey.value !== '1d') return '1d'
  return item?.asset_class === 'stock' || item?.asset_class === 'etf' ? '1m' : '1d'
}

function periodReturnValue(symbol: string) {
  return historicalReturns.value[symbol] ?? null
}

function periodReturnClass(symbol: string) {
  const value = periodReturnValue(symbol)
  if (value === null) return ''
  return value >= 0 ? 'text-green' : 'text-red'
}

const selectedPeriodReturn = computed(() => {
  if (!klineSymbol.value) return null
  return periodReturnValue(klineSymbol.value)
})

const selectedPeriodReturnClass = computed(() => {
  if (selectedPeriodReturn.value === null) return ''
  return selectedPeriodReturn.value >= 0 ? 'text-green' : 'text-red'
})

async function loadSettings() {
  const { data } = await client.get('/settings')
  settings.host = data.host
  settings.port = data.port
  settings.live_auto_start = data.live_auto_start
  settings.initial_cash = data.initial_cash
  settings.start_date = data.start_date
  settings.end_date = data.end_date
  settings.assets = data.assets ?? []
  settings.strategy = data.strategy
  settings.short_period = data.short_period
  settings.long_period = data.long_period
  settings.data_source = data.data_source
  settings.tushare_token = data.tushare_token ?? ''
  settings.live_poll_interval = data.live_poll_interval
  settings.notification = data.notification ?? { type: 'console' }
}

async function saveDataSource() {
  savingSource.value = true
  try {
    settings.assets = marketStore.watchlist.map((item) => ({
      symbol: item.symbol,
      asset_class: item.asset_class,
    }))
    await client.put('/settings', { ...settings })
    inlineNotice.value = { tone: 'success', title: '数据源已保存', message: '新的数据源配置已经写入，可立即用于后续拉取。' }
    uiStore.success('新的数据源配置已经写入。', '数据源已保存')
    await refreshAll()
  } catch (error: any) {
    inlineNotice.value = { tone: 'error', title: '保存失败', message: error.message ?? '请稍后重试。' }
    uiStore.error(error.message ?? '请稍后重试。', '数据源保存失败')
  } finally {
    savingSource.value = false
  }
}

async function refreshAll() {
  await Promise.all([
    marketStore.fetchWatchlist(),
    marketStore.fetchDataHealth(),
    portfolioStore.fetchPortfolio(),
  ])
  await marketStore.fetchAllQuotes()
  if (!selectedSymbol.value && marketStore.watchlist.length > 0) {
    selectedSymbol.value = marketStore.watchlist[0].symbol
  }
  await refreshHistoricalSeries()
}

async function addItem() {
  const symbol = draft.symbol.trim()
  if (!symbol || addingItem.value) return
  addingItem.value = true
  inlineNotice.value = null
  try {
    await marketStore.addWatchlistItem(symbol, draft.asset_class)
    settings.assets = marketStore.watchlist.map((item) => ({
      symbol: item.symbol,
      asset_class: item.asset_class,
    }))
    await refreshAll()
    draft.symbol = ''
    draft.asset_class = 'stock'
    inlineNotice.value = { tone: 'success', title: '关注已新增', message: `${symbol} 已进入本地观察列表。` }
    uiStore.success(`${symbol} 已进入本地观察列表。`, '关注已新增')
  } catch (error: any) {
    inlineNotice.value = { tone: 'error', title: '新增失败', message: error.response?.data?.detail ?? error.message ?? '请稍后重试。' }
    uiStore.error(error.response?.data?.detail ?? error.message ?? '请稍后重试。', '新增失败')
  } finally {
    addingItem.value = false
  }
}

async function removeItem(symbol: string) {
  removingSymbol.value = symbol
  try {
    await marketStore.removeWatchlistItem(symbol)
    settings.assets = marketStore.watchlist.map((item) => ({
      symbol: item.symbol,
      asset_class: item.asset_class,
    }))
    await refreshAll()
    if (klineSymbol.value === symbol) {
      klineSymbol.value = ''
      klineData.value = []
    }
    uiStore.info(`${symbol} 已从关注列表移除。`, '已移除')
  } catch (error: any) {
    uiStore.error(error.response?.data?.detail ?? error.message ?? '请稍后重试。', '移除失败')
  } finally {
    removingSymbol.value = ''
  }
}

async function showKline(symbol: string) {
  selectedSymbol.value = symbol
  klineSymbol.value = symbol
  const key = buildHistoryKey(symbol, selectedRangeKey.value)
  const bars =
    historicalSeries.value[key] ??
    (await marketStore.fetchKline(
      symbol,
      buildRangeStart(selectedRangeKey.value),
      buildRangeEnd(),
      resolveInterval(symbol),
    ))
  historicalSeries.value[key] = bars
  klineData.value = bars
  historicalReturns.value[symbol] = getHistoricalReturn(bars)
}

function buildHistoryKey(symbol: string, range: RangeValue) {
  return `${symbol}:${range}`
}

async function refreshHistoricalSeries() {
  const startDate = buildRangeStart(selectedRangeKey.value)
  const entries = await Promise.all(
    marketStore.watchlist.map(async (item) => {
      try {
        const key = buildHistoryKey(item.symbol, selectedRangeKey.value)
        const bars =
          historicalSeries.value[key] ??
          (await marketStore.fetchKline(item.symbol, startDate, buildRangeEnd(), resolveInterval(item.symbol)))
        return {
          symbol: item.symbol,
          key,
          bars,
          value: getHistoricalReturn(bars),
        }
      } catch {
        return {
          symbol: item.symbol,
          key: buildHistoryKey(item.symbol, selectedRangeKey.value),
          bars: [] as KlineBar[],
          value: null,
        }
      }
    }),
  )
  for (const entry of entries) {
    historicalSeries.value[entry.key] = entry.bars
  }
  historicalReturns.value = Object.fromEntries(entries.map((entry) => [entry.symbol, entry.value]))
  if (klineSymbol.value) {
    const selectedKey = buildHistoryKey(klineSymbol.value, selectedRangeKey.value)
    klineData.value = historicalSeries.value[selectedKey] ?? []
  } else if (selectedSymbol.value) {
    const selectedKey = buildHistoryKey(selectedSymbol.value, selectedRangeKey.value)
    klineSymbol.value = selectedSymbol.value
    klineData.value = historicalSeries.value[selectedKey] ?? []
  }
}

async function changeRange(range: RangeValue) {
  if (selectedRangeKey.value === range) return
  selectedRangeKey.value = range
  await refreshHistoricalSeries()
}

async function selectSymbol(symbol: string) {
  selectedSymbol.value = symbol
  await showKline(symbol)
}

async function focusAddForm() {
  await nextTick()
  addInputRef.value?.focus()
}

onMounted(async () => {
  await Promise.all([loadSettings(), refreshAll()])
  marketStore.startListening()
  if (marketStore.dataHealth?.refresh_policy !== 'cache_only') {
    refreshTimer = setInterval(() => {
      marketStore.fetchAllQuotes()
      marketStore.fetchDataHealth()
    }, 30000)
  }
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.market-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.intro-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.ops-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.sync-notice {
  margin-bottom: 14px;
}

.ops-card {
  padding: 18px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.58);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.ops-label,
.metric-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.ops-inline {
  display: flex;
  gap: 10px;
  margin-top: 10px;
}

.ops-inline input,
.ops-inline select {
  flex: 1;
}

.ops-select {
  min-width: 160px;
}

.ops-copy {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.55;
}

.ops-kpi {
  margin-top: 10px;
  font-size: 22px;
  letter-spacing: -0.03em;
}

.overview-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.overview-tile {
  padding: 18px 20px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: var(--shadow-card);
}

.overview-label {
  font-size: 12px;
  color: var(--text-muted);
}

.overview-value {
  margin-top: 8px;
  font-size: 28px;
  letter-spacing: -0.04em;
}

.market-layout {
  display: grid;
  grid-template-columns: minmax(300px, 0.78fr) minmax(0, 1.22fr);
  gap: 18px;
}

.market-main,
.market-side {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.filter-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.range-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.filter-tab {
  min-height: 32px;
  padding: 6px 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.66);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.filter-tab.active,
.range-tab.active {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.18);
  color: var(--primary);
}

.range-tab {
  min-height: 30px;
  padding: 4px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.66);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: 12px;
}

.toolbar-caption {
  font-size: 12px;
  color: var(--text-muted);
}

.watchlist-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.watch-row {
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid rgba(15, 23, 42, 0.06);
  cursor: pointer;
  transition: transform var(--transition-fast), border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.watch-row:hover,
.watch-row.active {
  transform: translateY(-1px);
  border-color: rgba(37, 99, 235, 0.18);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.08);
}

.watch-head,
.watch-actions,
.detail-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.watch-row-price {
  margin-top: 14px;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
}

.watch-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.watch-symbol {
  font-size: 18px;
  line-height: 1;
}

.watch-name {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.asset-badge,
.holding-badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.asset-badge {
  background: rgba(37, 99, 235, 0.08);
  color: var(--primary);
}

.holding-badge.is-held {
  background: rgba(31, 138, 112, 0.1);
  color: var(--success);
}

.holding-badge.is-empty {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-secondary);
}

.watch-price {
  font-size: 26px;
  letter-spacing: -0.04em;
}

.watch-change {
  font-size: 15px;
  font-weight: 600;
}

.watch-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 18px;
}

.stat-chip {
  padding: 12px;
  border-radius: 16px;
  background: rgba(247, 249, 252, 0.84);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.watch-actions {
  margin-top: 18px;
}

.detail-surface {
  overflow: hidden;
}

.detail-title {
  font-size: clamp(28px, 3vw, 42px);
  line-height: 1;
  letter-spacing: -0.05em;
}

.detail-subtitle {
  margin-top: 6px;
  font-size: 14px;
  color: var(--text-secondary);
}

.detail-status,
.detail-updated {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.detail-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.detail-price-block {
  text-align: right;
}

.detail-price {
  font-size: clamp(28px, 3vw, 38px);
  line-height: 1;
  letter-spacing: -0.05em;
}

.detail-return {
  margin-top: 8px;
  font-size: 14px;
  font-weight: 600;
}

.detail-range-tabs {
  margin: 18px 0 12px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.add-surface {
  position: sticky;
  top: 24px;
}

.inline-notice {
  margin-bottom: 14px;
}

.add-btn {
  width: 100%;
}

.empty-state {
  padding: 36px 0;
  font-size: 14px;
  color: var(--text-muted);
  text-align: center;
}

@media (max-width: 1180px) {
  .ops-grid,
  .overview-strip,
  .market-layout {
    grid-template-columns: 1fr;
  }

  .add-surface {
    position: static;
  }
}

@media (max-width: 768px) {
  .intro-actions,
  .ops-inline,
  .toolbar,
  .watch-head,
  .watch-row-price,
  .watch-actions,
  .detail-top {
    flex-direction: column;
    align-items: flex-start;
  }

  .watch-badges {
    justify-content: flex-start;
  }

  .watch-stats {
    grid-template-columns: 1fr;
  }

  .detail-price-block {
    text-align: left;
  }

  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
