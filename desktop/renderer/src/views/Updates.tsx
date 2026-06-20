import { useState } from "react";

import { apiPost } from "../api/client";
import type { RollbackResult, UpdateResult, UpdateStatus } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";

type Busy = "idle" | "updating" | "rolling-back";

export default function Updates() {
  const { data, error, loading, reload } = useApi<UpdateStatus>("/update/status");
  const [busy, setBusy] = useState<Busy>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function apply() {
    setBusy("updating");
    setMessage(null);
    setFailure(null);
    try {
      const res = await apiPost<UpdateResult>("/update/apply");
      setMessage(
        res.updated
          ? `Updated (${res.message}). Restart Momentum Lab to finish applying it.`
          : res.message,
      );
      reload();
    } catch (e: unknown) {
      setFailure(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("idle");
    }
  }

  async function rollback() {
    setBusy("rolling-back");
    setMessage(null);
    setFailure(null);
    try {
      const res = await apiPost<RollbackResult>("/update/rollback");
      setMessage(`Rolled back to ${res.commit.slice(0, 12)}. Restart Momentum Lab to apply.`);
      reload();
    } catch (e: unknown) {
      setFailure(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("idle");
    }
  }

  return (
    <div className="p-5">
      <PageTitle title="Updates" subtitle="Check for and install the latest version of Momentum Lab">
        <button
          onClick={reload}
          disabled={loading || busy !== "idle"}
          className="rounded border border-surface-border px-3 py-1.5 text-sm text-slate-300 hover:bg-surface/60 disabled:opacity-50"
        >
          Check again
        </button>
      </PageTitle>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error} />
      ) : !data ? null : (
        <div className="grid max-w-2xl grid-cols-1 gap-5">
          <Card title="Status">
            <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
              <dt className="text-slate-500">Installed version</dt>
              <dd className="text-slate-200">{data.current_version ?? "—"}</dd>
              {data.supported ? (
                <>
                  <dt className="text-slate-500">Latest version</dt>
                  <dd className="text-slate-200">{data.remote_version ?? "—"}</dd>
                  <dt className="text-slate-500">Channel</dt>
                  <dd className="text-slate-200">{data.branch ?? "—"}</dd>
                  <dt className="text-slate-500">Update available</dt>
                  <dd className={data.update_available ? "text-bull" : "text-slate-400"}>
                    {data.update_available ? `Yes — ${data.behind_by} new change(s)` : "Up to date"}
                  </dd>
                </>
              ) : (
                <>
                  <dt className="text-slate-500">In-app update</dt>
                  <dd className="text-slate-400">Not available here</dd>
                </>
              )}
            </dl>

            {!data.supported && data.reason ? (
              <p className="mt-4 rounded border border-surface-border bg-surface/60 p-3 text-xs text-slate-400">
                {data.reason}
              </p>
            ) : null}
          </Card>

          {data.supported ? (
            <Card title="Actions">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={apply}
                  disabled={!data.update_available || busy !== "idle"}
                  className="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-40"
                >
                  {busy === "updating" ? "Updating…" : "Update now"}
                </button>
                <button
                  onClick={rollback}
                  disabled={busy !== "idle"}
                  className="rounded border border-surface-border px-4 py-2 text-sm text-slate-300 hover:bg-surface/60 disabled:opacity-50"
                >
                  {busy === "rolling-back" ? "Rolling back…" : "Roll back last update"}
                </button>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                A backup is taken before every update; if anything goes wrong the change is rolled
                back automatically.
              </p>
            </Card>
          ) : null}

          {message ? (
            <div className="rounded-lg border border-bull/40 bg-bull/10 p-4 text-sm text-bull">
              {message}
            </div>
          ) : null}
          {failure ? <ErrorBox message={failure} /> : null}
        </div>
      )}
    </div>
  );
}
