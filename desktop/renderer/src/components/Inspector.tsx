import { useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

import type { CandidateDetail } from "../api/types";
import { useApi } from "../hooks/useApi";
import { money, num, pct } from "../lib/format";
import { useWorkspace } from "../state/workspace";
import { Badge } from "./Badge";

/** The candidate aggregate panel — one fetch fills it (scan + conviction + opp + analogs + risk). */
export function Inspector({ symbol }: { symbol: string | null }) {
  if (!symbol) {
    return (
      <div className="p-6 text-sm text-slate-500">Select a candidate — click a row or press j/k.</div>
    );
  }
  return <Body symbol={symbol} />;
}

function tierTone(tier: string | undefined): "bull" | "neutral" | "default" {
  if (tier === "home_run") return "bull";
  if (tier === "enhanced") return "neutral";
  return "default";
}

function Body({ symbol }: { symbol: string }) {
  const { runId } = useWorkspace();
  const navigate = useNavigate();
  const { data, error, loading } = useApi<CandidateDetail>(
    `/candidates/${symbol}${runId ? `?run_id=${runId}` : ""}`,
  );

  if (loading) return <div className="p-6 text-sm text-slate-500">Loading {symbol}…</div>;
  if (error) return <div className="p-6 text-sm text-bear">Failed: {error}</div>;
  if (!data) return null;

  const { scan, conviction, opportunity, analogs, risk_budget } = data;

  return (
    <div className="flex flex-col gap-3 overflow-auto p-4 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="text-base font-semibold text-slate-100">{data.symbol}</span>
        {scan?.sector ? <span className="text-xs text-slate-500">{scan.sector}</span> : null}
        {opportunity ? (
          <span className="ml-auto">
            <Badge tone={tierTone(opportunity.tier)}>{opportunity.tier.replace("_", " ")}</Badge>
          </span>
        ) : null}
      </div>

      {scan ? (
        <Row>
          <Field label="Px" value={num(scan.price, 2)} />
          <Field label="RVol" value={num(scan.relative_volume, 2)} />
          <Field label="ΔATH" value={pct(scan.distance_from_ath)} />
          <Field label="Rank" value={num(scan.rank, 0)} />
        </Row>
      ) : null}

      <Divider />

      <Line
        label="Conviction"
        onClick={conviction ? () => navigate("/conviction") : undefined}
        value={
          conviction ? (
            <span className="flex items-center gap-2">
              <b className="tabular-nums text-slate-100">{num(conviction.score, 0)}</b>
              <span className="text-xs uppercase text-slate-400">{conviction.band}</span>
              <span className="text-xs text-accent">→ 3</span>
            </span>
          ) : (
            "—"
          )
        }
      />

      <Line
        label="Risk budget"
        value={
          risk_budget ? (
            <span className="tabular-nums">
              {pct(risk_budget.granted_pct)} · {money(risk_budget.risk_dollars)}
              {risk_budget.binding_constraint ? (
                <span className="ml-1 text-xs text-neutral">[{risk_budget.binding_constraint}]</span>
              ) : null}
            </span>
          ) : (
            "—"
          )
        }
      />

      <Line
        label="Analogs"
        onClick={analogs && analogs.sample_size > 0 ? () => navigate("/analogs") : undefined}
        value={
          analogs && analogs.sample_size > 0 ? (
            <span className="tabular-nums">
              n={analogs.sample_size} · exp {num(analogs.expectancy_r, 2)}R · win{" "}
              {pct(analogs.win_rate)} <span className="text-xs text-accent">→ 4</span>
            </span>
          ) : (
            "no analogs"
          )
        }
      />

      <Divider />
      <div className="flex gap-2">
        <Jump onClick={() => navigate("/conviction")}>3 Conviction</Jump>
        <Jump onClick={() => navigate("/analogs")}>4 Analogs</Jump>
        <Jump onClick={() => navigate("/backtest")}>5 Backtest</Jump>
      </div>
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-4 gap-2">{children}</div>;
}
function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="tabular-nums text-slate-200">{value}</div>
    </div>
  );
}
function Line({
  label,
  value,
  onClick,
}: {
  label: string;
  value: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`flex items-center justify-between rounded px-2 py-1 text-left ${
        onClick ? "hover:bg-surface/60" : "cursor-default"
      }`}
    >
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-200">{value}</span>
    </button>
  );
}
function Divider() {
  return <div className="border-t border-surface-border" />;
}
function Jump({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="rounded bg-accent/15 px-2 py-1 text-xs text-accent hover:bg-accent/25"
    >
      {children}
    </button>
  );
}
