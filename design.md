# Design System Inspiration of Karkinos

## 1. Visual Theme & Atmosphere

Karkinos's current interface is a restrained portfolio workbench built for long-running daily use rather than short-lived campaign impact. The visual language combines an airy, near-white financial canvas with a graphite navigation rail and one dense dark “balance slab” used for the highest-signal financial number on the page. The result sits somewhere between Apple’s premium calm, GPT’s low-noise product surfaces, and a private-banking dashboard that has been simplified for a single operator.

This is not a trading terminal, and it should never drift into brokerage clutter. The homepage is intentionally quiet: large whitespace, few chromatic signals, clear numeric hierarchy, and compact operational modules. Most surfaces use translucent white with soft blur and low-contrast borders, allowing the background gradient to provide atmosphere without turning the UI into a decorative landing page. The dark sidebar and dark hero balance card create two anchors: navigation on the left, net-worth orientation on the right.

Typography is part of that restraint. The primary sans stack starts with Avenir Next and Chinese-native system fallbacks, which keeps headings refined and slightly more editorial than standard SaaS defaults. Monospace numbers use IBM Plex Mono / SFMono / JetBrains Mono so financial values feel instrument-like and stable. Financial numbers should feel machined; labels should feel quiet and supportive.

**Key Characteristics:**
- Cool light canvas with subtle radial haze and no aggressive gradients
- Graphite-black sidebar (`rgba(16, 17, 20, 0.92)`) as the persistent structural frame
- Frosted white cards (`rgba(255, 255, 255, 0.72–0.74)`) with soft shadows and minimal border contrast
- Single saturated action color: Karkinos Blue (`#2563eb`) used for primary actions and focus
- Controlled semantic accents only: teal cash, green profit, amber warning, red loss
- Large financial numerals presented in monospace, especially in the dark hero slab
- Dense but calm workspace layout: main action column + secondary state rail
- “Private terminal” mood rather than public marketing mood

## 2. Color Palette & Roles

### Core Backgrounds

- **Page Gray** (`#f5f5f7`): The base application canvas. Soft, slightly warm-neutral, never stark white.
- **Canvas White** (`#fbfbfc`): Top gradient stop in the body background. Used to create the luminous upper atmosphere.
- **Canvas Fog** (`#eef1f4`): Lower gradient stop in the body background. Prevents the app from feeling flat.
- **Sidebar Graphite** (`rgba(16, 17, 20, 0.92)`): The left navigation rail. Dense, quiet, premium.
- **Hero Dark Slab** (`#16181d` with layered dark gradients): Used for the total-assets block and other maximum-emphasis surfaces.

### Surface Layers

- **Glass Card** (`rgba(255, 255, 255, 0.74)`): Standard card surface with blur, used across modules.
- **Glass Card Soft** (`rgba(255, 255, 255, 0.72)`): Section panels and compact workspace surfaces.
- **Strong White** (`#ffffff`): High-clarity surface for the strongest light-mode contained moments.
- **Input White** (`rgba(255, 255, 255, 0.84)`): Form controls and entry surfaces.

### Text

- **Primary Ink** (`#111317`): Primary headings, strong values, table text.
- **Secondary Slate** (`#4b5563`): Supporting copy, descriptions, medium-emphasis labels.
- **Muted Gray-Blue** (`#8a94a6`): Eyebrows, metadata, timestamps, low-priority labels.
- **Hero White** (`#f5f7fa`): Text on the dark balance slab.
- **Hero Muted White** (`rgba(245, 247, 250, 0.48–0.68)`): Supporting text on dark hero surfaces.

### Primary and Semantic Colors

- **Karkinos Blue** (`#2563eb`): The single primary interactive color. Buttons, focus states, strong navigation/action emphasis.
- **Karkinos Blue Hover** (`#1d4ed8`): Hover/pressed state for primary actions.
- **Cash Teal** (`#0f6f8f`): Cash-related values and icons.
- **Profit Green** (`#1f8a70`): Positive PnL, healthy status states.
- **Warning Amber** (`#d08700`): Alerts, caution, degraded state.
- **Loss Red** (`#c2413b`): Negative PnL, destructive actions, error states.

### Border, Overlay, and Interaction Tints

- **Border Soft** (`rgba(15, 23, 42, 0.08)`): Default border throughout the product.
- **Border Strong** (`rgba(15, 23, 42, 0.14)`): Hover/strong separation border.
- **Primary Subtle** (`rgba(37, 99, 235, 0.10)`): Icon wells and selected/soft highlighted states.
- **Surface Hover** (`rgba(37, 99, 235, 0.06)`): Row hover, secondary button hover, light active tint.
- **Overlay** (`rgba(15, 23, 42, 0.34)`): Drawer and modal dimmer.

