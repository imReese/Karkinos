<template>
  <div class="side-nav" :class="{ collapsed: isCollapsed, 'mobile-open': mobileOpen }">
    <div class="nav-header">
      <div class="nav-brand" v-if="!isCollapsed">
        <span class="brand-mark">M</span>
        <span class="brand-text">MyQuant</span>
      </div>
      <div class="nav-brand collapsed-brand" v-else>
        <span class="brand-mark">M</span>
      </div>
    </div>

    <nav class="nav-items">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
        @click="mobileOpen = false"
      >
        <component :is="item.icon" class="nav-icon" :size="20" />
        <span class="nav-label" v-if="!isCollapsed">{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="nav-footer">
      <div class="nav-item live-item" v-if="!isCollapsed">
        <LiveIndicator />
      </div>
      <button class="collapse-btn" @click="isCollapsed = !isCollapsed">
        <ChevronLeft :size="18" v-if="!isCollapsed" />
        <ChevronRight :size="18" v-else />
      </button>
    </div>
  </div>

  <!-- Mobile overlay -->
  <div class="mobile-overlay" v-if="mobileOpen" @click="mobileOpen = false"></div>

  <!-- Mobile hamburger -->
  <button class="mobile-hamburger" @click="mobileOpen = true">
    <Menu :size="24" />
  </button>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  LayoutDashboard,
  Briefcase,
  ArrowLeftRight,
  LineChart,
  Radio,
  FlaskConical,
  Settings,
  ChevronLeft,
  ChevronRight,
  Menu,
} from 'lucide-vue-next'
import LiveIndicator from './LiveIndicator.vue'

const route = useRoute()
const isCollapsed = ref(false)
const mobileOpen = ref(false)

const navItems = [
  { path: '/', label: '仪表盘', icon: LayoutDashboard },
  { path: '/portfolio', label: '投资组合', icon: Briefcase },
  { path: '/trade', label: '交易记录', icon: ArrowLeftRight },
  { path: '/market', label: '行情', icon: LineChart },
  { path: '/signals', label: '信号', icon: Radio },
  { path: '/backtest', label: '回测', icon: FlaskConical },
  { path: '/settings', label: '设置', icon: Settings },
]

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}
</script>

<style scoped>
.side-nav {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: var(--sidebar-w);
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  z-index: 100;
  transition: width 0.2s ease;
}

.side-nav.collapsed {
  width: var(--sidebar-collapsed);
}

.nav-header {
  padding: 20px 16px 16px;
  border-bottom: 1px solid var(--border);
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  flex-shrink: 0;
}

.brand-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.collapsed-brand {
  justify-content: center;
}

.nav-items {
  flex: 1;
  padding: 8px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.15s ease;
  margin-bottom: 2px;
  cursor: pointer;
  border: none;
  background: none;
  width: 100%;
  text-align: left;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

.nav-item.active {
  background: rgba(99, 102, 241, 0.15);
  color: var(--primary);
}

.collapsed .nav-item {
  justify-content: center;
  padding: 10px;
}

.nav-icon {
  flex-shrink: 0;
}

.nav-label {
  white-space: nowrap;
  overflow: hidden;
}

.live-item {
  pointer-events: none;
}

.nav-footer {
  padding: 12px 8px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.collapsed .nav-footer {
  justify-content: center;
}

.collapse-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

/* Mobile hamburger */
.mobile-hamburger {
  display: none;
  position: fixed;
  top: 12px;
  left: 12px;
  z-index: 200;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  cursor: pointer;
  padding: 8px;
}

.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 99;
}

@media (max-width: 768px) {
  .side-nav {
    transform: translateX(-100%);
    width: var(--sidebar-w) !important;
  }

  .side-nav.mobile-open {
    transform: translateX(0);
  }

  .mobile-hamburger {
    display: flex;
  }

  .mobile-overlay {
    display: block;
  }

  .nav-label {
    display: inline !important;
  }

  .collapse-btn {
    display: none;
  }
}
</style>
