# Local Update System (`mrp update`)

A self-update for a **single-user local installation**: pull the latest code from
the remote git repository, migrate the database, verify it, and (optionally)
restart — with an automatic rollback if anything goes wrong.

## Commands

```bash
mrp update --check                      # report status only, change nothing
mrp update                              # update (asks to confirm)
mrp update --yes                        # update without prompting
mrp update --yes --restart-cmd "mrp serve"   # relaunch after a successful update
mrp rollback                            # restore the most recent backup
mrp rollback --backup-id 20260619-2210  # restore a specific backup
```

## Workflow

`Updater.update()` runs these steps; **4–6 are transactional** — a failure in any
of them triggers an automatic rollback:

1. **Check the remote** — `git fetch <remote>`.
2. **Detect a newer version** — compare the current commit to `origin/<branch>`
   (commits behind) and read the `version` from `pyproject.toml` at each.
3. **Create a backup** — copy the SQLite database file and record the current
   commit + version to a timestamped folder under `backups/updates/`.
4. **Pull updates** — fast-forward merge to the remote head (never rewrites local
   history; aborts if the working tree is dirty).
5. **Run migrations** — `alembic upgrade head`.
6. **Verify database integrity** — SQLite `PRAGMA integrity_check` passes, the
   schema is at the latest migration head, and the core tables exist.
7. **Restart the application** — optional; runs the `--restart-cmd` you supply.

If 4, 5 or 6 raises, the updater **resets the code to the backed-up commit and
restores the database from the backup**, then reports the failure (non-zero exit).

## Rollback

- **Automatic:** built into `update()` (above).
- **Manual:** `mrp rollback` restores the latest backup (code commit + DB); pass
  `--backup-id` to choose an older one. Backups are kept (default 8) and pruned
  oldest-first.

## Components (`src/momentum/update/`)

| Module | Responsibility |
|---|---|
| `config.py` | `UpdateConfig` (repo dir, remote, branch, backup dir, retention). |
| `git_ops.py` | `GitRunner` — a thin, testable git CLI wrapper. |
| `backup.py` | `BackupManager` — snapshot/restore the DB + commit manifest. |
| `integrity.py` | `run_migrations` + `check_integrity` (PRAGMA, head, tables). |
| `updater.py` | `Updater` — orchestrates the 7-step flow + rollback. |

The git runner, migrator, integrity check and restart hook are all injectable, so
the flow is tested end-to-end against a temporary git repository (no network).

## Desktop integration (no terminal needed)

The updater is reachable from inside Momentum Lab:

- **API:** `GET /update/status`, `POST /update/apply`, `POST /update/rollback`
  (`src/momentum/api/routes/update.py`) wrap the `Updater`.
- **UI:** the **Updates** view (left rail → *Updates*) shows the installed vs
  latest version and offers **Update now** / **Roll back** buttons.
- **Menu:** *Check for Updates…* (Help menu / app menu on macOS) routes the
  renderer to the Updates view via the preload `onNavigate` bridge.

**Packaged builds.** The installed Windows app ships a *frozen* backend with **no
git repository**, so in-place git updates don't apply there. On such a build the
endpoints report `supported: false` and the UI explains that updating means
installing a newer download (the auto-update path is still deliberately
deferred). In-app update is for **source installs** (a cloned repo running the
real Python backend).

## Notes & limitations

- **Single-user / local only.** It updates the working copy in place; it is not a
  multi-machine deployment tool.
- **Fast-forward only.** A dirty working tree or diverged history aborts the
  update (nothing is changed) — commit/stash local edits first.
- **SQLite backups.** The DB snapshot covers file-based SQLite (the default). For
  Postgres, back up via your DB tooling; the code rollback still applies.
- **Trust.** `mrp update` runs whatever is on the tracked branch. For
  paper/research that's fine; gate on reviewed/tagged releases before live use.
- **Not auto-update.** This is a user-initiated command, not a background updater.
