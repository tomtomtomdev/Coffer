# Pixel Spec — Coffer Dashboard

Precise measurements for a near-pixel-perfect rebuild. All values are the literal numbers used in the reference. **When in doubt, open `coffer-dashboard-standalone.html` and inspect the element** — every visual value is inline on the node. Base design width for the desktop layout is the **1120px** centered content column.

Units are `px` unless noted. `rgba` shadows are literal.

---

## Global
- App background `--paper` `#eaecf6`; text `--ink` `#1c1d26`.
- Content column: `max-width:1120px`, centered (`margin:0 auto`).
- Main padding: `24px 20px 40px` desktop → `18px 16px 40px` ≤860px.
- Body `padding-bottom:78px` (clears fixed bottom nav) + `env(safe-area-inset-bottom)`.
- Font smoothing: `-webkit-font-smoothing:antialiased`.
- Card recipe: `background:#fff` · `border:1px solid #eef0f6` · `box-shadow:0 6px 22px rgba(28,29,60,0.06)`.
- View-enter animation: `fadeUp` `0.4s ease` (opacity 0→1, translateY 8px→0).

## Header (sticky)
- `position:sticky; top:0; z-index:20`.
- Background `rgba(234,236,246,0.8)` + `backdrop-filter:blur(12px)`; `border-bottom:1px solid #edeef5`.
- Inner row: padding `14px 20px`; `display:flex; align-items:center; gap:16px`.
- **Avatar stack:** two `30×30` circles, `border-radius:50%`, `2px solid #fff` ring, second overlaps first by `margin-left:-9px`. First = `--cash` green "T"; second = `--port` violet "P". Initials: weight 700, 13px, white.
- **Wordmark** "Coffer": Plus Jakarta Sans, weight **800**, **20px**, `letter-spacing:-0.02em`, `line-height:1`.
- **Subtitle** "Tommy & Priskila": IBM Plex Mono, 11px, `--muted`. Hidden ≤620px (`.__brandsub`).
- **Top nav** (`.__topnav`): container `background:#fff; border:1px solid #edeef5; border-radius:12px; padding:3px; gap:2px`. Each tab button: 13px / weight 600, padding `7px 14px`, `border-radius:9px`. Active: bg `--port` `#7c5cff`, text `#fff`. Inactive: transparent, text `--muted`. Transition `all .15s`. Hidden ≤860px.
- **Month chip:** `margin-left:auto`; bg `#fff`, `border:1px solid #edeef5`, `border-radius:10px`, padding `7px 12px`; IBM Plex Mono 12px / weight 500; leading `6px` green dot (`--cash`).

## Bottom nav (`.__botnav`, ≤860px only)
- `position:fixed; bottom:0; left:0; right:0; z-index:20`.
- Background `rgba(255,255,255,0.94)` + blur(12px); `border-top:1px solid #edeef5`.
- Padding `8px 6px calc(8px + env(safe-area-inset-bottom))`.
- Each item: `flex:1`, column layout, `gap:4px`, 11px / weight 600. Active label color `--port`. Top mark: `20×3` rounded bar, `--port` when active else transparent.

## Overview — Hero card
- `border-radius:24`; padding `24`.
- Eyebrow "KEKAYAAN BERSIH RUMAH TANGGA": IBM Plex Mono, 11px, `letter-spacing:.14em`, uppercase, `--muted`.
- **Big figure:** Plus Jakarta Sans weight **800**, `font-size:clamp(38px,7.5vw,56px)`, `line-height:1.02`, `letter-spacing:-0.01em`, `margin-top:8px`.
- **Delta pill:** weight 600, 14px, text `--green`, bg `#e3f7ee`, padding `3px 9px`, `border-radius:20px`. Followed by "vs. bulan lalu · per 30 Jun 2026" 13px `--muted`.
- **Segmented toggle** (Gabungan/Per Anggota): container bg `--paper`, `border:1px solid #edeef5`, `border-radius:11px`, `padding:3px`. Buttons 12px / weight 600, padding `7px 13px`, `border-radius:8px`. Active button bg `#fff`, text `--ink`; inactive transparent, text `--muted`.
- Chart wrapper: `margin-top:18px; min-height:220px`.
- Footnote: 11.5px `--faint`, `line-height:1.5`, `border-top:1px dashed #edeef5`, `padding-top:12px`, `margin-top:14px`.

