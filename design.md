# Karkinos Design System

Karkinos uses a Catppuccin platform system: **Latte** for light mode and **Mocha** for dark mode. The product should feel calm enough for daily portfolio review, dense enough for financial operation, and clear enough that money, risk, and data freshness never require visual effort to parse.

This document is the source of truth for UI direction. If implementation and this document disagree, update the implementation or explicitly record the drift before moving on.

## Current Audit

Checked on 2026-06-17 against the in-app browser Overview route and a static token scan.

Conforming:

- The active theme is Catppuccin Latte with `--app-bg: #eff1f5`, `--app-text: #4c4f69`, and `--app-muted: #6c6f85`.
- The codebase already exposes most app colors through `--app-*` tokens instead of one-off page colors.
- The shell, panels, charts, and controls use a restrained financial-app density rather than a marketing layout.

Needs correction:

- The previous design spec described a white-glass/blue product system, which no longer matches the implemented Catppuccin Latte/Mocha direction.
- Raw Catppuccin Latte semantic colors can be too low-contrast for small financial text. For example, Latte green `#40a02b` on light surfaces is pleasant but not always readable enough for 12-14px values.
- Some components reference missing tokens: `--app-warning-bg`, `--app-warning-border`, and `--app-accent-strong`. These should be defined centrally or replaced with existing tokenized color mixes.
- Hard-coded theme colors should be rare. Current examples include `text-white`, `border-white/8`, and `bg-white/[0.03]`; they are acceptable only on controlled Mocha-like surfaces or active accent fills after contrast checks.
- Status chips, tooltips, chart labels, and tiny metadata need explicit Latte and Mocha contrast review, not only visual approval in one theme.

## North Star

Karkinos is a personal quant research and trading platform for one operator. It is not a brokerage clone, a marketing dashboard, or a toy backtester UI.

The first screen should quickly answer:

- What is the account worth?
- What changed today?
- Which data is fresh, stale, cached, or missing?
- What requires attention before any action?
- Where can I inspect the instrument-level evidence?

The interface should reduce eye strain during repeated daily use. Visual atmosphere is useful only when it improves orientation; it must never reduce legibility.

## Palette

Use Catppuccin names in design discussion and `--app-*` variables in code.

| Role         | Mocha     | Latte     | Token                             |
| ------------ | --------- | --------- | --------------------------------- |
| Base canvas  | `#1e1e2e` | `#eff1f5` | `--app-base`, `--app-bg`          |
| Mantle       | `#181825` | `#e6e9ef` | `--app-mantle`                    |
| Crust        | `#11111b` | `#dce0e8` | `--app-crust`                     |
| Panel        | `#313244` | `#ccd0da` | `--app-panel`, `--app-surface-0`  |
| Surface      | `#45475a` | `#bcc0cc` | `--app-surface-1`, `--app-border` |
| Primary text | `#cdd6f4` | `#4c4f69` | `--app-text`, `--app-foreground`  |
| Muted text   | `#a6adc8` | `#6c6f85` | `--app-muted`, `--app-subtext-0`  |
| Accent       | `#cba6f7` | `#8839ef` | `--app-accent`                    |
| Info accent  | `#89b4fa` | `#1e66f5` | `--app-accent-secondary`          |
| Success      | `#a6e3a1` | `#40a02b` | `--app-success`                   |
| Danger       | `#f38ba8` | `#d20f39` | `--app-danger`                    |
| Warning      | `#f9e2af` | `#df8e1d` | `--app-warning`                   |
| Teal         | `#94e2d5` | `#179299` | `--app-teal`                      |

Palette rules:

- Do not introduce generic Tailwind palette colors for product surfaces when a Catppuccin or `--app-*` token exists.
- Do not use `emerald-100`, `sky-100`, `amber-100`, or similar pale dark-mode text colors on Latte surfaces.
- Accent purple is for selected controls, focus, and platform emphasis. It is not a decorative background theme.
- Green, red, amber, blue, and teal are semantic. They should explain data state, PnL, risk, or action state.

## Contrast And Eye Comfort

Legibility rules:

- Body text, table text, status text, and small financial numbers should target WCAG AA contrast of 4.5:1 or better.
- Large financial values may use 3:1 or better only when size and weight make them unmistakable.
- Do not reduce text contrast with opacity when a proper token can express hierarchy.
- `--app-muted` is for secondary labels, not important values.
- Use `--app-text` for default readable text; use semantic colors only when the meaning matters.

Semantic color rules:

