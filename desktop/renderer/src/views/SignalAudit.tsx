import type { AuditArea, AuditFactorScore, SignalAudit as Report } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { num, pct } from "../lib/format";
import { useWorkspace } from "../state/workspace";

const f = (v: number | null | undefined, d = 2): string => (v == null ? "—" : num(v, d));
const tone = (v: number | null | undefined): string =>
  v == null ? "text-slate-400" : v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-slate-300";

export default function SignalAudit() {
  const { runId } = useWorkspace();
  const q = runId ? `?run_id=${runId}` : "";
  const { data, error, loading } = useApi<Report>(`/signal-audit${q}`);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;
  const r = data;

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Signal Validation Audit"
        subtitle={`Last ${r.n_candidates} candidates-with-outcomes — conclusions gated on statistical significance`}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Candidates" value={num(r.n_candidates, 0)} hint={`${r.n_with_conviction} scored`} />
        <Stat label="Win rate" value={r.win_rate == null ? "—" : pct(r.win_rate, 0)} />
        <Stat label="Expectancy" value={`${f(r.expectancy_r)}R`} />
        <Stat label="Avg reward:risk" value={r.avg_reward_risk == null ? "—" : `${f(r.avg_reward_risk)}×`} />
        <Stat label="Max drawdown" value={`${f(r.max_drawdown_r)}R`} />
      </div>

      <Card title="Recommendations — only where statistically significant">
        <ul className="space-y-1.5 text-sm text-slate-200">
          {r.recommendations.map((rec, i) => (
            <li key={i} className="flex gap-2">
              <span className="shrink-0 text-accent">▸</span>
              <span>{rec}</span>
            </li>
          ))}
        </ul>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title="Win rate & expected value by conviction bucket">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr className="border-b border-surface-border text-left">
                <th className="py-1.5 font-medium">Conviction</th>
                <th className="py-1.5 text-right font-medium">n</th>
                <th className="py-1.5 text-right font-medium">Win rate</th>
                <th className="py-1.5 text-right font-medium">EV (R)</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {r.conviction_buckets.map((b) => (
                <tr key={b.label} className="border-b border-surface-border/40">
                  <td className="py-1.5 text-slate-300">{b.label}</td>
                  <td className="py-1.5 text-right text-slate-400">{b.n}</td>
                  <td className="py-1.5 text-right text-slate-200">
                    {b.n > 0 ? pct(b.win_rate, 0) : "—"}
                  </td>
                  <td className={`py-1.5 text-right ${tone(b.expected_value_r)}`}>
                    {b.n > 0 ? f(b.expected_value_r) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">
            Calibration: Brier {f(r.calibration.brier_score, 3)} · conviction IC{" "}
            {f(r.calibration.ic)} (p {f(r.calibration.p_value, 3)}) ·{" "}
            {r.calibration.monotonic_win_rate ? "monotonic ✓" : "non-monotonic ✗"}
          </p>
        </Card>

        <Card title="Predictive factors — ranked by |IC|">
          <FactorTable factors={r.factor_scores} />
          <p className="mt-2 text-xs text-slate-500">
            IC = correlation with realised R. <span className="text-bull">Significant</span> rows met
            p &lt; α with sufficient n; others are not shown to be predictive (not "useless").
          </p>
        </Card>
      </div>

      <Card title="Subsystem effectiveness">
        <div className="space-y-2">
          {r.areas.map((a) => (
            <AreaRow key={a.area} area={a} />
          ))}
        </div>
      </Card>

      {r.weakest_factors.length > 0 ? (
        <Card title="Weakest predictive factors (no demonstrated edge)">
          <FactorTable factors={r.weakest_factors} />
        </Card>
      ) : null}

      <Card title="Caveats">
        <ul className="space-y-1 text-xs text-slate-500">
          {r.caveats.map((c, i) => (
            <li key={i} className="flex gap-2">
              <span className="shrink-0">•</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function FactorTable({ factors }: { factors: AuditFactorScore[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-xs uppercase tracking-wide text-slate-400">
        <tr className="border-b border-surface-border text-left">
          <th className="py-1.5 font-medium">Factor</th>
          <th className="py-1.5 text-right font-medium">IC</th>
          <th className="py-1.5 text-right font-medium">p</th>
          <th className="py-1.5 text-right font-medium">n</th>
          <th className="py-1.5 text-right font-medium">Significant</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {factors.map((fc) => (
          <tr key={fc.name} className="border-b border-surface-border/40">
            <td className="py-1.5 text-slate-300">{fc.name}</td>
            <td className={`py-1.5 text-right ${tone(fc.ic)}`}>{f(fc.ic)}</td>
            <td className="py-1.5 text-right text-slate-400">{f(fc.p_value, 3)}</td>
            <td className="py-1.5 text-right text-slate-500">{fc.n}</td>
            <td className="py-1.5 text-right">
              {fc.significant ? (
                <span className="text-bull">{fc.direction}</span>
              ) : (
                <span className="text-slate-500">—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AreaRow({ area }: { area: AuditArea }) {
  return (
    <div className="flex items-start gap-3 border-b border-surface-border/40 pb-2 text-sm last:border-0">
      <span
        className={`mt-0.5 rounded px-1.5 py-0.5 text-xs font-medium ${
          area.significant ? "bg-bull/20 text-bull" : "bg-slate-600/30 text-slate-400"
        }`}
      >
        {area.significant ? "significant" : "n.s."}
      </span>
      <div>
        <div className="text-slate-200">{area.area.replace(/_/g, " ")}</div>
        <div className="text-slate-400">{area.headline}</div>
      </div>
    </div>
  );
}
