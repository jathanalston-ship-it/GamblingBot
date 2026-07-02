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
        <span className="text-xs text-slate-500">
          Sample data populates every screen with a deterministic demo dataset (50 trades, signals,
          regimes, scans). Safe to run once.
        </span>
      </div>
    </Card>
  );
}

export default function Settings() {
  return (
    <div className="space-y-5 p-5">
      <PageTitle title="Settings" subtitle="Data provider, API keys, maintenance and configuration" />
      <DataProviderPanel />
      <DataModePanel />
      <UniversePanel />
      <Maintenance />
      <DiagnosticsPanel />
      <ResetPanel />
      <ConfigTemplates />
    </div>
  );
}
