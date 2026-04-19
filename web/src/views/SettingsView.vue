<template>
  <div class="settings">
    <section class="page-intro">
      <div>
        <div class="section-eyebrow">设置</div>
        <h1 class="page-title">运行方式、策略与通知配置</h1>
        <p class="page-copy">管理服务运行状态、关注列表、策略参数和通知方式。</p>
      </div>
    </section>

    <!-- Live control -->
    <div class="grid grid-2 mb-4">
      <div class="card">
        <div class="card-title">服务控制</div>
        <div class="control-status">
          <span class="status-dot" :class="liveRunning ? 'running' : 'stopped'"></span>
          <span :class="liveRunning ? 'text-green' : 'text-red'">
            {{ liveRunning ? '运行中' : '已停止' }}
          </span>
        </div>
        <div class="control-actions mt-4">
          <button class="btn btn-primary" @click="startLive" :disabled="liveRunning">启动</button>
          <button class="btn btn-danger" @click="stopLive" :disabled="!liveRunning">停止</button>
          <button class="btn btn-secondary" @click="refreshStatus">刷新</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">通知测试</div>
        <p class="text-muted section-desc">发送一条测试消息验证通知配置是否正确。</p>
        <button class="btn btn-primary" @click="testNotification">发送测试通知</button>
        <AppNotice
          v-if="inlineNotice"
          class="mt-4"
          :tone="inlineNotice.tone"
          :title="inlineNotice.title"
          :message="inlineNotice.message"
          dense
        />
      </div>
    </div>

    <!-- Structured config sections -->
    <div class="card mb-4">
      <div class="card-title">通用设置</div>
      <div class="settings-grid">
        <div class="form-group">
          <label>Host</label>
          <input type="text" v-model="config.host" />
        </div>
        <div class="form-group">
          <label>Port</label>
          <input type="number" v-model.number="config.port" />
        </div>
        <div class="form-group">
          <label>初始资金</label>
          <input type="number" v-model.number="config.initial_cash" />
        </div>
        <div class="form-group">
          <label>轮询间隔 (秒)</label>
          <input type="number" v-model.number="config.live_poll_interval" />
        </div>
      </div>
      <div class="form-group">
        <label class="checkbox-label">
          <input type="checkbox" v-model="config.live_auto_start" />
          自动启动实盘
        </label>
      </div>
    </div>

    <!-- Watchlist -->
    <div class="card mb-4">
      <div class="card-title">关注标的</div>
      <div v-for="(asset, idx) in config.assets" :key="idx" class="asset-row">
        <input type="text" v-model="asset.symbol" placeholder="代码" class="asset-input" />
        <select v-model="asset.asset_class" class="asset-select">
          <option value="stock">股票</option>
          <option value="etf">ETF</option>
          <option value="gold">黄金</option>
          <option value="bond">债券</option>
        </select>
        <button class="btn btn-sm btn-danger" @click="config.assets.splice(idx, 1)" v-if="config.assets.length > 1">&times;</button>
      </div>
      <button class="btn btn-sm btn-secondary mt-4" @click="config.assets.push({ symbol: '', asset_class: 'stock' })">+ 添加标的</button>
    </div>

    <!-- Strategy -->
    <div class="card mb-4">
      <div class="card-title">策略参数</div>
      <div class="settings-grid">
        <div class="form-group">
          <label>策略</label>
          <select v-model="config.strategy">
            <option value="dual_ma">双均线</option>
            <option value="rsi">RSI</option>
            <option value="bollinger">布林带</option>
            <option value="monthly_rebalance">月度再平衡</option>
          </select>
        </div>
        <div class="form-group">
          <label>短周期</label>
          <input type="number" v-model.number="config.short_period" />
        </div>
        <div class="form-group">
          <label>长周期</label>
          <input type="number" v-model.number="config.long_period" />
        </div>
        <div class="form-group">
          <label>数据源</label>
          <select v-model="config.data_source">
            <option value="akshare">AKShare</option>
            <option value="tushare">Tushare</option>
          </select>
        </div>
      </div>
      <div v-if="config.data_source === 'tushare'" class="form-group" style="margin-top: 12px;">
        <label>Tushare Token</label>
        <div class="token-input-wrapper">
          <input
            :type="showToken ? 'text' : 'password'"
            v-model="config.tushare_token"
            :placeholder="tokenPlaceholder"
            class="token-input"
          />
          <button class="btn btn-sm btn-secondary toggle-visibility" @click="showToken = !showToken">
            {{ showToken ? '隐藏' : '显示' }}
          </button>
        </div>
        <p v-if="hasToken" class="text-muted token-hint">Token 已配置，如需修改请输入新 Token</p>
      </div>
    </div>

    <!-- Notification -->
    <div class="card mb-4">
      <div class="card-title">通知方式</div>
      <div class="form-group">
        <label>通知类型</label>
        <select v-model="config.notification.type">
          <option value="console">控制台</option>
          <option value="webhook">Webhook</option>
          <option value="email">邮件</option>
        </select>
      </div>
      <div v-if="config.notification.type === 'webhook'" class="form-group">
        <label>Webhook URL</label>
        <input type="text" v-model="config.notification.webhook_url" placeholder="https://..." />
      </div>
      <div v-if="config.notification.type === 'email'" class="settings-grid">
        <div class="form-group">
          <label>SMTP Host</label>
          <input type="text" v-model="config.notification.smtp_host" />
        </div>
        <div class="form-group">
          <label>收件人</label>
          <input type="text" v-model="config.notification.recipient" />
        </div>
      </div>
    </div>

    <!-- Raw JSON fallback -->
    <div class="card mb-4">
      <div class="card-title">高级配置 (JSON)</div>
      <div class="form-group">
        <textarea v-model="configJson" rows="10" class="config-editor"></textarea>
      </div>
      <div class="json-actions">
        <button class="btn btn-secondary" @click="loadFromJson">从 JSON 加载</button>
        <button class="btn btn-primary" @click="saveConfig">保存配置</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import client from '../api/client'
