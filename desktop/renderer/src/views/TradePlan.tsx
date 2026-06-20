import { Link } from "react-router-dom";

import type { TradePlan as Plan } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { money, num, pct } from "../lib/format";
import { useWorkspace } from "../state/workspace";

export default function TradePlan() {
  const { runId, symbol } = useWorkspace();
  if (!symbol) {
    return (
      <div className="p-6 text-sm text-slate-500">
        No symbol selected — pick a candidate in{" "}
        <Link className="text-accent" to="/scan">
          Scan
        </Link>
        .
      </div>
    );
  }
  return <Body symbol={symbol} runId={runId} />;
}

function Body({ symbol, runId }: { symbol: string; runId: string | null }) {
  const { data, error, loading } = useApi<Plan>(
    `/tradeplan/${symbol}${runId ? `?run_id=${runId}` : ""}`,
  );

  if (loading) return <Loading />;
  if (error)
    return (
      <div className="p-5">
        <PageTitle title={`Trade Plan · ${symbol}`} subtitle="Derived plan — no order is placed" />
        <ErrorBox message={`No plan for ${symbol} — needs a scan with price + ATR. (${error})`} />
      </div>
    );
  if (!data) return null;

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title={`Trade Plan · ${data.symbol}`}
        subtitle="Derived from ATR, support, analogs, volatility & regime — no order is placed"
      />

      {/* headline numbers */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Entry" value={money(data.entry)} />
        <Stat
          label="Stop"
          value={money(data.stop)}
          hint={`${pct(data.stop_pct, 1)} · risk ${money(data.risk_per_share)}/sh`}
        />
        <Stat
          label="Reward : Risk"
          value={`${num(data.blended_reward_risk, 2)}R`}
          hint={`blended · ${num(data.final_reward_risk, 1)}R to T3`}
        />
        <Stat
          label="Hold"
          value={`${data.expected_holding_days_low}–${data.expected_holding_days_high}d`}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* trade plan: targets + sizing */}
        <Card title="Trade Plan">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr className="border-b border-surface-border text-left">
                <th className="py-1.5 font-medium">Level</th>
                <th className="py-1.5 text-right font-medium">Price</th>
                <th className="py-1.5 text-right font-medium">R</th>
                <th className="py-1.5 text-right font-medium">Gain</th>
                <th className="py-1.5 text-right font-medium">Scale</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              <tr className="border-b border-surface-border/40">
                <td className="py-1.5 font-medium text-slate-200">Entry</td>
                <td className="py-1.5 text-right">{money(data.entry)}</td>
                <td className="py-1.5 text-right text-slate-500">—</td>
                <td className="py-1.5 text-right text-slate-500">—</td>
                <td className="py-1.5 text-right text-slate-500">in</td>
              </tr>
              {data.targets.map((t) => (
                <tr key={t.label} className="border-b border-surface-border/40">
                  <td className="py-1.5 font-medium text-bull">{t.label}</td>
                  <td className="py-1.5 text-right">{money(t.price)}</td>
                  <td className="py-1.5 text-right text-bull">{num(t.r_multiple, 1)}R</td>
                  <td className="py-1.5 text-right text-slate-300">{pct(t.gain_pct, 1)}</td>
                  <td className="py-1.5 text-right text-slate-400">
                    {Math.round(t.scale_out_pct * 100)}%
                  </td>
                </tr>
              ))}
              <tr>
                <td className="py-1.5 font-medium text-bear">Stop</td>
                <td className="py-1.5 text-right text-bear">{money(data.stop)}</td>
                <td className="py-1.5 text-right text-bear">-1R</td>
                <td className="py-1.5 text-right text-bear">{pct(-data.stop_pct, 1)}</td>
                <td className="py-1.5 text-right text-slate-400">out</td>
              </tr>
            </tbody>
          </table>
          <div className="mt-3 grid grid-cols-3 gap-3 border-t border-surface-border pt-3 text-sm">
            <Field label="Size" value={`${num(data.suggested_shares, 0)} sh`} />
            <Field label="Position" value={money(data.suggested_position_value)} />
            <Field
              label="Portfolio risk"
              value={`${pct(data.suggested_portfolio_risk_pct, 2)}`}
              hint={money(data.suggested_risk_dollars)}
            />
          </div>
        </Card>

        {/* reward summary */}
        <Card title="Reward Summary">
          <BulletList items={data.reward_summary} tone="bull" />
        </Card>

        {/* risk summary */}
        <Card title="Risk Summary">
          <BulletList items={data.risk_summary} tone="muted" />
        </Card>

        {/* failure conditions */}
        <Card title="Failure Conditions — invalidation">
          <BulletList items={data.failure_conditions} tone="bear" />
        </Card>
      </div>

      <p className="text-xs text-slate-500">{data.methodology.join(" · ")}</p>
    </div>
  );
}

function Field({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="tabular-nums text-slate-100">{value}</div>
      {hint ? <div className="text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

function BulletList({ items, tone }: { items: string[]; tone: "bull" | "bear" | "muted" }) {
  const dot = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-slate-500";
  if (items.length === 0)
    return <div className="text-sm text-slate-500">—</div>;
  return (
    <ul className="space-y-1.5 text-sm text-slate-300">
      {items.map((s, i) => (
        <li key={i} className="flex gap-2">
          <span className={`${dot} shrink-0`}>•</span>
          <span>{s}</span>
        </li>
      ))}
    </ul>
  );
}
