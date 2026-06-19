# Momentum Lab — Product Review & Prioritized Roadmap

A PM / quant-trader / UX review of the whole platform, judged against the bar that
matters: **a trader using it daily with real money**, and a software company **preparing
for public release**. No code — findings and a prioritized roadmap.

---

## 0. Executive summary (the headline)

**Momentum Lab is an excellent research and decision-support engine with no execution
layer, no operational safety net, and a large gap between its documented vision and its
usable product.** It can *find and reason about* trades superbly; it cannot yet *place,
manage, or survive* a real-money trading day.

Three structural facts drive everything below (verified in the codebase):

| Reality | Evidence | Consequence for real money |
|---|---|---|
| **Decision engines are built & tested** | data, scanner, regime, **risk (14 modules)**, conviction, opportunity, instruments, analytics, backtester — 614 passing tests | The hard quant work is done and trustworthy |
| **The execution half does not exist** | `execution/` 8/8 stub · `portfolio/` 5/5 stub · `orchestration/` 3/3 stub · `cli/` stub · **API is read-only** | You cannot place an order, manage a position, or run the daily loop |
| **The safety net is design-only** | `core/logging` stub · `persistence/audit` stub · backups/integrity/recovery are *docs* (SYSTEM_LOGGING.md) | No audit trail, backups, or crash recovery for real money |

Plus: the rich workflows (Trade Replay, Conviction Analysis, Strategy/Simulation Labs) are
**wireframes, not software**; options recommendations use **simplified pricing**, not a real
chain; and data is **end-of-day**, not real-time.

**One-line verdict:** *Not releasable for real-money daily use today.* The path to release
is **narrow and deep, not broad** — build one reliable loop (shares, paper→gated-live) with
a real safety net, and defer the labs.

---

## 1. Current-state map (built · designed · stubbed)

| Capability | State |
|---|---|
| Market data (EOD, cached, validated) | ✅ built |
| Universe / momentum scanner | ✅ built |
| Regime, conviction, opportunity, risk, instruments engines | ✅ built |
| Backtester (event-driven, no-look-ahead) + analytics | ✅ built |
| Read-only API + desktop shell (8 views) | ✅ built (read-only) |
| **Order execution / broker / fills / OMS** | ⛔ stub |
| **Live portfolio / position management** | ⛔ stub |
| **Orchestration (run the daily pipeline)** | ⛔ stub |
| **Real-time / streaming data** | ⛔ absent |
| **Logging / audit / backups / integrity / crash recovery** | 📐 designed only |
| **Trade Replay / Conviction Analysis / Strategy & Simulation Labs UI** | 📐 wireframed only |
| Deployment / installer / auto-update / signing | 📐 designed only |
| Options pricing / chain / greeks | ⚠️ simplified approximations |

---

## 2. Missing features

