import { Link } from "react-router-dom";

import type {
  OptionsEligibility,
  OptionsRecommendation,
  TradePlan as Plan,
} from "../api/types";
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

      {/* structure levels driving the stop/targets */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm text-slate-400">
        <span>
          Structure:{" "}
          <span className="text-bull">
            support {data.structural_support != null ? money(data.structural_support) : "—"}
          </span>{" "}
          ·{" "}
          <span className="text-bear">
            resistance {data.overhead_resistance != null ? money(data.overhead_resistance) : "—"}
          </span>
        </span>
        <span className="text-xs text-slate-500">
          stops &amp; targets snap to swing pivots (EMA fallback when none)
        </span>
      </div>

      <OptionsEligibilityCard symbol={data.symbol} runId={runId} />

      <OptionsRecommendationCard symbol={data.symbol} runId={runId} />

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

const STATUS_DOT: Record<string, string> = {
  pass: "bg-bull",
  warn: "bg-amber-400",
  fail: "bg-bear",
};

function OptionsEligibilityCard({ symbol, runId }: { symbol: string; runId: string | null }) {
  const { data, error, loading } = useApi<OptionsEligibility>(
    `/options-eligibility/${symbol}${runId ? `?run_id=${runId}` : ""}`,
  );
  if (loading || error || !data) return null; // optional panel — stay quiet if unavailable

  const lev = data.eligible;
  return (
    <Card title="Options Eligibility">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`rounded px-2.5 py-1 text-sm font-semibold ${
              lev ? "bg-bull/20 text-bull" : "bg-slate-600/30 text-slate-300"
            }`}
          >
            {data.recommendation}
          </span>
          <span className="text-sm text-slate-400">
            confidence <span className="tabular-nums text-slate-100">{num(data.confidence, 0)}</span>
            /100
          </span>
          <span className="text-sm text-slate-500">{data.summary}</span>
        </div>
        <div className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {data.factors.map((f) => (
            <div key={f.name} className="flex items-center gap-2 text-sm">
              <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[f.status] ?? "bg-slate-500"}`} />
              <span className="w-28 shrink-0 text-slate-300">{f.label}</span>
              <span className="truncate text-xs text-slate-500" title={f.detail}>
                {f.detail}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

const RISK_TONE: Record<string, string> = {
  Low: "bg-bull/20 text-bull",
  Medium: "bg-amber-400/20 text-amber-300",
  High: "bg-bear/20 text-bear",
};

function OptionsRecommendationCard({ symbol, runId }: { symbol: string; runId: string | null }) {
  const { data, error, loading } = useApi<OptionsRecommendation>(
    `/options-recommendation/${symbol}${runId ? `?run_id=${runId}` : ""}`,
  );
  if (loading || error || !data) return null; // optional panel — stay quiet if unavailable

  const c = data.contract;
  const rec = data.recommended;
  return (
    <Card title="Options Recommendation">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`rounded px-2.5 py-1 text-sm font-semibold ${
              rec ? "bg-bull/20 text-bull" : "bg-slate-600/30 text-slate-300"
            }`}
          >
            {rec && c ? c.display : "No recommendation"}
          </span>
          {rec && c ? (
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                RISK_TONE[c.risk_level] ?? "bg-slate-600/30 text-slate-300"
              }`}
            >
              {c.risk_level} risk
            </span>
          ) : null}
          <span className="text-sm text-slate-500">{data.summary}</span>
        </div>

        {rec && c ? (
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            <Field label="Expiration" value={`~${c.expiration_days}d`} />
            <Field
              label="Strike"
              value={c.short_strike != null ? `${money(c.strike)} / ${money(c.short_strike)}` : money(c.strike)}
              hint={c.short_strike != null ? "long / short" : undefined}
            />
            <Field
              label="Delta"
              value={c.short_delta != null ? `${num(c.delta, 2)} / ${num(c.short_delta, 2)}` : num(c.delta, 2)}
            />
            <Field
              label="Reward : Risk"
              value={c.reward_to_risk != null ? `${num(c.reward_to_risk, 1)}R` : "—"}
            />
            <Field label="Max Loss" value={money(c.max_loss)} />
            <Field label="Target Profit" value={money(c.target_profit)} />
            <Field
              label="Allocation"
              value={c.contracts > 0 ? `${c.contracts}×` : "—"}
              hint={
                c.contracts > 0
                  ? `${money(c.suggested_allocation)} · ${pct(c.allocation_pct, 1)} equity`
                  : `≈ ${money(c.est_premium_per_contract)}/contract`
              }
            />
            <Field label="Premium / contract" value={money(c.est_premium_per_contract)} />
          </div>
        ) : null}

        {/* avoid gates */}
        <div className="flex flex-wrap gap-x-5 gap-y-1.5 border-t border-surface-border pt-2.5">
          {data.gates.map((g) => (
            <div key={g.name} className="flex items-center gap-2 text-xs">
              <span className={`h-2 w-2 shrink-0 rounded-full ${g.passed ? "bg-bull" : "bg-bear"}`} />
              <span className="text-slate-500" title={g.detail}>
                {g.name.replace(/_/g, " ")}
              </span>
            </div>
          ))}
        </div>

        {/* risk disclosures */}
        <ul className="space-y-1 text-xs text-slate-500">
          {data.risk_disclosures.map((d, i) => (
            <li key={i} className="flex gap-2">
              <span className="shrink-0 text-slate-600">⚠</span>
              <span>{d}</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
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
