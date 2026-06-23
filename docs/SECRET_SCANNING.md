# Secret Scanning (preventing future leaks)

Automated, layered defence so a **future** commit can never silently introduce a
secret — the gap the manual public-readiness audit could not cover on its own.

## Layers

| Layer | Where | What it does |
|---|---|---|
| **Pre-commit hook** | `.pre-commit-config.yaml` (gitleaks) | Blocks a `git commit` locally if staged changes contain a secret. Opt-in: `pip install pre-commit && pre-commit install`. |
| **CI gate** | `.github/workflows/secret-scan.yml` | gitleaks scans the **full git history** on every push / PR; a finding **fails the build** (`--exit-code 1`). Secrets are `--redact`ed so they never print in CI logs. |
| **Release gate** | `.github/workflows/release.yml` (quality job) | The same gitleaks scan runs before a release is built/published — a release can never ship with a secret. |
| **Config** | `.gitleaks.toml` | Default ruleset (`useDefault = true`) + a tiny allowlist for the empty `.env.example` template and obviously-fake test fixtures. |
| **Runtime redaction** | `core/secrets.RedactingFormatter` | Even at runtime, a secret value never reaches a log line. |
| **Targeted tests** | `tests/unit/core/test_secrets.py`, `desktop/scripts/no-secret-exposure.test.cjs` | `.env.example` has no values; the renderer preload exposes no secret. |
| **Guard test** | `tests/unit/test_secret_scanning_gate.py` | Asserts the scanner wiring exists and is set to fail — so the gate can't be silently removed. |

## What gitleaks catches that the targeted tests don't

The Python/JS tests only check **known surfaces** (the `.env.example` file, the
preload). gitleaks catches a **new, unknown** secret in **any** file — a hardcoded
`sk-…` / `ghp_…` / `AKIA…` token, a `-----BEGIN PRIVATE KEY-----`, a credentialed
URL — added in a future PR.

Verified: a planted `AKIA…` AWS key + `ghp_…` GitHub token makes the scan exit `1`
(build fails); the current repo (105 commits + tree) scans clean (exit `0`).

## Recommended GitHub setting (post-public)

Once the repository is public, enable **Settings → Code security → Secret scanning**
and **Push protection** (free for public repos). That adds a server-side block at
`git push` and partner-token verification — a backstop independent of CI and the
local hook. (This is a repository setting, not code.)

## Running it locally

```bash
# scan the whole history
gitleaks detect --source . --config .gitleaks.toml --redact

# or install the commit hook
pip install pre-commit && pre-commit install
```
