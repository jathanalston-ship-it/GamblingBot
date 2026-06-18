# CLAUDE.md — guidance for Claude Code in this repository

## ⚠️ Push policy — READ FIRST

**`claude/vigilant-wozniak-oueczq` is the ONLY branch you may push to.**

- All development, commits, and pushes go to **`claude/vigilant-wozniak-oueczq`**.
- Do **not** push to any other branch (including `main`/`master` or any other
  `claude/*` branch) without explicit, in-session permission from the user.
- Always push with `git push -u origin claude/vigilant-wozniak-oueczq`.
- Do **not** open a pull request unless the user explicitly asks for one.

This is the single source of truth for the push target; if other instructions
disagree, this branch wins unless the user says otherwise in the session.

## Project

Momentum Research Platform (MRP) — a systematic momentum-breakout research &
trading platform for US equities. Python 3.12, strictly typed. See
`README.md` and `docs/ARCHITECTURE.md` for the full design.

## Layout

`src/momentum/` holds the package (`core`, `data`, `universe`, `signals`,
`risk`, `portfolio`, `execution`, `backtest`, `analytics`, `reporting`,
`persistence`, `api`, `orchestration`, `cli`). Tests live in `tests/`
(`unit/`, `integration/`, `fixtures/`). Tunables are YAML in `config/`.

### Implemented so far

- **Market data layer** (`src/momentum/data/`) — Alpaca/Polygon/Yahoo providers
  behind one interface, parquet cache, ingestion, validation, calendar. See the
  canonical OHLCV contract in `data/schema.py`.
- **Market regime engine** (`src/momentum/signals/regime.py`) — Bullish/Neutral/
  Bearish classification. See `docs/REGIME_ENGINE.md`.
- **Momentum scanner** (`src/momentum/universe/`) — screens & ranks the universe
  by a momentum score; indicators in `signals/indicators.py` &
  `signals/momentum.py`; results persist to `scan_results` (migration `0002`).
  See `docs/SCANNER.md`.
- **Risk engine** (`src/momentum/risk/`) — the gateway (`risk_manager.py`) sizes,
  stops and vets every trade (position size, stops, heat, exposure, correlation,
  drawdown/regime throttle, circuit breakers). See `docs/RISK_MANAGEMENT.md`.
- **Analytics** (`src/momentum/analytics/`) — performance & trade metrics built
  around the positive-skew objective (expectancy, profit factor, avg/largest
  winner, trend capture); win rate is reported, never targeted. See
  `docs/ANALYTICS.md`.
- **Backtester** (`src/momentum/backtest/`) — event-driven, no look-ahead
  (next-bar-open fills + truncated history, with proof tests), commissions,
  slippage, gap-aware stops; cost models in `execution/slippage.py`; time
  boundary in `core/clock.py`. See `docs/BACKTESTING.md`.
- **Trade intelligence DB** (`trades` table + migration `0003`) — per-trade
  entry/exit, holding time, MFE/MAE, sector, volume, relative volume, regime,
  entry/exit reasons; attribution (`analytics/attribution.py`), SQL
  (`analytics/queries.py`, `sql/trade_intelligence.sql`) and markdown dashboards
  (`analytics/dashboard.py`). See `docs/TRADE_INTELLIGENCE.md`.

## Philosophy (what we optimise for)

Optimise for **expectancy, profit factor, average winner, largest winner, trend
capture** — a positive-skew payoff. Do **not** maximise win rate or trade count.
Low win rates, long holds and large winner/loser asymmetry are accepted by
design; win rate / trade count / holding time are diagnostics only.

Most other modules under `src/momentum/` remain documented stubs.

## Commands

```bash
make install                       # runtime + dev deps, editable install
make test            # or: PYTHONPATH=src python -m pytest tests
make lint            # ruff check + mypy --strict
make format                        # ruff format
```

## Conventions

- Match the surrounding code: strict typing (`mypy --strict`), ruff
  (line length 100), `from __future__ import annotations`.
- The data layer is DataFrame-centric on the canonical OHLCV schema; reuse
  `normalize_bars` / `Timeframe` rather than re-inventing bar handling.
- Configuration is immutable Pydantic loaded from `config/*.yaml`; add tunables
  there, not as hard-coded constants.
- Keep vendor/broker/DB access behind interfaces — never import a concrete
  vendor outside its adapter.
