import { useMemo, useState } from "react";

import type {
  AdviceReport,
  JournalEntry,
  ManagementAnalytics,
  TrackedTrade,
  TradeEvaluation,
} from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import { CloseTradeButton, TradeActions } from "../components/TradeActions";
import { PriceChart } from "../components/PriceChart";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { Stat } from "../components/Stat";
import { useApi } from "../hooks/useApi";
import { date, num, signed } from "../lib/format";

/* Health = the trade's battery percentage. Color by band. */
function healthColor(score: number | null): string {
  if (score == null) return "text-slate-400";
  if (score >= 75) return "text-emerald-400";
  if (score >= 55) return "text-accent";
  if (score >= 35) return "text-amber-400";
  return "text-bear";
}

function healthBar(score: number | null): string {
  if (score == null) return "bg-slate-600";
  if (score >= 75) return "bg-emerald-400";
  if (score >= 55) return "bg-accent";
  if (score >= 35) return "bg-amber-400";
  return "bg-bear";
}

const ACTION_CLASS: Record<string, string> = {
  Hold: "bg-slate-600/30 text-slate-300",
  "Scale In": "bg-emerald-500/20 text-emerald-300",
  "Scale Out": "bg-amber-500/20 text-amber-300",
  "Raise Stop": "bg-indigo-500/20 text-indigo-300",
  "Lower Stop": "bg-sky-500/20 text-sky-300",
  Exit: "bg-bear/20 text-bear",
};

