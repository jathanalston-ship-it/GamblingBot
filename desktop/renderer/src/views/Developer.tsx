/**
 * Developer Panel (Development Mode only).
 *
 * A single screen for testing startup/shutdown behaviour without rebuilding the
 * installer: live backend diagnostics (PID, status, health, DB/config/log paths,
 * startup stage, branch, version) plus one-click controls (restart backend, reload
 * renderer, open the logs/database folders, seed/reset local data, run the route
 * health audit, export a diagnostic bundle). Any startup failure stays visible here
 * — the panel never depends on the backend being healthy to render.
 */
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { apiGet } from "../api/client";
import { Card } from "../components/Card";
import type { DevDiagnostics } from "../vite-env";

interface HealthAudit {
  total: number;
  passed: number;
  server_errors: number;
  failed: number;
  timeouts: number;
  skipped: number;
  healthy: boolean;
}

const btn =
  "rounded border border-surface-border px-3 py-1.5 text-sm text-slate-200 hover:bg-surface/60 disabled:opacity-50";
const dangerBtn =
  "rounded border border-bear/60 px-3 py-1.5 text-sm text-bear hover:bg-bear/10 disabled:opacity-50";

export default function Developer() {
  const tools = window.mrp?.dev ? window.mrp.devtools : undefined;
  const [diag, setDiag] = useState<DevDiagnostics | null>(null);
  const [health, setHealth] = useState<"checking" | "ok" | "down">("checking");
  const [audit, setAudit] = useState<HealthAudit | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!tools) return;
    try {
      setDiag(await tools.diagnostics());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    try {
      await apiGet("/health");
      setHealth("ok");
    } catch {
      setHealth("down");
    }
  }, [tools]);

  // Poll diagnostics + health so the panel reflects backend restarts live.
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 2000);
    return () => clearInterval(id);
  }, [refresh]);

  const run = useCallback(
    async (label: string, fn: () => Promise<void>) => {
      setBusy(label);
      setNote(null);
      setError(null);
      try {
        await fn();
        setNote(`${label}: done`);
      } catch (e) {
        setError(`${label}: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setBusy(null);
        void refresh();
      }
    },
    [refresh],
  );

  if (!tools) {
    return (
      <div className="p-6">
        <Card title="Developer Panel">
          <p className="text-sm text-slate-400">
            The Developer Panel is only available in Development Mode. Launch the app with{" "}
            <code className="rounded bg-surface px-1 py-0.5 text-slate-200">npm run dev-app</code>.
          </p>
        </Card>
      </div>
    );
  }

  const seedDemo = () =>
    run("Seed demo data", async () => {
      const job = await pollJob("/actions/seed-demo");
      if (job.status === "failed") throw new Error(job.error ?? "seed failed");
    });
  const resetLocal = () =>
    run("Reset local data", async () => {
      if (!window.confirm("Wipe all local Development Mode data (DB, cache, settings, logs)?"))
        throw new Error("cancelled");
      await postJson("/actions/reset", { load_demo: false, preserve_api_keys: true });
    });
  const runAudit = () =>
    run("Health audit", async () => {
      setAudit(await apiGet<HealthAudit>("/health/routes"));
    });

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Developer Panel</h1>
        <span className="text-xs text-slate-500">auto-refreshing · Development Mode</span>
      </div>

      {/* Startup failure stays visible regardless of backend health. */}
      {diag?.startupFailure ? (
        <div className="rounded-lg border border-bear/60 bg-bear/10 p-4">
          <p className="text-sm font-semibold text-bear">
            ✗ Startup failed at stage &ldquo;{diag.startupFailure.stage}&rdquo;
          </p>
          <p className="mt-1 break-words text-xs text-slate-300">{diag.startupFailure.message}</p>
        </div>
      ) : null}

      <Card title="Diagnostics">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <Row k="Backend PID" v={diag?.backendPid ?? "—"} />
          <Row k="Backend status" v={<StatusPill status={diag?.backendStatus} />} />
          <Row k="Health endpoint" v={<HealthPill state={health} />} />
          <Row k="Startup stage" v={diag?.startupStage ?? "—"} />
          <Row k="Current branch" v={diag?.branch ?? "—"} mono />
          <Row k="Version" v={diag?.version ?? "—"} mono />
          <Row k="Database path" v={diag?.databasePath ?? "—"} mono wrap />
          <Row k="Config path" v={diag?.configPath ?? "—"} mono wrap />
          <Row k="Log path" v={diag?.logPath ?? "—"} mono wrap />
          <Row k="Health URL" v={diag?.healthUrl ?? "—"} mono wrap />
        </dl>
      </Card>

      <Card title="Controls">
        <div className="flex flex-wrap gap-2">
          <button
            className={btn}
            disabled={busy !== null}
            onClick={() =>
              run("Restart backend", async () => {
                await tools.restartBackend();
              })
            }
          >
            Restart Backend
          </button>
          <button className={btn} disabled={busy !== null} onClick={() => void tools.reloadRenderer()}>
            Reload Renderer
          </button>
          <button
            className={btn}
            disabled={busy !== null}
            onClick={() => void tools.openPath("logs")}
          >
            Open Logs Folder
          </button>
          <button
            className={btn}
            disabled={busy !== null}
            onClick={() => void tools.openPath("database")}
          >
            Open Database Folder
          </button>
          <button className={btn} disabled={busy !== null} onClick={() => void seedDemo()}>
            Seed Demo Data
          </button>
          <button className={dangerBtn} disabled={busy !== null} onClick={() => void resetLocal()}>
            Reset Local Data
          </button>
          <button className={btn} disabled={busy !== null} onClick={() => void runAudit()}>
            Run Health Audit
          </button>
          <button
            className={btn}
            disabled={busy !== null}
            onClick={() =>
              run("Export diagnostic bundle", async () => {
                await tools.exportBundle();
              })
            }
          >
            Export Diagnostic Bundle
          </button>
        </div>

        <div className="mt-3 min-h-[1.25rem] text-xs">
          {busy ? <span className="text-slate-400">{busy}…</span> : null}
          {!busy && note ? <span className="text-bull">✓ {note}</span> : null}
          {!busy && error ? <span className="text-bear">✗ {error}</span> : null}
        </div>

        {audit ? (
          <div className="mt-3 rounded border border-surface-border bg-surface/40 p-3 text-xs text-slate-300">
            Route audit:{" "}
            <span className={audit.healthy ? "text-bull" : "text-bear"}>
              {audit.healthy ? "healthy" : "unhealthy"}
            </span>{" "}
            · {audit.passed}/{audit.total} passed · {audit.server_errors} 500 · {audit.failed} fail
            · {audit.timeouts} timeout · {audit.skipped} skipped
          </div>
        ) : null}
      </Card>
    </div>
  );
}

function Row({ k, v, mono, wrap }: { k: string; v: ReactNode; mono?: boolean; wrap?: boolean }) {
  return (
    <div className="flex justify-between gap-3 border-b border-surface-border/50 py-1">
      <dt className="shrink-0 text-slate-500">{k}</dt>
      <dd
        className={`text-right text-slate-200 ${mono ? "font-mono text-xs" : ""} ${
          wrap ? "break-all" : "truncate"
        }`}
      >
        {v}
      </dd>
    </div>
  );
}

function StatusPill({ status }: { status?: string }) {
  const tone =
    status === "healthy"
      ? "text-bull"
      : status === "failed"
        ? "text-bear"
        : status === "restarting" || status === "starting"
          ? "text-amber-300"
          : "text-slate-400";
  return <span className={tone}>{status ?? "—"}</span>;
}

function HealthPill({ state }: { state: "checking" | "ok" | "down" }) {
  if (state === "ok") return <span className="text-bull">● reachable</span>;
  if (state === "down") return <span className="text-bear">✗ unreachable</span>;
  return <span className="text-slate-400">checking…</span>;
}

// -- minimal job/HTTP helpers (avoid coupling to the renderer's action hook) -- //

interface JobLike {
  id: string;
  status: string;
  error?: string | null;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${window.mrp?.apiBaseUrl ?? "http://127.0.0.1:8000"}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* no JSON body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

/** Submit a 202 job action and poll until it reaches a terminal state. */
async function pollJob(path: string): Promise<JobLike> {
  let job = await postJson<JobLike>(path, {});
  while (job.status !== "succeeded" && job.status !== "failed") {
    await new Promise((r) => setTimeout(r, 800));
    job = await apiGet<JobLike>(`/actions/jobs/${job.id}`);
  }
  return job;
}
