# Repository Security Audit — Public-Repo Readiness

**Scope:** every git-tracked file (617) **and** the full commit history (96
commits). **Verdict: ✅ SAFE TO MAKE PUBLIC.** No API keys, tokens, passwords,
private keys, credentialed URLs, or webhook secrets were found in the working tree
or history. One low-severity hygiene gap was found and fixed (gitignore hardening).

## Method

| Surface | How it was scanned |
|---|---|
| All tracked files | `git grep` for token formats + keyword=value secrets |
| Full history (96 commits) | `git grep` across `git rev-list --all`; `--diff-filter=A` for ever-committed secret files |
| Token formats | `sk-ant-`, `sk-proj-`, `sk-…`, `ghp_`/`gho_`/`ghu_`/`ghs_`/`github_pat_`, `AKIA…`, `xox[baprs]-`, `AIza…`, `-----BEGIN … PRIVATE KEY-----`, JWT `eyJ….….…` |
| Keywords | api key, secret, access/auth/session/refresh/id token, password, client_secret, bearer, oauth |
| Providers | Anthropic, OpenAI, GitHub, Alpaca, Polygon, Yahoo, AWS, Slack, Google |
| URLs | credentialed (`user:pass@`), webhooks (slack/discord/teams), non-loopback hosts/IPs |
| PII | personal emails (gmail/yahoo/…), the owner's email |

Inspected per the request: source code, config files, `.env` files, example
configs, build scripts, GitHub Actions, installer scripts, Electron code, backend
code, desktop code — all clean.

## Findings

| # | Severity | Finding | Location | Remediation |
|---|---|---|---|---|
| F-1 | **Low** (fixed) | `settings.yaml` / `config/settings.yaml` and `.env.*` variants were not gitignored. No secret is in them today (secrets live only in the gitignored `.env`; `settings.yaml` holds the non-secret provider *selection*), but the dev fallback writes `settings.yaml` to the repo root, so it could be committed by accident. | `.gitignore` | **Fixed in this commit** — `.gitignore` now ignores `.env`, `.env.*` (keeping `!.env.example`), `settings.yaml`, `config/settings.yaml`. |
| F-2 | **Info** | Commit messages carry `Claude-Session: https://claude.ai/code/session_…` trailers (96 commits, 3 distinct URLs) and `Co-Authored-By: Claude …` trailers. These are session **references**, not credentials — opening them requires the owner's Claude auth — but they become visible in public history. | git history (commit messages) | None required. Optional: rewrite history to drop the trailers if you'd rather not expose the session URLs. Not a secret. |
| F-3 | **Info** (clean) | `.env.example` contains only **empty** placeholders plus `BROKER_BASE_URL=https://paper-api.alpaca.markets` — Alpaca's **public** paper endpoint, not a secret. | `.env.example` | None — correct as-is (template with no values). |
| F-4 | **Info** (clean) | CI references credentials only by **name**: `${{ secrets.GITHUB_TOKEN }}` (Actions-injected at runtime), and `CSC_LINK` / `CSC_KEY_PASSWORD` / `MRP_UPDATE_TOKEN` as env-var names in comments/code. No values are embedded. | `.github/workflows/release.yml`, `desktop/electron-builder.yml`, `desktop/electron/main.ts` | None — correct (secrets come from the environment / GitHub Secrets). |
| F-5 | **Info** (clean) | Provider API keys are handled **write-only**: the API returns `keys_present: dict[str, bool]` (present/absent), never the values; keys persist to the gitignored `.env` under `MRP_USER_DIR`. | `src/momentum/api/user_settings.py`, `routes/settings.py`, `schemas.py` | None — correct by design. |

## What was verified absent (working tree AND all 96 commits)

- ❌ No Anthropic / OpenAI / Claude API keys (`sk-ant-…`, `sk-…`).
- ❌ No GitHub tokens (`ghp_`, `github_pat_`, …) — CI uses the injected `secrets.GITHUB_TOKEN`.
- ❌ No Alpaca / Polygon / broker keys (only env-var **names** and UI labels).
- ❌ No AWS / Slack / Google keys, no private keys, no JWTs.
- ❌ No OAuth / client / session / refresh tokens.
- ❌ No passwords or bearer-token literals.
- ❌ No credentialed URLs (`user:pass@…`) and no webhook URLs.
- ❌ No private/internal hosts or IPs — only loopback (`127.0.0.1`) and public endpoints (github.com, registry.npmjs.org, *.python.org, alpaca paper API).
- ❌ No personal email / PII (the owner's email is **not** in any tracked file).
- ❌ No committed `.env` / secrets file in history; no real DB/parquet/data files tracked (`data/`, `logs/` hold only `.gitkeep`).
- ✅ The build infra proxy URL (`local_proxy@127.0.0.1:…`) lives only in `.git/config` (untracked) — never committed.

## Secret-handling posture (good practices already in place)

- Secrets are environment-only (`.env`, gitignored); tunables are in `config/*.yaml`.
- The desktop app stores keys in a writable `.env` under `MRP_USER_DIR` (e.g.
  `%APPDATA%`), **outside** the repo, and the API never echoes them.
- Update/signing/publish tokens are read from the environment, never embedded.

## Pre-public checklist

- [x] Working tree scanned — no secrets.
- [x] Full history (96 commits) scanned — no secrets, no committed env/secret files.
- [x] `.gitignore` hardened (`.env*`, `settings.yaml`, `config/settings.yaml`).
- [x] Secrets are write-only via the API; live only in the gitignored `.env`.
- [ ] *(Optional)* Decide whether to keep the `Claude-Session:` commit trailers in
      public history (informational only — not a credential).
- [ ] *(Operational, post-public)* Rotate any credential you may have used locally
      in a `.env` during development, as standard hygiene — none are in the repo,
      but rotation after opening a repo is cheap insurance.

**Conclusion:** the repository contains no secrets in tracked files or history and
is safe to make public. The auto-update feed (`docs/AUTO_UPDATE_AUDIT.md`) will
start working the moment the repo is public.
