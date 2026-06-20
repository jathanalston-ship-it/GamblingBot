#!/usr/bin/env python
"""Seed a demo dataset so the UI can be explored without running the scanner.

Generates a deterministic, positive-skew demo:

    * 100 historical signals
    * 50 completed (closed) trades  → the analytics dataset
    * ~30 daily portfolio snapshots (an equity curve)
    * ~30 daily market regimes
    * recent runs + audit events    → replay data (`mrp replay`)

All demo rows are tagged (``run_id`` / ``model_version`` = ``demo``) and cleared
before re-seeding, so the script is idempotent. Deterministic via a fixed RNG
seed — the same dataset every time.

    python scripts/seed_demo.py                 # seed data/momentum.db
    DATABASE_URL=sqlite:///demo.db python scripts/seed_demo.py
    python scripts/seed_demo.py --reset-only    # just delete demo rows
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from sqlalchemy import delete  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from momentum.persistence.database import (  # noqa: E402
    create_all,
    create_db_engine,
    create_session_factory,
)
from momentum.conviction.engine import ConvictionEngine  # noqa: E402
from momentum.conviction.inputs import ConvictionInputs  # noqa: E402
from momentum.persistence.models.audit_log import AuditLog  # noqa: E402
from momentum.persistence.models.conviction_score import ConvictionScore  # noqa: E402
from momentum.persistence.models.market_regime import MarketRegime  # noqa: E402
from momentum.persistence.models.opportunity_classification import (  # noqa: E402
    OpportunityClassification,
)
from momentum.persistence.models.optimization_result import OptimizationResult  # noqa: E402
from momentum.persistence.models.portfolio_snapshot import PortfolioSnapshot  # noqa: E402
from momentum.persistence.models.risk_metric import RiskMetric  # noqa: E402
from momentum.persistence.models.run import Run  # noqa: E402
from momentum.persistence.models.scan_result import ScanResult  # noqa: E402
from momentum.persistence.models.signal import Signal  # noqa: E402
from momentum.persistence.models.trade import Trade  # noqa: E402

DEMO_TAG = "demo"
SEED = 7
START_EQUITY = 100_000.0
UTC = dt.UTC

SYMBOLS: list[tuple[str, str]] = [
    ("AAPL", "Technology"),
    ("MSFT", "Technology"),
    ("NVDA", "Technology"),
    ("AMZN", "Consumer Discretionary"),
    ("META", "Communication Services"),
    ("GOOGL", "Communication Services"),
    ("AVGO", "Technology"),
    ("TSLA", "Consumer Discretionary"),
    ("JPM", "Financials"),
    ("XOM", "Energy"),
    ("LLY", "Health Care"),
    ("COST", "Consumer Staples"),
    ("AMD", "Technology"),
    ("NFLX", "Communication Services"),
    ("CRM", "Technology"),
]
REGIMES = ["bullish", "neutral", "bearish"]
ENTRY_REASONS = ["breakout_50d", "momentum_rank", "pullback", "new_ath"]
EXIT_REASONS = ["target", "stop", "trailing_stop", "time_stop"]


def _bdays(end: dt.date, n: int) -> list[dt.date]:
    """The last ``n`` business days ending at ``end`` (oldest first)."""
    days: list[dt.date] = []
    cursor = end
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= dt.timedelta(days=1)
    return list(reversed(days))


def reset(session: Session) -> None:
    """Remove every demo-tagged row (idempotent re-seed)."""
    session.execute(delete(AuditLog).where(AuditLog.run_id.like(f"{DEMO_TAG}%")))
    session.execute(delete(Run).where(Run.run_id.like(f"{DEMO_TAG}%")))
    session.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.run_id == DEMO_TAG))
    session.execute(delete(Trade).where(Trade.run_id == DEMO_TAG))
    session.execute(delete(Signal).where(Signal.run_id == DEMO_TAG))
    session.execute(delete(MarketRegime).where(MarketRegime.model_version == DEMO_TAG))
    session.execute(delete(ScanResult).where(ScanResult.run_id == DEMO_TAG))
    session.execute(delete(ConvictionScore).where(ConvictionScore.run_id == DEMO_TAG))
    session.execute(
        delete(OpportunityClassification).where(OpportunityClassification.run_id == DEMO_TAG)
    )
    session.execute(delete(RiskMetric).where(RiskMetric.run_id == DEMO_TAG))
    session.execute(delete(OptimizationResult).where(OptimizationResult.run_id == DEMO_TAG))
    session.flush()


def seed_regimes(session: Session, days: list[dt.date], rng: np.random.Generator) -> None:
    # Mostly bullish with occasional neutral/bearish patches.
    weights = np.array([0.6, 0.3, 0.1])
    for d in days:
        label = REGIMES[int(rng.choice(3, p=weights))]
        score = {"bullish": 0.7, "neutral": 0.45, "bearish": 0.2}[label] + rng.normal(0, 0.05)
        session.add(
            MarketRegime(
                as_of=d,
                benchmark_symbol="SPY",
                model_version=DEMO_TAG,
                regime=label,
                trend_state="uptrend" if label == "bullish" else "sideways",
                volatility_state="normal" if label != "bearish" else "high",
                score=round(float(np.clip(score, 0, 1)), 4),
                confidence=round(float(rng.uniform(0.5, 0.95)), 3),
                breadth=round(float(rng.uniform(0.35, 0.75)), 3),
                adx=round(float(rng.uniform(15, 40)), 2),
            )
        )


def seed_signals(session: Session, days: list[dt.date], rng: np.random.Generator) -> None:
    for _ in range(100):
        symbol, _sector = SYMBOLS[int(rng.integers(len(SYMBOLS)))]
        d = days[int(rng.integers(len(days)))]
        price = float(rng.uniform(40, 400))
        session.add(
            Signal(
                run_id=DEMO_TAG,
                source="demo",
                strategy="breakout",
                symbol=symbol,
                ts=dt.datetime.combine(d, dt.time(15, 45), tzinfo=UTC),
                session_date=d,
                signal_type=str(rng.choice(["breakout", "momentum"])),
                direction="long",
                strength=round(float(rng.uniform(0.4, 1.0)), 3),
                momentum_score=round(float(rng.uniform(50, 100)), 2),
                reference_price=round(price, 2),
                atr=round(price * 0.02, 3),
                status="generated",
            )
        )


def seed_trades(session: Session, days: list[dt.date], rng: np.random.Generator) -> list[Trade]:
    """50 closed trades with a positive-skew payoff (few big winners, many small losers)."""
    trades: list[Trade] = []
    for i in range(50):
        symbol, sector = SYMBOLS[int(rng.integers(len(SYMBOLS)))]
        entry_day = days[int(rng.integers(0, len(days) - 5))]
        win = rng.random() < 0.4  # low win rate by design
        if win:
            r_multiple = float(rng.uniform(1.0, 8.0))
            holding = int(rng.integers(8, 40))  # winners ride the trend
        else:
            r_multiple = float(rng.uniform(-1.1, -0.3))
            holding = int(rng.integers(2, 12))
        entry_price = round(float(rng.uniform(40, 400)), 2)
        atr = round(entry_price * 0.02, 3)
        stop_dist = round(atr * 2.0, 3)
        quantity = max(1, int((START_EQUITY * 0.005) / stop_dist))
        initial_risk = round(stop_dist * quantity, 2)
        net_pnl = round(r_multiple * initial_risk, 2)
        exit_price = round(entry_price + net_pnl / quantity, 2)
        exit_day = entry_day + dt.timedelta(days=holding)
        regime = str(rng.choice(REGIMES, p=[0.6, 0.3, 0.1]))
        trade = Trade(
            run_id=DEMO_TAG,
            symbol=symbol,
            direction="long",
            entry_ts=dt.datetime.combine(entry_day, dt.time(15, 30), tzinfo=UTC),
            exit_ts=dt.datetime.combine(exit_day, dt.time(15, 30), tzinfo=UTC),
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            initial_stop=round(entry_price - stop_dist, 2),
            initial_risk=initial_risk,
            r_multiple=round(r_multiple, 3),
            gross_pnl=net_pnl + 2.0,
            fees=2.0,
            net_pnl=net_pnl,
            return_pct=round(net_pnl / (entry_price * quantity), 4),
            mae=round(float(rng.uniform(-1.0, -0.1)), 3),
            mfe=round(float(abs(r_multiple) + rng.uniform(0, 1.5)), 3),
            holding_days=holding,
            bars_held=holding,
            exit_reason=("target" if win else str(rng.choice(["stop", "time_stop"]))),
            status="closed",
            sector=sector,
            regime_label=regime,
            entry_reason=str(rng.choice(ENTRY_REASONS)),
            entry_volume=round(float(rng.uniform(1e6, 2e7)), 0),
            entry_relative_volume=round(float(rng.uniform(1.0, 4.0)), 2),
        )
        trades.append(trade)
        session.add(trade)
    return trades


def seed_snapshots(session: Session, trades: list[Trade], days: list[dt.date]) -> None:
    """Daily equity curve from cumulative realised P&L (last 30 sessions)."""
    by_exit: dict[dt.date, float] = {}
    for t in trades:
        if t.exit_ts and t.net_pnl is not None:
            by_exit.setdefault(t.exit_ts.date(), 0.0)
            by_exit[t.exit_ts.date()] += t.net_pnl

    snapshot_days = days[-30:]
    realized = sum(pnl for d, pnl in by_exit.items() if d < snapshot_days[0])
    equity = START_EQUITY + realized
    peak = equity
    for d in snapshot_days:
        realized += by_exit.get(d, 0.0)
        equity = START_EQUITY + realized
        peak = max(peak, equity)
        session.add(
            PortfolioSnapshot(
                run_id=DEMO_TAG,
                as_of=dt.datetime.combine(d, dt.time(16, 0), tzinfo=UTC),
                session_date=d,
                equity=round(equity, 2),
                cash=round(equity * 0.6, 2),
                positions_value=round(equity * 0.4, 2),
                num_positions=int(min(8, max(0, (equity - START_EQUITY) // 2000 + 3))),
                gross_exposure=0.4,
                net_exposure=0.4,
                long_exposure=0.4,
                portfolio_heat=0.03,
                realized_pnl=round(realized, 2),
                unrealized_pnl=0.0,
                daily_pnl=round(by_exit.get(d, 0.0), 2),
                cumulative_return=round(equity / START_EQUITY - 1.0, 4),
                high_water_mark=round(peak, 2),
                drawdown=round(max(0.0, 1.0 - equity / peak), 4),
            )
        )


def seed_runs_and_audit(session: Session, trades: list[Trade]) -> None:
    """One umbrella ``demo`` run + a full audit trail, all aligned to the demo trades.

    Trades, the run and the audit events share ``run_id == "demo"`` so
    ``mrp replay`` shows the trades *and* their event history together.
    """
    closed = sum(1 for t in trades if t.status == "closed")
    last_exit = max((t.exit_ts for t in trades if t.exit_ts is not None), default=None)
    as_of = last_exit.date() if last_exit is not None else dt.date.today()
    started = dt.datetime.combine(as_of, dt.time(16, 0), tzinfo=UTC)
    total_pnl = sum(t.net_pnl or 0.0 for t in trades)

    session.add(
        Run(
            run_id=DEMO_TAG,
            mode=DEMO_TAG,
            as_of=as_of,
            status="completed",
            started_at=started,
            finished_at=started + dt.timedelta(seconds=3),
            equity_start=START_EQUITY,
            equity_end=round(START_EQUITY + total_pnl, 2),
            num_opened=len(trades),
            num_closed=closed,
        )
    )
    for t in trades:
        entry_ts = t.entry_ts or started
        events = [
            ("signal_generated", f"momentum candidate {t.symbol}", entry_ts),
            ("order_submitted", f"submitted long {t.quantity} {t.symbol}", entry_ts),
            ("order_filled", f"filled {t.quantity} {t.symbol} @ {t.entry_price}", entry_ts),
            ("position_opened", f"opened long {t.quantity} {t.symbol}", entry_ts),
        ]
        if t.exit_ts is not None:
            events.append(
                (
                    "position_closed",
                    f"closed {t.symbol} ({t.exit_reason}) net {t.net_pnl}",
                    t.exit_ts,
                )
            )
        for event, summary, ts in events:
            session.add(
                AuditLog(
                    event_type=event,
                    ts=ts,
                    run_id=DEMO_TAG,
                    symbol=t.symbol,
                    entity_type="trade",
                    summary=summary,
                )
            )


def build_candidates(rng: np.random.Generator) -> list[dict[str, Any]]:
    """A ranked candidate per universe symbol with realistic scan features."""
    cands: list[dict[str, Any]] = []
    for i, (symbol, sector) in enumerate(SYMBOLS):
        price = round(float(rng.uniform(40, 400)), 2)
        cands.append(
            {
                "symbol": symbol,
                "sector": sector,
                "momentum_score": round(float(95 - i * 2.6 + rng.normal(0, 1.2)), 2),
                "price": price,
                "atr": round(price * 0.02, 3),
                "dollar_volume": round(price * float(rng.uniform(3e6, 2e7)), 0),
                "relative_volume": round(float(rng.uniform(1.1, 3.5)), 2),
                "distance_from_ath": round(float(-rng.uniform(0.0, 0.08)), 4),
                "ema_fast": round(price, 2),
                "ema_mid": round(price * 0.97, 2),
                "ema_slow": round(price * 0.93, 2),
                "sector_rs": round(float(rng.uniform(0.55, 0.98)), 3),
            }
        )
    cands.sort(key=lambda c: c["momentum_score"], reverse=True)
    for rank, c in enumerate(cands, start=1):
        c["rank"] = rank
    return cands


def seed_scan_results(session: Session, as_of: dt.date, cands: list[dict[str, Any]]) -> None:
    for c in cands:
        session.add(
            ScanResult(
                run_id=DEMO_TAG,
                as_of=as_of,
                model_version="v1",
                symbol=c["symbol"],
                rank=c["rank"],
                momentum_score=c["momentum_score"],
                passed=True,
                price=c["price"],
                dollar_volume=c["dollar_volume"],
                relative_volume=c["relative_volume"],
                distance_from_ath=c["distance_from_ath"],
                ema_fast=c["ema_fast"],
                ema_mid=c["ema_mid"],
                ema_slow=c["ema_slow"],
                atr=c["atr"],
                sector=c["sector"],
                sector_rs=c["sector_rs"],
                components={
                    "c_momentum": round(c["momentum_score"] / 100, 3),
                    "c_trend": 0.8,
                    "c_ath": 0.9,
                    "c_rvol": round(min(1.0, c["relative_volume"] / 3.5), 3),
                    "c_sector": c["sector_rs"],
                },
            )
        )


def seed_conviction(
    session: Session, as_of: dt.date, cands: list[dict[str, Any]], rng: np.random.Generator
) -> None:
    engine = ConvictionEngine()
    ts = dt.datetime.combine(as_of, dt.time(15, 50), tzinfo=UTC)
    for c in cands:
        inputs = ConvictionInputs(
            market_regime="bull",
            sector_strength=c["sector_rs"],
            relative_volume=c["relative_volume"],
            distance_to_ath=abs(c["distance_from_ath"]),
            trend_strength=float(rng.uniform(20, 40)),
            breadth=float(rng.uniform(0.45, 0.72)),
            momentum_score=c["momentum_score"] / 100.0,
            historical_expectancy_r=float(rng.uniform(0.2, 1.4)),
            historical_sample_size=int(rng.integers(20, 60)),
        )
        result = engine.score(inputs)
        session.add(
            ConvictionScore.from_result(
                result, symbol=c["symbol"], run_id=DEMO_TAG, as_of=as_of, ts=ts
            )
        )


def seed_opportunity(
    session: Session, as_of: dt.date, cands: list[dict[str, Any]], rng: np.random.Generator
) -> None:
    ts = dt.datetime.combine(as_of, dt.time(15, 50), tzinfo=UTC)
    for c in cands:
        score = round(float(min(100.0, max(0.0, c["momentum_score"] + rng.normal(0, 6)))), 2)
        tier = "Home Run" if score >= 90 else "Enhanced" if score >= 70 else "Normal"
        session.add(
            OpportunityClassification(
                run_id=DEMO_TAG,
                symbol=c["symbol"],
                as_of=as_of,
                ts=ts,
                tier=tier,
                score=score,
                new_ath=bool(c["distance_from_ath"] > -0.005),
                model_version="v1",
                new_ath_score=round(float(rng.uniform(0, 1)), 3),
                momentum_score=round(c["momentum_score"] / 100, 3),
                relative_volume=round(min(1.0, c["relative_volume"] / 3.5), 3),
                regime_score=0.8,
                sector_leadership=c["sector_rs"],
                historical_edge=round(float(rng.uniform(0.3, 0.9)), 3),
                breakdown={"tier": tier, "score": score},
            )
        )


def seed_risk_metrics(
    session: Session, as_of_dt: dt.datetime, session_date: dt.date, rng: np.random.Generator
) -> None:
    for window in ("inception", "90d", "30d"):
        session.add(
            RiskMetric(
                run_id=DEMO_TAG,
                as_of=as_of_dt,
                session_date=session_date,
                scope="portfolio",
                window=window,
                volatility_annual=round(float(rng.uniform(0.12, 0.20)), 4),
                sharpe=round(float(rng.uniform(0.9, 1.8)), 3),
                sortino=round(float(rng.uniform(1.2, 2.4)), 3),
                calmar=round(float(rng.uniform(0.6, 1.3)), 3),
                max_drawdown=round(float(-rng.uniform(0.04, 0.12)), 4),
                current_drawdown=round(float(-rng.uniform(0.0, 0.03)), 4),
                var_95=round(float(-rng.uniform(0.01, 0.03)), 4),
                cvar_95=round(float(-rng.uniform(0.02, 0.05)), 4),
                gross_exposure=round(float(rng.uniform(0.3, 0.6)), 3),
                portfolio_heat=round(float(rng.uniform(0.01, 0.04)), 4),
                win_rate=round(float(rng.uniform(0.38, 0.48)), 3),
                profit_factor=round(float(rng.uniform(1.6, 2.8)), 3),
                expectancy_r=round(float(rng.uniform(0.4, 0.9)), 3),
                avg_win_r=round(float(rng.uniform(2.0, 3.5)), 3),
                avg_loss_r=round(float(-rng.uniform(0.8, 1.0)), 3),
                payoff_ratio=round(float(rng.uniform(2.0, 3.5)), 3),
                num_trades=int(rng.integers(20, 55)),
            )
        )


def seed_optimizations(session: Session, rng: np.random.Generator) -> int:
    """A couple of optimization studies for the Backtesting screen."""
    count = 0
    for study, objective in (("breakout_v1", "sharpe"), ("regime_filter_v1", "expectancy_r")):
        rows = []
        for _ in range(7):
            rows.append(
                (
                    int(rng.choice([20, 30, 50, 60, 80])),
                    round(float(rng.choice([1.5, 2.0, 2.5, 3.0])), 1),
                    round(float(rng.uniform(0.5, 1.8)), 4),
                )
            )
        rows.sort(key=lambda r: r[2], reverse=True)
        for rank, (lookback, atr_mult, obj) in enumerate(rows, start=1):
            session.add(
                OptimizationResult(
                    study_name=study,
                    optimizer="grid",
                    run_id=DEMO_TAG,
                    param_hash=f"{study}-{count:02d}",
                    parameters={"breakout_lookback": lookback, "atr_mult": atr_mult},
                    objective=objective,
                    objective_value=obj,
                    sample="full",
                    sharpe=round(float(rng.uniform(0.6, 1.8)), 3),
                    cagr=round(float(rng.uniform(0.08, 0.35)), 3),
                    calmar=round(float(rng.uniform(0.5, 1.3)), 3),
                    max_drawdown=round(float(-rng.uniform(0.06, 0.18)), 3),
                    expectancy_r=round(float(rng.uniform(0.3, 0.9)), 3),
                    num_trades=int(rng.integers(30, 120)),
                    rank=rank,
                    is_selected=(rank == 1),
                )
            )
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the MRP demo dataset.")
    parser.add_argument("--reset-only", action="store_true", help="Delete demo rows and exit.")
    args = parser.parse_args()

    engine = create_db_engine()
    create_all(engine)  # ensure the schema exists (idempotent)
    factory = create_session_factory(engine)
    rng = np.random.default_rng(SEED)

    with factory() as session:
        reset(session)
        if args.reset_only:
            session.commit()
            print("Demo rows removed.")
            return 0

        end = dt.date.today()
        days = _bdays(end, 120)
        regime_days = days[-30:]

        seed_regimes(session, regime_days, rng)
        seed_signals(session, days, rng)
        trades = seed_trades(session, days, rng)
        session.flush()
        seed_snapshots(session, trades, days)
        seed_runs_and_audit(session, trades)

        as_of = days[-1]
        as_of_dt = dt.datetime.combine(as_of, dt.time(16, 0), tzinfo=UTC)
        cands = build_candidates(rng)
        seed_scan_results(session, as_of, cands)
        seed_conviction(session, as_of, cands, rng)
        seed_opportunity(session, as_of, cands, rng)
        seed_risk_metrics(session, as_of_dt, as_of, rng)
        n_opt = seed_optimizations(session, rng)
        session.commit()

        wins = sum(1 for t in trades if (t.net_pnl or 0) > 0)
        total_pnl = sum(t.net_pnl or 0 for t in trades)
        print("Demo dataset seeded:")
        print(f"  market regimes     : {len(regime_days)}")
        print("  signals            : 100")
        print(f"  closed trades      : {len(trades)} ({wins} winners, net ${total_pnl:,.0f})")
        print("  portfolio snapshots: 30")
        print(f"  scan candidates    : {len(cands)} (ranked)")
        print(f"  conviction scores  : {len(cands)}")
        print(f"  opportunity tiers  : {len(cands)}")
        print("  risk metrics       : 3 (inception / 90d / 30d)")
        print(f"  optimization rows  : {n_opt} (2 studies)")
        print("  run + audit trail  : 1 'demo' run (replay-ready)")
        print(f"\nDatabase: {engine.url}")
        print("Try:  mrp replay   |   mrp health   |   start the API and open the desktop app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
