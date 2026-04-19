<template>
  <teleport to="body">
    <div class="toast-stack">
      <transition-group name="toast">
        <AppNotice
          v-for="notice in uiStore.notices"
          :key="notice.id"
          :tone="notice.tone"
          :title="notice.title"
          :message="notice.message"
          dismissible
          @dismiss="uiStore.dismiss(notice.id)"
        />
      </transition-group>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import AppNotice from './AppNotice.vue'
import { useUiStore } from '../stores/ui'

const uiStore = useUiStore()
</script>

<style scoped>
.toast-stack {
  position: fixed;
  top: 22px;
  right: 22px;
  z-index: 1200;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(360px, calc(100vw - 28px));
  pointer-events: none;
}

.toast-stack :deep(.app-notice) {
  pointer-events: auto;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 768px) {
  .toast-stack {
    top: 72px;
    right: 14px;
    left: 14px;
    width: auto;
  }
}
</style>