### Role Guidance

- Color must never replace hierarchy. Use typography and spacing first.
- Blue belongs to action, not decoration.
- Semantic colors appear mostly in values, pills, badges, and compact indicators.
- The dark slab is reserved for top-level account figures, not routine content panels.

### Do / Don't

- **Do** keep the app overwhelmingly neutral and let action blue appear only when the user can do something.
- **Do** use semantic colors on values, compact status chips, and micro indicators.
- **Do** keep the dark slab exclusive to top-level balance orientation.
- **Don't** introduce warm beige, gold, or luxury-finance tones into routine controls.
- **Don't** use multiple accent families on the same surface.
- **Don't** color entire modules by status; color the signal, not the container.

## 3. Typography Rules

### Font Family

- **Primary Sans**: `Avenir Next`, with fallbacks `PingFang SC, Noto Sans SC, Helvetica Neue, sans-serif`
- **Monospace**: `IBM Plex Mono`, with fallbacks `SFMono-Regular, JetBrains Mono, monospace`

### Hierarchy

| Role | Font | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|------|--------|-------------|----------------|-------|
| Hero Display | Avenir Next | 38px max via clamp | 600 | 1.02 | -0.04em | Homepage hero title, compact and authoritative |
| Balance Display | IBM Plex Mono | 42px max via clamp | 500–600 | 1.00 | -0.04em | Total assets, top-level financial slab |
| Surface Title | Avenir Next | 18px | 600 | 1.15 | -0.03em | Panel headings |
| Nav Brand | Avenir Next | 18px | 700 | 1.20 | 0.02em | Sidebar brand lockup |
| Metric Value | Avenir Next / Mono | 18px | 600 | 1.20 | normal | Compact summary metrics |
| Body | Avenir Next | 13px | 400 | 1.50–1.60 | normal | Standard UI copy |
| Label | Avenir Next | 12px | 500–600 | 1.40 | 0.06em | Form labels, metadata, table headings |
| Eyebrow | Avenir Next | 11px | 600 | 1.20 | 0.08em–0.12em | Section overlines, uppercase utility labels |
| Micro | Avenir Next | 10–11px | 400–500 | 1.30 | normal | Timestamps, compact helper text |
| Financial Mono | IBM Plex Mono | 13px–42px | 400–600 | 1.00–1.45 | normal to slight negative | Numeric values, price, cash, PnL |

### Principles

- Headings are compact, not loud. Avoid marketing-scale display type unless used for net-worth orientation.
- Negative tracking belongs to hero and major financial values only.
- Most UI text should live at 12–14px and remain extremely scannable.
- Use monospace whenever the user is comparing amounts, ratios, timestamps, or codes.
- Chinese copy should stay operational and concise; do not use decorative brand slogans in product surfaces.

### Do / Don't

- **Do** write headings like product UI: `账户状态`, `待处理任务`, `交易与资金流水`.
- **Do** keep support copy to one short operational sentence.
- **Do** default to monospace for money, ratios, codes, and timestamps.
- **Don't** write homepage copy like a marketing hero or internal design commentary.
- **Don't** stack multiple long explanatory sentences inside operational panels.

## 4. Component Stylings

### Buttons

**Primary Button**
- Background: `#2563eb`
- Text: `#ffffff`
- Padding: `8px 16px`
- Radius: `6px`
- Shadow: `0 10px 20px rgba(37, 99, 235, 0.16)`
- Hover: darkens to `#1d4ed8`
- Use: Primary decision or submission action

**Secondary Button**
- Background: `rgba(255, 250, 242, 0.7)` or lightly tinted glass
- Text: `#111317`
- Border: `1px solid rgba(15, 23, 42, 0.08)`
- Hover: `rgba(37, 99, 235, 0.06)`
- Use: Secondary actions and low-risk navigation

**Danger Button**
- Background: `rgba(239, 68, 68, 0.12)`
- Text: `#c2413b`
- Border: `1px solid rgba(239, 68, 68, 0.25)`
- Hover: darker red tint
- Use: destructive or reversing actions

### Cards & Panels

- Default surface: translucent white glass card with subtle blur and soft shadow
- Border radius scale:
  - Small control: `6px`
  - Standard input/icon well: `10px–12px`
  - Metric tile: `18px`
  - Section panel: `20px`
  - Hero panel: `24px–30px`
- Borders are present but understated; never heavy or dark
- Cards should feel contained and premium, but the app should avoid card-mosaic overload