- **Execution path (the #1 gap):** broker integration (even Alpaca paper), an order
  management system, fills, partial fills, cancels, time-in-force, and **reconciliation of
  internal state against the broker's truth**. Today nothing leaves the app.
- **Real-time data:** streaming quotes, last price, intraday bars, halts. The data layer is
  batch/EOD — fine for research, unusable for *managing* a live position.
- **Live risk & a kill switch:** real-time portfolio heat/exposure/correlation monitoring,
  circuit breakers acting on the **live** account, and an **emergency "flatten everything"**
  control. The risk engine sizes at entry but does not yet *govern a live book*.
- **Alerts & notifications delivered out of the app:** stop hit, +1R/breakeven, conviction
  change, **data outage** — via desktop/OS push (and optionally mobile/email). In-app-only
  alerts are useless when the window is closed.
- **Position management actions:** adjust/trail stop, scale in/out, exit — from the UI,
  written through the risk gateway.
- **Account & P&L reconciliation, statements, tax/export** (CSV/1099-ready), broker
  statement import.
- **Research journaling / notes** (the Obsidian layer) — per-trade thesis, tags, links — is
  designed but not built; today there is nowhere to record *why*.
- **Onboarding:** first-run setup, sample dataset, guided "scan → paper trade", and the legal
  disclaimers a trading product must ship with.
- **Settings/config UI** with validation, versioning and diffs (config is YAML on disk).

## 3. Missing workflows

- **The end-to-end loop is not wired.** Each engine works in isolation; `orchestration/` is
  stub, so there is no "run today's scan → score → size → recommend → stage" flow, and no
  scheduler. A trader must currently invoke pieces by hand/tests.
- **No paper-trading loop**, so no way to accrue a track record before risking money — the
  single most important pre-release workflow for a trading product.
- **No live-management loop:** intraday monitoring, stop updates, alert→action.
- **No "act" path in the app:** the API is read-only; the UI can display but not *do*
  (no `POST /scan`, `/orders`, `/backtests/run`). The wireframes assume actions that don't exist.
- **No data-refresh / ingest workflow in-app**, no data-health view — the user can't tell if
  prices are stale.
- **No close-the-loop review workflow built:** Trade Replay + journaling + attribution exist
  as design/analytics but aren't a usable post-trade ritual yet.

## 4. UX bottlenecks

- **Design ↔ build gap is the dominant UX risk:** five rich workflows are documented and will
  be *expected* by anyone who reads the app's own vision, but only 8 read-only views exist. A
  daily user hits dead ends.
- **Two competing UX specs** (`DESKTOP_UX.md` workflow-spine vs `APP_WIREFRAMES.md` atlas) —
  must be merged to one canonical IA before build, or the product will feel incoherent.
- **Density/keyboard learning curve:** the Bloomberg-dense, keyboard-first model is fast for
  experts and steep for everyone else; no onboarding, shortcut discovery, or "calm mode" yet.
- **Blocking long operations:** backtests/Monte-Carlo with no async job model (designed, not
  built) will freeze the UI; no progress, no cancel.
- **Empty/error/stale states** are unspecified — first run, no data, feed down, broker
  disconnected. These are where trust is won or lost.
- **No undo / confirm discipline** around money actions (once execution exists).

## 5. Operational risks (the scary ones for real money)

- **No audit trail of decisions/orders** (designed, not built). For real money this is
  table-stakes and a compliance must.
- **No automatic backups, no integrity checks, no crash recovery** (all designed only). A
  corrupt or lost SQLite file = lost book/history.
- **Secrets handling:** broker/data API keys — storage, encryption at rest, never-in-logs —
  is unspecified in the running code.
- **Unsigned, un-pipelined distribution:** DEPLOYMENT.md is a design; today there is no
  signed installer or auto-update, so no safe way to ship fixes.
- **Stale-data-drives-live-decisions:** with EOD data and no health gating, a live decision
  could run on yesterday's prices.
- **Clock/timezone correctness** for entries/stops/sessions in live; **no reconciliation** so
  internal vs broker state can silently diverge.
- **Single local node:** no failover; if the machine dies mid-session, open risk is unmanaged.

## 6. Research limitations (quant lens)

- **Overfitting is too easy:** Strategy/Simulation Labs invite parameter mining; walk-forward
  / out-of-sample exists in the backtester but is **not enforced or surfaced** as the default,
  and there's no deflated-Sharpe / multiple-testing correction.
- **Options modeling is not execution-grade:** structures use **approximate premiums**
  (`_atm_premium`/`_call_premium`), no live chain, greeks, skew, assignment or early-exercise
  — fine for sizing intuition, **wrong for real options trades**.
- **No live track record / forward validation:** conviction and regime scores are unproven
  out-of-sample on real fills; their predictive value is asserted, not measured.
- **Cost/slippage realism:** modeled slippage isn't calibrated against realized fills (there
  are none yet); options/illiquid costs especially.
- **Survivorship & point-in-time:** the universe must be verified bias-free with real
  delisting data and **point-in-time corporate actions in the live path**, not just backtest.
- **Small-sample fragility:** conviction's historical-similarity and many metrics get noisy on
  thin samples; surfaced as caveats but easy to over-trust.

## 7. Scalability issues

- **SQLite single-file** is great for one local user but caps concurrency, DB size, and any
  future multi-user/cloud story (the persistence layer is swappable to Postgres — use it when
  needed).
- **Full-universe scan & multi-year/multi-symbol backtests** performance is unproven at scale;
  no incremental/parallel compute or caching strategy stated.
- **No job queue:** long backtests/sims block; concurrent runs and cancellation aren't modeled.
- **Big result sets** (scans, trades, audit log) need pagination/virtualization and an
  archival/retention plan (the audit log especially will grow without bound).
- **Single-user, single-machine** by construction — no sync, no multi-device, no team.

## 8. Likely user frustration

- **"The docs promise features the app doesn't have."** The biggest trust hit.
- **Manual everything:** no scheduler/orchestration → the daily loop is hand-cranked.
- **Can't act in the app** (read-only) — display without do is frustrating fast.
- **Long operations freeze the UI**; no progress/cancel.
- **Steep keyboard density** with no onboarding.
- **Options recommendations that can't be traded** (no chain/execution) feel like a tease.
- **No notes/journal** — research evaporates after the trade.
- **Config by YAML file**, validation errors surfaced poorly.

---

## 9. Prioritized roadmap

Framed as a release company would: **MUST = release-gating for real-money daily use; SHOULD
= makes it genuinely good (fast-follow); NICE = differentiation/vision.** Each item names the
risk it retires.

### 🟥 MUST HAVE — v1.0 (release-gating)

> Theme: **make one narrow loop real and safe.** Recommend scoping v1.0 to **shares-only,
> paper-first, single account.**

