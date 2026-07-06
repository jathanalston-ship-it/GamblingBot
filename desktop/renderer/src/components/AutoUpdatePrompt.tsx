import { useEffect, useState } from "react";

import type { UpdatePrompt } from "../vite-env";

/**
 * The automatic-update confirmation prompt.
 *
 * When the app checks for updates on launch and finds a newer release, the main
 * process raises this ONE prompt — the new version, the download size and the
 * disk space to have free — so the user can plan before anything downloads. On
 * "Update now" the update downloads and installs automatically (the full-screen
 * UpdateOverlay then narrates the rest); "Later" defers this version; and the
 * user can turn automatic updates off entirely (falling back to the manual
 * Updates screen). No-op unless the packaged auto-updater is present.
 */
export function AutoUpdatePrompt() {
  const [prompt, setPrompt] = useState<UpdatePrompt | null>(null);

  useEffect(() => {
    const updater = window.mrp?.updater;
    if (!(window.mrp?.packaged && updater)) return;
    // Seed from any prompt already pending (the launch check can fire before this
    // component mounts), then subscribe for future ones. The seed can race handler
    // registration on startup — ignore that; onPrompt still delivers the prompt.
    void updater
      .getPending?.()
      .then((p) => {
        if (p) setPrompt(p);
      })
      .catch(() => {});
    const off = updater.onPrompt?.((p) => setPrompt(p));
    return off;
  }, []);

  if (!prompt) return null;

  const updater = window.mrp?.updater;

  const confirm = (): void => {
    // Dismiss immediately and hand off to the full-screen UpdateOverlay, which
    // narrates the unattended download → verify → install → restart from here.
    void updater?.confirm();
    setPrompt(null);
  };

  const later = (): void => {
    void updater?.defer(prompt.version);
    setPrompt(null);
  };

  const turnOff = (): void => {
    void updater?.setPrefs({ autoUpdate: false });
    setPrompt(null);
  };

  return (
    <div
      data-testid="auto-update-prompt"
      className="fixed inset-0 z-[95] flex items-center justify-center bg-[#0b1220]/90 backdrop-blur-sm"
    >
      <div className="w-[440px] max-w-[92vw] rounded-xl border border-surface-border bg-surface-raised p-7 shadow-2xl">
        <div className="mb-5 flex items-center gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-500/20 text-xl text-sky-300">
            ↑
          </div>
          <div>
            <div className="text-lg font-semibold text-slate-100">Update available</div>
            <div className="text-sm text-slate-400">
              Momentum Lab {prompt.version} is ready to install
              {prompt.releaseName ? ` — ${prompt.releaseName}` : ""}.
            </div>
          </div>
        </div>

        <dl className="mb-5 grid grid-cols-[10rem_1fr] gap-y-2 rounded-lg border border-surface-border bg-surface/50 p-4 text-sm">
          <dt className="text-slate-500">New version</dt>
          <dd className="text-slate-200">{prompt.version}</dd>
          <dt className="text-slate-500">Download size</dt>
          <dd className="text-slate-200">{prompt.downloadLabel}</dd>
          <dt className="text-slate-500">Recommended free space</dt>
          <dd className="text-slate-200">{prompt.recommendedFreeLabel}</dd>
        </dl>

        <p className="mb-5 text-xs text-slate-500">
          {prompt.sizeKnown
            ? "The update downloads in the background and verifies its checksum, then the app restarts to finish installing. Your data is preserved."
            : "The release size could not be read; the update will still download, verify and install automatically. Your data is preserved."}
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={confirm}
            className="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90"
          >
            Update now
          </button>
          <button
            onClick={later}
            className="rounded border border-surface-border px-4 py-2 text-sm text-slate-300 hover:bg-surface/60"
          >
            Later
          </button>
          <button
            onClick={turnOff}
            className="ml-auto text-xs text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
          >
            Turn off automatic updates
          </button>
        </div>
      </div>
    </div>
  );
}
