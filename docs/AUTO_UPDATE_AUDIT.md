# Auto-Update Audit

> **Status update (resolved):** the repository is now **public**, so
> `releases.atom` returns 200 and the anonymous updater feed works — the root
> cause below is fixed. The updater has since been overhauled into a fully
> **automatic** flow (check on launch → one confirmation prompt with size + free
> space → auto download & install); see **`docs/AUTO_UPDATE.md`**. This audit is
> kept for the diagnosis and the (still-present) feed diagnostics.

Audit of the in-app auto-update (electron-updater) after a **404** on:

```
https://github.com/jathanalston-ship-it/GamblingBot/releases.atom
```

## Answers to the five questions

**1. Where is the update URL configured?**
`desktop/electron-builder.yml` → `publish:` block. electron-builder bakes it into
`app-update.yml` inside the package; at runtime electron-updater's
`GitHubProvider` builds the feed URL from it:

```
publish:
  provider: github
  owner: jathanalston-ship-it
  repo: GamblingBot
```
→ `GitHubProvider.getLatestVersion()` fetches
`https://github.com/jathanalston-ship-it/GamblingBot/releases.atom` **unauthenticated**
(verified in `node_modules/electron-updater/out/providers/GitHubProvider.js`).

**2. Is the repository name correct?** **Yes.** `GamblingBot` matches the git
remote (`jathanalston-ship-it/GamblingBot`) and the real repository (GitHub repo
paths are case-insensitive, so `gamblingbot` is the same repo). Owner is correct.

**3. Is the release feed URL valid?** The **format is correct** and is exactly what
electron-updater uses. It only 404s because of repository visibility (below) — for
a *public* repo this same URL returns 200.

**4. Is electron-updater configured correctly?** **Structurally, yes.** Provider /
owner / repo are right, and the published releases carry the assets the updater
needs (verified via the GitHub API): `latest.yml`, `MomentumLab-Setup-<v>.exe`,
`.blockmap`. The defect is environmental, not config.

**5. Does GitHub Releases publishing match updater expectations?** **Yes.** The
releases are **non-draft, non-prerelease**, with `latest.yml` + installer +
`.blockmap` attached (e.g. `v0.0.48`). The release workflow already uploads all of
these.

## Exact root cause

**The repository is PRIVATE.** electron-updater's GitHub provider fetches
`releases.atom` **without authentication**, and GitHub returns **404** for a
private repository's atom feed to anonymous clients. The update check dies at that
first request — before it ever reads `latest.yml`.

Proof (verified against the real URLs):

| Request | Result |
|---|---|
| `GET github.com/jathanalston-ship-it/GamblingBot/releases.atom` (anon) | **404** (`logged_in=no`) |
| `GET github.com/electron/electron/releases.atom` (anon, public repo) | **200** |
| GitHub API `releases` (authenticated) | v0.0.48 … v0.0.23, non-draft, with `latest.yml` + `.exe` + `.blockmap` |

A public repo's `releases.atom` returns **200 even with zero releases**; a **404
means private** (or the repo doesn't exist — but it does, and releases are
published). So the feed is private and the anonymous updater can't read it.

## Current vs expected configuration

| | Current | Expected (working) |
|---|---|---|
| `publish.provider` | `github` | `github` ✓ |
| `publish.owner` | `jathanalston-ship-it` | `jathanalston-ship-it` ✓ |
| `publish.repo` | `GamblingBot` | `GamblingBot` ✓ |
| Release assets | `latest.yml` + `.exe` + `.blockmap` | same ✓ |
| **Repository visibility** | **private** ⟶ `releases.atom` 404 | **public** ⟶ `releases.atom` 200 |

The configuration is already correct. **The only change required is repository
visibility.**

## The fix

### Primary (the actual fix — a repo setting, not code)

**Make the repository public** (Settings → General → Danger Zone → *Change
visibility* → Public). It ships public end-user installers and is built for
distribution, so the releases are meant to be publicly downloadable. Once public,
`releases.atom` returns 200 and the **existing** updater config works unchanged —
no app rebuild needed for the feed to resolve (clients pick it up on the next
check).

> This cannot be toggled from the app/CI — it's a one-time repository setting by an
> owner/admin.

### Code changes in this commit (robustness + observability)

Because the failure must be **visible, not suppressed**, and to support private /
internal distribution:

1. **Detailed diagnostics in the Updates screen** (`Updates.tsx` + a new
   `mrp:update:diagnostics` IPC). It shows the resolved provider / owner / repo,
   the **exact feed URL**, the current version, whether a token is configured, and
   a **live HTTP probe** of the feed with its status code and a plain-language
   interpretation (a 404 says: *"the repository is private or has no releases — make
   it public or set MRP_UPDATE_TOKEN"*). The feed config is read from the baked
   `app-update.yml` (the real source of truth).
2. **Full error surfaced, never swallowed.** The updater `error` event now carries
   the HTTP `statusCode`; the screen renders the raw message + status.
3. **Optional private-repo auth for testing / internal distribution.** If
   `MRP_UPDATE_TOKEN` (or `GH_TOKEN`/`GITHUB_TOKEN`) is present in the app's
   environment, electron-updater authenticates the feed + asset requests
   (`autoUpdater.requestHeaders`). The token is **never embedded** in the build —
   read from the environment only. (For public end-user distribution, make the repo
   public instead; do **not** ship a token.)

## Verification (against real GitHub URLs)

- The diagnostics probe returns **200** for a public repo (`electron/electron`) and
  **404** for ours, with the correct interpretation — proving both the mechanism
  and the diagnosis.
- Once the repo is public, the same feed returns 200 and the published assets
  (`latest.yml` + installer + blockmap, already present) satisfy electron-updater.

## What was NOT the problem

- Repo name / owner — correct.
- Feed URL format — correct (electron-updater's standard GitHub feed).
- Release publishing — correct (non-draft, with `latest.yml` + installer +
  blockmap).
- The earlier `electron_updater_1.default` crash — a separate bug, already fixed.
