import { useEffect, useRef, useState } from "react";

import { apiGet, apiPost } from "../../api/client";

/**
 * The Trade Plan Generator: search any ticker the platform knows, get the
 * complete thesis — BUY / WATCH / WAIT / AVOID with named reasons, the next
 * condition that would change the verdict (never a bare no), and the full
 * decision explainer (why this trade / why now / why not yesterday /
 * invalidation / stop / target / size / instrument). Actions: paper trade,
 * track only, watch. Everything shown comes from /command-center/search,
 * /tradeplan/{symbol} and /tradeplan/{symbol}/verdict.
 */

interface SearchHit {
  symbol: string;
  price?: number;
  sector?: string | null;
  momentum_score?: number | null;
  source: string;
}

interface VerdictOut {
  symbol: string;
  verdict: "BUY" | "WATCH" | "WAIT" | "AVOID";
  confidence: number | null;
  reasons: string[];
  next_condition: string;
  explainer: {
    why_this_trade: {
      narrative: string | null;
      strongest_factors: string[];
      momentum_score: number | null;
      sector: string | null;
    };
    why_now: string[];
    why_not_yesterday: string;
    what_would_invalidate: string[];
    what_would_improve: string[];
    what_would_reduce_conviction: string[];
    why_this_stop: string | null;
    why_this_target: string | null;
    why_this_size: string | null;
    instrument: { recommendation: string | null; reasons: string[] };
  };
}

interface PlanOut {
  symbol: string;
  entry: number;
  stop: number;
  targets: { label: string; price: number; r_multiple: number }[];
  final_reward_risk: number;
  expected_holding_days_low: number;
  expected_holding_days_high: number;
  suggested_shares: number;
  suggested_risk_dollars: number;
}

const VERDICT_TONE: Record<string, string> = {
  BUY: "bg-emerald-500/15 text-emerald-300 border-emerald-500/50",
  WATCH: "bg-sky-500/15 text-sky-300 border-sky-500/50",
  WAIT: "bg-amber-400/15 text-amber-200 border-amber-400/50",
  AVOID: "bg-rose-500/15 text-rose-300 border-rose-500/50",
};

