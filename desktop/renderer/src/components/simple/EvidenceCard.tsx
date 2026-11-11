import type { Evidence } from "../../api/today";
import { useAction } from "../../hooks/useAction";
import { Panel, fraction, usd } from "./common";

function Bar({
  label,
  strategy,
  benchmark,
  format,
  lowerIsBetter = false,
}: {
  label: string;
  strategy: number | null;
  benchmark: number | null;
  format: (v: number | null) => string;
  lowerIsBetter?: boolean;
}) {
  const s = Math.abs(strategy ?? 0);
  const b = Math.abs(benchmark ?? 0);
  const max = Math.max(s, b, 1e-9);
  const better =
    strategy != null && benchmark != null && (lowerIsBetter ? s < b : strategy > benchmark);
  return (
    <div>
      <div className="mb-1.5 text-[12px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      {[
        { name: "These rules", value: strategy, width: s / max, tone: "bg-accent-soft", strong: true },
        { name: "Just holding SPY", value: benchmark, width: b / max, tone: "bg-slate-600", strong: false },
      ].map((row) => (
        <div key={row.name} className="mb-1 flex items-center gap-3 text-[13px]">
          <span className={`w-32 shrink-0 ${row.strong ? "text-slate-200" : "text-slate-400"}`}>
            {row.name}
          </span>
          <span className="h-2.5 min-w-0 flex-1 rounded-full bg-surface">
            <span
              className={`block h-2.5 rounded-full ${row.tone}`}
              style={{ width: `${Math.max(2, row.width * 100)}%` }}
            />
          </span>
          <span
            className={`w-16 shrink-0 text-right tabular-nums ${
              row.strong ? "font-semibold text-slate-100" : "text-slate-400"
            }`}
          >
            {format(row.value)}
          </span>
        </div>
      ))}
      <div className="mt-1 text-[12px] text-slate-500">
        {strategy == null || benchmark == null
          ? ""
          : better
            ? "Better than holding the index."
            : "Worse than holding the index."}
      </div>
    </div>
  );
}

/** Run (or re-run) the long-history backtest of the live rules, with progress. */
export function RunBacktestButton({ onDone, label }: { onDone: () => void; label: string }) {
  const { job, running, start } = useAction("/actions/backtest", onDone);
  return (
    <span className="inline-flex items-center gap-2.5">
      {job && running ? (
        <span className="text-xs text-slate-400">
          {Math.round((job.progress ?? 0) * 100)}% · {job.message}
        </span>
      ) : null}
      {job && !running && job.status === "failed" ? (
        <span className="max-w-xs truncate text-xs text-bear" title={job.error ?? ""}>
          Failed: {job.error}
        </span>
      ) : null}
      <button className="btn-ghost" disabled={running} onClick={() => void start({})}>
        {running ? "Testing… (about a minute)" : label}
      </button>
    </span>
  );
}

/**
 * The evidence: how exactly these rules performed on the user's own stock list,
 * next to simply holding the index over the same dates. Honest by construction —
 * it shows the comparison whichever way it comes out, and says what it leaves out.
 */
export function EvidenceCard({
  evidence,
  onChanged,
  compact = false,
}: {
  evidence: Evidence | null;
  onChanged: () => void;
  compact?: boolean;
}) {
  if (evidence == null) {
    return (
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-5">
          <div className="max-w-xl text-[13px] leading-relaxed text-slate-400">
            <div className="text-[15px] font-semibold text-slate-100">
              See how these rules did over the last 20 years
            </div>
            Runs the exact rules this app trades — same signals, stops and exits — on your stock
            list with realistic costs, through the 2008 crash and the bull markets since, and
            compares the result with simply holding the S&amp;P 500.
          </div>
          <RunBacktestButton onDone={onChanged} label="Run the 20-year test" />
        </div>
      </Panel>
    );
  }
  const e = evidence;
  const years = e.years != null ? e.years.toFixed(0) : "?";
  return (
    <Panel>
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[15px] font-semibold text-slate-100">
              {usd(e.starting_equity)} became {usd(e.final_equity)} in {years} years
            </div>
            <div className="mt-0.5 text-[13px] text-slate-400">
              Backtest of these exact rules on {e.symbols ?? "your"} stocks, {e.start} to {e.end},
              after trading costs.
              {e.matches_live_rules ? "" : " The rules have changed since — run it again."}
            </div>
          </div>
          <RunBacktestButton onDone={onChanged} label="Run again" />
        </div>

        <div className="mt-4 grid gap-x-10 gap-y-5 md:grid-cols-2">
          <Bar
            label="Average yearly return"
            strategy={e.cagr}
            benchmark={e.benchmark_cagr}
            format={(v) => fraction(v, 1)}
          />
          <Bar
            label="Worst drop along the way"
            strategy={e.max_drawdown}
            benchmark={e.benchmark_max_drawdown}
            format={(v) => fraction(v, 0)}
            lowerIsBetter
          />
        </div>

        {compact ? null : (
          <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-surface-border/60 pt-4 text-[13px] sm:grid-cols-4">
            <div>
              <div className="text-slate-500">Trades</div>
              <div className="font-semibold tabular-nums text-slate-100">{e.num_trades}</div>
            </div>
            <div>
              <div className="text-slate-500">Winning trades</div>
              <div className="font-semibold tabular-nums text-slate-100">
                {fraction(e.win_rate, 0)}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Average winner / loser</div>
              <div className="font-semibold tabular-nums text-slate-100">
                +{e.avg_winner_r.toFixed(1)}R / {e.avg_loser_r.toFixed(1)}R
              </div>
            </div>
            <div>
              <div className="text-slate-500">$ won per $ lost</div>
              <div className="font-semibold tabular-nums text-slate-100">
                {e.profit_factor.toFixed(2)}
              </div>
            </div>
          </div>
        )}

        <p className="mt-4 text-[12px] leading-relaxed text-slate-500">
          Most trades lose a little ({fraction(1 - e.win_rate, 0)} of them); the profit comes from a
          few big winners, so every signal has to be taken. A backtest is not a promise: it uses
          today&apos;s stock list (companies that failed are missing, which flatters the result),
          and the future will differ. R = the amount risked on a trade.
        </p>
      </div>
    </Panel>
  );
}
