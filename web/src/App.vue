<template>
  <div id="app">
    <SideNav />
    <main class="main-content">
      <router-view />
    </main>
    <AppToastStack />
  </div>
</template>

<script setup lang="ts">
import AppToastStack from './components/AppToastStack.vue'
import SideNav from './components/SideNav.vue'
</script>

<style>
:root {
  --bg-page: #f5f5f7;
  --bg-card: rgba(255, 255, 255, 0.74);
  --bg-card-strong: #ffffff;
  --bg-sidebar: rgba(16, 17, 20, 0.92);
  --bg-input: rgba(255, 255, 255, 0.84);
  --border: rgba(15, 23, 42, 0.08);
  --border-strong: rgba(15, 23, 42, 0.14);
  --text-primary: #111317;
  --text-secondary: #4b5563;
  --text-muted: #8a94a6;
  --primary: #2563eb;
  --primary-hover: #1d4ed8;
  --danger: #c2413b;
  --success: #1f8a70;
  --warning: #d08700;
  --cash: #0f6f8f;
  --font-sans: 'Avenir Next', 'PingFang SC', 'Noto Sans SC', 'Helvetica Neue', sans-serif;
  --font-mono: 'IBM Plex Mono', 'SFMono-Regular', 'JetBrains Mono', monospace;
  --sidebar-w: 236px;
  --sidebar-collapsed: 64px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 18px;
  --radius-xl: 24px;
  --spacing-unit: 8px;
  --transition-fast: 0.15s ease;
  --transition-normal: 0.2s ease;
  --overlay: rgba(15, 23, 42, 0.34);
  --surface-hover: rgba(37, 99, 235, 0.06);
  --primary-subtle: rgba(37, 99, 235, 0.1);
  --shadow-soft: 0 20px 50px rgba(15, 23, 42, 0.08);
  --shadow-card: 0 12px 30px rgba(15, 23, 42, 0.05);
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background:
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.88), transparent 24%),
    radial-gradient(circle at top right, rgba(212, 222, 240, 0.34), transparent 26%),
    linear-gradient(180deg, #fbfbfc 0%, #f4f5f7 52%, #eef1f4 100%);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  line-height: 1.6;
}

#app {
  min-height: 100vh;
}

.main-content {
  margin-left: var(--sidebar-w);
  padding: 30px clamp(24px, 2.6vw, 44px) 48px;
  min-height: 100vh;
  transition: margin-left var(--transition-normal);
  width: calc(100vw - var(--sidebar-w));
  max-width: none;
}

.page-intro {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 18px 0 4px;
}

.section-eyebrow {
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.page-title,
.surface-title {
  color: var(--text-primary);
  letter-spacing: -0.03em;
}

.page-title {
  font-size: 22px;
  line-height: 1.08;
}

.page-copy {
  margin-top: 8px;
  max-width: 42ch;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.surface {
  padding: 20px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.07);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(16px);
}

.surface-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.surface-title {
  font-size: 22px;
  line-height: 1.08;
}

.surface-meta {
  color: var(--text-muted);
  font-size: 12px;
}

.card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 24px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(16px);
}

.card-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

/* Grid */
.grid {
  display: grid;
  gap: 16px;
}

.grid-2 { grid-template-columns: repeat(2, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }

@media (max-width: 1024px) {
  .grid-4 { grid-template-columns: repeat(2, 1fr); }
  .grid-3 { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .main-content {
    margin-left: 0;
    padding: 16px;
    width: 100vw;
    padding-top: 64px;
  }
  .grid-2, .grid-3, .grid-4 {
    grid-template-columns: 1fr;
  }

  .page-intro,
  .surface-head {
    flex-direction: column;
  }
}

/* Table */
table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

th {
  font-weight: 600;
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

tbody tr:hover {
  background: var(--surface-hover);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-normal);
  font-family: var(--font-sans);
  min-height: 36px;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.btn-primary {
  background: var(--primary);
  color: #fff;
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.16);
}

.btn-primary:hover {
  background: var(--primary-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.82);
  color: var(--text-primary);
  border: 1px solid rgba(15, 23, 42, 0.1);
}

.btn-secondary:hover {
  background: rgba(247, 249, 252, 0.96);
  border-color: rgba(15, 23, 42, 0.16);
}

.btn-danger {
  background: rgba(239, 68, 68, 0.12);
  color: var(--danger);
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.2);
}

.btn-sm {
  font-size: 12px;
  padding: 4px 12px;
  min-height: 28px;
}

/* Form inputs */
input, select, textarea {
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-primary);
  font-family: var(--font-sans);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  outline: none;
}

input:focus, select:focus, textarea:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

input::placeholder, textarea::placeholder {
  color: var(--text-muted);
}

/* Utility */
.mt-4 { margin-top: 16px; }
.mb-4 { margin-bottom: 16px; }
.text-green { color: var(--success); }
.text-red { color: var(--danger); }
.text-muted { color: var(--text-muted); }
.font-mono { font-family: var(--font-mono); }
.text-cash { color: var(--cash); }

/* Scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* Responsive table */
.table-wrap {
  overflow-x: auto;
}
</style>