## Tide chart (SVG)
- `viewBox="0 0 680 300"`, rendered `width:100%` (`height:auto`), `preserveAspectRatio:xMidYMid meet`.
- Insets: L=14, R=16, T=26, B=34. 6 points across (`n=6`).
- Y scale max = `1.15 × max(cash+port)` (household) or `1.15 × max(hadi,pris)` (member).
- **3 gridlines** at 0/⅓/⅔/max: `stroke:#e7e0d4`→ use `--border` `#edeef5` in prod; `stroke-width:1`. Labels above line: 10px, `#b4b8c9`, IBM Plex Mono (short-form IDR).
- Household: portfolio area `fill:url(#gPort)` violet gradient (stop 0% `#7c5cff` @0.26 → 100% @0.03); cash band `fill:url(#gCash)` green gradient (0% `#17b26a` @0.30 → 100% @0.05). Portfolio top-line `#7c5cff` `stroke-width:1.5` opacity .5; asset top-line `#17b26a` `stroke-width:1.5` opacity .65. **Net line** `#1c1d26`, `stroke-width:2.5`, round caps/joins; dots r=3 (last r=5, filled ink).
- Member: two lines Tommy `#17b26a` / Priskila `#7c5cff`, `stroke-width:2.5`; dots r=3 (last r=4.5).
- X labels: 11px `--muted`, IBM Plex Mono, centered, y=`H-10`.
- Month keys: `Jan Feb Mar Apr Mei Jun`.

## Overview — KPI row (`.__kpis`)
- `display:grid; grid-template-columns:repeat(3,1fr); gap:14px`. → 1 col ≤720px.
- Each card (button): `border-radius:20`, padding `18`, card recipe, `text-align:left`, `cursor:pointer`.
- Eyebrow: IBM Plex Mono 10.5px `letter-spacing:.1em` uppercase `--muted`.
- Figure: Plus Jakarta Sans weight **800**, **31px**, `margin-top:6px` (savings green, cash flow green).
- Sub: 12px `--muted`, `margin-top:5px`.

## Overview — Rincian Akun
- Card `border-radius:20`, padding `20px 22px`.
- Row: `display:flex; align-items:center; gap:12px; padding:13px 0; border-bottom:1px solid #edeef5`.
- Leading dot `9×9`, `border-radius:3` (cash green / port violet / liab rose).
- Name 14px / weight 600; sub 11.5px `--muted` mono. Right: balance mono 14px / weight 600 (neg → `−` prefix, `--red`); "per <date>" 10.5px `--faint` mono.

## Portfolio
- **Caveat banner:** bg `#fef0f2`, `border:1px solid #fbdbe1`, `border-radius:16`, padding `13px 16px`, `gap:11`. `⚠` in `--liab`; text 12.5px `#b23a52`, `line-height:1.5`.
- **Summary cards** (`.__pcards`): `grid-template-columns:1fr 1fr; gap:14` → 1 col ≤720px. Card `border-radius:20`, padding `18`. Figures weight 800, 33px, `margin-top:6px`; P/L colored by sign.
- **Holdings table** (`.__ptable`): card `border-radius:20`, `overflow:hidden`. ≤620px: `overflow-x:auto`, rows `min-width:540px`.
  - Grid columns: `1.6fr 0.7fr 1fr 1fr 1.1fr`, `gap:8`, row padding `13px 18px`, `border-bottom:1px solid #edeef5`.
  - Head: IBM Plex Mono 10px `letter-spacing:.08em` uppercase `--muted`.
  - Ticker: mono weight 600 14px. **CORP ACTION** tag: 9px / weight 600, `--liab` on `#fde3e8`, padding `2px 6px`, `border-radius:6`. CA note `↳` line: 10.5px `--liab`.
  - Company name 11.5px `--muted`; broker 12px `--muted`.
  - Numbers mono: lots 13px (+ shares 10px `--faint`); avg 12.5px + price 11px `--muted`; MV 13.5px weight 600 + P/L 11.5px colored (with %).
  - Total row: bg `--paper`, padding `14px 18px`; label weight 700 13px; total mono weight 700 14px + P/L 11.5px.

