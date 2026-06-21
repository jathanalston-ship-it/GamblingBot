# Secret Management

Production-grade secret handling. **Every credential comes from the environment —
never from source, TypeScript, Python, Electron, config files, example YAML,
`package.json` or `pyproject.toml`.** The single source of truth is the secret
**registry** in `src/momentum/core/secrets.py`.

## Where secrets live

```
your shell / CI env   ─┐
.env  (git-ignored)   ─┼─►  process environment  ─►  providers / broker / updater
  (under MRP_USER_DIR) │         ▲
.env.example (tracked) ┘         │ load_user_env() at startup (existing env wins)
  empty placeholders only
```

- The only tracked env file is **`.env.example`** (empty values + comments).
- The desktop app persists user-entered keys to a git-ignored **`.env`** under
  `MRP_USER_DIR` (e.g. `%APPDATA%\Momentum Lab`), **outside** the repo.
- `load_user_env()` loads `.env` into the process env at startup; a real
  environment variable always wins (`setdefault`).

## The registry (`core/secrets.py`)

Each secret is declared **once** as a `SecretSpec` (env var, description, which
provider / environment makes it required):

| Env var | Required when | Optional |
|---|---|---|
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | data provider = `alpaca` | no |
| `POLYGON_API_KEY` | data provider = `polygon` | no |
| `BROKER_API_KEY` / `BROKER_API_SECRET` | `MRP_ENV = live` | no |
| `MRP_UPDATE_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` | never (private-repo auto-update) | yes |

The default provider `yfinance` requires **no** secrets, so a fresh install runs
with zero configuration.

## Startup validation

The backend (`python -m momentum.api`) validates the **active** configuration on
startup (after `load_user_env()`):

- **All present** → an INFO line: *"All required secrets present (provider=…,
  environment=…)"*.
- **Missing** → a clear, **value-free** ERROR naming the missing env vars and how to
  set them. By default this is **non-fatal** so the desktop app still boots to the
  Settings screen where keys can be entered; the provider raises a precise auth
  error on first use.
- **`MRP_STRICT_SECRETS=1`** (operator / CI) → a missing required secret is a **hard
  error**: `MissingSecretsError` is raised, `backend-startup.json` records
  `status: failed`, and the process exits non-zero.

```
secret validation: Missing required secret(s) for provider 'alpaca' / environment
'research': ALPACA_API_KEY, ALPACA_API_SECRET. Set them in your environment or in
the .env file under MRP_USER_DIR (see .env.example). Never commit real secrets.
```

The message **never** contains a secret value.

## Never printed to logs

`setup_logging` wraps every formatter in a **`RedactingFormatter`**. Before any log
line reaches a handler (console or `mrp.log`), every known secret **value** in the
formatted string — message, args, exception text or structured extras — is replaced
with `<redacted>`. Even an accidental `log.info("key=%s", api_key)` is scrubbed.
(Values shorter than 6 chars are not treated as secret material, so trivial values
can't mangle logs.)

Use `secrets.mask(value)` (→ `••••••••`) or `secrets.is_set(env_var)` (presence
boolean) when you need to *show* something about a secret.

## Never exposed to the renderer

The Electron renderer is sandboxed (`contextIsolation` on, `nodeIntegration` off)
and can only see the typed **preload bridge**. The preload:

- reads only non-secret env vars (`MRP_API_PORT`, `MRP_APP_VERSION`, `MRP_PACKAGED`,
  `MRP_DEV_APP`),
- never spreads or exposes `process.env`,
- surfaces secret *presence* only (e.g. the Updates screen shows
  `tokenConfigured: boolean`, never the token).

The backend process *does* receive `process.env` (it needs the keys) — that is the
main process spawning the sidecar, not the renderer. The API never returns secret
values either: `read_provider_settings()` returns `keys_present: dict[str, bool]`.

`desktop/scripts/no-secret-exposure.test.cjs` enforces this against the compiled
preload (no secret env var referenced, no `process.env` exposure).

## Tests

- `tests/unit/core/test_secrets.py` — registry integrity, per-provider/environment
  requirements, validate/require (value-free messages), masking, redaction,
  `RedactingFormatter` scrubbing (incl. exception text), and **drift guards**:
  every `user_settings.PROVIDER_KEYS` env var is registered, and `.env.example`
  lists every required secret with an **empty** value.
- `desktop/scripts/no-secret-exposure.test.cjs` — the renderer bridge exposes no
  secret.

## Adding a new secret

1. Add a `SecretSpec(...)` to `SECRET_REGISTRY` in `core/secrets.py` (set
   `providers=` / `environments=` to make it required, or `optional=True`).
2. Read it via `secrets.get("ENV_VAR")` — never hard-code it anywhere.
3. Add an **empty** line to `.env.example`.
4. If it's a provider key surfaced in the UI, add it to
   `user_settings.PROVIDER_KEYS` (the drift test will confirm consistency).

That's it — validation, redaction and the example file pick it up automatically.