import AppNotice from '../components/AppNotice.vue'
import { useUiStore } from '../stores/ui'

const liveRunning = ref(false)
const inlineNotice = ref<{ tone: 'success' | 'error' | 'info'; title: string; message: string } | null>(null)
const configJson = ref('')
const showToken = ref(false)
const hasToken = ref(false)
const uiStore = useUiStore()

const config = reactive({
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
  notification: {
    type: 'console',
    webhook_url: '',
    smtp_host: '',
    recipient: '',
  },
})

const tokenPlaceholder = computed(() => hasToken.value ? '****（已配置）' : '请输入 Tushare Token')

async function refreshStatus() {
  try {
    const { data } = await client.get('/settings/live/status')
    liveRunning.value = data.running
  } catch {
    uiStore.error('当前无法获取服务运行状态。', '状态获取失败')
  }
}

async function startLive() {
  try {
    await client.post('/settings/live/start')
    await refreshStatus()
    inlineNotice.value = { tone: 'success', title: '服务已启动', message: '实时任务已经进入运行状态。' }
    uiStore.success('实时任务已经启动。', '服务已启动')
  } catch {
    inlineNotice.value = { tone: 'error', title: '启动失败', message: '服务未能启动，请检查后端状态。' }
    uiStore.error('实时任务未能启动，请检查后端状态。', '启动失败')
  }
}

async function stopLive() {
  try {
    await client.post('/settings/live/stop')
    await refreshStatus()
    inlineNotice.value = { tone: 'info', title: '服务已停止', message: '实时任务已经停止运行。' }
    uiStore.info('实时任务已经停止。', '服务已停止')
  } catch {
    inlineNotice.value = { tone: 'error', title: '停止失败', message: '服务未能停止，请稍后重试。' }
    uiStore.error('实时任务未能停止，请稍后重试。', '停止失败')
  }
}

async function testNotification() {
  inlineNotice.value = null
  try {
    const { data } = await client.post('/settings/notification/test')
    const tone = data.status === 'ok' ? 'success' : 'error'
    inlineNotice.value = { tone, title: '通知测试', message: data.message }
    if (tone === 'success') {
      uiStore.success(data.message, '通知测试')
    } else {
      uiStore.error(data.message, '通知测试')
    }
  } catch (e: any) {
    inlineNotice.value = { tone: 'error', title: '通知测试失败', message: e.message }
    uiStore.error(e.message, '通知测试失败')
  }
}

