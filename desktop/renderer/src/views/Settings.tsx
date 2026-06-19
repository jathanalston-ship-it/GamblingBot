import { useEffect, useState } from "react";

import type { ConfigFile } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";

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

export default function Settings() {
  const { data, error, loading } = useApi<string[]>("/settings/config");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (data && data.length > 0 && selected == null) setSelected(data[0]);
  }, [data, selected]);

  return (
    <div>
      <PageTitle title="Settings" subtitle="Configuration templates — editing lands via a guarded write endpoint" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
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
      )}
    </div>
  );
}
