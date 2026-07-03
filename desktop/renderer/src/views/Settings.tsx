import { useEffect, useState } from "react";

import { apiDelete, apiPost, apiPut } from "../api/client";
import type {
  ConfigFile,
  DataModeSettings,
  DataProviderSettings,
  UniverseList,
} from "../api/types";
import { ActionButton } from "../components/ActionButton";
import { Card } from "../components/Card";
import { DiagnosticsPanel } from "../components/DiagnosticsPanel";
import { StartupWaterfall } from "../components/StartupWaterfall";
import { TOUR_EVENT } from "../components/OnboardingTour";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { ResetPanel } from "../components/ResetPanel";
import { useApi } from "../hooks/useApi";

// Which secret fields each provider needs (yfinance needs none).
const PROVIDER_FIELDS: Record<string, { name: string; label: string }[]> = {
  yfinance: [],
  alpaca: [
    { name: "alpaca_api_key", label: "Alpaca API Key" },
    { name: "alpaca_api_secret", label: "Alpaca API Secret" },
  ],
  polygon: [{ name: "polygon_api_key", label: "Polygon API Key" }],
};

const PROVIDER_LABEL: Record<string, string> = {
  yfinance: "Yahoo Finance (no key required)",
  alpaca: "Alpaca",
  polygon: "Polygon",
};

const inputClass =
  "w-full rounded border border-surface-border bg-surface px-3 py-2 text-sm text-slate-200 " +
  "outline-none focus:border-accent";

