import type {
  WatchlistPerformanceReport as Report,
  WatchlistPredictionQuality,
  WatchlistScorecard,
} from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { num, pct, signed } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const tone = (v: number | null | undefined): string =>
  v == null ? "text-slate-500" : v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-slate-300";

const pctCell = (v: number | null | undefined, d = 1): string => (v == null ? "—" : pct(v, d));

export default function WatchlistPerformance() {
  const { runId } = useWorkspace();
  const q = runId ? `?run_id=${runId}` : "";
  const { data, error, loading, reload } = useApi<Report>(`/watchlist-performance${q}`);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const r = data;
  const best = r.quality.find((qq) => qq.horizon === r.best_horizon);

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Watchlist Performance"
        subtitle="Do the watchlists actually work? Forward 1d/1w/1m returns + MFE/MAE, scored per horizon"
      />

      <div className="flex flex-wrap items-center gap-4">
        <Stat label="Tracked entries" value={num(r.n_total, 0)} hint={`${r.n_complete} matured`} />
        <Stat label="Generations" value={num(r.generations, 0)} />
        <Stat
          label="Best horizon"
          value={best ? best.label : "—"}
          hint={best ? `quality ${num(best.quality_score, 0)}/100` : "needs more data"}
        />
        <div className="ml-auto">
          <ActionButton
            label="Track performance"
            path="/actions/track-watchlist-performance"
            body={runId ? { run_id: runId } : undefined}
            onDone={() => reload()}
          />
        </div>
      </div>

      {r.scorecards.length === 0 ? (
        <Card title="No tracked watchlists yet">
          <p className="text-sm text-slate-400">
            Generate watchlists, then run <span className="text-slate-200">Track performance</span>{" "}
            (or load sample data) to measure how they played out.
          </p>
        </Card>
      ) : (
        <>
          <ScorecardComparison cards={r.scorecards} />
          <QualityRanking quality={r.quality} bestHorizon={r.best_horizon} />
          {best ? <Calibration quality={best} /> : null}
        </>
      )}
    </div>
  );
}