- Raw semantic colors can be used for icons, dots, chart strokes, borders, and heatmap fills.
- For small text on Latte, prefer a future `--app-success-text`, `--app-danger-text`, `--app-warning-text`, and `--app-info-text` if raw Catppuccin colors fail contrast.
- Positive or negative money should remain readable before it is colorful.
- Warning badges must be readable in both Latte and Mocha; missing or stale data should never look decorative.

Surface rules:

- Latte should not feel like pure white paper. Use Base, Mantle, Crust, and Surface layers.
- Mocha should not feel like pure black. Keep panels lifted from Base with border and surface tokens.
- Transparent backgrounds must be checked against the effective parent background, not only their declared color.
- Avoid large empty decorative zones; empty space should support scanning, not luxury branding.

## Typography

Use system-native readability over decorative branding.

Font stack:

- Sans: `-apple-system`, `BlinkMacSystemFont`, `SF Pro Text`, `Segoe UI`, `PingFang SC`, `Microsoft YaHei`, `Noto Sans CJK SC`, sans-serif
- Numeric and instrument-like values: tabular numerals through `font-variant-numeric: tabular-nums`

Rules:

- Chinese UI text should be concise and operational.
- Do not use negative letter spacing except on major financial display values where it has been visually checked.
- Do not scale type with viewport width.
- Numbers that users compare side by side should align visually and use stable decimals.
- Buttons and chips should use clear labels or icons with accessible names; they should not compress Chinese labels into ambiguous shapes.

## Components

Panels:

- Use app panel tokens and 8px-based spacing.
- Cards are for repeated items, modals, and framed tools. Avoid cards inside cards unless the inner object is a genuine repeated item.
- Panel content should be dense but not cramped. If a value needs explanation, add a compact label rather than a paragraph.

Buttons and segmented controls:

- Active selected controls may use the accent fill, but text contrast must be verified in both Latte and Mocha.
- Do not rely on `text-white` unless the active fill is known to be dark enough in Latte and Mocha.
- Icon-only controls require accessible names and should have visible selected state.

Status chips:

- Must show the label and the reason clearly.
- Use tokenized semantic backgrounds and borders.
- Never use pale dark-theme text on Latte.
- Long Chinese status text should truncate only when the full meaning is available elsewhere or the chip is non-critical.

Tables:

- Wide tables scroll locally, never by stretching the whole app shell.
- Numeric cells use consistent alignment, width, and currency formatting.
- Chinese asset-class labels must not wrap character-by-character.

Charts:

- Axes, grid lines, tooltips, and selected markers must be readable in Latte and Mocha.
- Tooltips should show exact values and context, not only decorative hover dots.
- Chart stroke colors may use Catppuccin semantic colors, but labels and tooltip text must use readable text tokens.

Financial calendar:

- Calendar cells should prioritize date, period label, and amount.
- Positive/negative fill intensity can communicate direction, but amount text must stay readable.
- Week, month, and year cards should use stable layout rules so values do not drift between views.

## Layout

Karkinos should behave like a focused financial platform:

- Main content owns the primary decision area.
- Secondary rails hold action queues, recent activity, or diagnostics.
- On narrow screens, content should reflow by priority rather than shrink globally.
- Root and shell containers must not silently clip important content.
- Wide tables, grids, and charts should scroll inside local containers.

Breakpoints:

- Desktop: two-column workbench where the secondary rail remains useful.
- Tablet: single-column with high-priority cards first.
- Mobile: compact cards and local scrolling; no horizontal page overflow.

## Copy

The UI should sound like an operating instrument, not a marketing page.

Use:

- `行情缓存`
- `估值可用`
- `待确认`
- `风险阻断`
- `买入`
- `卖出`
- `资金转入`

Avoid:

- Internal reason codes without localization.
- English fallback in Chinese mode.
- Design commentary in the product UI.
- Phrases that imply guaranteed profit or investment advice.

## Implementation Guardrails

Before merging UI changes:

- Check Latte and Mocha.
- Check at least one common desktop viewport and one narrower viewport when layout changes.
- Scan for new hard-coded colors and replace them with `--app-*` tokens unless there is a documented reason.
- Run frontend tests and build for user-visible frontend changes.
- Add deterministic tests for contracts that previously regressed, such as status chip contrast classes, local overflow, or chart tooltip behavior.

Recommended cleanup backlog from this audit:

- Define or remove `--app-warning-bg`, `--app-warning-border`, and `--app-accent-strong`.
- Add text-specific semantic tokens for Latte/Mocha if raw Catppuccin colors remain below contrast requirements.
- Replace remaining unscoped white utilities on routine surfaces.
- Add a lightweight contrast audit for key platform surfaces.
