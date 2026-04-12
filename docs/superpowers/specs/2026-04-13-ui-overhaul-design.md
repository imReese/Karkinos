# UI/UX Overhaul: Modern Developer Aesthetic

**Date:** 2026-04-13
**Status:** Approved
**Scope:** Full frontend restyling — 7 views + 8 components + global styles

## Design Principles

- Deep dark mode with neutral grays (no purple/blue tint in surfaces)
- Single accent color: Indigo (#6366f1)
- 1px borders instead of shadows (Linear precision look)
- Consistent border-radius: 6px (buttons/badges), 8px (inputs/dropdowns), 12px (cards), 16px (FAB)
- 8px grid system for all spacing
- Snappy transitions: 0.15-0.2s ease
- Glassmorphism for nav and overlays (backdrop-filter: blur)

## 1. Color Palette

### Updated CSS Variables

| Token | Old | New |
|-------|-----|-----|
| `--bg-page` | `#0f1117` | `#0a0a0a` |
| `--bg-card` | `#1a1b23` | `#161616` |
| `--bg-sidebar` | `#13141c` | `#111111` |
| `--bg-input` | `#1e1f2b` | `#1c1c1c` |
| `--border` | `#2a2b3a` | `#27272a` |
| `--text-primary` | `#e4e4e7` | `#ededed` |

### Unchanged Tokens

`--text-secondary: #a1a1aa`, `--text-muted: #71717a`, `--primary: #6366f1`, `--primary-hover: #818cf8`, `--danger: #ef4444`, `--success: #22c55e`, `--warning: #f59e0b`, `--cash: #38bdf8`

### New Tokens

| Token | Value | Purpose |
|-------|-------|---------|
| `--radius-sm` | `6px` | Buttons, badges |
| `--radius-md` | `8px` | Cards, inputs |
| `--radius-lg` | `12px` | Hero cards, drawers |
| `--radius-xl` | `16px` | FAB |
| `--spacing-unit` | `8px` | Base grid unit |
| `--transition-fast` | `0.15s ease` | Hover, focus |
| `--transition-normal` | `0.2s ease` | Layout, drawers |
| `--overlay` | `rgba(0,0,0,0.6)` | Modal/drawer backdrop |
| `--surface-hover` | `rgba(255,255,255,0.04)` | Surface hover |
| `--primary-subtle` | `rgba(99,102,241,0.12)` | Active nav, accent bg |

## 2. Typography & Spacing

- Font stack unchanged: Inter + JetBrains Mono
- Body line-height: 1.6 (compact areas: 1.4)
- 8px grid: all padding/margin/gap in multiples of 8
- Migrations: `12px` → `16px`, `10px` → `8px`, `20px` → `24px`, card padding `20px` → `24px`, main content `24px 32px` → `32px 40px`

## 3. Card & Surface System

- `.card`: bg `#161616`, border `1px solid #27272a`, radius `12px`, padding `24px`
- No box-shadow on cards (border-only depth, Linear style)
- `.card-title`: `12px`, `#71717a`, uppercase, `letter-spacing: 0.06em`, `margin-bottom: 16px`
- Hero card: gradient `linear-gradient(135deg, #6366f1, #4f46e5)`, radius `12px`, padding `40px`

Surface hierarchy: `#0a0a0a` (page) → `#111111` (sidebar) → `#161616` (card) → `#1c1c1c` (input) → `#27272a` (border)

## 4. SideNav

- Background `#111111`, right border `1px solid #27272a`
- Nav items: padding `8px 12px`, radius `8px`, gap `12px`
- Hover: `background: rgba(255,255,255,0.04)`
- Active: `background: rgba(99,102,241,0.12)`, `color: #6366f1`, left 2px indigo indicator bar
- Footer: `backdrop-filter: blur(12px)` on desktop
- Mobile: `backdrop-filter: blur(20px)` + `background: rgba(17,17,17,0.85)`
- Overlay: `rgba(0,0,0,0.6)`

## 5. Interactive Elements

### Buttons

- `.btn`: padding `8px 16px`, radius `6px`, font `13px/500`, transition `0.2s ease`
- `.btn-primary`: bg `#6366f1`, hover `#818cf8`
- `.btn-secondary`: bg transparent, border `1px solid #27272a`, hover bg `rgba(255,255,255,0.04)`
- `.btn-danger`: bg `rgba(239,68,68,0.12)`, border `1px solid rgba(239,68,68,0.25)`, hover bg `rgba(239,68,68,0.2)`
- `.btn-sm`: padding `4px 12px`

### Inputs

- bg `#1c1c1c`, border `1px solid #27272a`, radius `8px`
- Focus: `border-color: #6366f1` + `box-shadow: 0 0 0 1px #6366f1`
- Placeholder: `#71717a`

### Tabs/Toggles

- Container bg `#1c1c1c`, radius `8px`, padding `3px`
- Primary active: bg `#6366f1`, text white
- Secondary active: bg `rgba(255,255,255,0.06)`, text `#ededed`

### Tables

- th: `12px`, `#71717a`, uppercase, padding `12px 16px`
- td: `13px`, padding `12px 16px`
- Row hover: `background: rgba(255,255,255,0.02)`
- Borders: `1px solid #27272a`

## 6. ECharts Theme

- Tooltip: `bg rgba(22,22,22,0.95)`, border `#27272a`, text `#ededed`
- Axis lines: `#27272a`
- Split lines: `#27272a`
- Axis labels: `#71717a`, fontSize 11
- Legend text: `#a1a1aa`, fontSize 12
- Palette: `['#6366f1','#34d399','#fbbf24','#f43f5e','#a78bfa','#22d3ee','#38bdf8','#8b5cf6']`
- Pie border: `#161616`
- Area gradient: `rgba(99,102,241,0.2)` → `rgba(99,102,241,0.01)`

## 7. Drawer & FAB

### CashFlowDrawer

- bg `#161616`, left border `1px solid #27272a`
- Overlay: `rgba(0,0,0,0.6)` + `backdrop-filter: blur(4px)`
- Transition: `0.2s ease`

### FAB

- Size `48x48`, radius `14px`, bg `#6366f1`, hover `#818cf8`
- No box-shadow, border `1px solid rgba(99,102,241,0.5)`
- FAB menu: bg `#161616`, border `1px solid #27272a`, radius `12px`

## 8. Badges & Indicators

- Radius `6px`, padding `2px 8px`, font-size `12px`
- Buy/Deposit: bg `rgba(34,197,94,0.12)`, color `#22c55e`
- Sell/Withdraw: bg `rgba(239,68,68,0.12)`, color `#ef4444`
- NEW: bg `rgba(99,102,241,0.12)`, color `#6366f1`
- Live dot: `8px`, green glow connected, red no glow disconnected
- Market badge: bg `rgba(245,158,11,0.12)`, color `#f59e0b`

## Files to Modify

| File | Changes |
|------|---------|
| `web/src/App.vue` | `:root` variables, global styles (card, btn, grid, table, inputs) |
| `web/src/components/SideNav.vue` | Colors, hover/active states, glassmorphism, left indicator bar |
| `web/src/components/AllocationPie.vue` | ECharts theme colors, border, tooltip |
| `web/src/components/AllocationBar.vue` | COLORS array, bar styling |
| `web/src/components/SignalBadge.vue` | Colors, radius |
| `web/src/components/LiveIndicator.vue` | Colors, badge styling |
| `web/src/components/KlineChart.vue` | ECharts theme (tooltip, axes, grid) |
| `web/src/components/EquityCurve.vue` | ECharts theme (tooltip, axes, area gradient) |
| `web/src/components/CashFlowDrawer.vue` | Overlay, panel bg, form styles |
| `web/src/views/DashboardView.vue` | Hero card, metric cards, FAB, signal list, spacing |
| `web/src/views/PortfolioView.vue` | Overview grid, toggle, FAB, spacing |
| `web/src/views/TradeView.vue` | Direction toggle, form, table, badges |
| `web/src/views/MarketView.vue` | Table, asset badge, spacing |
| `web/src/views/SignalsView.vue` | NEW badge, table, row highlighting |
| `web/src/views/BacktestView.vue` | Tabs, form, metrics grid, tables |
| `web/src/views/SettingsView.vue` | Form groups, control status, JSON editor |

Total: 16 files, CSS-only changes (no logic/HTML structural changes)

## Implementation Strategy

1. Update `:root` variables in App.vue (foundation)
2. Update global classes in App.vue (card, btn, grid, table, inputs)
3. Update SideNav (layout shell)
4. Update views top-down (Dashboard → Portfolio → Trade → Market → Signals → Backtest → Settings)
5. Update remaining components (AllocationPie, AllocationBar, SignalBadge, LiveIndicator, KlineChart, EquityCurve, CashFlowDrawer)
6. Visual verification
