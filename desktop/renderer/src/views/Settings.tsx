import { useEffect, useState } from "react";

import { apiPut } from "../api/client";
import type { ConfigFile, DataProviderSettings } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
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

function ConfigViewer({ name }: { name: string }) {
  const { data, error, loading } = useApi<ConfigFile>(`/settings/config/${name}`);
  if (loading) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;
  return (
    <pre className="max-h-[60vh] overflow-auto rounded bg-surface p-4 text-xs leading-relaxed text-slate-300">
      {data.content}
    </pre>
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

export default function Settings() {
  return (
    <div className="space-y-5">
      <PageTitle title="Settings" subtitle="Data provider, API keys and configuration templates" />
      <DataProviderPanel />
      <ConfigTemplates />
    </div>
  );
}
