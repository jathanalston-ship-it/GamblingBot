# GitHub Actions Security Audit

Audit of every workflow in `.github/workflows/` for secret handling and
public-visibility safety. **Two workflows:** `desktop.yml` (build/test) and
`release.yml` (build + publish the GitHub Release).

**Verdict: ✅ safe for public visibility** after the fixes below. Only one secret
is used anywhere — the auto-provisioned `GITHUB_TOKEN` — and it is never printed,
never written to an artifact, and never written to a log.

## Secret inventory

| Secret | Where | Handling |
|---|---|---|
| `secrets.GITHUB_TOKEN` | `release.yml` publish step | Passed via `env:` to `softprops/action-gh-release@v2`. **Auto-masked** by Actions; never echoed. |
| (none) | `desktop.yml` | No secrets used at all. |
| `CSC_LINK` / `CSC_KEY_PASSWORD` | referenced **by name only** in `electron-builder.yml` comments | Code-signing is opt-in; not configured in CI. If added, electron-builder reads them from the env and Actions masks them. |

## Verification checklist

| Requirement | Result |
|---|---|
| Secrets are masked | ✅ Only `GITHUB_TOKEN`, which Actions masks automatically. |
| Secrets never printed | ✅ No `echo $TOKEN`, `env`, `printenv`, or `set -x` in any workflow or CI script. |
| Secrets never written to artifacts | ✅ Uploaded assets (installer, portable zip, `latest.yml`, `*.blockmap`, `release-validation.json`) carry no secret. The one runtime-derived artifact (`release-validation.json`) was hardened to redact URL credentials (F-4). |
| Secrets never written to logs | ✅ The `cat release-validation.json` / `cat release_notes.md` steps print only non-secret content. Release notes use commit **subjects** (`%s`), not bodies, so trailers never appear. |
| Release workflow safe | ✅ Least-privilege token; injection fixed; publish gated behind the quality + startup-validation gates. |
| Updater workflow safe | ✅ `latest.yml` + `*.blockmap` are electron-builder metadata (version + file hashes) — no secrets. Auto-update reads the public release feed (see `docs/AUTO_UPDATE_AUDIT.md`). |

## Findings & remediation

| # | Severity | Finding | Fix |
|---|---|---|---|
| F-1 | **Medium** | **Script injection.** `release.yml` interpolated the untrusted `workflow_dispatch` input directly into a `run:` shell block: `VERSION="${{ github.event.inputs.version }}"` (also `${{ github.ref_name }}`). A crafted input could inject shell commands (exploitable only by a user with dispatch/write access, but it is the canonical Actions injection anti-pattern). | **Fixed** — the input + `github.*` context are passed via `env:` and referenced as quoted shell variables (`"$INPUT_VERSION"`, `"$REF_NAME"`). No `${{ }}` remains in any `run:` body. |
| F-2 | **Low** | **Over-broad permissions.** `release.yml` granted `contents: write` at the **workflow** level, so the `quality` job (which only reads code) also had write. | **Fixed** — top-level `permissions: contents: read`; `contents: write` granted **only** to the `release` (publish) job. |
| F-3 | **Low** | **No explicit permissions** in `desktop.yml` → it inherited the repository default token scope. | **Fixed** — added `permissions: contents: read` (build/test needs read only; no secrets). |
| F-4 | **Low** (defensive) | **Public artifact could leak DB credentials.** `release-validation.json` (uploaded to the public release) embedded the raw `database_url` in a check detail. Today that is a local SQLite path (no credentials), but a `postgres://user:pass@host/db` URL would have leaked. | **Fixed** — `redactUrl()` strips `//user:pass@` → `//***@` from every URL in the report (DB URL + health URL). Unit-tested. |
| F-5 | **Info** | Third-party/community actions are pinned to **mutable major tags** (`softprops/action-gh-release@v2`, `actions/checkout@v4`, `actions/setup-node@v4`, `actions/setup-python@v5`) rather than commit SHAs. | **Recommendation** (not changed to avoid an unverifiable SHA in this environment): pin `softprops/action-gh-release` to a full commit SHA for supply-chain hardening — it is the action that holds `GITHUB_TOKEN`. The `actions/*` are GitHub-owned and lower risk. |

## Confirmed safe (no violation)

- **Triggers.** `desktop.yml` uses `pull_request` (not `pull_request_target`), so
  fork PRs run with **no secret access** and a read-only token. `release.yml` only
  triggers on `push` of a `v*` **tag** or a manual `workflow_dispatch` (both require
  write access). No untrusted trigger touches secrets.
- **No secret echo.** Grepped all workflows + `scripts/` + `desktop/scripts/` for
  `set -x` / `printenv` / `env |` / `echo $TOKEN` — none.
- **Release notes.** Built from `git log --pretty='- %s (%h)'` (subjects only). The
  `Claude-Session:` commit trailers live in commit **bodies** and never reach the
  notes.
- **Build artifacts.** The installer/portable zip bundle `dist-electron/` +
  `renderer/dist/` + the frozen backend; there is no `.env` in the repo to bundle,
  and the PyInstaller spec includes no secret. `latest.yml`/`*.blockmap` are
  hashes/metadata.

## Result

After F-1–F-4, the workflows expose no secret in logs or artifacts, use
least-privilege tokens, and are free of the known injection vector. The CI/CD is
**safe for a public repository.** (F-5 is an optional supply-chain hardening.)
