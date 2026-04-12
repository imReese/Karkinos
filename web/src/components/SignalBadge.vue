<template>
  <span class="signal-badge" :class="direction">{{ direction }}</span>
</template>

<script setup lang="ts">
defineProps<{
  direction: string
}>()
</script>

<style scoped>
.signal-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
}

.买入 {
  background: rgba(34, 197, 94, 0.12);
  color: var(--success);
}

.卖出 {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
}
</style>
