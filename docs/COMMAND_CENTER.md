# Market Command Center

The **default landing page** — one read-only screen that answers "what does the
market look like and where should I focus today?" by aggregating every subsystem.

## Panels

| Panel | Source |
|---|---|
| Current Market Regime | `signals/regime` (`/regimes/latest`) |
| Top 5 Daily / Weekly / Monthly Opportunities | the multi-horizon watchlists (top 5 each) |
| Highest Conviction Setup | the conviction score with the max score |
| Best Risk/Reward Setup | the watchlist entry with the max reward:risk |
| Most Attractive Sector | highest average conviction across current candidates (≥2 names preferred) |
| Portfolio Heat | latest `portfolio_snapshots` (heat + equity + daily P&L) |
| Recent Performance | trade stats (expectancy R, profit factor, win rate, net P&L) |
| Watchlist Changes | diff of the two most recent **daily** watchlist generations |
| Recently Triggered Setups | setups currently in the lifecycle `Triggered` state |

## Implementation

A single aggregate endpoint, `GET /command-center` (`api/command_center.py`),
**reuses the existing service layer** — regime, `watchlist_service`,
`lifecycle_service`, conviction/scan queries, the portfolio snapshot and
`performance_summary` — so it owns **no new persistence**. Non-finite metrics are
already sanitised upstream, so the payload is always strict-valid JSON.

The desktop **Command Center** view (`views/CommandCenter.tsx`) is the index
route (and a `◎ Command` entry at the top of the nav rail). Every symbol is
click-through: opportunities and Best-R/R jump to the **Trade Plan**, Highest
Conviction to **Conviction**, triggered setups to **Lifecycle** — carrying the
selected symbol through the workspace.