function DataProviderPanel() {
  const { data, error, loading, reload } = useApi<DataProviderSettings>("/settings/data-provider");
  const [provider, setProvider] = useState<string>("yfinance");
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Adopt the persisted provider once loaded.
  useEffect(() => {
    if (data) setProvider(data.provider);
  }, [data]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const fields = PROVIDER_FIELDS[provider] ?? [];

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    // Send the provider plus only the non-empty key fields (blank = keep existing).
    const body: Record<string, string> = { provider };
    for (const f of fields) {
      const v = keys[f.name]?.trim();
      if (v) body[f.name] = v;
    }
    try {
      await apiPut<DataProviderSettings>("/settings/data-provider", body);
      setKeys({});
      setSaved(true);
      reload();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Data Provider">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Choose where market data comes from. Scans and backtests use this provider. Yahoo needs no
          account; Alpaca and Polygon require API keys. Keys are stored locally in a private{" "}
          <code className="text-slate-300">.env</code> file and never displayed again.
        </p>

        <div className="max-w-sm">
          <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
            Provider
          </label>
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setSaved(false);
            }}
            className={inputClass}
          >
            {data.valid_providers.map((p) => (
              <option key={p} value={p}>
                {PROVIDER_LABEL[p] ?? p}
              </option>
            ))}
          </select>
        </div>

        {fields.length === 0 ? (
          <div className="text-sm text-slate-500">No API key required for this provider.</div>
        ) : (
          <div className="grid max-w-sm gap-3">
            {fields.map((f) => {
              const present = data.keys_present[f.name];
              return (
                <div key={f.name}>
                  <label className="mb-1 flex items-center justify-between text-xs uppercase tracking-wide text-slate-400">
                    <span>{f.label}</span>
                    <span className={present ? "text-bull" : "text-slate-500"}>
                      {present ? "✓ set" : "not set"}
                    </span>
                  </label>
                  <input
                    type="password"
                    autoComplete="off"
                    value={keys[f.name] ?? ""}
                    placeholder={present ? "•••••••• (leave blank to keep)" : "Enter key"}
                    onChange={(e) => {
                      setKeys((k) => ({ ...k, [f.name]: e.target.value }));
                      setSaved(false);
                    }}
                    className={inputClass}
                  />
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={save}
            disabled={saving}
            className="rounded bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          {saved ? <span className="text-sm text-bull">Saved.</span> : null}
          {saveError ? <span className="text-sm text-bear">{saveError}</span> : null}
        </div>
      </div>
    </Card>
  );
}

function DataModePanel() {
  const { data, error, loading, reload } = useApi<DataModeSettings>("/settings/data-mode");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const setMode = async (mode: string) => {
    if (mode === data.mode) return;
    if (
      mode === "production" &&
      data.demo_rows > 0 &&
      !window.confirm(
        `Switch to Production mode? This permanently deletes ${data.demo_rows} demo rows and ` +
          `hides any seeded data from every screen. Only live Yahoo + database data will be used.`,
      )
    )
      return;
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const res = await apiPut<{ purged_total?: number }>("/settings/data-mode", { mode });
      setMsg(
        mode === "production"
          ? `Production mode on — purged ${res.purged_total ?? 0} demo rows.`
          : "Demo mode on — sample data is allowed.",
      );
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const prod = data.mode === "production";
  return (
    <Card title="Data Mode">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          <strong>Demo</strong> allows seeded sample data on every screen. <strong>Production</strong>{" "}
          uses only live Yahoo data, the database, and live scan results — demo rows are purged and
          can never be displayed. Guarantees a scan cannot accidentally show seeded data.
        </p>
        <div className="flex gap-3">
          {(data.valid_modes ?? ["demo", "production"]).map((m) => (
            <button
              key={m}
              disabled={busy}
              onClick={() => setMode(m)}
              className={`rounded px-4 py-2 text-sm capitalize disabled:opacity-50 ${
                data.mode === m
                  ? "bg-accent text-white"
                  : "border border-surface-border text-slate-300 hover:bg-surface/60"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <div className="text-xs text-slate-500">
          Current: <span className={prod ? "text-bull" : "text-slate-300"}>{data.mode}</span>
          {" · "}
          demo rows in database: <span className="tabular-nums text-slate-300">{data.demo_rows}</span>
        </div>
        {msg ? <div className="text-sm text-bull">{msg}</div> : null}
        {err ? <div className="text-sm text-bear">{err}</div> : null}
      </div>
    </Card>
  );
}

interface AutopilotSettings {
  enabled: boolean;
  starting_balance: number;
  max_open_positions: number;
  max_entries_per_cycle: number;
  min_conviction_score: number;
  include_premarket: boolean;
  prevent_sleep: boolean;
}

function AutopilotPanel() {
  const { data, error, loading, reload } = useApi<AutopilotSettings>("/settings/autopilot");
  const [balance, setBalance] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const save = async (patch: Record<string, unknown>, ok: string) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await apiPut("/settings/autopilot", patch);
      setMsg(ok);
      reload();
      // Nudge the desktop shell so the power-save blocker reacts immediately.
      void window.mrp?.automation?.sync?.().catch(() => undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async () => {
    if (
      !data.enabled &&
      !window.confirm(
        "Turn Autopilot ON? While the app is open and the market is in session, the " +
          "daemon will automatically open paper positions in the cycle's strongest " +
          "committee-approved candidates (respecting your caps), and manage them to " +
          "their stops and targets. Paper money only — no live brokerage is ever touched.",
      )
    )
      return;
    await save({ enabled: !data.enabled }, data.enabled ? "Autopilot off." : "Autopilot ON.");
  };

  const numField = (
    key: "max_open_positions" | "max_entries_per_cycle" | "min_conviction_score",
    label: string,
    hint: string,
  ) => (
    <div>
      <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">{label}</label>
      <input
        type="number"
        defaultValue={data[key]}
        disabled={busy}
        onBlur={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v) && v !== data[key]) void save({ [key]: v }, "Saved.");
        }}
        className={`${inputClass} w-28`}
      />
      <div className="mt-1 text-[11px] text-slate-500">{hint}</div>
    </div>
  );

  return (
    <Card title="Account & Autopilot">
      <div className="space-y-5">
        <div className="max-w-sm">
          <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
            Account starting balance
          </label>
          <div className="flex items-center gap-2">
            <input
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
              placeholder={String(data.starting_balance)}
              className={inputClass}
            />
            <button
              disabled={busy || !Number(balance)}
              onClick={() =>
                void save(
                  { starting_balance: Number(balance) },
                  "Balance saved — used by paper sessions and new brokerage accounts.",
                ).then(() => setBalance(""))
              }
              className="whitespace-nowrap rounded bg-accent px-3 py-2 text-sm text-white disabled:opacity-50"
            >
              Set balance
            </button>
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Paper sessions and a fresh brokerage account start from this equity. An account that
            has already traded keeps its history.
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            disabled={busy}
            onClick={() => void toggle()}
            className={`rounded px-4 py-2 text-sm font-medium disabled:opacity-50 ${
              data.enabled
                ? "bg-bull/20 text-bull border border-bull/40"
                : "border border-surface-border text-slate-300 hover:bg-surface/60"
            }`}
          >
            {data.enabled ? "Autopilot: ON" : "Autopilot: OFF"}
          </button>
          <span className="text-xs text-slate-500">
            {data.enabled
              ? "While the app is open, each market-hours scan takes the strongest committee-approved entries automatically and manages them to their stops and targets."
              : "Entries stay manual (the Take button). Scanning and management of positions you take run automatically either way."}
          </span>
        </div>

        {data.enabled ? (
          <div className="grid gap-4 md:grid-cols-3">
            {numField(
              "max_open_positions",
              "Max open positions",
              "hard cap across the whole book",
            )}
            {numField(
              "max_entries_per_cycle",
              "Max entries per scan",
              "restraint per 60-second cycle",
            )}
            {numField(
              "min_conviction_score",
              "Min conviction",
              "0–100; 70 ≈ the HIGH band",
            )}
          </div>
        ) : null}

        {data.enabled ? (
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={data.include_premarket}
              disabled={busy}
              onChange={(e) => void save({ include_premarket: e.target.checked }, "Saved.")}
            />
            Allow premarket entries (default: premarket cycles scan &amp; manage, entries wait for
            the 9:30 open)
          </label>
        ) : null}

        <div className="border-t border-surface-border pt-4">
          <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">Automation</div>
          <label className="flex items-start gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={data.prevent_sleep}
              disabled={busy}
              onChange={(e) =>
                void save(
                  { prevent_sleep: e.target.checked },
                  e.target.checked ? "System sleep will be prevented." : "OS sleep policy restored.",
                )
              }
              className="mt-0.5"
            />
            <span>
              Prevent system sleep while Auto Pilot is running
              <span className="block text-[11px] text-slate-500">
                Keeps the CPU, timers, networking, scheduler and backend running for days. The
                display may still sleep, the screen saver may still run and you can still lock
                the machine. Released automatically the moment Auto Pilot stops or the app
                closes.
              </span>
            </span>
          </label>
        </div>

        {msg ? <div className="text-sm text-bull">{msg}</div> : null}
        {err ? <div className="text-sm text-bear">{err}</div> : null}
      </div>
    </Card>
  );
}

interface ExecutionModeSettings {
  mode: string;
  valid_modes: string[];
  alpaca_keys_present: boolean;
}

const EXECUTION_LABEL: Record<string, string> = {
  internal: "Internal simulator (offline, deterministic)",
  alpaca_paper: "Alpaca paper trading (real quotes & fills)",
};

function ExecutionModePanel() {
  const { data, error, loading, reload } = useApi<ExecutionModeSettings>(
    "/settings/execution-mode",
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const setMode = async (mode: string) => {
    if (mode === data.mode) return;
    setBusy(true);
    setErr(null);
    try {
      await apiPut("/settings/execution-mode", { mode });
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Paper Execution Venue">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Which venue fills paper orders. The internal simulator works offline with deterministic
          slippage; Alpaca paper trading uses their live paper API (real market fills, still not
          real money — this app never touches a live brokerage account). Alpaca requires the same
          API keys as the Alpaca data provider.
        </p>
        <div className="flex flex-wrap gap-3">
          {data.valid_modes.map((m) => (
            <button
              key={m}
              disabled={busy}
              onClick={() => setMode(m)}
              className={`rounded px-4 py-2 text-sm disabled:opacity-50 ${
                data.mode === m
                  ? "bg-accent text-white"
                  : "border border-surface-border text-slate-300 hover:bg-surface/60"
              }`}
            >
              {EXECUTION_LABEL[m] ?? m}
            </button>
          ))}
        </div>
        {data.mode === "alpaca_paper" && !data.alpaca_keys_present ? (
          <div className="text-sm text-amber-400">
            Alpaca API keys are not set — sessions will fall back to the internal simulator until
            keys are saved under Data Provider above.
          </div>
        ) : null}
        {err ? <div className="text-sm text-bear">{err}</div> : null}
      </div>
    </Card>
  );
}

interface NotificationPrefs {
  enabled: boolean;
  min_severity: string;
  muted_kinds: string[];
  valid_severities: string[];
}

const SEVERITY_LABEL: Record<string, string> = {
  info: "Everything (info and up)",
  warning: "Important (warning and up)",
  critical: "Critical only",
};

// The alert kinds the daemon emits today (free-typed kinds still work via the API).
const KNOWN_ALERT_KINDS = [
  "trade_managed",
  "autopilot_entry",
  "conviction_change",
  "regime_change",
  "concentration",
];

function NotificationsPanel() {
  const { data, error, loading, reload } = useApi<NotificationPrefs>("/settings/notifications");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const save = async (patch: Partial<NotificationPrefs>) => {
    setBusy(true);
    setErr(null);
    try {
      await apiPut("/settings/notifications", patch);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const muted = new Set(data.muted_kinds);
  const toggleKind = (kind: string) => {
    const next = new Set(muted);
    if (next.has(kind)) next.delete(kind);
    else next.add(kind);
    void save({ muted_kinds: [...next] });
  };

  return (
    <Card title="Notifications">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Desktop notifications for market alerts — automatic trade management (stop-loss /
          take-profit), conviction upgrades and downgrades, regime changes and sector concentration
          warnings.
        </p>
        <label className="flex items-center gap-2 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={data.enabled}
            disabled={busy}
            onChange={(e) => void save({ enabled: e.target.checked })}
          />
          Show OS notifications
        </label>
        <div className="max-w-sm">
          <label className="mb-1 block text-xs uppercase tracking-wide text-slate-400">
            Notify me about
          </label>
          <select
            value={data.min_severity}
            disabled={busy || !data.enabled}
            onChange={(e) => void save({ min_severity: e.target.value })}
            className={inputClass}
          >
            {data.valid_severities.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABEL[s] ?? s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">Muted alert types</div>
          <div className="flex flex-wrap gap-2">
            {KNOWN_ALERT_KINDS.map((kind) => {
              const isMuted = muted.has(kind);
              return (
                <button
                  key={kind}
                  disabled={busy || !data.enabled}
                  onClick={() => toggleKind(kind)}
                  title={isMuted ? "Muted — click to unmute" : "Active — click to mute"}
                  className={`rounded px-2.5 py-1 text-xs disabled:opacity-50 ${
                    isMuted
                      ? "border border-surface-border text-slate-500 line-through"
                      : "border border-accent/40 bg-accent/10 text-slate-200"
                  }`}
                >
                  {kind.replace(/_/g, " ")}
                </button>
              );
            })}
          </div>
        </div>
        {err ? <div className="text-sm text-bear">{err}</div> : null}
      </div>
    </Card>
  );
}

function UniversePanel() {
  const { data, error, loading, reload } = useApi<UniverseList>("/universes");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Create/import/sector inputs.
  const [customLabel, setCustomLabel] = useState("");
  const [customText, setCustomText] = useState("");
  const [importLabel, setImportLabel] = useState("");
  const [importText, setImportText] = useState("");
  const [sector, setSector] = useState("");

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const select = (key: string) =>
    run(() => apiPut("/universes/selected", { key }), "Universe selected.");

  return (
    <Card title="Scanner Universe">
      <div className="space-y-5">
        <p className="text-sm text-slate-400">
          Choose which set of symbols the scanner fetches and ranks. Built-in index universes plus
          your own custom / imported / sector universes. The selection is saved and used by every
          scan.
        </p>

        {/* Selector + list */}
        <div className="overflow-hidden rounded border border-surface-border">
          <table className="w-full text-sm">
            <thead className="bg-surface-raised text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Universe</th>
                <th className="px-3 py-2 text-left font-medium">Kind</th>
                <th className="px-3 py-2 text-right font-medium">Symbols</th>
                <th className="px-3 py-2 text-right font-medium" />
              </tr>
            </thead>
            <tbody>
              {data.universes.map((u) => {
                const selected = u.key === data.selected;
                return (
                  <tr
                    key={u.key}
                    className={`border-b border-surface-border/40 ${
                      selected ? "bg-accent/15" : "hover:bg-surface/40"
                    }`}
                  >
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-100">
                        {u.label} {selected ? <span className="text-accent">● selected</span> : null}
                      </div>
                      {u.description ? (
                        <div className="text-xs text-slate-500">{u.description}</div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-slate-400">{u.kind}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-300">{u.size}</td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-2">
                        {!selected ? (
                          <button
                            disabled={busy}
                            onClick={() => select(u.key)}
                            className="rounded border border-surface-border px-2 py-1 text-xs text-slate-300 hover:bg-surface/60 disabled:opacity-50"
                          >
                            Select
                          </button>
                        ) : null}
                        {!u.editable && u.key !== "default" ? (
                          <button
                            disabled={busy}
                            title="Update this universe's members from the data provider (if supported)"
                            onClick={() =>
                              run(
                                () => apiPost(`/universes/${u.key}/refresh`, {}),
                                "Universe refreshed from provider.",
                              )
                            }
                            className="rounded border border-surface-border px-2 py-1 text-xs text-slate-300 hover:bg-surface/60 disabled:opacity-50"
                          >
                            Refresh
                          </button>
                        ) : null}
                        {u.editable ? (
                          <button
                            disabled={busy}
                            onClick={() =>
                              run(() => apiDelete(`/universes/${u.key}`), "Universe deleted.")
                            }
                            className="rounded border border-surface-border px-2 py-1 text-xs text-bear hover:bg-surface/60 disabled:opacity-50"
                          >
                            Delete
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Create / import / sector */}
        <div className="grid gap-4 md:grid-cols-3">
          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-slate-400">Custom watchlist</div>
            <input
              value={customLabel}
              onChange={(e) => setCustomLabel(e.target.value)}
              placeholder="Name"
              className={inputClass}
            />
            <textarea
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              placeholder="AAPL MSFT NVDA…"
              rows={3}
              className={inputClass}
            />
            <button
              disabled={busy || !customText.trim()}
              onClick={() =>
                run(
                  () =>
                    apiPost("/universes", {
                      label: customLabel || "Custom",
                      symbols: customText.split(/[\s,;]+/).filter(Boolean),
                    }),
                  "Custom universe created.",
                )
              }
              className="w-full rounded bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              Create
            </button>
          </div>

          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-slate-400">Import symbol list</div>
            <input
              value={importLabel}
              onChange={(e) => setImportLabel(e.target.value)}
              placeholder="Name"
              className={inputClass}
            />
            <textarea
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder="Paste a comma / newline separated list…"
              rows={3}
              className={inputClass}
            />
            <button
              disabled={busy || !importText.trim()}
              onClick={() =>
                run(
                  () =>
                    apiPost("/universes/import", {
                      label: importLabel || "Imported",
                      text: importText,
                    }),
                  "Symbol list imported.",
                )
              }
              className="w-full rounded bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              Import
            </button>
          </div>

          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-slate-400">Sector universe</div>
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className={inputClass}
            >
              <option value="">Select a sector…</option>
              {data.sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <button
              disabled={busy || !sector}
              onClick={() =>
                run(
                  () => apiPost("/universes/sector", { sector, base: "default" }),
                  "Sector universe created.",
                )
              }
              className="w-full rounded bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              Create from sector
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 text-sm">
          {msg ? <span className="text-bull">{msg}</span> : null}
          {err ? <span className="text-bear">{err}</span> : null}
        </div>
      </div>
    </Card>
  );
}

function ProfilesPanel() {
  const bridge = window.mrp?.profiles;
  const [state, setState] = useState<{ active: string; profiles: string[] } | null>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!bridge) return;
    bridge
      .get()
      .then(setState)
      .catch(() => setState(null));
  }, [bridge]);

  // Profiles are a desktop-shell feature (separate data dirs) — hidden on plain web.
  if (!bridge || !state) return null;

  const activate = async (name: string) => {
    if (name === state.active) return;
    if (
      !window.confirm(
        `Switch to profile "${name}"? The app restarts with that profile's own database, ` +
          `settings and history. Nothing in the current profile is lost.`,
      )
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const res = await bridge.switch(name);
      if (!res.ok) {
        setErr("invalid profile name");
        return;
      }
      await window.mrp?.relaunch?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Profiles">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Profiles keep completely separate copies of the app's data — database, trades, settings
          and API keys — under one install. Use them to run e.g. a “research” and a “live paper”
          workflow side by side. Switching restarts the app.
        </p>
        <div className="flex flex-wrap gap-2">
          {state.profiles.map((p) => (
            <button
              key={p}
              disabled={busy}
              onClick={() => void activate(p)}
              className={`rounded px-3 py-1.5 text-sm capitalize disabled:opacity-50 ${
                p === state.active
                  ? "bg-accent text-white"
                  : "border border-surface-border text-slate-300 hover:bg-surface/60"
              }`}
            >
              {p}
              {p === state.active ? " · active" : ""}
            </button>
          ))}
        </div>
        <div className="flex max-w-sm items-center gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New profile name…"
            className={inputClass}
          />
          <button
            disabled={busy || !newName.trim()}
            onClick={() => void activate(newName)}
            className="whitespace-nowrap rounded bg-accent px-3 py-2 text-sm text-white disabled:opacity-50"
          >
            Create &amp; switch
          </button>
        </div>
        {err ? <div className="text-sm text-bear">{err}</div> : null}
      </div>
    </Card>
  );
}

function flatten(obj: Record<string, unknown>, prefix = ""): [string, string][] {
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      out.push(...flatten(v as Record<string, unknown>, key));
    } else {
      out.push([key, Array.isArray(v) ? v.join(", ") : String(v)]);
    }
  }
  return out;
}

function ConfigViewer({ name }: { name: string }) {
  const { data, error, loading } = useApi<ConfigFile>(`/settings/config/${name}`);
  const [raw, setRaw] = useState(false);
  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const pairs = data.parsed ? flatten(data.parsed) : null;
  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button
          onClick={() => setRaw((r) => !r)}
          className="rounded border border-surface-border px-2 py-0.5 text-xs text-slate-400 hover:text-slate-200"
        >
          {raw ? "Show fields" : "Show raw YAML"}
        </button>
      </div>
      {raw || !pairs ? (
        <pre className="max-h-[55vh] overflow-auto rounded bg-surface p-4 text-xs leading-relaxed text-slate-300">
          {data.content}
        </pre>
      ) : (
        <div className="max-h-[55vh] overflow-auto rounded bg-surface">
          <table className="w-full text-sm">
            <tbody>
              {pairs.map(([k, v]) => (
                <tr key={k} className="border-b border-surface-border/40">
                  <td className="px-3 py-1.5 font-mono text-xs text-slate-400">{k}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-slate-200">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ConfigTemplates() {
  const { data, error, loading } = useApi<string[]>("/settings/config");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (data && data.length > 0 && selected == null) setSelected(data[0]);
  }, [data, selected]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[16rem_1fr]">
      <Card title="Files">
        <div className="flex flex-col gap-0.5">
          {(data ?? []).map((f) => (
            <button
              key={f}
              onClick={() => setSelected(f)}
              className={`rounded px-3 py-2 text-left text-sm ${
                selected === f ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-surface/60"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </Card>
      <Card title={selected ?? "Select a file"}>
        {selected ? (
          <ConfigViewer name={selected} />
        ) : (
          <div className="text-sm text-slate-500">Choose a configuration file.</div>
        )}
      </Card>
    </div>
  );
}

function Maintenance() {
  return (
    <Card title="Data & Maintenance">
      <div className="flex flex-wrap items-center gap-3">
        <ActionButton
          label="Load sample data"
          path="/actions/seed-demo"
          variant="ghost"
          onDone={() => window.location.reload()}
        />
        <ActionButton label="Refresh market data" path="/actions/refresh-data" variant="ghost" />
        <button
          onClick={() => window.dispatchEvent(new Event(TOUR_EVENT))}
          className="rounded border border-surface-border px-3 py-1.5 text-sm text-slate-300 hover:bg-surface/60"
        >
          Show getting-started tour
        </button>
        <span className="text-xs text-slate-500">
          Sample data populates every screen with a deterministic demo dataset (50 trades, signals,
          regimes, scans). Safe to run once.
        </span>
      </div>
    </Card>
  );
}


function ShadowPanel() {
  const { data, error, loading, reload } = useApi<{ enabled: boolean }>("/shadow/settings");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;

  const toggle = async () => {
    setBusy(true);
    setErr(null);
    try {
      await apiPut("/shadow/settings", { enabled: !data.enabled });
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Shadow Trading Mode">
      <div className="space-y-3">
        <p className="text-sm text-slate-400">
          While enabled, every scan records the orders the strategy <em>would</em> place —
          expected fills modeled with spread and slippage — and manages them to their stops
          and targets, <strong>never submitting anything anywhere</strong>. The Shadow screen
          grades 60 consecutive trading days of execution accuracy and expected P&amp;L
          before live trading is even a conversation.
        </p>
        <label className="flex items-center gap-2 text-sm text-slate-200">
          <input type="checkbox" checked={data.enabled} disabled={busy} onChange={toggle} />
          Enable shadow mode (records a shadow ledger on every scan)
        </label>
        {err ? <p className="text-xs text-rose-400">{err}</p> : null}
      </div>
    </Card>
  );
}


export default function Settings() {
  return (
    <div className="space-y-5 p-5">
      <PageTitle title="Settings" subtitle="Data provider, API keys, maintenance and configuration" />
      <DataProviderPanel />
      <AutopilotPanel />
      <ShadowPanel />
      <DataModePanel />
      <ExecutionModePanel />
      <NotificationsPanel />
      <ProfilesPanel />
      <UniversePanel />
      <Maintenance />
      <DiagnosticsPanel />
      <StartupWaterfall />
      <ResetPanel />
      <ConfigTemplates />
    </div>
  );
}
