# Handoff: Coffer — Household Finance Dashboard

## Overview
Coffer is a private, self-hosted household finance consolidator for a two-person household (couple: **Tommy & Priskila**). It ingests Indonesian bank statements (BCA savings + credit card, CIMB credit card) and broker exports (Ajaib, Stockbit), then presents a consolidated view of net worth, portfolio, routine spending, and cash flow. All figures are IDR, formatted with the `id-ID` locale.

This handoff covers the **dashboard UI** — four views:
1. **Ringkasan / Net Worth** (overview) — consolidated net worth with a stacked "tide" area chart
2. **Portofolio** — cross-broker holdings consolidator
3. **Belanja** (Spend) — routine-spend estimate + per-category medians + review queue
4. **Arus Kas** (Cash Flow) — income vs. spend + savings rate

It is **mobile-responsive** (single-user LAN/VPN tool used on phone and desktop).

---

## About the Design Files
The files in this bundle are **design references created in HTML** — a working prototype showing the intended look, layout, data shape, and interactions. They are **not production code to copy directly**.

- `Household Finance.dc.html` is authored as a "Design Component" (a lightweight in-house HTML component format). It contains an HTML template plus a JavaScript logic class (`class Component`). **Ignore the DC wrapper/runtime mechanics** — `support.js` is only there so the prototype opens in a browser. What matters is the markup structure, the inline styles (all visual tokens live here), the SVG chart-drawing code, and the mock data.
- Your task is to **recreate this design in the target codebase's environment** using its established patterns and libraries (React/Vue/Svelte components, a real charting lib, etc.). If no frontend environment exists yet, pick the most appropriate stack for a small self-hosted dashboard (e.g. React + Vite + Recharts/visx, or SvelteKit) and implement there.
- The prototype hand-draws its charts with raw SVG so it has zero dependencies. **In production, prefer a charting library** (Recharts, visx, ECharts, Chart.js) — the SVG code here is the spec for *what to draw*, not *how to build it*.

## Fidelity
**High-fidelity (hifi).** Colors, typography, spacing, radii, and interactions are final and intentional. Recreate the UI faithfully using the codebase's component library. Exact hex values, font families, and sizes are documented below and are also present inline in the HTML.

---

## Design Tokens

### Colors
| Token | Hex | Usage |
|---|---|---|
| `--paper` | `#eaecf6` | App background (light lavender) |
| `--card` | `#ffffff` | Card surfaces |
| `--ink` | `#1c1d26` | Primary text, big figures |
| `--muted` | `#8a8fa3` | Secondary/label text |
| `--faint` | `#b4b8c9` | Tertiary text, footnotes, axis labels |
| `--border` | `#edeef5` | Hairline dividers (rows, table lines). Charts use `#eceef6` for gridlines. |
| `--cardbd` | `#eef0f6` | Card hairline border (paired with shadow) |
| `--sh` (shadow) | `0 6px 22px rgba(28,29,60,0.06)` | Card elevation |
| `--cash` / `--green` | `#17b26a` | Cash stack, positive values, savings |
| `--port` | `#7c5cff` | **Primary accent** (violet) — portfolio stack, active nav, learned-rule badges |
| `--liab` / `--red` | `#f04766` | Liabilities, losses, alerts (rose) |
| `--orange` | `#f59e0b` | 4th accent — annual-cadence categories |

Semantic tints (used in alert cards & badges):
- Positive delta pill: text `--green` on bg `#e3f7ee`
- Rose alert card: bg `#fef0f2`, border `#fbdbe1`, heading `#c0304a`, body `#b23a52`, sub `#c47488`
- Badge "Auto · pelajaran" (learned): fg `#6b46e0` on bg `#eee9ff`
- Badge "Parser": fg `#5b6070` on bg `#eef0f6`
- Badge "Manual": fg `#1c1d26` on bg `#e7e8f0`
- Badge "Perlu tag" (needs tagging): fg `#c0304a` on bg `#fde3e8`
- CORP ACTION tag: fg `--liab` on bg `#fde3e8`

