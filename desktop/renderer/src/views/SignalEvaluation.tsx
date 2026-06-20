import type {
  CalibrationBucket,
  EvaluatedSignal,
  SignalEvaluation as Report,
  SignalQuality,
} from "../api/types";
import { Badge, type Tone } from "../components/Badge";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { num, pct, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const f1 = (v: number | null | undefined, d = 2): string => (v == null ? "—" : num(v, d));

function outcomeTone(o: string): Tone {
  if (o === "win") return "bull";
  if (o === "loss") return "bear";
  return "neutral";
}

export default function SignalEvaluation() {
  const { runId } = useWorkspace();
  const q = runId ? `?run_id=${runId}` : "";
  const report = useApi<Report>(`/signal-evaluation${q}`);
  const rows = useApi<EvaluatedSignal[]>(`/signal-evaluation/signals${q}`);

  if (report.loading) return <Loading />;
  if (report.error) return <ErrorBox message={report.error} />;
  if (!report.data) return null;
  const r = report.data;
  const o = r.overall;
  const ca = r.conviction_accuracy;
  const ma = r.move_accuracy;

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Signal Evaluation"
        subtitle={`${o.n_signals} signals · ${o.n_evaluated} evaluated (closed trades)`}
      />

      {/* signal quality */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
        <Stat label="Win Rate" value={o.win_rate != null ? pct(o.win_rate, 0) : "—"} />
        <Stat label="Expectancy" value={`${f1(o.expectancy_r)}R`} />
        <Stat label="Profit Factor" value={f1(o.profit_factor)} />
        <Stat label="E-ratio" value={f1(o.e_ratio)} hint="avg MFE / |MAE|" />
        <Stat label="Avg MFE / MAE" value={`${f1(o.avg_mfe, 1)} / ${f1(o.avg_mae, 1)}R`} />
        <Stat label="Avg Hold" value={o.avg_holding_days != null ? `${num(o.avg_holding_days, 0)}d` : "—"} />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* calibration */}
        <Card title="Calibration — predicted conviction vs actual win rate">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <CalibrationPlot buckets={r.calibration} />
            <table className="flex-1 text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-400">
                <tr className="text-left">
                  <th className="py-1 font-medium">Conv</th>
                  <th className="py-1 text-right font-medium">N</th>
                  <th className="py-1 text-right font-medium">Pred</th>
                  <th className="py-1 text-right font-medium">Actual</th>
                  <th className="py-1 text-right font-medium">Avg R</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {r.calibration.map((b) => (
                  <tr key={b.label} className="border-b border-surface-border/30">
                    <td className="py-1 text-slate-300">{b.label}</td>
                    <td className="py-1 text-right text-slate-400">{b.count}</td>
                    <td className="py-1 text-right text-slate-400">
                      {b.avg_predicted != null ? pct(b.avg_predicted, 0) : "—"}
                    </td>
                    <td className="py-1 text-right text-slate-100">
                      {b.count > 0 && b.actual_win_rate != null ? pct(b.actual_win_rate, 0) : "—"}
                    </td>
                    <td className="py-1 text-right">
                      <span className={(b.avg_r ?? 0) >= 0 ? "text-bull" : "text-bear"}>
                        {b.count > 0 ? f1(b.avg_r) : "—"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {/* accuracy */}
        <div className="space-y-5">
          <Card title="Conviction Accuracy">
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Rank AUC" value={f1(ca.rank_auc, 3)} hint="P(winner conv > loser)" />
              <Stat label="Correlation" value={f1(ca.pearson_conviction_r, 3)} hint="conviction vs R" />
              <Stat label="Brier Score" value={f1(ca.brier_score, 3)} hint="lower is better" />
              <Stat
                label="Monotonic"
                value={
                  <span className={ca.monotonic_win_rate ? "text-bull" : "text-bear"}>
                    {ca.monotonic_win_rate ? "yes" : "no"}
                  </span>
                }
                hint="win rate rises w/ conviction"
              />
            </div>
          </Card>
          <Card title="Predicted Move vs Actual">
            {ma.n === 0 ? (
              <div className="text-sm text-slate-500">
                No predicted-move data (needs watchlist expected moves).
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <Stat label="Mean Predicted" value={ma.mean_predicted != null ? pct(ma.mean_predicted, 1) : "—"} />
                <Stat label="Mean Actual" value={ma.mean_actual != null ? pct(ma.mean_actual, 1) : "—"} />
                <Stat label="Mean Abs Error" value={ma.mean_abs_error != null ? pct(ma.mean_abs_error, 1) : "—"} />
                <Stat
                  label="Bias"
                  value={
                    ma.bias != null ? (
                      <span className={ma.bias >= 0 ? "text-bull" : "text-bear"}>
                        {signed(ma.bias * 100, 1)}%
                      </span>
                    ) : (
                      "—"
                    )
                  }
                  hint="actual − predicted"
                />
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* quality by group */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <QualityTable title="By Source" rows={r.by_source} />
        <QualityTable title="By Signal Type" rows={r.by_type} />
      </div>

      {/* per-signal */}
      <Card title="Signals">
        {rows.loading ? (
          <Loading />
        ) : rows.error ? (
          <ErrorBox message={rows.error} />
        ) : (rows.data ?? []).length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-500">No signals.</div>
        ) : (
          <div className="max-h-[40vh] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface-raised text-xs uppercase tracking-wide text-slate-400">
                <tr className="text-left">
                  <th className="px-2 py-1.5 font-medium">Symbol</th>
                  <th className="px-2 py-1.5 font-medium">Type</th>
                  <th className="px-2 py-1.5 text-right font-medium">Conv</th>
                  <th className="px-2 py-1.5 font-medium">Outcome</th>
                  <th className="px-2 py-1.5 text-right font-medium">R</th>
                  <th className="px-2 py-1.5 text-right font-medium">MFE/MAE</th>
                  <th className="px-2 py-1.5 text-right font-medium">Hold</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {(rows.data ?? []).map((s) => (
                  <tr key={s.signal_id} className="border-b border-surface-border/30">
                    <td className="px-2 py-1 font-medium text-slate-100">{s.symbol}</td>
                    <td className="px-2 py-1 text-slate-400">{s.signal_type}</td>
                    <td className="px-2 py-1 text-right text-slate-300">{f1(s.conviction, 0)}</td>
                    <td className="px-2 py-1">
                      <Badge tone={outcomeTone(s.outcome)}>{s.outcome}</Badge>
                    </td>
                    <td className="px-2 py-1 text-right">
                      <span className={(s.r_multiple ?? 0) >= 0 ? "text-bull" : "text-bear"}>
                        {s.r_multiple != null ? signed(s.r_multiple, 1) : "—"}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-right text-slate-400">
                      {s.mfe != null ? f1(s.mfe, 1) : "—"} / {s.mae != null ? f1(s.mae, 1) : "—"}
                    </td>
                    <td className="px-2 py-1 text-right text-slate-400">
                      {s.holding_days != null ? `${s.holding_days}d` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function CalibrationPlot({ buckets }: { buckets: CalibrationBucket[] }) {
  const S = 180;
  const pad = 24;
  const pts = buckets.filter((b) => b.count > 0 && b.avg_predicted != null && b.actual_win_rate != null);
  const x = (v: number): number => pad + v * (S - pad * 2);
  const y = (v: number): number => S - pad - v * (S - pad * 2);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="w-44 shrink-0" role="img" aria-label="Calibration plot">
      <rect x={pad} y={pad} width={S - pad * 2} height={S - pad * 2} className="fill-surface" />
      {/* perfect-calibration diagonal */}
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} className="stroke-slate-600" strokeDasharray="3 3" />
      {/* path through buckets */}
      {pts.length >= 2 ? (
        <path
          d={pts.map((b, i) => `${i === 0 ? "M" : "L"} ${x(b.avg_predicted!)} ${y(b.actual_win_rate!)}`).join(" ")}
          className="fill-none stroke-accent"
          strokeWidth={1.5}
        />
      ) : null}
      {pts.map((b) => (
        <circle key={b.label} cx={x(b.avg_predicted!)} cy={y(b.actual_win_rate!)} r={3} className="fill-accent" />
      ))}
      <text x={x(0.5)} y={S - 6} textAnchor="middle" className="fill-slate-500 text-[9px]">
        predicted →
      </text>
      <text x={8} y={y(0.5)} textAnchor="middle" transform={`rotate(-90 8 ${y(0.5)})`} className="fill-slate-500 text-[9px]">
        actual →
      </text>
    </svg>
  );
}

function QualityTable({ title, rows }: { title: string; rows: SignalQuality[] }) {
  return (
    <Card title={title}>
      {rows.length === 0 ? (
        <div className="py-4 text-center text-sm text-slate-500">No data.</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-400">
            <tr className="border-b border-surface-border text-left">
              <th className="py-1.5 font-medium">Group</th>
              <th className="py-1.5 text-right font-medium">N</th>
              <th className="py-1.5 text-right font-medium">Win%</th>
              <th className="py-1.5 text-right font-medium">Exp R</th>
              <th className="py-1.5 text-right font-medium">PF</th>
              <th className="py-1.5 text-right font-medium">E-ratio</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((q) => (
              <tr key={q.key} className="border-b border-surface-border/30">
                <td className="py-1.5 text-slate-200">{q.key}</td>
                <td className="py-1.5 text-right text-slate-400">{q.n_evaluated}</td>
                <td className="py-1.5 text-right text-slate-300">
                  {q.win_rate != null ? pct(q.win_rate, 0) : "—"}
                </td>
                <td className="py-1.5 text-right">
                  <span className={(q.expectancy_r ?? 0) >= 0 ? "text-bull" : "text-bear"}>
                    {f1(q.expectancy_r)}
                  </span>
                </td>
                <td className="py-1.5 text-right text-slate-300">{f1(q.profit_factor)}</td>
                <td className="py-1.5 text-right text-slate-300">{f1(q.e_ratio)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
