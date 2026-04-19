<template>
  <div class="app-notice" :class="[`tone-${tone}`, { dense }]">
    <div class="notice-accent"></div>
    <div class="notice-body">
      <div v-if="title" class="notice-title">{{ title }}</div>
      <div class="notice-message">{{ message }}</div>
    </div>
    <button v-if="dismissible" class="notice-close" type="button" @click="$emit('dismiss')">关闭</button>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: 'success' | 'error' | 'info'
    title?: string
    message: string
    dense?: boolean
    dismissible?: boolean
  }>(),
  {
    tone: 'info',
    title: '',
    dense: false,
    dismissible: false,
  },
)

defineEmits<{
  dismiss: []
}>()
</script>

<style scoped>
.app-notice {
  display: grid;
  grid-template-columns: 3px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(16px);
}

.app-notice.dense {
  padding: 12px 14px;
}

.notice-accent {
  width: 3px;
  min-height: 100%;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.75);
}

.notice-body {
  min-width: 0;
}

.notice-title {
  font-size: 12px;
  line-height: 1.3;
  font-weight: 600;
  color: var(--text-primary);
}

.notice-message {
  margin-top: 2px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.notice-close {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  cursor: pointer;
  transition: color var(--transition-fast);
}

.notice-close:hover {
  color: var(--text-primary);
}

.tone-success {
  background: rgba(245, 255, 251, 0.92);
  border-color: rgba(31, 138, 112, 0.14);
}

.tone-success .notice-accent {
  background: var(--success);
}

.tone-error {
  background: rgba(255, 248, 248, 0.94);
  border-color: rgba(194, 65, 59, 0.16);
}

.tone-error .notice-accent {
  background: var(--danger);
}

.tone-info {
  background: rgba(247, 250, 255, 0.92);
  border-color: rgba(37, 99, 235, 0.14);
}

.tone-info .notice-accent {
  background: var(--primary);
}
</style>