| # | Item | Retires |
|---|---|---|
| M1 | **Execution layer**: broker adapter (Alpaca **paper** first), OMS, fills, cancels, TIF | §2 #1 missing feature |
| M2 | **Broker/account reconciliation** + authoritative position & P&L from the broker | §5 state divergence |
| M3 | **Real-time data** (streaming quotes + intraday bars) **with a data-health gate** that blocks decisions on stale data | §2, §5 stale-data |
| M4 | **Build the safety net** (implement SYSTEM_LOGGING design): structured logs, **append-only audit of every decision/order**, automatic backups, integrity checks, crash recovery | §5 operational |
| M5 | **Live risk governance + kill switch**: real-time heat/exposure/correlation, circuit breakers on the live book, **emergency flatten** | §2, §5 |
| M6 | **Alerts delivered out-of-app** (OS/desktop push): stop, +1R, conviction change, **feed/broker outage** | §2 |
| M7 | **Wire the daily loop** (`orchestration` + action API: `POST /scan|/orders|/backtests/run`) and **build the core UI spine** (Scanner→Symbol→Conviction→Size→Order→Portfolio→Journal) | §3, §4 |
| M8 | **One canonical UX/IA** (merge DESKTOP_UX + APP_WIREFRAMES) + **first-run onboarding, sample data, disclaimers** | §4 |
| M9 | **Secrets management + signed installer + auto-update** (implement DEPLOYMENT design) | §5 distribution/secrets |
| M10 | **Scope options to research-only for v1** (shares-only execution) until a real chain/greeks/exec exists — *or* integrate one (larger) | §6 options realism |

### 🟧 SHOULD HAVE — v1.x (fast-follow)

| Item | Retires |
|---|---|
| **Gated small live trading** after a sustained paper track record (promotion workflow) | §3 |
| **Build the research workflows for real**: Trade Replay, Conviction Analysis, Strategy & Simulation Labs (currently wireframes) | §4 design-gap |
| **Research journal / notes** (per-trade thesis + tags + links) — the Obsidian layer, basic first | §2, §8 |
| **Enforce & surface walk-forward / OOS** as the default; add overfitting guardrails (deflated Sharpe, trade-count significance) | §6 |
| **Async job queue** for backtests/sims (progress, cancel, non-blocking) | §4, §7 |
| **Slippage/cost calibration vs realized fills**; per-broker commission models | §6 |
| **Position-management actions** (trail/scale/exit) through the risk gateway | §3 |
| **Settings/config UI** with validation + versioning/diff; **data-health dashboard** | §4, §8 |
| **Telemetry + crash reporting** (opt-in) and support tooling | §5 release-ops |
| **Reporting/export** (performance, tax/statement reconciliation) | §2 |
| **Empty/error/stale-state design** across the app | §4 |

### 🟩 NICE TO HAVE — v2+ (differentiation / vision)

| Item |
|---|
| Full **Obsidian knowledge graph** (linked notes, backlinks, graph view, daily/weekly notes) |
| **Mobile companion** + push notifications; **cloud sync / multi-device / cloud backup** |
| **Postgres / multi-user / team** edition (the persistence layer already allows it) |
| **Execution-grade options** (live chain, vol surface, greeks dashboard, assignment handling) |
| More **instruments & vendors** (futures, crypto; multiple data providers with failover) |
| **AI-assisted research summaries** (carefully, never in the decision path) |
| **Strategy/research sharing or marketplace**; reproducibility browser over `runs` |
| **Calm mode / theming / accessibility**; deeper keyboard customization |

---

## 10. Release-readiness gate (what a software company should require before GA)

- [ ] A trader can go **install → onboard → scan → paper-trade → manage → review** with no docs.
- [ ] **End-to-end paper trading** reconciled against a broker, run daily for weeks, stable.
- [ ] **Audit trail, automatic backups, integrity checks, crash recovery** implemented and tested.
- [ ] **Kill switch / emergency flatten** verified; circuit breakers act on the live book.
- [ ] **Real-time data with a stale-data gate**; graceful feed/broker outage handling.
- [ ] **Signed installer + auto-update**; secrets encrypted at rest, never logged.
- [ ] **One coherent UX**; empty/error/stale states designed; long ops async with cancel.
- [ ] **Legal:** risk disclaimers, "not financial advice", data-vendor & broker ToS/licensing.
- [ ] **Support/observability:** opt-in telemetry, crash reporting, a way to get logs for support.
- [ ] **Options either execution-grade or clearly research-only** in the product, not implied tradeable.

---

## 11. The one recommendation that matters

**Trade breadth for depth.** The platform's risk is not capability — it's that ~70% of the
surface is design docs and isolated engines while the daily-usable, real-money product is
~0% (no execution, no safety net, read-only UI). A release company should **freeze new
engines/labs** and converge every effort on a single, reliable, auditable loop:

> **Scanner → Conviction → Risk-sized order → Paper execution (reconciled) → live risk +
> alerts → Journal/Replay review** — shares-only, with backups/audit/recovery — then gate a
> small live rollout.

Ship that narrow loop rock-solid, earn a paper track record, and *then* light up the labs and
options. Everything in §9-Should/Nice is valuable; none of it matters until the core loop is
real, safe, and trusted with money.
