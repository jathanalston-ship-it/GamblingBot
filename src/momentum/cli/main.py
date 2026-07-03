"""``mrp`` command-line interface.

Commands:
    mrp serve       launch the read-only API (uvicorn sidecar)
    mrp paper-run   pull data → scan → conviction → risk → paper orders → journal
    mrp scan        run the momentum scanner and print ranked candidates
    mrp health      check the database connection, schema and migration state
    mrp replay      print a stored session (run, trades, audit) from the ledger

Every command configures logging first (rotating file + console, plain or JSON).
The database URL comes from ``DATABASE_URL`` (default ``sqlite:///data/momentum.db``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import typer

from momentum.core.logging import get_logger, setup_logging

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from momentum.data.providers.base import MarketDataProvider

app = typer.Typer(add_completion=False, help="Momentum Research Platform CLI.")


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _init(json_logs: bool, level: str) -> None:
    setup_logging(level=level, json_logs=json_logs)


def _parse_symbols(raw: str) -> list[str]:
    """Parse ``--symbols``; an empty value falls back to the configured universe."""
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if symbols:
        return symbols
    from momentum.universe.membership import select_universe

    return select_universe()[0]


def _parse_date(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value) if value else dt.date.today()


def _make_provider(name: str) -> MarketDataProvider:
    """Build a market-data provider by name (kept tiny so tests can monkeypatch).

    ``yahoo`` is keyless; ``alpaca``/``polygon`` read their API keys from the
    environment / ``.env`` exactly like the desktop Settings screen (the shared
    ``user_settings.build_provider`` does the wiring + validation).
    """
    lowered = name.lower()
    if lowered == "yahoo":
        from momentum.data.providers.yfinance import YahooProvider

        return YahooProvider()
    if lowered in ("alpaca", "polygon"):
        from momentum.api import user_settings

        return user_settings.build_provider(lowered)
    raise typer.BadParameter(f"unknown provider {name!r} (supported: yahoo, alpaca, polygon)")


def _session_factory(ensure_schema: bool) -> sessionmaker[Session]:
    from momentum.persistence.database import (
        create_all,
        create_db_engine,
        create_session_factory,
    )

    engine = create_db_engine()
    if ensure_schema:
        create_all(engine)
    # Activate the persisted data mode (registers the demo-exclusion filter).
    from momentum.api import data_mode

    data_mode.load_from_settings()
    return create_session_factory(engine)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host (loopback by default)."),
    port: int = typer.Option(8000, help="Bind port."),
    log_json: bool = typer.Option(False, "--json", help="Structured JSON logs."),
    log_level: str = typer.Option("INFO", help="Log level."),
) -> None:
    """Launch the read-only API as a local sidecar."""
    _init(log_json, log_level)
    log = get_logger("serve")

    import uvicorn

    from momentum.api.app import create_app
    from momentum.persistence.database import (
        create_all,
        create_db_engine,
        create_session_factory,
    )

    engine = create_db_engine()
    create_all(engine)
    app_ = create_app(create_session_factory(engine))
    log.info("serving API on http://%s:%d", host, port)
    uvicorn.run(app_, host=host, port=port, log_level=log_level.lower())


@app.command(name="paper-run")
def paper_run(
    symbols: str = typer.Option(
        "", help="Comma-separated universe (default: configured universe)."
    ),
    as_of: str = typer.Option(None, "--as-of", help="Session date YYYY-MM-DD (default today)."),
    equity: float = typer.Option(100_000.0, help="Starting account equity."),
    lookback_days: int = typer.Option(400, help="Calendar days of history to pull."),
    provider: str = typer.Option("yahoo", help="Market-data provider (yahoo, alpaca, polygon)."),
    log_json: bool = typer.Option(False, "--json", help="Structured JSON logs."),
    log_level: str = typer.Option("INFO", help="Log level."),
) -> None:
    """Run one paper-trading session end to end and print the summary."""
    _init(log_json, log_level)
    log = get_logger("paper-run")

    from momentum.conviction.engine import ConvictionEngine
    from momentum.orchestration.engine import DailyOrchestrationEngine
    from momentum.orchestration.session import run_paper_session
    from momentum.risk.risk_manager import RiskManager
    from momentum.universe.screener import MomentumScanner

    day = _parse_date(as_of)
    syms = _parse_symbols(symbols)
    market = _make_provider(provider)
    engine = DailyOrchestrationEngine(
        conviction=ConvictionEngine(),
        risk=RiskManager(),
        broker=_paper_broker(),
        starting_equity=equity,
    )
    factory = _session_factory(ensure_schema=True)
    with factory() as session:
        report = run_paper_session(
            session,
            provider=market,
            scanner=MomentumScanner(),
            engine=engine,
            symbols=syms,
            as_of=day,
            lookback_days=lookback_days,
        )
    typer.echo(report.to_markdown())
    log.info("paper-run complete: %s", report.run_id)


@app.command()
def scan(
    symbols: str = typer.Option(
        "", help="Comma-separated universe (default: configured universe)."
    ),
    lookback_days: int = typer.Option(400, help="Calendar days of history to pull."),
    top: int = typer.Option(10, help="How many ranked candidates to show."),
    provider: str = typer.Option("yahoo", help="Market-data provider (yahoo, alpaca, polygon)."),
    log_json: bool = typer.Option(False, "--json", help="Structured JSON logs."),
    log_level: str = typer.Option("WARNING", help="Log level."),
) -> None:
    """Run the momentum scanner and print the ranked candidates."""
    _init(log_json, log_level)

    from momentum.orchestration.session import pull_bars
    from momentum.universe.screener import MomentumScanner

    syms = _parse_symbols(symbols)
    bars = pull_bars(
        _make_provider(provider), syms, end=dt.date.today(), lookback_days=lookback_days
    )
    result = MomentumScanner().scan(bars)
    candidates = result.candidates[:top]
    if not candidates:
        typer.echo("No candidates passed the scan filters.")
        raise typer.Exit(code=0)
    typer.echo(f"{'RANK':<5}{'SYMBOL':<10}{'SCORE':>8}{'PRICE':>10}{'DIST_ATH':>10}")
    for c in candidates:
        typer.echo(
            f"{c.rank:<5}{c.symbol:<10}{c.momentum_score:>8.2f}{c.price:>10.2f}"
            f"{c.distance_from_ath:>10.3f}"
        )


@app.command()
def health(
    log_level: str = typer.Option("WARNING", help="Log level."),
) -> None:
    """Check the database connection, schema and migration revision."""
    _init(False, log_level)

    from sqlalchemy import inspect, text

    from momentum.persistence.database import create_db_engine, get_database_url

    url = get_database_url()
    typer.echo(f"database: {url}")
    try:
        engine = create_db_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            tables = set(inspect(conn).get_table_names())
            revision = None
            if "alembic_version" in tables:
                revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001 - health must report, not crash
        typer.echo(f"status: FAIL ({type(exc).__name__}: {exc})")
        raise typer.Exit(code=1) from exc

    required = {"trades", "runs", "audit_log", "scan_results", "conviction_scores"}
    missing = sorted(required - tables)
    typer.echo(f"tables: {len(tables)} present")
    typer.echo(f"migration revision: {revision or 'NONE (run: alembic upgrade head)'}")
    if missing:
        typer.echo(f"status: FAIL (missing tables: {', '.join(missing)})")
        raise typer.Exit(code=1)
    typer.echo("status: OK")


@app.command()
def replay(
    run_id: str = typer.Option(None, help="Run id to replay (default: latest)."),
    log_level: str = typer.Option("WARNING", help="Log level."),
) -> None:
    """Print a stored session — its run, trades and audit trail — from the ledger."""
    _init(False, log_level)

    from momentum.persistence.repositories.audit_log import AuditLogRepository
    from momentum.persistence.repositories.runs import RunRepository
    from momentum.persistence.repositories.trades import TradeRepository

    factory = _session_factory(ensure_schema=False)
    with factory() as session:
        runs = RunRepository(session)
        run = runs.get(run_id) if run_id else runs.latest()
        if run is None:
            typer.echo("No runs found." if not run_id else f"Run {run_id!r} not found.")
            raise typer.Exit(code=1)

        typer.echo(f"# Replay — {run.run_id} ({run.mode}, {run.as_of})")
        typer.echo(
            f"status={run.status} equity {run.equity_start} → {run.equity_end} "
            f"opened={run.num_opened} closed={run.num_closed}"
        )
        trades = TradeRepository(session)
        opened = trades.open_positions(run.run_id)
        closed = trades.closed(run.run_id)
        typer.echo(f"\n## Trades: {len(opened)} open, {len(closed)} closed")
        for t in opened + closed:
            pnl = f"{t.net_pnl:+.2f}" if t.net_pnl is not None else "—"
            typer.echo(f"- {t.symbol} {t.status} qty={t.quantity} net={pnl}")

        events = AuditLogRepository(session).by_run(run.run_id)
        typer.echo(f"\n## Audit trail: {len(events)} events")
        for e in events:
            typer.echo(f"- {e.ts} {e.event_type}: {e.summary}")


@app.command()
def update(
    check: bool = typer.Option(False, "--check", help="Only report status; make no changes."),
    restart_cmd: str = typer.Option(
        None, "--restart-cmd", help='Command to relaunch after updating, e.g. "mrp serve".'
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    branch: str = typer.Option(None, help="Branch to track (default: current)."),
    log_level: str = typer.Option("INFO", help="Log level."),
) -> None:
    """Update this installation from the remote repository (with auto-rollback)."""
    _init(False, log_level)

    from momentum.core.exceptions import UpdateError
    from momentum.update.config import UpdateConfig
    from momentum.update.updater import Updater

    updater = Updater(UpdateConfig(branch=branch), restart=_restart_runner(restart_cmd))
    try:
        status = updater.check()
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        typer.echo(f"update check failed: {exc}")
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"branch {status.branch}: {status.current_version or '?'} "
        f"({status.current_commit[:12]}) → {status.remote_version or '?'} "
        f"({status.target_commit[:12]})"
    )
    if not status.update_available:
        typer.echo("Already up to date.")
        return
    typer.echo(f"{status.behind_by} new commit(s) available.")
    if check:
        return
    if not yes and not typer.confirm("Download and apply this update?"):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)

    try:
        result = updater.update(restart=bool(restart_cmd))
    except UpdateError as exc:
        typer.echo(f"FAILED: {exc}")
        raise typer.Exit(code=1) from exc

    typer.echo(f"Updated. {result.message} (backup {result.backup_id}).")
    if result.restarted:
        typer.echo("Application restarted.")
    else:
        typer.echo("Restart Momentum Lab to apply the update.")


@app.command()
def rollback(
    backup_id: str = typer.Option(None, help="Backup id to restore (default: latest)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
    log_level: str = typer.Option("INFO", help="Log level."),
) -> None:
    """Roll back to a previous backup (restores the code commit and the database)."""
    _init(False, log_level)

    from momentum.core.exceptions import UpdateError
    from momentum.update.updater import Updater

    updater = Updater()
    target = updater.backups.get(backup_id) if backup_id else updater.backups.latest()
    if target is None:
        typer.echo("No backup available to roll back to.")
        raise typer.Exit(code=1)
    typer.echo(f"Rolling back to {target.backup_id} (commit {target.commit[:12]}).")
    if not yes and not typer.confirm("Restore this backup?"):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)
    try:
        record = updater.rollback(target.backup_id)
    except UpdateError as exc:
        typer.echo(f"FAILED: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"Rolled back to {record.commit[:12]}. Restart Momentum Lab to apply.")


def _restart_runner(command: str | None) -> Callable[[], None] | None:
    if not command:
        return None

    def _run() -> None:
        import shlex
        import subprocess

        subprocess.Popen(shlex.split(command), close_fds=True)  # noqa: S603 - user-supplied relaunch

    return _run


def _paper_broker() -> Any:
    """The configured execution venue (internal simulator or Alpaca paper)."""
    from momentum.api import user_settings

    return user_settings.build_broker()


if __name__ == "__main__":  # pragma: no cover
    app()