### Typography
Two families loaded from Google Fonts:
- **Plus Jakarta Sans** (400/500/600/700/800) — wordmark, headings, and **all big figures** (used bold, weight 800, `letter-spacing:-0.01em` to `-0.02em`). This is the `--display` family.
- **IBM Plex Mono** (400/500/600) — **tabular numerics only**: portfolio table cells, chart axis labels, account balance stamps, small "eyebrow" section labels (uppercase, `letter-spacing:.1–.14em`), and code-like transaction descriptions in the review queue.
- Body / UI text also uses Plus Jakarta Sans (fallback `Hanken Grotesk`, system-ui).

Type scale (px):
- Big hero figure (net worth): `clamp(38, 7.5vw, 56)`, weight 800
- Spend hero figure: `clamp(34, 6.5vw, 48)`, weight 800
- KPI / portfolio card figures: 31–37, weight 800
- Wordmark "Coffer": 20, weight 800
- Section eyebrow (mono uppercase): 10–11
- Body: 13–14; small/labels: 11.5–12.5; footnotes: 11.5 (`--faint`)

### Spacing / Radius / Elevation
- Card padding: 18–24px
- Card radius: **24px** (large hero/chart cards), **20px** (standard cards)
- Small controls (nav pill, segmented toggle, month chip) radius: 8–12px
- Chips/tags radius: 5–6px; progress-bar track radius: 5px
- Card elevation: `0 6px 22px rgba(28,29,60,0.06)` with a 1px `--cardbd` border
- Grid gaps: 14–18px

---

## Screens / Views

All four views share:
- A **sticky top header**: avatar stack (T / P circles, green + violet), "Coffer" wordmark + "Tommy & Priskila" subtitle, centered segmented **top-nav** (Ringkasan / Portofolio / Belanja / Arus Kas), and a month chip ("Juni 2026") on the right.
- A **fixed bottom-nav** (mobile only) mirroring the four tabs with a colored top-mark for the active tab.
- Max content width **1120px**, centered, `24px 20px` padding (tightens to `18px 16px` on mobile).
- Active tab: violet (`--port`) background, white text (top-nav) / violet label + violet mark (bottom-nav).
- View switches animate in with a `fadeUp` keyframe (opacity 0→1, translateY 8px→0, 0.4s ease).

### 1. Ringkasan / Net Worth (overview)
**Purpose:** At-a-glance household net worth and its composition over time.
**Layout:** single column, `gap:18px`.
- **Hero card** (radius 24): eyebrow "KEKAYAAN BERSIH RUMAH TANGGA"; big figure `Rp 943.000.000`; green delta pill `↑ Rp 35 jt (3,9%)` + "vs. bulan lalu · per 30 Jun 2026". Top-right **segmented toggle**: "Gabungan" (household) / "Per Anggota" (per-member).
  - **Tide chart** (SVG, ~680×300 viewBox, scales to 100% width): 
    - *Household mode:* stacked area — portfolio band (violet gradient, bottom), cash band (green gradient, on top), and a solid near-black **net-worth line** with dots (last dot emphasized). 3 horizontal gridlines with short-form IDR labels (`fmtShort`: e.g. "611 jt", "1,1 M").
    - *Per-member mode:* two lines — Tommy (green), Priskila (violet), each with dots.
  - Legend row below (color chip + label). Household legend: Kas / Portofolio / Kekayaan bersih. Member legend: Bersih — Tommy / Bersih — Priskila.
  - Footnote (`--faint`, dashed top border) explaining the carry-forward month-end balance logic.