export function PlanSearch() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    if (!query.trim()) {
      setHits([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      apiGet<SearchHit[]>(`/command-center/search?q=${encodeURIComponent(query.trim())}`)
        .then(setHits)
        .catch(() => setHits([]));
    }, 200);
  }, [query]);

  return (
    <div className="relative">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search ticker → full trade thesis…"
        className="w-64 rounded border border-surface-border bg-surface px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-accent"
      />
      {hits.length > 0 ? (
        <div className="absolute z-40 mt-1 w-72 rounded border border-surface-border bg-surface-raised shadow-2xl">
          {hits.map((hit) => (
            <button
              key={hit.symbol}
              onClick={() => {
                setOpen(hit.symbol);
                setHits([]);
                setQuery("");
              }}
              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-surface/70"
            >
              <span className="font-medium text-slate-200">{hit.symbol}</span>
              <span className="text-xs text-slate-500">
                {hit.price ? `$${hit.price.toFixed(2)} · ` : ""}
                {hit.sector ?? hit.source}
              </span>
            </button>
          ))}
        </div>
      ) : null}
      {open ? <PlanModal symbol={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

export function PlanModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [verdict, setVerdict] = useState<VerdictOut | null>(null);
  const [plan, setPlan] = useState<PlanOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);

  useEffect(() => {
    apiGet<VerdictOut>(`/tradeplan/${symbol}/verdict`)
      .then(setVerdict)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    apiGet<PlanOut>(`/tradeplan/${symbol}`)
      .then(setPlan)
      .catch(() => setPlan(null));
  }, [symbol]);

  const act = async (path: string, label: string) => {
    setAction(label);
    setOutcome(null);
    try {
      const result = await apiPost<{ ok?: boolean; error?: string }>(path, { symbol });
      setOutcome(result.ok === false ? (result.error ?? "refused") : `${label} — done.`);
    } catch (e) {
      setOutcome(e instanceof Error ? e.message : String(e));
    } finally {
      setAction(null);
    }
  };

  const e = verdict?.explainer;
  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-black/60 p-6">
      <div className="w-[720px] max-w-[95vw] rounded-xl border border-surface-border bg-surface-raised p-6 shadow-2xl">
        <div className="mb-4 flex items-center gap-3">
          <span className="text-xl font-bold text-slate-100">{symbol}</span>
          {verdict ? (
            <span
              className={`rounded border px-3 py-1 text-sm font-semibold ${VERDICT_TONE[verdict.verdict]}`}
            >
              {verdict.verdict}
              {verdict.confidence != null ? ` · ${Math.round(verdict.confidence)}` : ""}
            </span>
          ) : null}
          <button
            onClick={onClose}
            className="ml-auto rounded border border-surface-border px-3 py-1 text-sm text-slate-300 hover:bg-surface/60"
          >
            Close
          </button>
        </div>

        {error ? <p className="text-sm text-rose-400">{error}</p> : null}
        {!verdict && !error ? <p className="text-sm text-slate-500">Building the thesis…</p> : null}

        {verdict ? (
          <div className="space-y-4 text-sm">
            <section>
              <ul className="list-disc space-y-1 pl-5 text-slate-300">
                {verdict.reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
              <p className="mt-2 text-amber-200/90">
                <span className="font-medium">Next condition:</span> {verdict.next_condition}
              </p>
            </section>

            {plan ? (
              <section className="grid grid-cols-3 gap-3 rounded border border-surface-border bg-surface/50 p-3 text-xs sm:grid-cols-6">
                <PlanCell label="Ideal entry" value={plan.entry.toFixed(2)} />
                <PlanCell label="Ideal stop" value={plan.stop.toFixed(2)} />
                <PlanCell
                  label="Ideal target"
                  value={plan.targets[0] ? plan.targets[0].price.toFixed(2) : "—"}
                />
                <PlanCell label="Reward/risk" value={`${plan.final_reward_risk.toFixed(1)}R`} />
                <PlanCell
                  label="Expected hold"
                  value={`${plan.expected_holding_days_low}–${plan.expected_holding_days_high}d`}
                />
                <PlanCell label="Size" value={`${plan.suggested_shares} sh`} />
              </section>
            ) : (
              <p className="text-xs text-slate-500">
                No complete trade plan yet — it appears once a scan surfaces this symbol.
              </p>
            )}

            {e ? (
              <section className="grid gap-3 md:grid-cols-2">
                <Explain title="Why this trade" items={e.why_this_trade.strongest_factors}>
                  {e.why_this_trade.narrative}
                </Explain>
                <Explain title="Why now (and not yesterday)" items={e.why_now}>
                  {e.why_not_yesterday}
                </Explain>
                <Explain title="What would invalidate it" items={e.what_would_invalidate} />
                <Explain title="What would improve it" items={e.what_would_improve} />
                <Explain title="Why this stop / target / size">
                  {[e.why_this_stop, e.why_this_target, e.why_this_size]
                    .filter(Boolean)
                    .join(" · ") || "Plan pending — run a scan that surfaces this symbol."}
                </Explain>
                <Explain
                  title={`Instrument: ${e.instrument.recommendation ?? "not assessed"}`}
                  items={e.instrument.reasons}
                />
              </section>
            ) : null}

            <section className="flex flex-wrap items-center gap-2 border-t border-surface-border pt-3">
              <button
                disabled={!!action || verdict.verdict === "AVOID"}
                onClick={() => void act("/actions/take-trade", "Paper trade opened")}
                className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
              >
                {action === "Paper trade opened" ? "Placing…" : "Paper trade"}
              </button>
              <button
                disabled={!!action}
                onClick={() => void act("/actions/track-trade", "Now tracked")}
                className="rounded border border-surface-border px-3 py-1.5 text-xs text-slate-300 hover:bg-surface/60 disabled:opacity-40"
              >
                {action === "Now tracked" ? "Tracking…" : "Track (bot monitors, no position)"}
              </button>
              {outcome ? <span className="text-xs text-slate-400">{outcome}</span> : null}
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function PlanCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="tabular-nums text-slate-200">{value}</div>
    </div>
  );
}

function Explain({
  title,
  items,
  children,
}: {
  title: string;
  items?: string[];
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded border border-surface-border bg-surface/40 p-3">
      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </div>
      {children ? <p className="text-xs leading-relaxed text-slate-300">{children}</p> : null}
      {items && items.length ? (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-slate-400">
          {items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