### Navigation

- Sidebar is fixed, dark, and slightly translucent
- Active item uses a soft white background fill plus a narrow cool highlight rail
- Hover states brighten text rather than introducing new color
- The sidebar should feel infrastructural, not decorative

### Forms

- Inputs use semi-opaque white backgrounds with subtle borders
- Focus state uses a 1px blue ring and border shift to primary blue
- Form surfaces should look financial and calm, not enterprise-heavy

### Data Modules

**Summary Tiles**
- Compact metric cards with small icon wells, short labels, and one dominant value
- Prefer a single line of interpretation, not paragraphs

**Action Center**
- Clear task rows with symbol, price, recommendation title, supporting detail, and concise controls
- This is the most important operational component after the asset summary

**Risk Cluster**
- Risk items should be compact stacks with level badges, title, and one-line explanation
- Warnings should be visually restrained; avoid alarm-dashboard red walls

**Recent Activity**
- A compressed timeline/list of trades and cash flows
- Emphasis should be on timestamp + action type + amount, not verbose narratives

**Hero Balance Slab**
- Dark, high-contrast, minimal chrome
- Used for total assets and relative performance only
- Never overload this surface with secondary metrics

### Floating Action Button

- Circular blue FAB pinned at bottom-right
- Use sparingly as a convenience launcher for cash flow and trade entry
- Should feel like a utility affordance, not the center of the page

### Do / Don't

- **Do** make cards and panels feel compact, operational, and scannable.
- **Do** keep action controls inline and close to the data they affect.
- **Do** let the sidebar feel infrastructural and calm.
- **Don't** build a homepage out of equal-weight card mosaics.
- **Don't** put process commentary such as “place secondary information correctly” into user-visible UI.
- **Don't** make secondary buttons feel warm or promotional.

## 5. Layout Principles

### Structure

- Application shell = fixed sidebar + full-height content workspace
- Content width is viewport-driven, not narrow marketing-container driven
- Homepage should resolve into:
  - top orientation strip
  - primary action/work area
  - secondary state rail

### Page Composition

- The page is a workbench, not a story page
- The first screen should answer:
  - how much is the account worth
  - what the cash/holding state is
  - what needs action now
  - whether there is immediate risk
- Deeper analytics should move to secondary pages rather than inflate the homepage

### Spacing System

- Base unit: `8px`
- Common application spacing: `8px, 10px, 12px, 14px, 16px, 18px, 20px, 24px, 30px, 48px`
- Internal card spacing is compact
- Inter-section spacing should be clear but never wasteful

### Grid

- Sidebar width: `236px`
- Collapsed sidebar width: `64px`
- Homepage hero: `minmax(0, 1.6fr)` content + `minmax(280px, 0.9fr)` balance slab
- Main workspace: `minmax(0, 1.45fr)` primary column + `minmax(300px, 0.72fr)` secondary rail
- Metric strip: 4-up desktop grid
- At tablet and below, workspace collapses to single column

### Whitespace Philosophy

- Use whitespace to clarify decisions, not to imitate luxury branding
- The UI should feel breathable, but every large empty area must still earn its place
- Information density should be moderate: tighter than a marketing site, calmer than a trading terminal

### Do / Don't

- **Do** prioritize a first screen that answers account value, task state, and risk state without scrolling.
- **Do** compress spacing before removing information hierarchy.
- **Do** maintain a main-workspace / side-rail split on desktop.
- **Don't** leave large decorative empty zones that do not improve readability.
- **Don't** let the homepage become a generic dashboard or a landing page.

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Page Canvas | layered radial + linear light gradient, no border | Global background atmosphere |
| Flat Glass | `rgba(255,255,255,0.72)` + `1px` soft border | Standard panels |
| Card Lift | `0 12px 30px rgba(15, 23, 42, 0.05)` | Tiles, drawers, floating controls |
| Soft Hero Lift | `0 30px 60px rgba(15, 23, 42, 0.06)` | Homepage hero container |
| Sidebar Depth | `30px 0 80px rgba(15, 23, 42, 0.16)` | Persistent navigation rail |
| Primary Action | blue shadow bloom at low opacity | Primary CTA only |
| Dark Slab Inset | `inset 0 1px 0 rgba(255,255,255,0.05)` | Hero total-assets panel |

### Elevation Principles

- Most depth comes from translucency and gentle shadows, not thick borders
- The UI should never look like layered neon glass; shadows must stay soft and cool
- Elevated surfaces should appear only where interaction or emphasis justifies them
- The darkest surfaces belong to navigation and top-level balance emphasis, not to routine content blocks