function ActionBadge({ action }: { action: string | null }) {
  if (!action) return null;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs font-medium ${ACTION_CLASS[action] ?? "bg-surface-border text-slate-300"}`}
    >
      {action}
    </span>
  );
}

function Battery({ score }: { score: number | null }) {
  const pctWidth = Math.max(0, Math.min(100, score ?? 0));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-surface-border/60">
      <div className={`h-full ${healthBar(score)}`} style={{ width: `${pctWidth}%` }} />
    </div>
  );
}

export default function Trades() {
  const [status, setStatus] = useState<"open" | "closed">("open");
  const [selected, setSelected] = useState<string | null>(null);

  const trades = useApi<TrackedTrade[]>(`/trade-lifecycle?status=${status}`);
  const analytics = useApi<ManagementAnalytics>("/trade-lifecycle/management-analytics");

  const rows = trades.data ?? [];
  const active = rows.find((t) => t.trade_uid === selected) ?? null;

  return (
    <div className="space-y-5 p-5">
      <PageTitle
        title="Trades — Portfolio Command Center"
        subtitle="Every recommendation tracked; health is the trade's battery percentage"
      >
        <div className="flex items-center gap-2">
          <div className="flex rounded border border-surface-border text-xs">
            {(["open", "closed"] as const).map((s) => (
              <button
                key={s}
                onClick={() => {
                  setStatus(s);
                  setSelected(null);
                }}
                className={`px-2.5 py-1 capitalize ${status === s ? "bg-surface text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
              >
                {s}
              </button>
            ))}
          </div>
          <ActionButton
            label="Reevaluate now"
            path="/actions/reevaluate-trades"
            onDone={() => {
              trades.reload();
              analytics.reload();
            }}
          />
        </div>
      </PageTitle>

      {trades.loading ? (
        <Loading />
      ) : trades.error ? (
        <ErrorBox message={trades.error} />
      ) : rows.length === 0 ? (
        <Card title={`${status === "open" ? "Open" : "Closed"} trades`}>
          <div className="py-8 text-center text-sm text-slate-500">
            No {status} tracked trades yet — run a scan to turn recommendations into tracked
            trades.
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
          {rows.map((t) => (
            <button
              key={t.trade_uid}
              onClick={() => setSelected(selected === t.trade_uid ? null : t.trade_uid)}
              className={`space-y-1.5 rounded-lg border p-3 text-left ${
                selected === t.trade_uid
                  ? "border-accent ring-1 ring-accent/40"
                  : "border-surface-border hover:bg-surface/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">{t.symbol}</span>
                <ActionBadge
                  action={t.status === "closed" ? (t.close_reason ? "Exit" : null) : latestAction(t)}
                />
              </div>
              <div className={`text-2xl font-bold tabular-nums ${healthColor(t.current_health_score)}`}>
                {t.current_health_score != null ? num(t.current_health_score, 0) : "—"}
              </div>
              <Battery score={t.current_health_score} />
              <div className="text-[11px] text-slate-500">
                {t.status === "closed" && t.realized_r != null
                  ? `realized ${signed(t.realized_r, 2)}R`
                  : `since ${date(t.recommended_at)}`}
                {t.journal_trade_id != null ? (
                  <span className="ml-1 text-accent" title="taken as a paper trade">
                    ● paper
                  </span>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      )}

      {active ? <TradeDetail trade={active} onChanged={() => trades.reload()} /> : null}

      <ManagementPanel state={analytics} />
      <AdviceReportCard />
    </div>
  );
}

/** Hindsight accuracy of the reevaluation advice, judged by realized outcomes. */
function AdviceReportCard() {
  const report = useApi<AdviceReport>("/trade-lifecycle/advice-report");
  const r = report.data;
  return (
    <Card title="Advice accuracy — graded against realized outcomes">
      {report.loading ? (
        <Loading />
      ) : report.error ? (
        <ErrorBox message={report.error} />
      ) : !r || r.trades_realized === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">
          No realized outcomes yet — grades appear once a taken trade closes.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Trades realized" value={String(r.trades_realized)} />
            <Stat label="Evaluations graded" value={String(r.evaluations_graded)} />
            <Stat
              label="Overall accuracy"
              value={r.overall_accuracy != null ? `${num(r.overall_accuracy * 100, 0)}%` : "—"}
              hint="advice correct in hindsight"
            />
          </div>
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr className="border-b border-surface-border text-left">
                <th className="px-2 py-1.5 font-medium">Action</th>
                <th className="px-2 py-1.5 text-right font-medium">n</th>
                <th className="px-2 py-1.5 text-right font-medium">Correct</th>
                <th className="px-2 py-1.5 text-right font-medium">Incorrect</th>
                <th className="px-2 py-1.5 text-right font-medium">Accuracy</th>
                <th className="px-2 py-1.5 text-right font-medium">Avg remaining R</th>
              </tr>
            </thead>
            <tbody>
              {r.by_action.map((row) => (
                <tr key={row.action} className="border-b border-surface-border/40">
                  <td className="px-2 py-1.5 text-slate-200">{row.action}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">{row.n}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-emerald-400">
                    {row.correct}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-bear">
                    {row.incorrect}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                    {row.accuracy != null ? `${num(row.accuracy * 100, 0)}%` : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-400">
                    {row.avg_remaining_r != null ? signed(row.avg_remaining_r, 2) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* The card list shows current health; the freshest action lives on the trade's
   last evaluation, which the detail view loads. Cards fall back to health band. */
function latestAction(t: TrackedTrade): string | null {
  return t.trade_health === "Broken"
    ? "Exit"
    : t.trade_health === "Weakening"
      ? "Scale Out"
      : t.trade_health === "Strong"
        ? "Add?"
        : "Hold";
}

/* --------------------------------------------------------------------- */
/* Detail: thesis + time machine + health breakdown + explanation + journal */
/* --------------------------------------------------------------------- */
function TradeDetail({ trade, onChanged }: { trade: TrackedTrade; onChanged?: () => void }) {
  const evals = useApi<TradeEvaluation[]>(`/trade-lifecycle/${trade.trade_uid}/evaluations`);
  const journal = useApi<JournalEntry[]>(`/trade-lifecycle/${trade.trade_uid}/journal`);

  // API returns newest-first; the time machine slides oldest → newest.
  const timeline = useMemo(() => [...(evals.data ?? [])].reverse(), [evals.data]);
  const [idx, setIdx] = useState<number | null>(null);
  const cursor = idx ?? Math.max(0, timeline.length - 1);
  const current = timeline[cursor];

  return (
    <div className="space-y-4">
      <Card title={`${trade.symbol} — thesis`}>
        <div className="grid gap-4 md:grid-cols-[2fr,3fr]">
          <div className="space-y-2 text-sm">
            <p className="text-slate-300">{trade.thesis ?? "No thesis text recorded."}</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400">
              <span>Entry {num(trade.entry_price)}</span>
              <span>Stop {num(trade.stop_price)}</span>
              <span>
                Conviction{" "}
                {trade.conviction_score != null ? num(trade.conviction_score, 0) : "—"}
                {trade.conviction_band ? ` (${trade.conviction_band})` : ""}
              </span>
              <span>Regime {trade.regime ?? "—"}</span>
              <span>Sector {trade.sector ?? "—"}</span>
              <span>Opened {date(trade.recommended_at)}</span>
              {trade.status === "open" && trade.last_price != null ? (
                <>
                  <span title="last scan-known price — not a realtime quote">
                    Last {num(trade.last_price)}
                  </span>
                  <span
                    className={
                      (trade.unrealized_r ?? 0) >= 0 ? "text-emerald-400" : "text-bear"
                    }
                  >
                    Unrealized {trade.unrealized_r != null ? `${signed(trade.unrealized_r, 2)}R` : "—"}
                    {trade.unrealized_pnl != null ? ` (${signed(trade.unrealized_pnl, 0)})` : ""}
                  </span>
                  <span>
                    To stop{" "}
                    {trade.distance_to_stop_pct != null
                      ? `${num(trade.distance_to_stop_pct * 100, 1)}%`
                      : "—"}
                  </span>
                </>
              ) : null}
              {trade.status === "closed" ? (
                <>
                  <span>Closed {date(trade.closed_at)}</span>
                  <span>
                    {trade.realized_r != null ? `Realized ${signed(trade.realized_r, 2)}R` : ""}
                  </span>
                </>
              ) : null}
            </div>
            {trade.close_reason ? (
              <p className="text-xs text-slate-500">Close reason: {trade.close_reason}</p>
            ) : null}
            {trade.status === "open" ? (
              <div className="pt-1">
                {trade.journal_trade_id != null ? (
                  <CloseTradeButton tradeUid={trade.trade_uid} onDone={onChanged} />
                ) : (
                  <TradeActions symbol={trade.symbol} onDone={onChanged} compact />
                )}
              </div>
            ) : null}
          </div>

          {/* Time machine */}
          <div className="space-y-2">
            {evals.loading ? (
              <Loading />
            ) : evals.error ? (
              <ErrorBox message={evals.error} />
            ) : timeline.length === 0 ? (
              <div className="text-sm text-slate-500">No evaluations yet.</div>
            ) : (
              <>
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>Time machine — {date(current?.evaluated_at ?? null)}</span>
                  <span>
                    {cursor + 1} / {timeline.length}
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, timeline.length - 1)}
                  value={cursor}
                  onChange={(e) => setIdx(Number(e.target.value))}
                  className="w-full accent-indigo-400"
                />
                <div className="flex items-end gap-4">
                  <div>
                    <div
                      className={`text-4xl font-bold tabular-nums ${healthColor(current?.health_score ?? null)}`}
                    >
                      {current?.health_score != null ? num(current.health_score, 0) : "—"}
                    </div>
                    <div className="text-[11px] uppercase tracking-wide text-slate-500">
                      Trade health
                    </div>
                  </div>
                  <div className="pb-1">
                    <ActionBadge action={current?.action ?? null} />
                  </div>
                  <div className="flex-1 pb-1">
                    {/* Health history strip: every evaluation as a bar */}
                    <div className="flex h-10 items-end gap-0.5">
                      {timeline.map((ev, i) => {
                        const score = ev.health_score ?? ev.thesis_strength;
                        return (
                          <button
                            key={i}
                            onClick={() => setIdx(i)}
                            title={`${date(ev.evaluated_at)} · ${num(score, 0)}`}
                            className={`${healthBar(score)} ${i === cursor ? "opacity-100" : "opacity-40"} w-full rounded-t`}
                            style={{ height: `${Math.max(6, score)}%` }}
                          />
                        );
                      })}
                    </div>
                  </div>
                </div>
                {current?.reasons?.length ? (
                  <p className="text-xs text-slate-400">{current.reasons.join("; ")}</p>
                ) : null}
              </>
            )}
          </div>
        </div>
      </Card>

      <Card title={`${trade.symbol} — price vs plan (bars are real; last price is scan-fresh)`}>
        <PriceChart
          symbol={trade.symbol}
          overlays={[
            { label: "entry", price: trade.entry_price, kind: "entry" },
            { label: "stop", price: trade.stop_price, kind: "stop" },
            ...(trade.targets ?? [])
              .filter((t) => typeof t["price"] === "number")
              .map((t, i) => ({
                label: String(t["label"] ?? `T${i + 1}`),
                price: Number(t["price"]),
                kind: "target" as const,
              })),
          ]}
        />
      </Card>

      {current ? <ExplanationPanel evaluation={current} /> : null}

      <ManagementReportCard tradeUid={trade.trade_uid} />

      <Card title="Thesis journal — the trade's story (append-only)">
        {journal.loading ? (
          <Loading />
        ) : journal.error ? (
          <ErrorBox message={journal.error} />
        ) : (
          <ol className="space-y-0">
            {(journal.data ?? []).map((entry, i) => (
              <li
                key={i}
                className="grid grid-cols-[6.5rem,10rem,1fr] gap-2 border-b border-surface-border/40 py-1.5 text-sm last:border-0"
              >
                <span className="text-slate-500">{date(entry.at)}</span>
                <span className="flex items-center gap-2 font-medium text-slate-200">
                  {entry.label}
                  {entry.health_score != null ? (
                    <span className={`text-xs tabular-nums ${healthColor(entry.health_score)}`}>
                      {num(entry.health_score, 0)}
                    </span>
                  ) : null}
                </span>
                <span className="truncate text-xs text-slate-400" title={entry.detail ?? ""}>
                  {entry.detail ?? "—"}
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

interface ManagementEvent {
  at: string | null;
  kind: string;
  price: number | null;
  fraction: number | null;
  target_index: number | null;
  reason: string;
  analysis: string;
  evidence: Record<string, unknown>;
  health_at_decision: number | null;
  conviction_at_decision: number | null;
}

interface ManagementReport {
  trade_uid: string;
  symbol: string;
  status: string;
  targets: Record<string, unknown>[];
  close_reason: string | null;
  realized_r: number | null;
  realized_pnl: number | null;
  events: ManagementEvent[];
  summary: string;
}

const MANAGEMENT_KIND: Record<string, { label: string; tone: string }> = {
  stop_loss: { label: "STOP LOSS", tone: "bg-red-500/20 text-red-300" },
  raise_stop: { label: "STOP → BREAKEVEN", tone: "bg-sky-500/20 text-sky-300" },
  take_profit_scale: { label: "PARTIAL TAKE PROFIT", tone: "bg-emerald-500/20 text-emerald-300" },
  take_profit_final: { label: "FINAL TARGET", tone: "bg-emerald-500/20 text-emerald-300" },
};

/** How and why the system managed this trade — the automatic TP/SL record. */
function ManagementReportCard({ tradeUid }: { tradeUid: string }) {
  const report = useApi<ManagementReport>(`/trade-lifecycle/${tradeUid}/management-report`);
  if (report.loading) return null;
  if (report.error || !report.data) return null;
  const r = report.data;
  return (
    <Card title="System management — how and why the trade was managed">
      <p className="mb-3 text-sm text-slate-300">{r.summary}</p>
      {r.events.length === 0 ? null : (
        <ol className="space-y-3">
          {r.events.map((e, i) => {
            const kind = MANAGEMENT_KIND[e.kind] ?? {
              label: e.kind,
              tone: "bg-surface text-slate-300",
            };
            return (
              <li key={i} className="rounded border border-surface-border/60 p-2.5">
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
                  <span className={`rounded px-1.5 py-0.5 font-medium ${kind.tone}`}>
                    {kind.label}
                  </span>
                  <span className="text-slate-500">{date(e.at)}</span>
                  {e.price != null ? (
                    <span className="tabular-nums text-slate-400">@ {num(e.price)}</span>
                  ) : null}
                  {e.fraction != null && e.fraction < 1 ? (
                    <span className="text-slate-400">{num(e.fraction * 100, 0)}% of position</span>
                  ) : null}
                  {e.health_at_decision != null ? (
                    <span className={healthColor(e.health_at_decision)}>
                      health {num(e.health_at_decision, 0)}
                    </span>
                  ) : null}
                </div>
                <p className="text-xs leading-relaxed text-slate-400">{e.analysis}</p>
              </li>
            );
          })}
        </ol>
      )}
      {r.realized_r != null ? (
        <p className="mt-3 text-xs">
          <span className="text-slate-500">Realized outcome: </span>
          <span className={r.realized_r >= 0 ? "text-emerald-400" : "text-bear"}>
            {signed(r.realized_r, 2)}R{r.realized_pnl != null ? ` (${signed(r.realized_pnl, 0)})` : ""}
          </span>
        </p>
      ) : null}
    </Card>
  );
}

function ExplanationPanel({ evaluation }: { evaluation: TradeEvaluation }) {
  const explanation = evaluation.explanation;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Health breakdown — every point explained">
        {evaluation.health_breakdown?.length ? (
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-slate-500">
              <tr className="border-b border-surface-border text-left">
                <th className="px-1.5 py-1 font-medium">Component</th>
                <th className="px-1.5 py-1 text-right font-medium">Points</th>
                <th className="px-1.5 py-1 text-right font-medium">±</th>
                <th className="px-1.5 py-1 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.health_breakdown.map((c) => (
                <tr key={c.name} className="border-b border-surface-border/40 last:border-0">
                  <td className="px-1.5 py-1 capitalize text-slate-300">
                    {c.name.replace(/_/g, " ")}
                  </td>
                  <td className="px-1.5 py-1 text-right tabular-nums text-slate-300">
                    {num(c.earned, 1)}/{num(c.available, 0)}
                  </td>
                  <td
                    className={`px-1.5 py-1 text-right tabular-nums ${c.delta >= 0 ? "text-emerald-400" : "text-bear"}`}
                  >
                    {signed(c.delta, 1)}
                  </td>
                  <td className="px-1.5 py-1 text-slate-400">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="py-4 text-center text-xs text-slate-500">
            No health breakdown for this evaluation (pre-health history).
          </div>
        )}
      </Card>

      <Card title="Explanation — what changed & why">
        {explanation ? (
          <div className="space-y-2 text-xs">
            <div>
              <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                What changed
              </div>
              <ul className="list-inside list-disc text-slate-300">
                {explanation.what_changed.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                Confidence {explanation.confidence.direction}
              </div>
              <p className="text-slate-400">{explanation.confidence.reason}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="mb-0.5 text-[10px] uppercase tracking-wide text-emerald-400">
                  Evidence for
                </div>
                <ul className="space-y-0.5 text-slate-400">
                  {explanation.supporting.length ? (
                    explanation.supporting.map((s, i) => <li key={i}>{s}</li>)
                  ) : (
                    <li className="text-slate-600">none above neutral</li>
                  )}
                </ul>
              </div>
              <div>
                <div className="mb-0.5 text-[10px] uppercase tracking-wide text-bear">
                  Evidence against
                </div>
                <ul className="space-y-0.5 text-slate-400">
                  {explanation.contradicting.length ? (
                    explanation.contradicting.map((s, i) => <li key={i}>{s}</li>)
                  ) : (
                    <li className="text-slate-600">none below neutral</li>
                  )}
                </ul>
              </div>
            </div>
          </div>
        ) : (
          <div className="py-4 text-center text-xs text-slate-500">
            No stored explanation for this evaluation (pre-explainability history).
          </div>
        )}
      </Card>
    </div>
  );
}

/* --------------------------------------------------------------------- */
/* Phase 8 — management analytics (grades the management logic itself)     */
/* --------------------------------------------------------------------- */
function ManagementPanel({
  state,
}: {
  state: { data: ManagementAnalytics | null; loading: boolean; error: string | null };
}) {
  const a = state.data;
  return (
    <Card title="Management analytics — is the management logic improving?">
      {state.loading ? (
        <Loading />
      ) : state.error ? (
        <ErrorBox message={state.error} />
      ) : !a || a.trades_tracked === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">
          No tracked trades yet — analytics appear after the first scan.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat
              label="Avg conviction decay"
              value={a.avg_conviction_decay != null ? signed(a.avg_conviction_decay, 1) : "—"}
              hint="last vs entry conviction"
            />
            <Stat
              label="Avg trade health"
              value={a.avg_trade_health != null ? num(a.avg_trade_health, 0) : "—"}
              hint="across all evaluations"
            />
            <Stat
              label="Avg holding period"
              value={
                a.avg_holding_period_days != null ? `${num(a.avg_holding_period_days, 1)}d` : "—"
              }
              hint="closed trades"
            />
            <Stat
              label="Max thesis age"
              value={a.max_thesis_age_days != null ? `${num(a.max_thesis_age_days, 0)}d` : "—"}
            />
            <Stat
              label="Best health decile"
              value={a.most_successful_health ? a.most_successful_health.bucket : "—"}
              hint={
                a.most_successful_health
                  ? `${signed(a.most_successful_health.avg_realized_r, 2)}R over ${a.most_successful_health.trades} trades`
                  : "needs realized outcomes"
              }
            />
            <Stat
              label="Avg conviction recovery"
              value={
                a.avg_conviction_recovery != null ? signed(a.avg_conviction_recovery, 1) : "—"
              }
              hint="rebound after dips"
            />
            <Stat
              label="Avg stop raises"
              value={a.avg_stop_raises != null ? num(a.avg_stop_raises, 2) : "—"}
              hint="per trade"
            />
            <Stat
              label="Avg stop lowers"
              value={a.avg_stop_lowers != null ? num(a.avg_stop_lowers, 2) : "—"}
              hint="per trade"
            />
            <Stat
              label="Avg health before exit"
              value={a.avg_health_before_exit != null ? num(a.avg_health_before_exit, 0) : "—"}
              hint="final evaluation of closed trades"
            />
            <Stat label="Trades tracked" value={a.trades_tracked} />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <ExitList title="Best exits (loss avoided)" grades={a.best_exits} />
            <ExitList title="Worst exits (upside left behind)" grades={a.worst_exits} />
          </div>
        </div>
      )}
    </Card>
  );
}

function ExitList({ title, grades }: { title: string; grades: ManagementAnalytics["best_exits"] }) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-500">{title}</div>
      {grades.length === 0 ? (
        <div className="text-xs text-slate-600">No realized Exit advice yet.</div>
      ) : (
        <ul className="space-y-1 text-xs">
          {grades.map((g, i) => (
            <li key={i} className="flex items-center justify-between text-slate-300">
              <span>
                {g.symbol} · {date(g.evaluated_at)}
              </span>
              <span className={`tabular-nums ${g.remaining_r < 0 ? "text-emerald-400" : "text-bear"}`}>
                {signed(-g.remaining_r, 2)}R {g.remaining_r < 0 ? "saved" : "missed"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
