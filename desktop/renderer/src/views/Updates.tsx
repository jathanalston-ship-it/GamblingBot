import { useCallback, useEffect, useRef, useState } from "react";

import { apiPost } from "../api/client";
import type { RollbackResult, UpdateResult, UpdateStatus } from "../api/types";
import { Card } from "../components/Card";
import { ErrorBox, Loading, PageTitle } from "../components/Page";
import { useApi } from "../hooks/useApi";
import type { UpdateDiagnostics } from "../vite-env";

/**
 * Updates screen. In the **packaged** desktop build it drives the in-app
 * auto-updater (electron-updater) over the preload bridge; in a source/dev
 * install it falls back to the git-based self-update backend (`/update/*`).
 */
export default function Updates() {
  const packaged = window.mrp?.packaged === true && !!window.mrp?.updater;
  return packaged ? <PackagedUpdates /> : <SourceUpdates />;
}

/* ── Packaged build: electron-updater ───────────────────────────────────── */

type UpdState =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "downloaded"
  | "uptodate"
  | "error";

function PackagedUpdates() {
  const installed = window.mrp?.version ?? "—";
  const [state, setState] = useState<UpdState>("idle");
  const [version, setVersion] = useState<string | null>(null);
  const [percent, setPercent] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [diag, setDiag] = useState<UpdateDiagnostics | null>(null);
  const busy = useRef(false);

  // Pull the live feed diagnostics (config + a real probe of the release feed) so a
  // failure is explained, never suppressed.
  const loadDiagnostics = useCallback((): void => {
    void window.mrp?.updater?.diagnostics().then(setDiag).catch(() => setDiag(null));
  }, []);

  const check = useCallback((): void => {
    const updater = window.mrp?.updater;
    if (!updater) return;
    setErr(null);
    setState("checking");
    loadDiagnostics();
    void updater.check().catch((e: unknown) => {
      setErr(e instanceof Error ? e.message : String(e));
      setState("error");
    });
  }, [loadDiagnostics]);

  // Subscribe to updater events, then kick off an initial check.
  useEffect(() => {
    const updater = window.mrp?.updater;
    if (!updater) return;
    const off = updater.onEvent((e) => {
      switch (e.kind) {
        case "checking":
          setState("checking");
          break;
        case "available":
          setVersion(e.payload?.version ?? null);
          setState("available");
          break;
        case "not-available":
          setVersion(e.payload?.version ?? null);
          setState("uptodate");
          break;
        case "progress":
          setPercent(Math.round(e.payload?.percent ?? 0));
          setState("downloading");
          break;
        case "downloaded":
          setVersion(e.payload?.version ?? null);
          setState("downloaded");
          break;
        case "error":
          setErr(
            e.payload?.statusCode
              ? `${e.payload?.message ?? "Update failed."} (HTTP ${e.payload.statusCode})`
              : (e.payload?.message ?? "Update failed."),
          );
          setState("error");
          loadDiagnostics(); // re-probe so the screen explains the failure
          break;
      }
    });
    check();
    return off;
  }, [check, loadDiagnostics]);

  const download = (): void => {
    const updater = window.mrp?.updater;
    if (!updater || busy.current) return;
    busy.current = true;
    setErr(null);
    setState("downloading");
    setPercent(0);
    void updater
      .download()
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e));
        setState("error");
      })
      .finally(() => {
        busy.current = false;
      });
  };

  const install = (): void => {
    void window.mrp?.updater?.install();
  };

  return (
    <div className="p-5">
      <PageTitle title="Updates" subtitle="Check for and install the latest version of Momentum Lab">
        <button
          onClick={check}
          disabled={state === "checking" || state === "downloading"}
          className="rounded border border-surface-border px-3 py-1.5 text-sm text-slate-300 hover:bg-surface/60 disabled:opacity-50"
        >
          {state === "checking" ? "Checking…" : "Check again"}
        </button>
      </PageTitle>

      <div className="grid max-w-2xl grid-cols-1 gap-5">
        <Card title="Status">
          <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
            <dt className="text-slate-500">Installed version</dt>
            <dd className="text-slate-200">{installed}</dd>
            <dt className="text-slate-500">Latest version</dt>
            <dd className="text-slate-200">{version ?? "—"}</dd>
            <dt className="text-slate-500">Status</dt>
            <dd className={statusClass(state)}>{statusLabel(state, percent)}</dd>
          </dl>
          {state === "downloading" ? (
            <div className="mt-3 h-2 w-full overflow-hidden rounded bg-surface">
              <div className="h-full bg-accent transition-all" style={{ width: `${percent}%` }} />
            </div>
          ) : null}
        </Card>

        <Card title="Actions">
          <div className="flex flex-wrap items-center gap-3">
            {state === "downloaded" ? (
              <button
                onClick={install}
                className="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
              >
                Restart &amp; install
              </button>
            ) : (
              <button
                onClick={download}
                disabled={state !== "available"}
                className="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-40"
              >
                {state === "downloading" ? `Downloading… ${percent}%` : "Download update"}
              </button>
            )}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Updates download from the official GitHub release and verify their checksum before
            installing. A downloaded update also installs automatically the next time you quit.
          </p>
        </Card>

        {err ? (
          <div className="rounded-lg border border-bear/40 bg-bear/10 p-4 text-sm text-bear">
            <div className="font-medium">Update check failed</div>
            <div className="mt-1 break-words font-mono text-xs text-bear/90">{err}</div>
            <div className="mt-2 text-xs text-slate-400">
              You can always update manually: download the latest{" "}
              <span className="text-slate-200">MomentumLab-Setup-*.exe</span> from the project's
              GitHub Releases and run it (your data is preserved).
            </div>
          </div>
        ) : null}

        <UpdateDiagnosticsCard diag={diag} onRefresh={loadDiagnostics} />
      </div>
    </div>
  );
}

