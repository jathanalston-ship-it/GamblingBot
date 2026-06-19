# Setup — From a Fresh Machine to a Running System

Exact, copy-paste instructions assuming **no prior setup**. Two runnable
surfaces today: the **backend** (read-only API + `mrp` CLI) and the **desktop
app** (Electron UI over the API). Everything defaults to a local SQLite database
and a keyless data provider, so it runs with **zero credentials**.

---

## 1. Dependencies

Install these system tools first:

| Tool | Version | Why | Check |
|---|---|---|---|
| **Python** | 3.12+ (3.11 works) | backend, CLI | `python --version` |
| **pip** | recent | install Python deps | `pip --version` |
| **git** | any | clone the repo | `git --version` |
| **Node.js + npm** | Node 18+ | desktop UI only | `node --version` |

> macOS: `brew install python@3.12 node git` · Ubuntu:
> `sudo apt install python3.12 python3-pip nodejs npm git`

Python packages are installed in step 3 (`fastapi`, `uvicorn`, `typer`,
`sqlalchemy`, `alembic`, `pandas`, `numpy`, `pyarrow`, `pydantic`, `httpx`,
`pandas-market-calendars`, …). A virtual environment is strongly recommended.

## 2. Get the code

```bash
git clone <repository-url> GamblingBot
cd GamblingBot
```

## 3. Python environment + install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
make install                       # = pip install -r requirements.txt && pip install -e .
```

*Verify:* `python -c "import momentum; print('ok')"` prints `ok`.

## 4. Environment variables

**None are required** — the defaults below work out of the box. Set any you want
to override (export in your shell, or put in a `.env` you `source`):

| Variable | Default | When to set |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/momentum.db` | point at Postgres |
| `MRP_API_HOST` | `127.0.0.1` | change the API bind host |
| `MRP_API_PORT` | `8000` | change the API bind port |
| `MRP_CORS_ORIGINS` | `*` | lock down the desktop origin |
| `MRP_LOG_LEVEL` | `INFO` | `DEBUG` for verbose logs |
| `MRP_LOG_DIR` | `logs` | log file location |
| `MRP_LOG_JSON` | unset | `1` for structured JSON logs |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | — | only for the Alpaca data provider |
| `POLYGON_API_KEY` | — | only for the Polygon data provider |

The default data provider is **Yahoo**, which needs no key.

## 5. Database setup + migrations

The schema is owned by Alembic. Create/upgrade it:

```bash
alembic upgrade head
```

*Expected output* (first run):
```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, initial schema
...
INFO  [alembic.runtime.migration] Running upgrade 0008 -> 0009, audit log
```
This creates `data/momentum.db` with 15 tables. *Verify:*
```bash
mrp health
# database: sqlite:///data/momentum.db
# tables: 15 present
# migration revision: 0009
# status: OK
```

## 6. Backend startup (API)

```bash
mrp serve --host 127.0.0.1 --port 8000
#   or: make serve
#   or: python -m momentum.api
```
*Expected:* uvicorn logs `Uvicorn running on http://127.0.0.1:8000`. In another
shell:
```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok", ...}
```

## 7. CLI usage

```bash
mrp health                                  # connection + schema + migration check
mrp scan --symbols AAPL,MSFT,NVDA --top 10  # ranked momentum candidates
mrp paper-run --symbols AAPL,MSFT,NVDA --as-of 2025-06-18   # one paper session
mrp replay --run-id paper-20250618          # replay a stored session
mrp paper-run --json                        # structured JSON logs
```
`paper-run` runs the full workflow (pull data → scan → conviction → risk → paper
orders → positions → audit → summary) and prints a Daily Report. See
[CLI.md](CLI.md) for full examples and expected output.

## 8. Frontend startup (desktop app)

The Electron UI talks to the backend API. **Start the backend first** (step 6),
then:

```bash
cd desktop
npm install
npm run dev        # Vite renderer on :5173 + Electron window
```
To build a packaged app: `npm run build && npm run package`.

> The desktop app expects the API at `http://127.0.0.1:8000`. If you changed the
> port, set `MRP_API_PORT` for the backend and the matching renderer config.

## 9. Verification

Run the full end-to-end checklist (offline, deterministic):
```bash
python scripts/verify_e2e.py
```
*Expected:* `10/10 checks passed`. Then the quality gate:
```bash
make check     # ruff + mypy --strict + pytest + migration drift
```
*Expected:* `All checks passed!`, the test summary (`... passed`), and
`No new upgrade operations detected.`

See [E2E_VERIFICATION.md](E2E_VERIFICATION.md) for the per-stage checklist.

## 10. Expected end-state

After steps 1–6 you have:
- `data/momentum.db` migrated to revision `0009` (15 tables).
- `mrp health` → `status: OK`.
- API serving on `http://127.0.0.1:8000` (`/health` returns 200).
- `logs/mrp.log` accumulating timestamped log lines.
- (optional) the desktop window open, reading from the API.

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: momentum` | deps not installed / venv not active | `source .venv/bin/activate && make install` |
| `mrp: command not found` | editable install not picked up | re-run `pip install -e .`; ensure the venv is active |
| `mrp health` → `status: FAIL (missing tables …)` | DB not migrated | `alembic upgrade head` |
| `mrp health` → `migration revision: NONE` | schema made via `create_all`, not Alembic | run `alembic upgrade head` (safe; idempotent) |
| API: `Address already in use` | port 8000 taken | `mrp serve --port 8010` (or set `MRP_API_PORT`) |
| `paper-run` opens no trades | no candidates passed filters / market closed | normal on thin data; try more/again `--symbols`, or a prior `--as-of` |
| Provider auth error | Alpaca/Polygon keys missing | unset them to use keyless Yahoo, or export the keys |
| Desktop: blank window / fetch errors | backend not running or wrong port | start `mrp serve` first; match `MRP_API_PORT` |
| `alembic: command not found` | venv not active | activate the venv (Alembic is a dependency) |
| mypy/ruff failures in `make check` | local edits | run `make format`, then `make check` |

For how the remote/web execution environment is configured, see
<https://code.claude.com/docs/en/claude-code-on-the-web>.
