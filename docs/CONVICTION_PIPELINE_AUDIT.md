# Conviction Pipeline Audit (read-only — no fixes)

**Symptoms:** scan succeeds & shows live candidates, but Watchlists say *"No live
conviction data available,"* and the Conviction / Analogs / Trade-Plan panels are blank.

**Method:** the real pipeline run offline (`scratchpad/conv_audit.py`, `stale_probe.py`):
fresh-data scan and stale-data scan, then every read probed for row counts.

## Reproduced facts

| Read | Fresh scan (newest bar = today) | Stale scan (newest bar = 10d old) |
|---|---|---|
| `scan_results` (candidates) | **38** | 39 |
| `conviction_scores` | **38** | **0 (skipped)** |
| `GET /conviction` | 38 | **0** |
| Analogs (`sample_size`) | **0** | 0 |
| `GET /tradeplan` | PLAN | PLAN (conviction=None) |
| `GET /watchlists` | 30 | **0** |

## Per-stage trace

| Stage | Function | In rows | Out rows | Table | run_id | Exists after scan? | UI same run? | Broken? | Root cause |
|---|---|---|---|---|---|---|---|---|---|
| Candidate Gen | `scanner.scan` → `.candidates` | 96 bars | 38 | `scan_results` | `scan-<bar date>` | ✅ | ✅ | ✅ | — |
| **Conviction Engine** | `ConvictionEngine.score` (per candidate) | 38 | 38 / **0** | — | `scan-…` | fresh ✅ / **stale ❌** | — | **❌ when stale** | `run_scan` gates conviction behind `if not stale:` (`actions.py:274`) — a stale pull skips it entirely |
| Conviction Persistence | `session.add_all(conviction_rows)` | 38 | 38 / 0 | `conviction_scores` | `scan-…` | fresh ✅ | ✅ (`resolve_active_run_id`) | ✅ fresh | — |
| Regime | `RegimeEngine.evaluate` | 1 | 1 | `market_regimes` | `scan-…` / `v1` | ✅ | ✅ | ✅ | — |
| **Analogs Generation** | `services.analogs` / `tradeplan._analog_stats` | trades for `scan-…` = **0** | sample_size **0** | **none** | n/a | **❌** | n/a | **❌ always** | cohort = `TradeRepository.closed(run_id=scan-…)` — a scan run has **no trades**; analogs are also **never persisted** (no table) |
| Watchlist Generation | `watchlist_service.generate_watchlists` | 38 conv | 30 / **0** | `watchlist_entries` | `scan-…` | fresh ✅ / stale ❌ | ✅ | ✅ fresh | empty when conviction is empty (stale) |
| **Trade Plan Generation** | `tradeplan_service.trade_plan` (on-demand) | scan price+ATR | 1 plan | **none** | n/a | computed, **not persisted** | n/a | **⚠️ partial** | works on-demand from scan price/ATR, but **no `trade_plans` table** — cannot be queried as rows or share the run_id |
| UI Rendering | `candidate_detail` / panels | — | — | — | resolves to live run | — | ✅ | ✅ | reads pin to the live run (prior fix) |

## First point where live candidate data stops flowing

There are **two** break points, depending on data freshness:

1. **Stale path → the Conviction Engine stage (first break).** `run_scan` skips conviction
   when the pull is flagged stale (`actions.py:270-274`, `if not stale:`). Conviction = 0 →
   watchlists empty → Conviction/Analogs panels blank. This single gate reproduces **every
   reported symptom at once**, so if the user's Yahoo data is >4 days old (or the
   `MRP_STALE_AFTER_MINUTES` threshold is tight) this is the cause.

2. **Fresh path → the Analogs Generation stage.** Even with conviction flowing, analogs are
   **structurally empty**: the cohort is drawn from `closed(run_id=scan-…)` — closed *trades*
   tagged with the scan's run_id — but a scan produces **no trades**, so `sample_size` is
   always 0. Analogs and Trade Plans are additionally **never persisted** (no tables), so they
   can neither share the scan `run_id` nor be returned as rows.

### Root causes (summary)
- **Stale gate** halts the whole conviction → watchlist → panel chain.
- **Analog cohort is scoped to the scan run_id** (which has no trades) instead of all
  historical trades; and **analogs + trade plans have no persistence**, so the "after a scan
  there should be analog/trade-plan rows" expectation can never hold.
- Conviction, regime and watchlists themselves persist correctly under one run_id (prior fix).

The follow-up task adds analog + trade-plan persistence (sharing the scan run_id), points the
analog cohort at historical trades, and verifies every screen populates from one scan.