## Spend
- **Hero card** `border-radius:24`, padding `24`. Big figure weight 800 `clamp(34px,6.5vw,48px)` `line-height:1`. Inline explainer 13px `--muted`.
  - **Bar sparkline:** `display:flex; gap:6; align-items:flex-end; height:70px; margin-top:20`. Each bar `max-width:34px`, `border-radius:5px 5px 0 0`, height ∝ value; color `--liab` when >26 (jt) else `--cash`. Month label 10px mono `--muted`.
- **Per-category card** `border-radius:20`, padding `20px 22px`. Row `margin-bottom:13`: label 13.5px / weight 500 + cadence tag (9.5px / weight 600, `--muted` on `--paper`, `border:1px solid #edeef5`, `border-radius:5`, padding `2px 7px`); median mono 13px weight 600. Progress track `height:8`, bg `--paper`, `border-radius:5`; fill width ∝ median/max, color `--cash` (Bulanan) / `--orange` (Tahunan).
- **Anomaly card:** bg `#fef0f2`, `border:1px solid #fbdbe1`, `border-radius:20`, padding `18px 20px`, card shadow. Heading weight 700 13.5px `#c0304a`. Row `padding:10px 0; border-top:1px solid #fbdbe1`: desc 13px / weight 500 + reason 11.5px `#c47488` mono; amount mono weight 600 14px `--liab`.
- **Review queue card** `border-radius:20`, padding `20px 22px`. Row `padding:12px 0; border-top:1px solid #edeef5; gap:12`. Desc mono 12.5px / weight 500 (ellipsis). Badge 10px / weight 600, padding `2px 8px`, `border-radius:6` — colors: Parser fg `#5b6070`/bg `#eef0f6`; Auto·pelajaran fg `#6b46e0`/bg `#eee9ff`; Manual fg `#1c1d26`/bg `#e7e8f0`; Perlu tag fg `#c0304a`/bg `#fde3e8`. Category 11.5px `--muted`; optional `→ acct` 10.5px `--faint` mono. Right: amount mono weight 600 13px; action 11px / weight 600 (`--liab` for "Tag →", `--port` for "Ubah").

## Cash Flow
- **Summary cards** (`.__pcards`, `1fr 1fr`): figures weight 800, 37px, `--cash`/`--green`.
- **Chart card** `border-radius:24`, padding `22`, `min-height:230`.
- **Income chart (SVG):** `viewBox="0 0 680 300"`. Insets L=16 R=16 T=18 B=32; `n=6`. Grouped bars per month: income `--cash` + spend `--liab`, both `fillOpacity:0.85`, `rx:4`, bar width = 30% of slot, small gap between pair. Primary Y max = `1.22 × max(income)`. **Savings-rate line** (secondary scale 0–80%): `#1c1d26` `stroke-width:2.5` round caps, `stroke-dasharray:1 6`; dots r=3.5 (white fill, ink stroke); per-point `%` label 10.5px / weight 600 ink, `9px` above dot.
- **List cards** (`1fr 1fr`): row `padding:9px 0; border-bottom:1px solid #edeef5`, 13.5px; income amounts mono weight 600 `--cash`, spend amounts mono weight 600 `--liab`.

## Responsive breakpoints (summary)
- `≥861px`: top nav shown, bottom nav hidden.
- `≤860px`: top nav hidden, bottom nav shown; header/main padding → 16px.
- `≤720px`: `.__kpis` and `.__pcards` → single column.
- `≤620px`: portfolio table scrolls horizontally (rows `min-width:540px`); brand subtitle hidden.

## Number formatting
- Currency: `Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0})` → `Rp 943.000.000`.
- Short axis form: ≥1000 jt → `"1,1 M"`; else `"611 jt"` (comma decimal, id-ID).
- Negative balances: leading `−` (U+2212) + rose color.
