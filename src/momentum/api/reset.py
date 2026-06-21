"""Development / factory reset: wipe local state back to a fresh-install.

A developer-facing maintenance operation behind the Settings "Reset Local Data"
button. It clears the **contents** of the local application state — every database
row, the cached market-data parquet, the writable user settings and the on-disk
logs — while deliberately **preserving** the things that make the app work: the
application code/binaries, the database *schema*, and the Alembic *migration
history* (the ``alembic_version`` table is never touched). After clearing, the
schema is reconciled so every table exists and is empty — i.e. fresh-install state.

Pure helpers (`clear_database` / `clear_bar_cache` / `clear_logs`) + a thin
orchestrator (`reset_local_data`). The HTTP layer (routes/actions.py) calls the
orchestrator synchronously so a running job can be stopped as part of the reset.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from momentum.persistence.database import reconcile_schema
from momentum.persistence.models.base import Base

if TYPE_CHECKING:
    from momentum.api.jobs import JobManager

_log = logging.getLogger(__name__)


def clear_database(session: Session) -> dict[str, int]:
    """Delete every row from every ORM table; return the per-table counts cleared.

    Tables are emptied in **reverse** dependency order (children before parents) so
    foreign keys are satisfied. The Alembic ``alembic_version`` table is not part of
    ``Base.metadata`` and is intentionally left untouched, preserving the schema and
    migration history.
    """
    cleared: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        count = int(session.scalar(select(func.count()).select_from(table)) or 0)
        if count:
            session.execute(delete(table))
        cleared[table.name] = count
    session.commit()
    return cleared


def clear_bar_cache(cache_dir: str | None) -> int:
    """Remove the cached market-data parquet files; return how many were removed."""
    root = Path(cache_dir or os.environ.get("MRP_BAR_CACHE", "data/bars"))
    if not root.exists():
        return 0
    removed = sum(1 for _ in root.rglob("*.parquet"))
    shutil.rmtree(root, ignore_errors=True)
    return removed


def clear_logs(log_dir: str | None) -> int:
    """Best-effort clear of on-disk logs + diagnostic reports; return files affected.

    The active ``mrp.log`` may be held open by a still-attached handler (and on
    Windows cannot be unlinked while open), so a file that won't delete is truncated
    instead. Never raises — clearing logs must not be able to fail a reset.
    """
    if not log_dir:
        return 0
    directory = Path(log_dir)
    if not directory.is_dir():
        return 0
    affected = 0
    for path in directory.iterdir():
        if not path.is_file():
            continue
        try:
            path.unlink()
            affected += 1
        except OSError:
            try:
                path.write_text("", encoding="utf-8")
                affected += 1
            except OSError:
                pass
    return affected


def reset_local_data(
    *,
    session_factory: sessionmaker[Session],
    cache_dir: str | None = None,
    log_dir: str | None = None,
    preserve_api_keys: bool = True,
    job_manager: JobManager | None = None,
) -> dict[str, Any]:
    """Reset all local application state back to fresh-install. Returns a summary.

    Sequence: stop active jobs → clear the database → reconcile the schema (recreate
    any tables, leaving them empty) → clear the bar cache → clear user settings
    (preserving API keys unless asked) → clear logs **last** (after the reset event
    is logged). Schema and migration history are preserved throughout.
    """
    from momentum.api import user_settings

    _log.warning("FACTORY RESET requested (preserve_api_keys=%s)", preserve_api_keys)

    # 1. Stop active jobs so nothing writes to the database mid-wipe.
    jobs_stopped = job_manager.clear() if job_manager is not None else 0

    # 2. Clear the database contents (schema + alembic_version preserved).
    with session_factory() as session:
        cleared = clear_database(session)
        bind = session.get_bind()

    # 3. Reconcile the schema -> every table exists and is empty (fresh install).
    if isinstance(bind, Engine):
        reconcile_schema(bind)

    # 4. Clear cached market data.
    cache_files_removed = clear_bar_cache(cache_dir)

    # 5. Clear writable user settings (optionally preserving API-key secrets).
    settings_cleared = user_settings.clear_user_settings(preserve_api_keys=preserve_api_keys)

    rows_cleared = sum(cleared.values())
    _log.warning(
        "FACTORY RESET complete: %d rows across %d tables, %d cache files, %d jobs",
        rows_cleared,
        len(cleared),
        cache_files_removed,
        jobs_stopped,
    )

    # 6. Clear logs LAST, after the reset event has been written to them.
    logs_removed = clear_logs(log_dir)

    return {
        "ok": True,
        "rows_cleared": rows_cleared,
        "tables_cleared": cleared,
        "cache_files_removed": cache_files_removed,
        "logs_removed": logs_removed,
        "jobs_stopped": jobs_stopped,
        "settings_cleared": settings_cleared,
        "preserved_api_keys": preserve_api_keys,
    }
