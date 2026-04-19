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
      <button
        v-for="item in navItems"
        :key="item.path"
        type="button"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
        @click="navigateTo(item.path)"
      >
        <component :is="item.icon" class="nav-icon" :size="20" />
        <span class="nav-label" v-if="!isCollapsed">{{ item.label }}</span>
      </button>
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
import { useRoute, useRouter } from 'vue-router'
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
const router = useRouter()
const isCollapsed = ref(false)
const mobileOpen = ref(false)

const navItems = [
  { path: '/', label: '首页', icon: LayoutDashboard },
  { path: '/portfolio', label: '投资组合', icon: Briefcase },
  { path: '/trade', label: '交易记录', icon: ArrowLeftRight },
  { path: '/market', label: '行情', icon: LineChart },
  { path: '/signals', label: '任务中心', icon: Radio },
  { path: '/backtest', label: '回测', icon: FlaskConical },
  { path: '/settings', label: '设置', icon: Settings },
]

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

function navigateTo(path: string) {
  mobileOpen.value = false
  if (route.path === path) return
  router.push(path)
}
</script>

<style scoped>
.side-nav {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: var(--sidebar-w);
  background:
    linear-gradient(180deg, rgba(17, 18, 22, 0.96), rgba(24, 25, 29, 0.92)),
    rgba(16, 17, 20, 0.94);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  z-index: 100;
  transition: width var(--transition-normal);
  box-shadow: 30px 0 80px rgba(15, 23, 42, 0.16);
}

.side-nav.collapsed {
  width: var(--sidebar-collapsed);
}

.nav-header {
  padding: 24px 18px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #c8d2e1, #8a96a8);
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
  color: #f3f4f6;
  letter-spacing: 0.02em;
}

.collapsed-brand {
  justify-content: center;
}

.nav-items {
  flex: 1;
  padding: 8px;
  padding-bottom: 18px;
  overflow-y: auto;
  position: relative;
  z-index: 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  color: rgba(226, 232, 240, 0.66);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all var(--transition-fast);
  margin-bottom: 2px;
  cursor: pointer;
  border: none;
  background: none;
  width: 100%;
  text-align: left;
  position: relative;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #f8fafc;
}

.nav-item.active {
  background: rgba(255, 255, 255, 0.065);
  color: #f8fafc;
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 16px;
  background: linear-gradient(180deg, #d7e1ef, #8b97a9);
  border-radius: 1px;
}

.collapsed .nav-item {
  justify-content: center;
  padding: 8px;
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
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: relative;
  z-index: 1;
}

.collapsed .nav-footer {
  justify-content: center;
}

.collapse-btn {
  background: none;
  border: none;
  color: rgba(226, 232, 240, 0.5);
  cursor: pointer;
  padding: 8px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
}

/* Mobile hamburger */
.mobile-hamburger {
  display: none;
  position: fixed;
  top: 16px;
  left: 16px;
  z-index: 200;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  cursor: pointer;
  padding: 8px;
  box-shadow: var(--shadow-card);
}

.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: var(--overlay);
  z-index: 99;
}

@media (max-width: 768px) {
  .side-nav {
    transform: translateX(-100%);
    width: var(--sidebar-w) !important;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    background: rgba(15, 23, 42, 0.92);
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

  .nav-item.active::before {
    left: -8px;
  }
}
</style>
