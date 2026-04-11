<template>
  <div class="allocation-bar" v-if="data.length > 0">
    <div
      v-for="(item, i) in data"
      :key="item.name"
      class="bar-segment"
      :style="{
        width: (item.weight * 100).toFixed(2) + '%',
        background: COLORS[i % COLORS.length],
      }"
      :title="`${item.name}: ${(item.weight * 100).toFixed(1)}%`"
    >
      <span class="segment-label" v-if="item.weight > 0.08">
        {{ item.name }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  data: Array<{ name: string; weight: number }>
}>()

const COLORS = ['#6366f1', '#8b5cf6', '#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#38bdf8', '#a855f7']
</script>

<style scoped>
.allocation-bar {
  display: flex;
  height: 28px;
  border-radius: 6px;
  overflow: hidden;
  gap: 1px;
  margin-bottom: 8px;
}

.bar-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.15s;
  cursor: default;
  min-width: 2px;
}

.bar-segment:hover {
  opacity: 0.85;
}

.segment-label {
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 4px;
}
</style>
