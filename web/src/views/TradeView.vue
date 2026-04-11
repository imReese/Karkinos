<template>
  <div class="trade-view">
    <!-- Trade form -->
    <div class="card mb-4">
      <div class="card-title">记录交易</div>

      <!-- Direction toggle -->
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

        <div class="form-actions">
          <div class="trade-summary" v-if="form.quantity > 0 && form.price > 0">
            <span class="text-muted">成交金额:</span>
            <span class="font-mono" :class="direction === 'buy' ? 'text-green' : 'text-red'">
              ¥{{ (form.quantity * form.price).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
            </span>
            <span class="text-muted" v-if="form.commission > 0">+ 佣金 ¥{{ form.commission.toFixed(2) }}</span>
          </div>
          <button
            class="btn submit-btn"
            :class="direction === 'buy' ? 'btn-buy' : 'btn-sell'"
            @click="submitTrade"
            :disabled="!canSubmit"
          >
            {{ direction === 'buy' ? '确认买入' : '确认卖出' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Trade history -->
    <div class="card">
      <div class="card-title">交易历史</div>
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
              <th>备注</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in portfolioStore.trades" :key="t.id">
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
              <td class="text-muted">{{ t.note || '-' }}</td>
              <td>
                <button class="btn btn-sm btn-danger" @click="portfolioStore.deleteTrade(t.id)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="text-muted empty-text">暂无交易记录</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { usePortfolioStore } from '../stores/portfolio'

const portfolioStore = usePortfolioStore()

const direction = ref<'buy' | 'sell'>('buy')
const dateStr = ref(new Date().toISOString().slice(0, 10))

const form = reactive({
  symbol: '',
  quantity: 0,
  price: 0,
  commission: 0,
  asset_class: 'stock',
  note: '',
})

const canSubmit = computed(() => form.symbol.trim() && form.quantity > 0 && form.price > 0)

async function submitTrade() {
  if (!canSubmit.value) return
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
  // Reset form
  form.symbol = ''
  form.quantity = 0
  form.price = 0
  form.commission = 0
  form.note = ''
}

onMounted(() => {
  portfolioStore.fetchTrades()
})
</script>

<style scoped>
.direction-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  background: var(--bg-input);
  border-radius: 8px;
  padding: 3px;
}

.dir-btn {
  flex: 1;
  padding: 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: var(--font-sans);
}

.dir-btn.buy.active {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.dir-btn.sell.active {
  background: rgba(239, 68, 68, 0.15);
  color: var(--danger);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.trade-form {
  margin-top: 16px;
}

.form-group {
  margin-bottom: 14px;
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

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.trade-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.submit-btn {
  min-width: 120px;
}

.btn-buy {
  background: var(--success);
  color: #fff;
}

.btn-buy:hover:not(:disabled) {
  background: #16a34a;
}

.btn-sell {
  background: var(--danger);
  color: #fff;
}

.btn-sell:hover:not(:disabled) {
  background: #dc2626;
}

.dir-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.dir-badge.buy {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
}

.dir-badge.sell {
  background: rgba(239, 68, 68, 0.15);
  color: var(--danger);
}

.empty-text {
  text-align: center;
  padding: 32px 0;
  font-size: 13px;
}

@media (max-width: 768px) {
  .form-actions {
    flex-direction: column;
    gap: 12px;
  }
  .submit-btn {
    width: 100%;
  }
}
</style>
