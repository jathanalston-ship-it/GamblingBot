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
from typing import TYPE_CHECKING

import typer

from momentum.core.logging import get_logger, setup_logging

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from momentum.data.providers.base import MarketDataProvider
    from momentum.execution.paper_broker import PaperBroker

app = typer.Typer(add_completion=False, help="Momentum Research Platform CLI.")

_DEFAULT_SYMBOLS = "AAPL,MSFT,NVDA,AMZN,META,GOOGL,AVGO,TSLA"


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _init(json_logs: bool, level: str) -> None:
    setup_logging(level=level, json_logs=json_logs)


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _parse_date(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value) if value else dt.date.today()


def _make_provider(name: str) -> MarketDataProvider:
    """Build a market-data provider by name (kept tiny so tests can monkeypatch)."""
    from momentum.data.providers.yfinance import YahooProvider

    if name.lower() in ("yahoo", "yfinance"):
        return YahooProvider()
    raise typer.BadParameter(f"unknown provider {name!r} (supported: yahoo)")


def _session_factory(ensure_schema: bool) -> sessionmaker[Session]:
    from momentum.persistence.database import (
        create_all,
        create_db_engine,
        create_session_factory,
    )

    engine = create_db_engine()
    if ensure_schema:
        create_all(engine)
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
    symbols: str = typer.Option(_DEFAULT_SYMBOLS, help="Comma-separated universe."),
    as_of: str = typer.Option(None, "--as-of", help="Session date YYYY-MM-DD (default today)."),
    equity: float = typer.Option(100_000.0, help="Starting account equity."),
    lookback_days: int = typer.Option(400, help="Calendar days of history to pull."),
    provider: str = typer.Option("yahoo", help="Market-data provider."),
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
    symbols: str = typer.Option(_DEFAULT_SYMBOLS, help="Comma-separated universe."),
    lookback_days: int = typer.Option(400, help="Calendar days of history to pull."),
    top: int = typer.Option(10, help="How many ranked candidates to show."),
    provider: str = typer.Option("yahoo", help="Market-data provider."),
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


def _paper_broker() -> PaperBroker:
    from momentum.execution.execution_config import ExecutionConfig
    from momentum.execution.paper_broker import PaperBroker

    return PaperBroker(ExecutionConfig())


if __name__ == "__main__":  # pragma: no cover
    app()