/** The Daily / Weekly / Monthly comparison — one column per horizon. */
function ScorecardComparison({ cards }: { cards: WatchlistScorecard[] }) {
  const rows: { label: string; get: (c: WatchlistScorecard) => string; cls?: (c: WatchlistScorecard) => string }[] = [
    { label: "Tracked (matured)", get: (c) => `${c.n} (${c.n_complete})` },
    { label: "Avg 1-day", get: (c) => pctCell(c.avg_ret_1d), cls: (c) => tone(c.avg_ret_1d) },
    { label: "Avg 1-week", get: (c) => pctCell(c.avg_ret_1w), cls: (c) => tone(c.avg_ret_1w) },
    { label: "Avg 1-month", get: (c) => pctCell(c.avg_ret_1m), cls: (c) => tone(c.avg_ret_1m) },
    { label: "Hit rate (1m)", get: (c) => pctCell(c.hit_rate_1m, 0) },
    { label: "Avg MFE", get: (c) => pctCell(c.avg_mfe), cls: () => "text-bull" },
    { label: "Avg MAE", get: (c) => pctCell(c.avg_mae), cls: () => "text-bear" },
    { label: "E-ratio (MFE/|MAE|)", get: (c) => (c.e_ratio == null ? "—" : `${num(c.e_ratio, 2)}×`) },
    { label: "Expected move", get: (c) => pctCell(c.avg_expected_move) },
    { label: "Move capture", get: (c) => (c.move_capture == null ? "—" : pct(c.move_capture, 0)) },
    {
      label: "Top-5 edge vs rest",
      get: (c) => (c.top_minus_rest == null ? "—" : signed(c.top_minus_rest * 100, 1) + "pp"),
      cls: (c) => tone(c.top_minus_rest),
    },
  ];
  return (
    <Card title="Daily · Weekly · Monthly — scorecard comparison">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-400">
          <tr className="border-b border-surface-border text-left">
            <th className="py-1.5 font-medium">Metric</th>
            {cards.map((c) => (
              <th key={c.horizon} className="py-1.5 text-right font-medium">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-surface-border/40">
              <td className="py-1.5 text-slate-300">{row.label}</td>
              {cards.map((c) => (
                <td key={c.horizon} className={`py-1.5 text-right ${row.cls ? row.cls(c) : ""}`}>
                  {row.get(c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/** Prediction-quality ranking — which horizon's recommendations are most useful. */
function QualityRanking({
  quality,
  bestHorizon,
}: {
  quality: WatchlistPredictionQuality[];
  bestHorizon: string | null;
}) {
  return (
    <Card title="Prediction quality — ranked">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-400">
          <tr className="border-b border-surface-border text-left">
            <th className="py-1.5 font-medium">Horizon</th>
            <th className="py-1.5 text-right font-medium">n</th>
            <th className="py-1.5 text-right font-medium">Quality</th>
            <th className="py-1.5 text-right font-medium">Conviction IC</th>
            <th className="py-1.5 text-right font-medium">Rank IC</th>
            <th className="py-1.5 text-right font-medium">Hit rate</th>
            <th className="py-1.5 text-right font-medium">Monotonic</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {quality.map((qq) => (
            <tr key={qq.horizon} className="border-b border-surface-border/40">
              <td className="py-1.5 text-slate-200">
                {qq.label}
                {qq.horizon === bestHorizon ? (
                  <span className="ml-2 rounded bg-bull/20 px-1.5 py-0.5 text-xs text-bull">best</span>
                ) : null}
              </td>
              <td className="py-1.5 text-right text-slate-400">{qq.n}</td>
              <td className="py-1.5 text-right text-slate-100">{num(qq.quality_score, 0)}/100</td>
              <td className={`py-1.5 text-right ${tone(qq.ic_conviction)}`}>
                {qq.ic_conviction == null ? "—" : num(qq.ic_conviction, 2)}
              </td>
              <td className={`py-1.5 text-right ${tone(qq.rank_ic)}`}>
                {qq.rank_ic == null ? "—" : num(qq.rank_ic, 2)}
              </td>
              <td className="py-1.5 text-right text-slate-300">{pctCell(qq.hit_rate_1m, 0)}</td>
              <td className="py-1.5 text-right">
                {qq.monotonic_calibration ? (
                  <span className="text-bull">✓</span>
                ) : (
                  <span className="text-slate-500">✗</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">
        IC = correlation of conviction / rank with realised 1-month return (higher = the ranking is
        more useful). Quality blends hit rate + ICs; 50 ≈ no skill.
      </p>
    </Card>
  );
}

function Calibration({ quality }: { quality: WatchlistPredictionQuality }) {
  const buckets = quality.calibration.filter((b) => b.count > 0);
  if (buckets.length === 0) return null;
  return (
    <Card title={`Conviction calibration — ${quality.label}`}>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-400">
          <tr className="border-b border-surface-border text-left">
            <th className="py-1.5 font-medium">Conviction</th>
            <th className="py-1.5 text-right font-medium">Count</th>
            <th className="py-1.5 text-right font-medium">Avg conviction</th>
            <th className="py-1.5 text-right font-medium">Avg 1m return</th>
            <th className="py-1.5 text-right font-medium">Hit rate</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {buckets.map((b) => (
            <tr key={b.label} className="border-b border-surface-border/40">
              <td className="py-1.5 text-slate-300">{b.label}</td>
              <td className="py-1.5 text-right text-slate-400">{b.count}</td>
              <td className="py-1.5 text-right text-slate-300">{num(b.avg_conviction, 0)}</td>
              <td className={`py-1.5 text-right ${tone(b.avg_ret_1m)}`}>{pctCell(b.avg_ret_1m)}</td>
              <td className="py-1.5 text-right text-slate-300">{pctCell(b.hit_rate, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