/** Detailed, non-suppressed diagnostics: the resolved feed config + a live probe. */
function UpdateDiagnosticsCard({
  diag,
  onRefresh,
}: {
  diag: UpdateDiagnostics | null;
  onRefresh: () => void;
}) {
  const probe = diag?.probe ?? null;
  const probeTone =
    probe == null ? "text-slate-400" : probe.ok ? "text-bull" : "text-bear";
  return (
    <Card
      title="Diagnostics"
      action={
        <button
          onClick={onRefresh}
          className="rounded border border-surface-border px-2 py-1 text-xs text-slate-300 hover:bg-surface/60"
        >
          Re-probe feed
        </button>
      }
    >
      <dl className="grid grid-cols-[9rem_1fr] gap-y-1.5 text-xs">
        <dt className="text-slate-500">Provider</dt>
        <dd className="text-slate-200">{diag?.provider ?? "—"}</dd>
        <dt className="text-slate-500">Repository</dt>
        <dd className="text-slate-200">
          {diag?.owner && diag?.repo ? `${diag.owner}/${diag.repo}` : "—"}
        </dd>
        <dt className="text-slate-500">Release feed</dt>
        <dd className="break-all font-mono text-slate-300">{diag?.feedUrl ?? "—"}</dd>
        <dt className="text-slate-500">Feed probe</dt>
        <dd className={probeTone}>
          {probe ? `HTTP ${probe.status}${probe.ok ? " — reachable" : ""}` : "—"}
        </dd>
        <dt className="text-slate-500">Current version</dt>
        <dd className="text-slate-200">{diag?.currentVersion ?? "—"}</dd>
        <dt className="text-slate-500">Access token</dt>
        <dd className="text-slate-200">{diag?.tokenConfigured ? "configured" : "none"}</dd>
        {diag?.autoUpdateDisabled ? (
          <>
            <dt className="text-slate-500">Auto-update</dt>
            <dd className="text-amber-300">disabled (MRP_DISABLE_AUTOUPDATE=1)</dd>
          </>
        ) : null}
      </dl>
      {probe && !probe.ok ? (
        <p className="mt-3 rounded border border-bear/30 bg-bear/5 p-2 text-xs text-bear/90">
          {probe.interpretation}
        </p>
      ) : null}
    </Card>
  );
}

function statusLabel(state: UpdState, percent: number): string {
  switch (state) {
    case "checking":
      return "Checking for updates…";
    case "available":
      return "Update available";
    case "downloading":
      return `Downloading… ${percent}%`;
    case "downloaded":
      return "Downloaded — ready to install";
    case "uptodate":
      return "Up to date";
    case "error":
      return "Update failed";
    default:
      return "—";
  }
}

function statusClass(state: UpdState): string {
  if (state === "available" || state === "downloaded") return "text-bull";
  if (state === "error") return "text-bear";
  return "text-slate-400";
}

/* ── Source/dev install: git-based self-update (/update/*) ───────────────── */

type Busy = "idle" | "updating" | "rolling-back";

function SourceUpdates() {
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
