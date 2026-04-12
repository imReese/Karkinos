<template>
  <div id="app">
    <SideNav />
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import SideNav from './components/SideNav.vue'
</script>

<style>
:root {
  --bg-page: #0a0a0a;
  --bg-card: #161616;
  --bg-sidebar: #111111;
  --bg-input: #1c1c1c;
  --border: #27272a;
  --text-primary: #ededed;
  --text-secondary: #a1a1aa;
  --text-muted: #71717a;
  --primary: #6366f1;
  --primary-hover: #818cf8;
  --danger: #ef4444;
  --success: #22c55e;
  --warning: #f59e0b;
  --cash: #38bdf8;
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
  --sidebar-w: 220px;
  --sidebar-collapsed: 64px;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --spacing-unit: 8px;
  --transition-fast: 0.15s ease;
  --transition-normal: 0.2s ease;
  --overlay: rgba(0, 0, 0, 0.6);
  --surface-hover: rgba(255, 255, 255, 0.04);
  --primary-subtle: rgba(99, 102, 241, 0.12);
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-page);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  line-height: 1.6;
}

#app {
  display: flex;
  min-height: 100vh;
}

.main-content {
  margin-left: var(--sidebar-w);
  padding: 32px 40px;
  min-height: 100vh;
  transition: margin-left var(--transition-normal);
  width: calc(100% - var(--sidebar-w));
}

/* Card system */
.card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 24px;
  border: 1px solid var(--border);
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
    width: 100%;
    padding-top: 64px;
  }
  .grid-2, .grid-3, .grid-4 {
    grid-template-columns: 1fr;
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

.btn-primary {
  background: var(--primary);
  color: #fff;
}

.btn-primary:hover {
  background: var(--primary-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: transparent;
  color: var(--text-primary);
  border: 1px solid var(--border);
}

.btn-secondary:hover {
  background: var(--surface-hover);
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
  padding: 8px 12px;
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
