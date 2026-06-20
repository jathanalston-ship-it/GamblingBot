# Editable Data-Provider Settings

The Settings screen lets you choose the **market-data provider** and enter its
**API keys** from the UI — no file editing. Scans and backtests use the selected
provider.

## What you can set

| Provider | Keys required | Notes |
|---|---|---|
| **Yahoo Finance** (`yfinance`) | none | Zero-setup default; rate-limited, unofficial. |
| **Alpaca** (`alpaca`) | `ALPACA_API_KEY`, `ALPACA_API_SECRET` | |
| **Polygon** (`polygon`) | `POLYGON_API_KEY` | |

## Where it's stored

Two stores live in a per-user **writable** directory (`MRP_USER_DIR`; the desktop
app points this at `%APPDATA%\Momentum Lab\`):

- `settings.yaml` — the non-secret `data.provider` choice (merged, other keys kept).
- `.env` — the API-key **secrets**.

Secrets are **never returned** by the API in plain text — the UI only learns
whether each key *is set*. A blank key field on save **keeps** the existing
secret (so you don't have to retype it).

## How it takes effect

- On **save** (`PUT /settings/data-provider`) the new secrets are written to
  `.env` *and* pushed into the running backend's environment, so the next scan
  authenticates immediately.
- On **startup** the backend loads `.env` (`load_user_env`) before building any
  provider, so the selection persists across restarts.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/settings/data-provider` | Current provider + per-key presence (booleans) + valid providers. |
| `PUT` | `/settings/data-provider` | Set provider and (optionally) API-key secrets. Rejects unknown providers (400). |

The provider used by the operator-console actions (`/actions/scan`, `/actions/backtest`,
`/actions/paper-session`, `/actions/refresh-data`) is built from this selection
via `momentum.api.user_settings.build_provider` (tests still inject a stub
provider through `app.state.provider_factory`).

The other `config/*.yaml` templates remain **read-only** in the Settings screen.