- **KPI row** (`repeat(3,1fr)`, collapses to 1 col ≤720px): three clickable cards →
  - "Belanja Rutin / bln" = `Rp 23,8 jt` (+ "Rp 1,87 jt amortisasi tahunan") → navigates to Belanja
  - "Tingkat Menabung" = `47%` (green) → Arus Kas
  - "Arus Kas Bulanan" = `+Rp 32 jt` (green) → Arus Kas
- **Rincian Akun** card: list of accounts, each row = color dot (green cash / violet portfolio / rose liability) + name + sub (masked acct id) + right-aligned balance (mono; negatives shown with `−` in rose) + "per <date>" stamp.

### 2. Portofolio
**Purpose:** Consolidated holdings across two brokers with a mixed-date caveat.
**Layout:**
- **Rose caveat banner** (top): warns combined P/L is "tanggal campuran" (mixed as-of dates: Ajaib 30 Jun, Stockbit 28 Jun).
- **Two summary cards** (`1fr 1fr`, collapses ≤720px): "Nilai Pasar Gabungan" (total market value) and "Unrealized P/L" (colored by sign, with %).
- **Holdings table** (radius 20, horizontally scrollable ≤620px with `min-width:540px` on rows): columns **Emiten / Broker / Lot / Avg-Harga / Nilai-P&L**. Each row: ticker (mono bold) + optional **CORP ACTION** tag + company name; broker; lots (+ shares "lbr"); avg & current price; market value + P/L (colored, with %). Rows with a corporate action show a `↳` note (e.g. ANTM bonus issue). Footer row: "Total Rumah Tangga" with grand total + total P/L.

### 3. Belanja (Spend)
**Purpose:** Estimate routine monthly spend and surface anomalies + a categorization queue.
**Layout:**
- **Estimasi Belanja Rutin** hero card (radius 24): big figure `Rp 23,8 jt` (median of monthly totals) + inline explanation ("+ Rp 1,87 jt amortisasi tahunan = Rp 25,67 jt/bln"). Mini **bar sparkline** of the last 6 months' routine totals (bars turn rose when > 26 jt, else green). Footnote on per-category medians not summing to the headline, and the <3-month cold-start rule.
- **Rincian per Kategori** card: each category = label + cadence tag ("Bulanan"/"Tahunan") + median (mono) + horizontal progress bar (width ∝ median/max; **green** for monthly, **orange** for annual).
- **Perlu Ditinjau** rose alert card: anomalies "kemungkinan bukan rutin" (e.g. groceries 2.3× median) with reason + amount.
- **Antrean Kategorisasi** card: review queue. Each row = transaction description (mono, truncated) + **source badge** (Parser / Auto·pelajaran / Manual / Perlu tag — see badge colors) + assigned category + optional target account + amount + action link ("Tag →" in rose for untagged, "Ubah" in violet otherwise). Header notes the resolution order: parser → learned rules → regex → uncategorized.

### 4. Arus Kas (Cash Flow)
**Purpose:** Income vs. spend and savings rate over time.
**Layout:**
- **Two summary cards** (`1fr 1fr`): "Tingkat Menabung" `47%` (green, "rata-rata 6 bulan") and "Arus Kas · Juni" `+Rp 32 jt` (green).
- **Pendapatan vs Belanja** chart card (radius 24): grouped **bar chart** — income (green) vs spend (rose) per month, plus a dotted near-black **savings-rate line** with per-point `%` labels on a secondary 0–80% scale. Legend: Pendapatan / Belanja / Tingkat menabung. Footnote: transfers & investment moves excluded; attributed to transaction month not upload date.
- **Two list cards** (`1fr 1fr`): "Sumber Pendapatan · Juni" (Gaji Tommy / Gaji Priskila / Lainnya, amounts in green) and "Belanja per Tipe · Juni" (Rutin / Discretionary / One-off, amounts in rose).

---

