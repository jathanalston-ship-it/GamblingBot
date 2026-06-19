"""Database migration + integrity verification for the update workflow.

After pulling new code the updater runs Alembic migrations and then verifies the
database is healthy: SQLite ``PRAGMA integrity_check`` passes, the schema is at
the latest migration head, and the core tables exist. A failure here triggers a
rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from momentum.persistence.database import create_db_engine

_REQUIRED_TABLES = frozenset(
    {"trades", "runs", "audit_log", "scan_results", "conviction_scores", "signals"}
)


def alembic_config(repo_dir: str | Path, db_url: str) -> Any:
    """Build an Alembic ``Config`` pointed at this repo and database."""
    from alembic.config import Config

    repo = Path(repo_dir).resolve()
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "src/momentum/persistence/migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def alembic_head(repo_dir: str | Path, db_url: str) -> str | None:
    """The latest migration revision defined in the repo."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config(repo_dir, db_url))
    return script.get_current_head()


def run_migrations(repo_dir: str | Path, db_url: str) -> None:
    """Upgrade the database to the latest migration head."""
    from alembic import command

    command.upgrade(alembic_config(repo_dir, db_url), "head")


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Outcome of the post-update database integrity check."""

    ok: bool
    pragma: str | None  # SQLite PRAGMA integrity_check result ("ok") or None
    revision: str | None  # current alembic_version
    head: str | None  # expected head
    missing_tables: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "pragma": self.pragma,
            "revision": self.revision,
            "head": self.head,
            "missing_tables": list(self.missing_tables),
            "reason": self.reason,
        }


def check_integrity(repo_dir: str | Path, db_url: str) -> IntegrityReport:
    """Verify the database is healthy and at the expected schema version."""
    is_sqlite = make_url(db_url).get_backend_name().startswith("sqlite")
    head = alembic_head(repo_dir, db_url)

    try:
        engine = create_db_engine(db_url)
        with engine.connect() as conn:
            pragma = conn.execute(text("PRAGMA integrity_check")).scalar() if is_sqlite else "ok"
            tables = set(inspect(conn).get_table_names())
            revision = (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if "alembic_version" in tables
                else None
            )
    except Exception as exc:  # noqa: BLE001 - report, never raise from a health check
        return IntegrityReport(
            ok=False,
            pragma=None,
            revision=None,
            head=head,
            missing_tables=(),
            reason=f"{type(exc).__name__}: {exc}",
        )

    missing = tuple(sorted(_REQUIRED_TABLES - tables))
    reason: str | None = None
    if pragma != "ok":
        reason = f"integrity_check returned {pragma!r}"
    elif missing:
        reason = f"missing tables: {', '.join(missing)}"
    elif head is not None and revision != head:
        reason = f"schema at {revision!r}, expected head {head!r}"

    return IntegrityReport(
        ok=reason is None,
        pragma=pragma,
        revision=revision,
        head=head,
        missing_tables=missing,
        reason=reason,
    )
