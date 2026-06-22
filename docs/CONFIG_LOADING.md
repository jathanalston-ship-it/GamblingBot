# Configuration Loading — Packaged vs Source

Audit of the `FileNotFoundError: config/watchlist.example.yaml` raised inside the
packaged Windows build, and the fix that makes config loading work identically in
source and packaged builds — **packaged builds never require repository files**.

## Root cause

Every engine's `default_config()` resolved its tunables as:

```python
Path(__file__).resolve().parents[3] / "config" / "<name>.example.yaml"
```

— which assumes a **source checkout** (`src/momentum/<pkg>/<file>.py` → up 3 → repo
root → `config/`). In a **frozen** (PyInstaller) build the layout is different, so
`parents[3]` points *outside* the bundle and the read fails.

| Question | Answer |
|---|---|
| **1. Why do packaged builds read source-repo files?** | The path is computed relative to `__file__` with a hard-coded `parents[3]` that only resolves to `config/` in a source tree. |
| **2. Is `watchlist.example.yaml` bundled into PyInstaller?** | **Yes** — `desktop/build/backend.spec` bundles `config/` (`datas += [(REPO_ROOT/config, "config")]`) to `<_MEIPASS>/config`. The file is present; the loader just looked in the wrong place. |
| **3. Does path resolution assume a source checkout?** | **Yes** — `parents[3]/config` is the bug. |
| **4. Is config bootstrap missing?** | **Yes** — there was no writable user config and no in-code default; loading depended entirely on a file at the source-tree path. |

### Path audit

| Build | `__file__` (`watchlist/config.py`) | OLD `parents[3]/config` | Bundled `config/` actually at |
|---|---|---|---|
| **Source** | `<repo>/src/momentum/watchlist/config.py` | `<repo>/config` ✅ exists | `<repo>/config` |
| **Packaged (onefile)** | `<_MEIPASS>/momentum/watchlist/config.py` | `<parent-of-_MEIPASS>/config` ❌ **missing** → `FileNotFoundError` | `<_MEIPASS>/config` |

Verified: under a simulated frozen layout the OLD `parents[3]` target does **not**
exist, while the bundled `<_MEIPASS>/config/watchlist.example.yaml` does.

This was **systemic** — the same pattern was in 7 engine config modules
(`watchlist`, `tradeplan`, `lifecycle`, `signal_audit`, `options_eligibility`,
`options_recommendation`, `watchlist_performance`) and `api/services._config_dir()`.

## Fix — `core/config_paths.py`

A single resolver, frozen-aware, used by every `default_config()`:

- **`bundled_config_dir()`** — `<_MEIPASS>/config` when `sys.frozen`, else
  `<repo>/config`; honours `MRP_CONFIG_DIR`. No more `parents[3]` assumption.
- **`user_config_dir()`** — `<MRP_USER_DIR>/config` (the desktop app points
  `MRP_USER_DIR` at `%APPDATA%/Momentum Lab`).
- **`load_config(name, *, embedded=None)`** resolves in order:
  1. **user override** — `<MRP_USER_DIR>/config/<name>.yaml`;
  2. **shipped example** — bundle (frozen) or repo (source);
  3. **in-code embedded defaults** — so a build with *no config files at all* works.

  On first use, the resolved defaults are **bootstrapped** to the user dir
  (best-effort) — a default configuration is created automatically and is editable
  thereafter. Watchlist ships an embedded default (`_EMBEDDED_DEFAULT`, mirroring
  `config/watchlist.example.yaml`, with a drift-guard test) so it never requires any
  file. The other engines read the bundled example (present in the build) and gain
  the same user-override + bootstrap behaviour.

### User configuration location

```
%APPDATA%/Momentum Lab/config/watchlist.yaml   (Windows packaged)
<MRP_USER_DIR>/config/<name>.yaml              (general)
<cwd>/config/<name>.yaml                        (source dev fallback)
```

## Verification

| Scenario | Result |
|---|---|
| **Source build** (not frozen, no env) | ✅ reads `<repo>/config/watchlist.example.yaml` |
| **Packaged build** (frozen, bundle has `config/`) | ✅ reads `<_MEIPASS>/config/...`; bootstraps `%APPDATA%/.../config/watchlist.yaml` |
| **Fresh install / worst case** (frozen, bundle missing `config/`, empty user dir) | ✅ uses the **embedded** default; auto-creates the user config — no `FileNotFoundError` |
| **User override** present | ✅ `<MRP_USER_DIR>/config/watchlist.yaml` wins |
| **Unwritable user dir** | ✅ defaults returned in memory; bootstrap failure is non-fatal |

Tests: `tests/unit/core/test_config_paths.py` (resolver, frozen `_MEIPASS`, user
override, bundled bootstrap, embedded fallback, invalid-config fallback, non-fatal
bootstrap) and `tests/unit/watchlist/test_config.py` (embedded == example drift
guard, fresh-install bootstrap, packaged-never-requires-repo-files, user override).
Full suite: 1075 passed; mypy `--strict` + ruff clean.
