# Research & Execution Platform — User Flows & Wireframes

> **Status: design (pre-implementation).** This is the UX spec to review *before*
> writing UI code, per request. It supersedes the eight generic dashboards in the
> current scaffold (`docs/DESKTOP_APP.md` covers the unchanged process/architecture
> — Electron shell + FastAPI sidecar + SQLite; only the renderer's screens change).

## 0. Reframe

This is **not a trading bot**. It is a **quantitative research & execution
workbench** — a terminal you *drive* through a pipeline, not a dashboard you
watch. The entire UI is organized around one workflow:

```
1 Scan ▸ 2 Review candidates ▸ 3 Analyze conviction ▸ 4 Review analogs
      ▸ 5 Backtest ▸ 6 Replay ▸ 7 Paper ▸ 8 Live (gated)
```

Every screen is a **stage** in that pipeline. A single **selected symbol** and a
single **active run/workspace** flow through all stages, so you never re-navigate
or re-type context.

## 1. Design principles

| Goal | How it shows up |
|---|---|
| **Speed** | local SQLite sidecar; prefetch-on-hover; virtualized tables; no spinners for cached data; optimistic UI; a *candidate aggregate* endpoint so one fetch fills a whole screen |
| **Data density** | compact rows (28px), tabular/monospace numerics, inline sparklines & micro-bars, multi-column master-detail, no oversized headers or hero cards |
| **Minimal clicks** | **command palette (⌘K)** + **single-key actions**; persistent symbol context (pick once, inspect everywhere); split panes so the list never disappears when you drill |
| **Dark mode** | one dark theme, near-black surfaces, thin 1px borders, color reserved for *meaning* (regime, R sign, conviction band) not decoration |
| **Power-user** | keyboard-first (vim-style `j/k`, `g`-prefixed jumps, number keys for stages); everything reachable without the mouse; a shortcuts overlay (`?`) |
| **No clutter** | low chrome: one context bar, one status bar, the stage, nothing else. No nested cards, no redundant titles, no modal stacks. |

## 2. The workflow IS the navigation

Left rail = the pipeline (numbered for keyboard jump); utilities below a divider.
Top context bar = what you're working *on*; bottom status bar = system state.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ MRP · Run 2024-Q2 ▾ │ ◆ BULLISH  ADX 28  VIX 14 │  ⌘K search / command…  │ ● PAPER  ◌ LIVE │  context bar
├───────────────┬─────────────────────────────────────────────────────────────────────────┤
│ 1  Scan       │                                                                           │
│ 2  Candidates │                                                                           │
│ 3  Conviction │                          STAGE  (master / detail)                         │
│ 4  Analogs    │                                                                           │
│ 5  Backtest   │                                                                           │
│ 6  Replay     │                                                                           │
│ 7  Paper      │                                                                           │
│ 8  Live   🔒  │                                                                           │
│ ───────────   │                                                                           │
│ ◷ Portfolio   │                                                                           │
│ Σ Analytics   │                                                                           │
│ ⚙ Settings    │                                                                           │
├───────────────┴─────────────────────────────────────────────────────────────────────────┤
│ ● backend ok · 412 symbols · last scan 09:32 · job: idle · ⌘K palette · ? shortcuts        │  status bar
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Run selector** scopes every screen to one research run/dataset (the `runs` table).
- **Regime badge** is always visible — it gates conviction, sizing and entries, so it
  belongs in the chrome, not on a separate screen.
- **Paper/Live toggle** sets the execution target; **Live** is locked (🔒) until explicitly enabled.

## 3. Interaction model

- **Persistent selection.** Selecting a symbol in *Scan* makes it the subject of
  *Conviction*, *Analogs*, *Backtest filter*, *Replay* and *Paper* — press `3/4/5/6/7`
  to move that symbol through the pipeline. The selected symbol shows in the context bar.
- **Command palette (⌘K / Ctrl-K).** Fuzzy over symbols, stages and actions:
  `AAPL`, `go conviction`, `run scan`, `run backtest`, `queue paper`, `open settings risk`.
  This is the primary navigation; the rail is a visible fallback.
- **Keyboard map (global):**
  `1‥8` jump stage · `g p/a/s` portfolio/analytics/settings · `j/k` row down/up ·
  `⏎` drill into selection · `esc` back/close · `/` focus filter · `⌘K` palette ·
  `?` shortcuts · `[ ]` prev/next symbol in the candidate set (carries across stages).
- **Master-detail, not modals.** Lists keep a right-hand inspector; drilling opens a
  split or replaces the detail, never a stack of dialogs.
- **Prefetch.** Hovering a candidate row warms its aggregate (conviction + opportunity +
  instrument + risk + analogs summary) so pressing `3/4` is instant.

## 4. Primary flow — the daily research loop

```
 Scan ──select──▶ Inspector (one glance: score · opp · instrument · risk)
   │                   │ 3                4              5            6
   │                   ▼                  ▼              ▼            ▼
   │              Conviction  ──────▶  Analogs  ─────▶ Backtest ──▶ Replay
   │              (why, 8 inputs)     (did it pay?)   (does edge   (build
   │                   │                  │            hold OOS?)   intuition)
   │                   └─────────┬────────┴──────┬─────────┘
   │                             ▼ 7             │
   └────────────── shortlist ─▶ Paper ◀──────────┘  accrue track record
                                  │ 8 (gated, deliberate)
                                  ▼
                                 Live
```

Concretely (mouse-optional): `1` run scan → `j/k` skim ranked candidates while the
inspector auto-shows conviction/opportunity/instrument/risk → `3` to interrogate the
score → `4` to check the historical edge → `5` to confirm it survives a backtest →
`6` to replay a couple of analog trades → `7 ⏎` to queue it to paper. Eight keystrokes,
no dialogs.

**Secondary flows**
- **Triage:** Scan → `/passed homerun` filter → `s` star / `x` dismiss to build a shortlist.
- **Backtest iteration:** Backtest → edit config inline → `⏎` run → compare runs → drill trade → `6` replay.
- **Promotion:** Paper accrues stats → Analytics confirms expectancy/PF → deliberate Live enablement.
- **Config tuning:** Settings → edit a config → validate → save → re-scan/backtest to see the effect.

## 5. Screen-by-screen wireframes

Each screen lists the **data it reads** (✓ endpoint exists, ✚ to add) and its **key keys**.

### 1–2 · Scan + Candidates (one screen, master-detail)

Scanning produces the ranked candidate set; "reviewing candidates" is the inspector.

```
┌ SCAN ───────────────────────────────────────────────┬ ⊙ AAPL · Apple · Technology ─────────┐
│ [Run scan ⏎]  universe SP500 ▾   /filter: passed,HR  │ Score 0.92  Rank 1   ⚑ HOME RUN       │
│ 412 scanned · 38 passed · 6 home-run · 09:32         │ Px 232.10  RVol 2.4x  ΔATH 0.0%  ATR 4.1│
│ #  Sym   Score   RVol  ΔATH   Sector   Reg  ⚑        │ 20d ▁▂▃▅▆█  · 50/200MA ▲              │
│ 1  AAPL  0.92 █▉ 2.4x  0.0%   Tech     ▲    HR       │ ─────────────────────────────────────│
│ 2  NVDA  0.89 █▊ 3.1x −1.2%   Tech     ▲    HR       │ Conviction   84  HIGH      → 3        │
│ 3  AVGO  0.86 █▋ 1.9x −0.4%   Tech     ▲    EN       │ Opportunity  HOME RUN  (rare)        │
│ 4  LLY   0.84 █▋ 2.2x  0.0%   Health   ▲    HR       │ Instrument   ATM Calls  ~0.50Δ 30d   │
│ 5  ...   (virtualized; j/k move · ⏎ drill · s star)  │ Risk budget  3.0%  $3,000  heat→4.0% │
│                                                      │ Analogs      n=24  exp 0.78R  PF 2.1 │
│ filter chips: [passed] [home-run] [sector:Tech] [+]  │ [3 Conviction] [4 Analogs] [5 BT] [7 ▸Paper]│
└──────────────────────────────────────────────────────┴──────────────────────────────────────┘
```
**Reads:** `GET /universe/scans` ✓ · candidate aggregate `GET /candidates/{sym}` ✚
(folds conviction/opportunity/instrument/risk/analogs into one call).
**Keys:** `r` run scan · `j/k` move · `⏎` drill conviction · `s/x` star/dismiss · `/` filter · `3‥7` send symbol to stage.

### 3 · Conviction (why this candidate, 8 inputs)

```
┌ CONVICTION · AAPL ───────────────────────────────────────────  config v1·a1b2c3 ─┐
│ 84 / 100   HIGH    ████████████████████░░░░░                                       │
│ Input               norm   wt    contrib   ▕ contribution                          │
│ Market regime       1.00   .18    15.1     ▕███████████████                        │
│ Momentum            0.95   .18    14.3     ▕██████████████▎                        │
│ Distance to ATH     1.00   .10     7.6     ▕███████▌                               │
│ Sector strength     0.80   .12     7.6     ▕███████▌                               │
│ Historical analogs  0.78   .10     6.0     ▕██████      n=24  → 4                   │
│ Relative volume     0.70   .10     5.0     ▕█████                                   │
│ Trend strength      0.62   .12     4.6     ▕████▌                                   │
│ Breadth             0.55   .10     3.9     ▕███▉                                    │
│ ───────────────────────────────────────────────────────────────────               │
│ Opportunity HOME RUN · Instrument ATM Calls · Risk 3.0% $3,000 (heat 1.0%→4.0%)     │
│ [4 Review analogs ⏎]   [5 Backtest this setup]   [7 Queue to paper]                 │
└────────────────────────────────────────────────────────────────────────────────────┘
```
**Reads:** `GET /conviction?symbol=&run_id=` ✚ (from `conviction_scores`); opportunity
`GET /opportunity?symbol=` ✚; instrument+budget from the aggregate. **Keys:** `4/5/7`, `c` copy breakdown.

### 4 · Historical Analogs (did setups like this pay off?)

```
┌ ANALOGS · AAPL setup ─────────────────────────────────────────────────────────────┐
│ Match  regime=bull · sector=Tech · new ATH · RVol≥2          n = 24 closed analogs  │
│ Expectancy 0.78R   Win 46%   AvgWin 2.9R   AvgLoss −0.9R   PF 2.1   Best 7.4R        │
│ R distribution  −1│▁▂  0│▃  +1│███  +2│██▌  +3│█▌  +5│▍  +7│▏                        │
│ Date     Sym   R      Hold  Exit          MFE    MAE   Regime  ▕ replay              │
│ 2023-07  NVDA  +7.4   41d   trail stop    +8.1   −0.4  bull    ▕ 6 ⏎                  │
│ 2023-11  MSFT  +3.2   18d   trail stop    +3.8   −0.6  bull    ▕ 6 ⏎                  │
│ 2024-02  AVGO  +1.1    9d   trail stop    +1.6   −0.7  bull    ▕ 6 ⏎                  │
│ 2023-03  AAPL  −0.9    4d   initial stop  +0.3   −1.0  neutral ▕ 6 ⏎                  │
│ …(j/k · ⏎ → replay)                                                                  │
└────────────────────────────────────────────────────────────────────────────────────┘
```
**Reads:** `GET /analogs?symbol=&regime=&sector=&run_id=` ✚ (the `SimilarSetupAnalyzer`
over `trades`). **Keys:** `j/k`, `⏎` open replay, `b` backtest the cohort.

### 5 · Backtest (configure ▸ run ▸ results)

```
┌ BACKTEST ─────────────────────────────────┬ RESULTS · bt-0912 ────────────────────────┐
│ Strategy  momentum-breakout ▾              │ Equity ▁▂▃▄▆▇█  +42.3%   CAGR 18%  Sharpe 1.4│
│ Universe  SP500 ▾   2018-01 ▸ 2024-06      │ MaxDD −14%  Calmar 1.3  PF 2.0  Exp 0.55R    │
│ Configs   risk▾ scanner▾ regime▾ budget▾   │ Trades 214  Win 41%  AvgWin 3.1R  Tail 1.8   │
│ Seed 7   Slippage on   Costs on            │  equity ╭────────────╮  drawdown ▔▁▁▂▁      │
│ [Run ⏎]   last 4.2s   ░░░░░░ (when running)│        ╱   ╲╱╲   ╱╲ ╱                        │
│ Recent runs                                │  ─ trades ───────────────────────────────   │
│  ● bt-0912  +42%  Sh1.4   ⏎                 │  Date    Sym   R     Hold  Exit   ▕ replay   │
│  ○ bt-0908  +31%  Sh1.1   ⏎  (compare ⌥⏎)   │  2024-05 NVDA  +5.1  33d  trail   ▕ 6 ⏎       │
│  ○ bt-0901  +28%  Sh1.0   ⏎                 │  2024-04 LLY   −1.0   3d  stop    ▕ 6 ⏎       │
└────────────────────────────────────────────┴────────────────────────────────────────────┘
```
**Reads:** `GET /backtests` ✓(optimizations) + `GET /backtests/{id}` ✚ (equity+trades);
**run** `POST /backtests/run` ✚ (command, streamed progress). **Keys:** `r` run, `⌥⏎` compare, `⏎` drill trade → replay.

### 6 · Trade Replay (bar-by-bar study)

```
┌ REPLAY · NVDA · 2023-07 · +7.4R ──────────────────────────────────────────────────┐
│ ◀◀ ◀ ⏯ ▶ ▶▶   bar 23/41 · 2023-07-24   space play · ←/→ step · r reset · x exit    │
│  248 ┤                              ▲entry        ◆exit                             │
│      │                 ╭─╮     ╭───╮│      ╭──╮  ╱                                   │
│      │      ╭──╮  ╭───╯ ╰─────╯   ╰╯ ╲────╯  ╰─╱   ┈┈┈ stop (trailing)              │
│  232 ┤ ╭───╯  ╰──╯                                                                  │
│      └────────────────────────────●──────────────────────  MFE +8.1R  MAE −0.4R     │
│ @bar 23  Px 246.0  R +4.2  stop 238.0 (−3.0R)  RVol 2.1x  regime bull               │
│ Decisions  d0 entry(20d breakout+ATH)  d6 stop→BE  d12 trail  d41 exit(trail)        │
│ Entry context  Conviction 81 · Opportunity HOME RUN · Instrument ATM Call            │
└────────────────────────────────────────────────────────────────────────────────────┘
```
**Reads:** `GET /trades/{id}/replay` ✚ (bars from `bars` + decision events/MFE/MAE from
`trades`). **Keys:** `space` play/pause · `←/→` step · `r` reset · `[ ]` prev/next trade.

### 7 · Paper Trading (candidate ▸ order ▸ position)

```
┌ PAPER ─────────────────────────────────────────────────────────────────────────────┐
│ Equity $103,240  +0.4% day   Heat 2.4%/5% ▕█████▌            Open 4  Pending 1        │
│ Queue (from shortlist)                                                                │
│  Sym   Conv  Opp      Instrument   Risk$   Stop    Size    ▕ stage  skip               │
│  AAPL  84    HOMERUN  ATM Call     3,000   46.25   2 cts   ▕ ⏎      x                   │
│ Open positions                                                                        │
│  Sym   Side  Qty  Entry   Px      R     P&L      Stop    Age  ▕ replay  close          │
│  TSLA  long  200  240.10  248.30  +1.1  +1,640   232.00  6d   ▕ 6      X               │
│  MSFT  long  120  410.00  402.10  −0.4   −948    396.00  2d   ▕ 6      X               │
│ Orders today  filled 2 · working 1 · rejected 0     ⤳ blotter                         │
└────────────────────────────────────────────────────────────────────────────────────┘
```
**Reads:** `GET /paper/positions|orders` ✚; **act:** `POST /paper/orders` ✚ (sized by the
risk-budget engine). **Keys:** `⏎` stage order · `x` skip · `X` close position · `6` replay.

### 8 · Live Execution (gated)

Identical layout to Paper, but **locked behind a deliberate enablement gate** —
broker connect, typed `ENABLE LIVE` confirmation, a visible kill-switch, and a
hard portfolio-heat ceiling. Shown as `8 Live 🔒` until enabled; the context-bar
toggle flips `◌ LIVE → ● LIVE` only after the gate. Every live order still passes the
same risk gateway as paper.

### Utilities

- **◷ Portfolio** — equity curve, exposure/heat gauges, positions, risk metrics (`/portfolio`, `/risk/metrics` ✓).
- **Σ Analytics** — research metrics: expectancy, profit factor, win/loss R, tail ratio, attribution by regime/sector (`/performance` ✓, attribution ✚).
- **⚙ Settings** — config editor: pick a config, edit YAML with schema validation, save (`/settings/config` ✓ read; `POST` ✚ write).

## 6. Design system (dark, dense)

- **Palette:** surface `#0b1220` / raised `#131c2e` / border `#1f2a3d`; text slate-200;
  semantic only — bull `#22c55e`, bear `#ef4444`, neutral `#eab308`, accent `#3b82f6`,
  conviction bands LOW→EXTREME on a blue→violet ramp.
- **Type:** UI sans; **all numbers tabular/monospace** (`font-variant-numeric: tabular-nums`)
  so columns align and scan fast.
- **Tables:** 28px rows, sticky header, right-aligned numerics, inline micro-bars/sparklines,
  `j/k` cursor row, `⏎` drill; **virtualized** (handle 5k+ rows at 60fps).
- **Density:** 12–13px base, 4/8px spacing grid, 1px borders, no card shadows, no hero sections.
- **Charts:** lightweight canvas (uPlot-class) for equity/price/replay — fast, minimal, dark.
- **Motion:** ≤120ms; used only for stage transitions and play/step in replay.

## 7. From the current scaffold → this IA

| Old (generic dashboards) | New (workflow stages) |
|---|---|
| Dashboard | folded into the **context bar** + Scan as the landing stage |
| Scanner | **1–2 Scan + Candidates** (master-detail with the aggregate inspector) |
| Market Regime | **context-bar badge** + a Portfolio/Analytics detail (not a top-level stop) |
| Trade Journal | **6 Replay** list + **Σ Analytics** |
| Backtesting | **5 Backtest** (configure ▸ run ▸ results, with compare) |
| Analytics | **Σ Analytics** utility + inline in Backtest results |
| Portfolio | **◷ Portfolio** utility + Paper/Live header |
| Settings | **⚙ Settings** utility (editable) |
| *(new)* | **3 Conviction, 4 Analogs, 6 Replay, 7 Paper, 8 Live** |

Reused unchanged: the Electron shell, the FastAPI sidecar, the typed client, the table/
format primitives. What changes is the **information architecture** (workflow spine + persistent
context + command palette) and the **density/keyboard** layer.

## 8. API surface this implies

Existing ✓: `/universe/scans`, `/trades`, `/regimes`, `/portfolio`, `/risk/metrics`,
`/backtests`, `/performance`, `/settings/config`, `/dashboard`.

To add ✚ (mostly thin reads over existing repositories, plus Phase-3 commands):
`GET /candidates/{symbol}` (aggregate) · `GET /conviction` · `GET /opportunity` ·
`GET /analogs` · `GET /backtests/{id}` · `GET /trades/{id}/replay` ·
`GET /paper/positions|orders` · `POST /scans/run` · `POST /backtests/run` ·
`POST /paper/orders` · `POST /settings/config/{name}` · live-enable command.

## 9. Build order (after this design is approved — no code yet)

1. **Shell & IA:** context bar (run + regime + ⌘K + paper/live), workflow rail, status bar, command palette, global keymap, persistent symbol/run store.
2. **Stages 1–4 (read-only research):** Scan+Candidates with the aggregate inspector, Conviction, Analogs — the core daily loop.
3. **Stages 5–6:** Backtest (run + results + compare) and Replay.
4. **Stages 7–8:** Paper (command endpoints, blotter), then the gated Live surface.
5. **Utilities & polish:** Portfolio, Analytics, editable Settings; virtualization, prefetch, charts, shortcuts overlay.

---
**Next:** review these flows/wireframes. On approval I'll implement in the order above,
starting with the shell + the Scan→Conviction→Analogs loop (Stage 1–4).