async function loadConfig() {
  const { data } = await client.get('/settings')
  configJson.value = JSON.stringify(data, null, 2)
  // Populate structured form
  config.host = data.host ?? '0.0.0.0'
  config.port = data.port ?? 8000
  config.live_auto_start = data.live_auto_start ?? true
  config.initial_cash = data.initial_cash ?? 100000
  config.start_date = data.start_date ?? '2025-01-02'
  config.end_date = data.end_date ?? ''
  config.assets = data.assets ?? [{ symbol: '600519', asset_class: 'stock' }]
  config.strategy = data.strategy ?? 'dual_ma'
  config.short_period = data.short_period ?? 5
  config.long_period = data.long_period ?? 20
  config.data_source = data.data_source ?? 'akshare'
  hasToken.value = !!(data.tushare_token && data.tushare_token.startsWith('****'))
  config.tushare_token = data.tushare_token ?? ''
  config.live_poll_interval = data.live_poll_interval ?? 60
  config.notification = {
    type: data.notification?.type ?? 'console',
    webhook_url: data.notification?.webhook_url ?? '',
    smtp_host: data.notification?.smtp_host ?? '',
    recipient: data.notification?.recipient ?? '',
  }
}

function loadFromJson() {
  try {
    const parsed = JSON.parse(configJson.value)
    Object.assign(config, {
      host: parsed.host ?? config.host,
      port: parsed.port ?? config.port,
      live_auto_start: parsed.live_auto_start ?? config.live_auto_start,
      initial_cash: parsed.initial_cash ?? config.initial_cash,
      assets: parsed.assets ?? config.assets,
      strategy: parsed.strategy ?? config.strategy,
      short_period: parsed.short_period ?? config.short_period,
      long_period: parsed.long_period ?? config.long_period,
      data_source: parsed.data_source ?? config.data_source,
      tushare_token: parsed.tushare_token ?? config.tushare_token,
      live_poll_interval: parsed.live_poll_interval ?? config.live_poll_interval,
      notification: parsed.notification ?? config.notification,
    })
    inlineNotice.value = { tone: 'info', title: 'JSON 已载入', message: '表单已经按 JSON 内容更新。' }
    uiStore.info('表单已经按 JSON 内容更新。', 'JSON 已载入')
  } catch {
    inlineNotice.value = { tone: 'error', title: 'JSON 格式错误', message: '请先修正 JSON 再重新载入。' }
    uiStore.error('请先修正 JSON 再重新载入。', 'JSON 格式错误')
  }
}

async function saveConfig() {
  try {
    const payload = {
      host: config.host,
      port: config.port,
      live_auto_start: config.live_auto_start,
      initial_cash: config.initial_cash,
      start_date: config.start_date,
      end_date: config.end_date,
      assets: config.assets,
      strategy: config.strategy,
      short_period: config.short_period,
      long_period: config.long_period,
      data_source: config.data_source,
      tushare_token: config.tushare_token,
      live_poll_interval: config.live_poll_interval,
      notification: config.notification,
    }
    await client.put('/settings', payload)
    configJson.value = JSON.stringify(payload, null, 2)
    inlineNotice.value = { tone: 'success', title: '配置已保存', message: '设置已经写入后端配置。' }
    uiStore.success('设置已经写入后端配置。', '配置已保存')
  } catch (e: any) {
    inlineNotice.value = { tone: 'error', title: '保存失败', message: e.message }
    uiStore.error(e.message, '保存失败')
  }
}

onMounted(async () => {
  await refreshStatus()
  await loadConfig()
})
</script>

<style scoped>
.control-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.status-dot.running {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
  animation: pulse 2s infinite;
}

.status-dot.stopped {
  background: var(--danger);
}

.control-actions {
  display: flex;
  gap: 8px;
}

.section-desc {
  font-size: 13px;
  margin-bottom: 16px;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
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

.checkbox-label {
  display: flex !important;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  text-transform: none !important;
  font-size: 14px !important;
  color: var(--text-primary) !important;
  letter-spacing: 0 !important;
}

.checkbox-label input {
  width: auto;
}

.asset-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}

.asset-input {
  flex: 1;
  padding: 8px 12px;
}

.asset-select {
  width: 104px;
  padding: 8px 12px;
}

.config-editor {
  width: 100%;
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 16px;
  border-radius: var(--radius-md);
  resize: vertical;
  line-height: 1.6;
}

.json-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.token-input-wrapper {
  display: flex;
  gap: 8px;
  align-items: center;
}

.token-input {
  flex: 1;
}

.toggle-visibility {
  white-space: nowrap;
}

.token-hint {
  font-size: 12px;
  margin-top: 8px;
}

@media (max-width: 768px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
