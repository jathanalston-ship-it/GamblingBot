---
name: verify
description: Run this project's full quality gate (ruff format-check + ruff lint + mypy --strict + pytest + Alembic migration-drift). Use before committing or pushing, or whenever the user asks to verify/check the build is green.
---

# verify — the quality gate

A change is **not done** until all of these pass. Run them in order and stop at
the first failure; fix, then re-run from the top.

```bash
ruff format --check src tests        # 1. formatting
ruff check src tests                 # 2. lint
MYPYPATH=src python -m mypy --strict src/momentum  # 3. types — must be 0 errors
PYTHONPATH=src python -m pytest tests -q  # 4. tests
```

5. **Migration drift** (only if `models/` or a migration changed):

```bash
tmp=$(mktemp -u --suffix=.db)
DATABASE_URL="sqlite:///$tmp" PYTHONPATH=src alembic upgrade head
DATABASE_URL="sqlite:///$tmp" PYTHONPATH=src alembic check   # expect: No new upgrade operations detected
rm -f "$tmp"
```

Shortcut: `make check` runs all five. `make format` auto-fixes formatting.

Notes:
- If imports fail with `ModuleNotFoundError`, deps aren't installed — run
  `make install` (the `SessionStart` hook normally does this).
- Don't mask exit codes; report the first real failure with its output.
- After green, **self-critique**: name one gap/risk before declaring done.