## Interactions & Behavior
- **Tab navigation:** clicking a top-nav or bottom-nav tab switches the view (`setView`) and scrolls to top (`window.scrollTo({top:0})` — use your router/scroll-restoration equivalent, **do not** use `scrollIntoView`). Active state is violet.
- **Net-worth toggle:** "Gabungan" vs "Per Anggota" swaps the tide chart between stacked-area (household) and two-line (per-member) renderings and updates the legend.
- **KPI cards** on the overview are buttons that deep-link to the Belanja / Arus Kas views.
- **Review-queue action links** ("Tag →" / "Ubah") are the entry points for (re)categorizing a transaction — wire to your categorization action/modal.
- **Charts scale fluidly** via SVG `viewBox` at 100% width; last data point is emphasized (larger dot).
- **Animation:** view enter = `fadeUp` 0.4s ease. Keep transitions subtle (nav hover `all .15s`).

### Responsive behavior
- **≥861px:** top segmented nav visible; bottom nav hidden.
- **≤860px:** top nav hidden; **fixed bottom nav** shown; header + main padding tighten.
- **≤720px:** KPI row and all `1fr 1fr` card pairs collapse to a single column.
- **≤620px:** portfolio table becomes horizontally scrollable (rows keep `min-width:540px`); brand subtitle ("Tommy & Priskila") hides.
- Body has `padding-bottom:78px` to clear the fixed bottom nav; respect `env(safe-area-inset-bottom)`.

## State Management
Minimal client state:
- `view`: one of `overview | portfolio | spend | cashflow` (default `overview`). Consider syncing to the URL/route.
- `nwMode`: `household | member` for the net-worth toggle (default `household`).
Everything else is derived from source data at render time (see below). In production, replace the mock data with fetched, parsed statement data.

### Derived computations (from mock data — replicate the logic)
- **Portfolio:** for each holding `shares = lots × 100`, `marketValue = shares × price`, `cost = shares × avg`, `P/L = mv − cost`, `P/L% = pl/cost`. Totals summed across holdings. P/L colored by sign.
- **Routine spend headline:** median of monthly totals (prototype hardcodes `Rp 23,8 jt`; implement as median). Per-category values are each category's own median — **they intentionally do not sum to the headline.**
- **Savings rate:** `(income − spend) / income` per month; headline is the 6-month figure.
- **Currency formatting:** `Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0})`. Short form (`fmtShort`): ≥1000 jt → "x,x M", else "x jt".
- **Cold-start rule:** with <3 months of data, do **not** show a routine estimate.
- **Carry-forward net worth:** each month-end grid point uses the most recent report with `period_end ≤ grid date`, to align savings/credit-card/broker reports that arrive on different cadences.

## Assets
No external image assets. Avatars are CSS circles with initials (T/P). All icons/marks in the prototype are CSS/SVG shapes. Fonts are Google Fonts (Plus Jakarta Sans, IBM Plex Mono). Charts are drawn programmatically — no asset files.

## Files
- `coffer-dashboard-standalone.html` — **self-contained** reference. Open directly in any browser (no runtime, no build). Click the four tabs and the Gabungan/Per Anggota toggle to see every state. **This is the source of truth for exact pixel values — inspect any element; all styling is inline.**
- `MEASUREMENTS.md` — pixel-precise spec: every size, weight, color, radius, shadow, inset, and breakpoint.
- `reference/` — full-page screenshots of each view (`01-ringkasan`, `02-portofolio`, `03-belanja`, `04-arus-kas`) at the 1120px desktop width.
- `Household Finance.dc.html` — the original authored prototype (HTML template + `Component` logic class with the two SVG chart builders `buildTide`/`buildIncome` + mock data). The standalone above is compiled from this.
- `support.js` — prototype runtime; **not needed for implementation**.

> All visual styling in the prototype is **inline** on the elements — read the markup (or inspect the standalone) for exact per-element values. The token block lives on the top-level `<div>`'s `style` (the `--paper`, `--card`, … custom properties under Design Tokens). See `MEASUREMENTS.md` for the pixel-level breakdown.
