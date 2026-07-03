/**
 * Electron main process for Momentum Lab.
 *
 * Owns the FastAPI backend lifecycle via `BackendManager`:
 *   1. Spawn (or adopt an already-running) backend and verify GET /health.
 *   2. Show the window immediately with a loading screen until the backend is healthy.
 *   3. Recover (bounded respawn) if the backend crashes; reload the window on recovery.
 *   4. Graceful → wait → force shutdown of the whole process tree on quit, with
 *      synchronous safety nets for crashes and a backend-side parent watchdog so the
 *      sidecar can never be orphaned.
 *
 * Security: contextIsolation on, nodeIntegration off; the renderer talks to the
 * backend only over http://127.0.0.1:<port> via the typed preload bridge.
 */
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  watch,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:net";
import {
  appendHistory,
  computeStats,
  recordFromTrace,
  waterfall,
  type LaunchRecord,
  type StageSample,
} from "./startup-metrics";
import { UpdateFlow, type SerializedUpdateFlow, type UpdateFlowEvent } from "./update-flow";
import { dirname, join } from "node:path";

import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  type MenuItemConstructorOptions,
  powerSaveBlocker,
  shell,
} from "electron";
// electron-updater is a CommonJS module whose `autoUpdater` is a LAZY named
// export (a getter) and which has NO default export. A default import resolves to
// `.default` (undefined) and crashes the PACKAGED app at startup
// ("Cannot destructure property 'autoUpdater' of … default … undefined"). Import
// it by name so it is resolved lazily, at the call site, inside the packaged guard.
import { autoUpdater } from "electron-updater";

import { AutomationManager } from "./automation";
import { BackendManager, type BackendStatus } from "./backend-manager";
import {
  DEFAULT_PROFILE,
  PORTABLE_MARKER,
  PROFILE_FILE,
  PROFILES_DIR,
  profileDataRoot,
  resolveDataRoot,
  sanitizeProfileName,
} from "./paths";
import { StartupTrace } from "./startup-trace";

const API_HOST = "127.0.0.1";
const isDev = process.env.NODE_ENV === "development";
// CI startup validation: boot the window from the built renderer WITHOUT the
// backend, confirm it paints, print a sentinel and exit. Set by `npm run smoke`.
const isSmoke = process.env.MRP_SMOKE === "1";
// Development Mode (`npm run dev-app`): runs from source with a visible banner, a
// Developer Panel, and backend auto-restart on Python changes. Isolated state.
const isDevApp = process.env.MRP_DEV_APP === "1";
const SHUTDOWN_TIMEOUT_MS = 5_000; // graceful window before force-killing the tree

let win: BrowserWindow | null = null;
// Automation Mode: one power-save blocker while Auto Pilot runs; never leaks
// past the process (released on quit/crash paths; the OS drops it on death).
const automation = new AutomationManager(powerSaveBlocker, (line) => console.log(line));
let automationTimer: NodeJS.Timeout | null = null;

/** Reconcile the sleep blocker with the backend's persisted autopilot state. */
async function syncAutomation(): Promise<void> {
  try {
    const res = await fetch(`http://${API_HOST}:${apiPort}/settings/autopilot`);
    if (!res.ok) return;
    const body = (await res.json()) as { enabled?: boolean; prevent_sleep?: boolean };
    automation.sync(body.enabled === true, body.prevent_sleep !== false);
    // Resilience: when Auto Pilot is on, relaunch at login so an OS restart
    // resumes the loop as soon as the user signs back in (packaged only).
    if (app.isPackaged && !isPortable()) {
      app.setLoginItemSettings({ openAtLogin: body.enabled === true });
    }
  } catch {
    // backend restarting — keep the current blocker state, retry next tick
  }
}

function startAutomationSync(): void {
  void syncAutomation();
  automationTimer = setInterval(() => void syncAutomation(), 60_000);
  automationTimer.unref?.();
}
let apiPort = 8000;
let manager: BackendManager | null = null;
let lastBackendStatus: BackendStatus = "starting";
let cleanupRan = false;
let windowShown = false;

// Forensic startup trace: every main-process startup stage with timestamps, so a
// launch that dies before the window appears (blue cursor → nothing) names the
// exact stage it failed at instead of vanishing. Created at module load so even
// the single-instance-lock stage is captured. Folded into the startup report.
const trace = new StartupTrace({ log: (line) => console.error(line) });
trace.enter("module-init");

/** Find a free loopback TCP port (prod), so a busy 8000 never blocks launch. */
function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, API_HOST, () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

/** The repo root when running from source (`dist-electron/` is two levels deep). */
function repoRoot(): string {
  return join(__dirname, "..", "..");
}

/**
 * Whether this is a PORTABLE build: a packaged app extracted from
 * `MomentumLab-Portable.zip`, identified by a marker file shipped beside the
 * executable (only in the zip, never in the installer). Portable builds keep all
 * state — including startup logs — beside the executable, so a release candidate
 * runs with no install, no registry and no uninstall. Memoised.
 */
let portableCache: boolean | null = null;
function isPortable(): boolean {
  if (portableCache !== null) return portableCache;
  try {
    // electron-builder's own portable target also sets this; honour it too.
    if (process.env.PORTABLE_EXECUTABLE_DIR) {
      portableCache = true;
    } else {
      portableCache =
        app.isPackaged && existsSync(join(dirname(app.getPath("exe")), PORTABLE_MARKER));
    }
  } catch {
    portableCache = false;
  }
  return portableCache;
}

/** The mode-resolved BASE data root (before the profile subdirectory). */
function baseDataRoot(): string {
  return resolveDataRoot({
    isDevApp,
    isPortable: isPortable(),
    repoRoot: repoRoot(),
    exeDir: app.isPackaged ? dirname(app.getPath("exe")) : repoRoot(),
    userDataDir: app.getPath("userData"),
  });
}

// -------------------------------------------------------------------------- //
// Profiles: isolated data roots (own DB / logs / settings) under one install.
// The active profile is recorded in `<baseRoot>/profile.json`; switching it
// takes effect on relaunch (the backend is spawned with the profile's root).
// -------------------------------------------------------------------------- //
let profileCache: string | null = null;

function activeProfile(): string {
  if (profileCache !== null) return profileCache;
  try {
    const raw = readFileSync(join(baseDataRoot(), PROFILE_FILE), "utf-8");
    const parsed: unknown = JSON.parse(raw);
    const name =
      parsed && typeof parsed === "object" && "active" in parsed
        ? sanitizeProfileName(String((parsed as { active: unknown }).active))
        : null;
    profileCache = name ?? DEFAULT_PROFILE;
  } catch {
    profileCache = DEFAULT_PROFILE;
  }
  return profileCache;
}

function listProfiles(): string[] {
  const names = new Set<string>([DEFAULT_PROFILE, activeProfile()]);
  try {
    const dir = join(baseDataRoot(), PROFILES_DIR);
    if (existsSync(dir)) {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) names.add(entry.name);
      }
    }
  } catch {
    // unreadable profiles dir — the defaults still work
  }
  return [...names].sort();
}

function setActiveProfile(name: string): string | null {
  const cleaned = sanitizeProfileName(name);
  if (!cleaned) return null;
  const base = baseDataRoot();
  mkdirSync(profileDataRoot(base, cleaned), { recursive: true });
  writeFileSync(join(base, PROFILE_FILE), JSON.stringify({ active: cleaned }, null, 2));
  profileCache = cleaned;
  return cleaned;
}

/**
 * Per-user, writable paths for the database, logs and editable config.
 *
 * Development Mode isolates everything under a visible, git-ignored `<repo>/.dev`;
 * a portable build uses `<exeDir>/MomentumLab-Data` (beside the executable); the
 * installed app uses the per-user `userData` directory. (See `paths.ts`.)
 * A non-default profile nests its own data root under `profiles/<name>/`.
 */
function userPaths(): { root: string; dataDir: string; logDir: string; dbUrl: string } {
  const base = baseDataRoot();
  const root = profileDataRoot(base, activeProfile());
  const dataDir = join(root, "data");
  const logDir = join(root, "logs");
  mkdirSync(dataDir, { recursive: true });
  mkdirSync(logDir, { recursive: true });
  // SQLAlchemy SQLite URL wants forward slashes, even on Windows.
  const dbPath = join(dataDir, "momentum.db").replace(/\\/g, "/");
  return { root, dataDir, logDir, dbUrl: `sqlite:///${dbPath}` };
}

/** Resolve the backend command: bundled binary in prod, `python -m momentum.api` in dev. */
function backendCommand(): { cmd: string; args: string[]; cwd: string } {
  if (isDev) {
    const python = process.env.MRP_PYTHON ?? "python3";
    return { cmd: python, args: ["-m", "momentum.api"], cwd: repoRoot() };
  }
  const binary = process.platform === "win32" ? "mrp-backend.exe" : "mrp-backend";
  // Onedir layout (current): resources/backend/mrp-backend/<binary> + _internal/.
  // Onefile layout (older builds): resources/backend/<binary>. Prefer onedir.
  const onedir = join(process.resourcesPath, "backend", "mrp-backend", binary);
  const cmd = existsSync(onedir) ? onedir : join(process.resourcesPath, "backend", binary);
  return { cmd, args: [], cwd: process.resourcesPath };
}

/** The environment the backend is launched with. */
function backendEnv(cwd: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    MRP_API_HOST: API_HOST,
    MRP_API_PORT: String(apiPort),
    // The backend self-terminates if WE die without cleaning it up (crash /
    // force-kill / system shutdown) — the orphan backstop.
    MRP_PARENT_PID: String(process.pid),
    // The market daemon runs automatically for as long as the app is open
    // (pause/stop from the UI); opt out with MRP_DAEMON_AUTOSTART=0.
    MRP_DAEMON_AUTOSTART: process.env.MRP_DAEMON_AUTOSTART ?? (isSmoke ? "0" : "1"),
    // Startup-performance instrumentation: the backend measures spawn->python.
    MRP_SPAWNED_AT: String(Date.now()),
    PYTHONPATH: isDev ? join(cwd, "src") : process.env.PYTHONPATH ?? "",
  };
  // Packaged: per-user dirs. Development Mode: the isolated `<repo>/.dev` dirs, so
  // the backend writes its DB/logs/diagnostics where the Developer Panel reports
  // and can open them. Plain `npm run dev` keeps the backend's own defaults.
  if (!isDev || isDevApp) {
    const { root, dbUrl, logDir } = userPaths();
    env.DATABASE_URL = process.env.DATABASE_URL ?? dbUrl;
    env.MRP_LOG_DIR = process.env.MRP_LOG_DIR ?? logDir;
    // Writable home for user-editable settings (provider choice -> settings.yaml,
    // API keys -> .env). The bundled config/ templates are read-only.
    env.MRP_USER_DIR = process.env.MRP_USER_DIR ?? root;
  }
  return env;
}

/** Push the backend status to the renderer (drives the loading screen). */
function sendBackendStatus(status: BackendStatus): void {
  lastBackendStatus = status;
  win?.webContents.send("mrp:backend:status", status);
}

/**
 * Write the startup diagnostic report to `<logDir>/startup-report.json`.
 *
 * This is the authoritative record of a launch: the backend executable + PID, how
 * long start → healthy took, the final health status, the configuration the
 * backend was launched with (database path, log dir) and the tail of any startup
 * exception. It is written after every `start()` attempt (success or failure) so a
 * broken install is diagnosable from disk with zero terminal interaction. The
 * backend writes its own companion `backend-startup.json` (config it actually
 * loaded); we point at it here. Best-effort — never throws.
 */
function writeStartupReport(): void {
  if (isSmoke) return;
  try {
    const { dbUrl, logDir } = userPaths();
    const report = {
      ts: new Date().toISOString(),
      appVersion: app.getVersion(),
      packaged: app.isPackaged,
      portable: isPortable(),
      platform: process.platform,
      host: API_HOST,
      port: apiPort,
      healthUrl: `http://${API_HOST}:${apiPort}/health`,
      databaseUrl: isDev ? process.env.DATABASE_URL ?? null : dbUrl,
      logDir,
      backendReport: join(logDir, "backend-startup.json"),
      // The main-process startup timeline (this is what was missing when the app
      // died before the window: now every stage + any failure is on disk).
      startup: trace.toReport(),
      // null on an early failure (before the backend manager is even built).
      backend: manager?.diagnostics ?? null,
    };
    writeFileSync(join(logDir, "startup-report.json"), JSON.stringify(report, null, 2), "utf-8");
    console.error(`[startup] timeline: ${trace.summary()}`);
    if (report.backend) {
      console.error(
        `[startup] status=${report.backend.status} ` +
          `pid=${report.backend.pid ?? "-"} ` +
          `adopted=${report.backend.adopted} ` +
          `duration=${report.backend.startupDurationMs ?? "-"}ms ` +
          `exe=${report.backend.executable}`,
      );
    }
  } catch (err) {
    console.error("[startup] failed to write startup report:", err);
  }
}

/**
 * Handle a fatal startup error WITHOUT vanishing.
 *
 * Before this, any rejection in the (unguarded) `whenReady` chain hit the global
 * unhandledRejection net and `process.exit(1)` — blue cursor, no window, no
 * process, nothing on disk. Now the failing stage is recorded, the startup report
 * (with the timeline) is flushed to disk, and — if the window never painted — a
 * native error box surfaces the cause so the launch is never silent. Returns after
 * quitting the app; safe to call from anywhere in startup.
 */
function fatalStartupError(err: unknown): void {
  trace.fail(err);
  const message = err instanceof Error ? err.message : String(err);
  console.error(`[startup] fatal: ${message}`);
  manager?.forceKillSync();
  writeStartupReport();
  // If the window has not painted, the user would otherwise see nothing — surface
  // a synchronous native dialog (works without a BrowserWindow). showErrorBox is
  // best-effort; never let the reporter itself throw.
  if (!windowShown && !isSmoke) {
    try {
      const logHint = app.isPackaged ? `\n\nDetails: ${join(userPaths().logDir, "mrp.log")}` : "";
      dialog.showErrorBox(
        "Momentum Lab failed to start",
        `Startup failed at "${trace.current ?? "?"}":\n${message}${logHint}`,
      );
    } catch {
      /* best effort — a broken dialog must not re-loop the crash net */
    }
  }
  app.quit();
}

/** Build the process manager and wire its lifecycle events to the UI. */
function createManager(): BackendManager {
  const { cmd, args, cwd } = backendCommand();
  const m = new BackendManager({
    host: API_HOST,
    port: apiPort,
    command: cmd,
    args,
    cwd,
    env: backendEnv(cwd),
    log: (line) => console.error(`[backend-manager] ${line}`),
  });
  m.onStatus(sendBackendStatus);
  m.onRestarted(() => win?.webContents.reload()); // re-fetch after a recovery
  m.onGiveUp(() => {
    if (promptBackendFailure("The backend stopped and could not be restarted.")) {
      void m.start();
    } else {
      app.quit();
    }
  });
  return m;
}

// ── Development Mode ──────────────────────────────────────────────────────── //

/** The current git branch (from `.git/HEAD`), or null when not a source checkout. */
function gitBranch(): string | null {
  try {
    const head = readFileSync(join(repoRoot(), ".git", "HEAD"), "utf-8").trim();
    const m = head.match(/^ref:\s*refs\/heads\/(.+)$/);
    return m ? m[1] : head.slice(0, 12); // detached HEAD → short sha
  } catch {
    return null;
  }
}

/** The diagnostics surfaced by the Developer Panel (everything it cannot fetch over HTTP). */
function devDiagnostics(): Record<string, unknown> {
  const { dataDir, logDir, root } = userPaths();
  const d = manager?.diagnostics ?? null;
  return {
    version: app.getVersion(),
    packaged: app.isPackaged,
    portable: isPortable(),
    devApp: isDevApp,
    platform: process.platform,
    host: API_HOST,
    port: apiPort,
    healthUrl: `http://${API_HOST}:${apiPort}/health`,
    backendPid: d?.pid ?? null,
    backendStatus: manager?.status ?? lastBackendStatus,
    adopted: d?.adopted ?? false,
    executable: d?.executable ?? null,
    startupStage: trace.current,
    startupFailure: trace.failure, // { stage, message, … } | null
    startupDurationMs: d?.startupDurationMs ?? null,
    databasePath: process.env.DATABASE_URL ?? join(dataDir, "momentum.db"),
    configPath: process.env.MRP_USER_DIR ?? root,
    logPath: logDir,
    dataDir,
    branch: gitBranch(),
    startupReport: join(logDir, "startup-report.json"),
    backendReport: join(logDir, "backend-startup.json"),
  };
}

/**
 * Bundle the on-disk diagnostics into a timestamped folder under the log dir
 * (startup report, backend report, the live diagnostics snapshot and the tail of
 * the backend log buffer), then reveal it. Returns the folder path. Best-effort.
 */
async function exportDiagnosticBundle(): Promise<string> {
  const { logDir } = userPaths();
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const dir = join(logDir, `diagnostic-bundle-${stamp}`);
  mkdirSync(dir, { recursive: true });

  const summary = {
    exportedAt: new Date().toISOString(),
    diagnostics: devDiagnostics(),
    startup: trace.toReport(),
    backendLogTail: manager?.logTail ?? null,
  };
  writeFileSync(join(dir, "summary.json"), JSON.stringify(summary, null, 2), "utf-8");

  for (const name of ["startup-report.json", "backend-startup.json", "mrp.log"]) {
    const src = join(logDir, name);
    if (existsSync(src)) {
      try {
        copyFileSync(src, join(dir, name));
      } catch {
        /* a locked/rotating log must not fail the bundle */
      }
    }
  }
  await shell.openPath(dir);
  return dir;
}

let backendWatcher: ReturnType<typeof watch> | null = null;
let watchTimer: NodeJS.Timeout | null = null;

/**
 * Development backend auto-restart: watch the Python source tree and, on a `.py`
 * change, restart the backend (debounced) and reload the renderer so it re-fetches.
 * Dev-app only, best-effort (a watch that can't start just disables the feature).
 */
function startBackendWatch(): void {
  if (!isDevApp || backendWatcher) return;
  const srcDir = join(repoRoot(), "src", "momentum");
  try {
    backendWatcher = watch(srcDir, { recursive: true }, (_event, filename) => {
      if (!filename || !filename.toString().endsWith(".py")) return;
      if (watchTimer) clearTimeout(watchTimer);
      watchTimer = setTimeout(() => {
        console.error(`[dev] backend source changed (${filename}) — restarting backend`);
        void manager
          ?.restart()
          .then((ok) => {
            if (ok) win?.webContents.reload();
          })
          .catch((err) => console.error("[dev] backend restart failed:", err));
      }, 400);
    });
    console.error(`[dev] watching ${srcDir} for backend changes`);
  } catch (err) {
    console.error("[dev] could not start backend source watch:", err);
  }
}

/** Register the Developer-Panel IPC surface (dev-app only). */
function registerDevIpc(): void {
  ipcMain.handle("mrp:dev:diagnostics", () => devDiagnostics());
  ipcMain.handle("mrp:dev:restart-backend", async () => {
    const ok = (await manager?.restart()) ?? false;
    if (ok) win?.webContents.reload();
    return { ok, status: manager?.status ?? "stopped" };
  });
  ipcMain.handle("mrp:dev:reload-renderer", () => {
    win?.webContents.reloadIgnoringCache();
    return true;
  });
  ipcMain.handle("mrp:dev:open-path", async (_e, which: string) => {
    const { dataDir, logDir, root } = userPaths();
    const target = which === "database" ? dataDir : which === "config" ? root : logDir;
    return shell.openPath(target);
  });
  ipcMain.handle("mrp:dev:export-bundle", () => exportDiagnosticBundle());
}

/** A modal "Retry / Quit" dialog showing the captured backend error. */
function promptBackendFailure(headline: string): boolean {
  const logHint = app.isPackaged ? `\n\nDetails: ${join(userPaths().logDir, "mrp.log")}` : "";
  const choice = dialog.showMessageBoxSync({
    type: "error",
    title: "Momentum Lab",
    message: headline,
    detail: `${manager?.logTail ?? ""}${logHint}`,
    buttons: ["Retry", "Quit"],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  return choice === 0;
}

/** Application menu, including "Check for Updates…" which routes the renderer. */
function buildMenu(target: BrowserWindow): Menu {
  const isMac = process.platform === "darwin";
  const checkForUpdates: MenuItemConstructorOptions = {
    label: "Check for Updates…",
    click: () => target.webContents.send("mrp:navigate", "/updates"),
  };

  const template: MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: "Momentum Lab",
            submenu: [
              { role: "about" as const },
              checkForUpdates,
              { type: "separator" as const },
              { role: "quit" as const },
            ],
          },
        ]
      : []),
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "togglefullscreen" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
      ],
    },
    {
      label: "Help",
      submenu: [
        ...(isMac ? [] : [checkForUpdates, { type: "separator" as const }]),
        {
          label: "Learn More",
          click: () => void shell.openExternal("https://code.claude.com/docs"),
        },
      ],
    },
  ];
  return Menu.buildFromTemplate(template);
}

/** Forward an updater lifecycle event to the renderer (the Updates screen). */
function sendUpdateEvent(kind: string, payload: unknown): void {
  win?.webContents.send("mrp:update:event", { kind, payload });
}

/* ── Update flow: the explicit state machine behind "Restart & install" ──────
 * Every step (stop backend → launch installer → relaunch → healthy) is an
 * explicit state streamed to the renderer, so the app can NEVER appear frozen
 * during an update. The flow survives the restart via a marker file and the
 * completed journey is written to update-report.json (with every operation
 * over 250 ms). See update-flow.ts. */

function sendFlowEvent(event: UpdateFlowEvent): void {
  console.error(`[update-flow] ${event.state}${event.detail ? ` — ${event.detail}` : ""}`);
  win?.webContents.send("mrp:update:flow", event);
}

let updateFlow = new UpdateFlow();
updateFlow.onEvent(sendFlowEvent);

function updateMarkerPath(): string {
  return join(userPaths().logDir, "update-flow.json");
}

function readUpdateMarker(): SerializedUpdateFlow | null {
  try {
    const raw = readFileSync(updateMarkerPath(), "utf-8");
    const parsed = JSON.parse(raw) as SerializedUpdateFlow;
    return parsed && parsed.version === 1 ? parsed : null;
  } catch {
    return null;
  }
}

function clearUpdateMarker(): void {
  try {
    rmSync(updateMarkerPath(), { force: true });
  } catch {
    /* best effort */
  }
}

/* ── Startup performance history: measured timings only ─────────────────────
 * Every launch's stage timeline (Electron trace + the backend's own boot
 * timings + the renderer's hydration/first-API marks) is appended to a rolling
 * startup-history.json; Developer Diagnostics renders the waterfall + per-stage
 * avg/median/p95/worst from it. See startup-metrics.ts. */

const rendererMarks: StageSample[] = [];

function startupHistoryPath(): string {
  return join(userPaths().logDir, "startup-history.json");
}

function readBackendTimings(): StageSample[] {
  try {
    const raw = readFileSync(join(userPaths().logDir, "backend-timings.json"), "utf-8");
    const parsed = JSON.parse(raw) as Record<string, number>;
    return Object.entries(parsed)
      .filter(([, v]) => typeof v === "number")
      .map(([key, value]) => ({
        stage: `backend:${key.replace(/_ms$/, "").replace(/_/g, "-")}`,
        durationMs: value,
      }));
  } catch {
    return [];
  }
}

function readStartupHistory(): LaunchRecord[] {
  try {
    const raw = readFileSync(startupHistoryPath(), "utf-8");
    const parsed = JSON.parse(raw) as LaunchRecord[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** Append/refresh THIS launch's record in the history (idempotent per launch). */
function persistStartupHistory(): void {
  try {
    const record = recordFromTrace(trace.toReport(), [...readBackendTimings(), ...rendererMarks]);
    const history = readStartupHistory().filter((r) => r.at !== record.at);
    writeFileSync(
      startupHistoryPath(),
      JSON.stringify(appendHistory(history, record), null, 2),
      "utf-8",
    );
  } catch (err) {
    console.error("[perf] could not persist startup history:", err);
  }
}

let updaterReady = false;

/** The GitHub release feed electron-updater is configured to use. */
interface UpdateFeed {
  provider: string | null;
  owner: string | null;
  repo: string | null;
  /** The exact unauthenticated URL electron-updater's GitHub provider fetches. */
  feedUrl: string | null;
}

/**
 * Read the release-feed coordinates electron-updater actually uses, from the
 * `app-update.yml` electron-builder bakes into the package (the single source of
 * truth). Falls back to null fields if it can't be read (e.g. dev/unpackaged).
 */
function readUpdateFeed(): UpdateFeed {
  const out: UpdateFeed = { provider: null, owner: null, repo: null, feedUrl: null };
  try {
    const ymlPath = join(process.resourcesPath, "app-update.yml");
    const text = readFileSync(ymlPath, "utf-8");
    const pick = (key: string): string | null => {
      const m = text.match(new RegExp(`^${key}:\\s*(.+?)\\s*$`, "m"));
      return m ? m[1].replace(/^['"]|['"]$/g, "") : null;
    };
    out.provider = pick("provider");
    out.owner = pick("owner");
    out.repo = pick("repo");
  } catch {
    /* not packaged / no feed file */
  }
  if (out.provider === "github" && out.owner && out.repo) {
    // electron-updater's GitHubProvider fetches exactly this (unauthenticated).
    out.feedUrl = `https://github.com/${out.owner}/${out.repo}/releases.atom`;
  }
  return out;
}

/** An optional token for PRIVATE-repo update checks (never embedded; env only). */
function updateToken(): string | null {
  return process.env.MRP_UPDATE_TOKEN || process.env.GH_TOKEN || process.env.GITHUB_TOKEN || null;
}

/**
 * Live diagnostics for the Updates screen: the resolved feed config + a real HTTP
 * probe of the release feed, so a failure (e.g. 404 because the repo is private)
 * is shown explicitly instead of a generic "update failed". Never throws.
 */
async function updateDiagnostics(): Promise<Record<string, unknown>> {
  const feed = readUpdateFeed();
  const token = updateToken();
  let probe: Record<string, unknown> | null = null;
  if (feed.feedUrl) {
    try {
      const headers: Record<string, string> = { accept: "application/atom+xml" };
      if (token) headers.authorization = `token ${token}`;
      const res = await fetch(feed.feedUrl, { headers, redirect: "follow" });
      probe = {
        url: feed.feedUrl,
        status: res.status,
        ok: res.ok,
        // The common, actionable case: a private repo 404s the public atom feed.
        interpretation:
          res.status === 404
            ? "404 — the repository is private or has no releases. The public GitHub updater feed is only readable for a PUBLIC repo (or with an access token). Make the repository public, or set MRP_UPDATE_TOKEN."
            : res.ok
              ? "Feed reachable."
              : `Feed returned HTTP ${res.status}.`,
      };
    } catch (err) {
      probe = {
        url: feed.feedUrl,
        status: 0,
        ok: false,
        interpretation: `Could not reach the feed: ${String((err as Error)?.message ?? err)}`,
      };
    }
  }
  return {
    packaged: app.isPackaged,
    currentVersion: app.getVersion(),
    provider: feed.provider,
    owner: feed.owner,
    repo: feed.repo,
    feedUrl: feed.feedUrl,
    autoUpdateDisabled: process.env.MRP_DISABLE_AUTOUPDATE === "1",
    tokenConfigured: !!token,
    probe,
  };
}

/**
 * In-app auto-update (electron-updater), surfaced in the Updates screen.
 *
 * No-op in dev / smoke / unpackaged runs. In a packaged build it registers IPC
 * handlers (check / download / install) and forwards updater events to the
 * renderer, then does one silent check on launch. Downloads are user-driven from
 * the Updates screen (`autoDownload = false`); a downloaded update installs on the
 * next quit, or immediately via "Restart & install". Failures (no release yet,
 * offline, unsigned-build quirks) are surfaced as events, never fatal. Disable the
 * launch check with MRP_DISABLE_AUTOUPDATE=1.
 */
function initAutoUpdates(): void {
  if (isDev || isSmoke || !app.isPackaged || updaterReady) return;
  updaterReady = true;

  // Register the IPC handlers FIRST, so the renderer's Updates screen can never
  // hit "No handler registered for 'mrp:update:check'" — even if the updater
  // wiring below throws on a given build (interop / missing app-update.yml /
  // unsigned-build quirks). Each handler surfaces its own failure to the screen.
  ipcMain.handle("mrp:update:check", async () => {
    const r = await autoUpdater.checkForUpdates();
    return { version: r?.updateInfo?.version ?? null };
  });
  ipcMain.handle("mrp:update:download", async () => {
    await autoUpdater.downloadUpdate();
    return true;
  });
  ipcMain.handle("mrp:update:install", async () => {
    // The seamless-update sequence. Each step is an explicit UpdateFlow state
    // streamed to the renderer's Update overlay, so the window shows exactly
    // what is happening instead of appearing frozen:
    //   preparing-restart -> stopping-backend (async, awaited HERE so the
    //   will-quit hook has nothing left to wait on) -> launching-installer
    //   (marker persisted) -> quitAndInstall on the next tick.
    updateFlow.transition("preparing-restart", "buttons disabled — saving state");
    updateFlow.transition("stopping-backend");
    try {
      await (manager?.stop() ?? Promise.resolve());
      updateFlow.transition("waiting-for-shutdown", "backend tree stopped cleanly");
    } catch (err) {
      // A stuck backend must not strand the update — will-quit force-kills.
      updateFlow.log(`backend stop errored (will-quit will force-kill): ${String(err)}`);
      updateFlow.transition("waiting-for-shutdown", "backend stop errored — forcing at quit");
    }
    updateFlow.transition("launching-installer", "handing off to the installer");
    try {
      writeFileSync(updateMarkerPath(), JSON.stringify(updateFlow.serialize()), "utf-8");
    } catch (err) {
      console.error("[update-flow] could not persist marker:", err);
    }
    // Defer so the IPC reply + the last flow event are flushed before quitting.
    setImmediate(() => autoUpdater.quitAndInstall());
    return true;
  });
  // Detailed diagnostics for the Updates screen (feed config + live feed probe).
  ipcMain.handle("mrp:update:diagnostics", () => updateDiagnostics());

  try {
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;

    // PRIVATE-repo support (testing / internal distribution): if a token is set in
    // the environment, authenticate the feed + asset requests. Never embedded in
    // the build — only read from the environment.
    const token = updateToken();
    if (token) {
      autoUpdater.requestHeaders = { authorization: `token ${token}` };
      console.error("[auto-update] using an access token for the release feed (private repo)");
    }

    autoUpdater.on("checking-for-update", () => {
      updateFlow.transition("checking-for-updates");
      sendUpdateEvent("checking", null);
    });
    autoUpdater.on("update-available", (info) =>
      sendUpdateEvent("available", { version: info.version }),
    );
    autoUpdater.on("update-not-available", (info) =>
      sendUpdateEvent("not-available", { version: info.version }),
    );
    autoUpdater.on("download-progress", (p) => {
      updateFlow.transition("downloading-update");
      updateFlow.setProgress(
        p.percent / 100,
        `${Math.round(p.transferred / 1024 / 1024)}MB of ${Math.round(p.total / 1024 / 1024)}MB`,
      );
      sendUpdateEvent("progress", {
        percent: p.percent,
        transferred: p.transferred,
        total: p.total,
      });
    });
    autoUpdater.on("update-downloaded", (info) => {
      // electron-updater verifies the artifact checksum/signature during the
      // download pipeline; record it as its own state for the report.
      updateFlow.transition("verifying-update", `v${info.version} checksum verified`);
      updateFlow.transition("idle", "downloaded — ready to install");
      sendUpdateEvent("downloaded", { version: info.version });
    });
    autoUpdater.on("error", (err) => {
      const e = err as { message?: string; statusCode?: number } | undefined;
      sendUpdateEvent("error", {
        message: String(e?.message ?? err),
        statusCode: e?.statusCode ?? null,
      });
    });

    if (process.env.MRP_DISABLE_AUTOUPDATE !== "1") {
      void autoUpdater.checkForUpdates().catch((err) => {
        console.error("[auto-update] launch check failed:", err);
      });
    }
  } catch (err) {
    console.error("[auto-update] init failed:", err);
    sendUpdateEvent("error", {
      message: `Auto-update could not start: ${String((err as Error)?.message ?? err)}`,
    });
  }
}

async function createWindow(): Promise<void> {
  trace.enter("create-window");
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 720,
    backgroundColor: "#0b1220",
    show: false,
    title: "Momentum Lab",
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  Menu.setApplicationMenu(buildMenu(win));

  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  // Every (re)load gets the current backend status, so the loading screen is right.
  win.webContents.on("did-finish-load", () => {
    win?.webContents.send("mrp:backend:status", lastBackendStatus);
    if (updateFlow.active) win?.webContents.send("mrp:update:flow", updateFlow.snapshot());
  });

  // Show the window exactly once, recording the stage, from whichever path gets
  // there first (ready-to-show, the load-failure catch, or the timeout backstop).
  const markShown = (detail?: string): void => {
    if (windowShown || !win) return;
    windowShown = true;
    trace.enter("window-shown", detail);
    win.show();
  };

  // Show the window even if the renderer load is slow/fails, so a bad bundle
  // path can never present as an invisible, process-less launch. ready-to-show
  // is the happy path; this timeout is the backstop.
  const showFallback = setTimeout(() => {
    if (!windowShown && !isSmoke) {
      console.error("[startup] ready-to-show did not fire in 8s — showing window anyway");
      markShown("forced after 8s (ready-to-show never fired)");
    }
  }, 8_000);

  win.once("ready-to-show", () => {
    clearTimeout(showFallback);
    markShown();
    if (isSmoke) {
      // The renderer mounted from the built bundle — report success and exit 0.
      console.log("MRP_SMOKE_OK");
      app.exit(0);
    }
  });

  trace.enter("load-renderer", isDev ? "http://localhost:5173" : "renderer/dist/index.html");
  try {
    if (isDev) {
      await win.loadURL("http://localhost:5173");
      win.webContents.openDevTools({ mode: "detach" });
    } else {
      await win.loadFile(join(__dirname, "..", "renderer", "dist", "index.html"));
    }
  } catch (err) {
    // A failed renderer load must not reject up into the fatal-exit net before the
    // window is even shown. Log it, show the (blank) window so the user sees the
    // app exists, and let the backend lifecycle continue.
    clearTimeout(showFallback);
    console.error("[startup] renderer load failed:", err);
    if (!isSmoke) markShown("renderer load failed — shown blank");
  }
}

// Single-instance: a second launch focuses the existing window instead of
// starting a second backend. A relaunch can race the previous instance's
// graceful shutdown (will-quit waits up to SHUTDOWN_TIMEOUT_MS + 2s for the
// backend tree), so a held lock gets a bounded grace-retry before we give up —
// otherwise "restart" during a slow teardown silently launches nothing.
const LOCK_RETRY_ATTEMPTS = 12;
const LOCK_RETRY_DELAY_MS = 750; // 12 × 750ms ≈ 9s — covers the shutdown window

const LOCK_SPLASH_HTML = `<!doctype html><html><body style="margin:0;background:#0b1220;color:#cbd5e1;
font-family:Segoe UI,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;
-webkit-app-region:drag;user-select:none"><div style="text-align:center">
<div style="width:26px;height:26px;margin:0 auto 12px;border:3px solid #1e293b;border-top-color:#38bdf8;
border-radius:50%;animation:s 0.9s linear infinite"></div>
<div style="font-size:14px;font-weight:600;color:#e2e8f0">Momentum Lab is restarting…</div>
<div style="font-size:12px;margin-top:6px;color:#64748b">Waiting for the previous instance to finish
shutting down — this can take a few seconds.</div>
<style>@keyframes s{to{transform:rotate(360deg)}}</style></div></body></html>`;

let lockSplash: BrowserWindow | null = null;

/** During lock retries there is otherwise NO window at all — after an update
 * (or a fresh-install "Launch" while the installer's elevated copy exits) the
 * relaunch can wait up to ~9s for the previous instance's teardown. This tiny
 * splash is what stands between the user and "Windows appears frozen". */
async function showLockSplash(): Promise<void> {
  if (lockSplash || isSmoke) return;
  try {
    await app.whenReady();
    lockSplash = new BrowserWindow({
      width: 440,
      height: 150,
      frame: false,
      resizable: false,
      alwaysOnTop: true,
      backgroundColor: "#0b1220",
      show: true,
    });
    await lockSplash.loadURL(
      "data:text/html;charset=utf-8," + encodeURIComponent(LOCK_SPLASH_HTML),
    );
  } catch (err) {
    console.error("[startup] lock splash failed (non-fatal):", err);
  }
}

function closeLockSplash(): void {
  try {
    lockSplash?.close();
  } catch {
    /* best effort */
  }
  lockSplash = null;
}

async function acquireSingleInstanceLock(): Promise<boolean> {
  if (app.requestSingleInstanceLock()) return true;
  void showLockSplash(); // never block the retry loop on the splash paint
  try {
    for (let attempt = 1; attempt <= LOCK_RETRY_ATTEMPTS; attempt++) {
      trace.enter(
        "single-instance-lock",
        `held by another instance — retry ${attempt}/${LOCK_RETRY_ATTEMPTS}`,
      );
      await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_DELAY_MS));
      // Electron resets its process singleton on a failed request, so a fresh
      // call re-attempts the lock rather than returning a cached false.
      if (app.requestSingleInstanceLock()) {
        trace.enter("single-instance-lock", `acquired after ${attempt} retries`);
        return true;
      }
    }
    return false;
  } finally {
    closeLockSplash();
  }
}

function runPrimaryInstance(): void {
  trace.enter("single-instance-lock", "acquired");
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  // The whole startup is guarded: any rejection used to hit the global
  // unhandledRejection net and `process.exit(1)` — an invisible, process-less
  // launch with nothing on disk. Now a failure is traced, reported, surfaced and
  // quit cleanly via fatalStartupError().
  const startup = async (): Promise<void> => {
    trace.enter("app-ready");
    // Startup validation (CI): create the window from the built renderer with no
    // backend, then let the ready-to-show handler print the sentinel and exit.
    if (isSmoke) {
      setTimeout(() => {
        console.error("MRP_SMOKE_TIMEOUT");
        app.exit(1);
      }, 30_000);
      await createWindow();
      return;
    }

    trace.enter("free-port");
    apiPort = isDev ? Number(process.env.MRP_API_PORT ?? 8000) : await freePort();
    // The preload reads these to build the API base URL and to know whether the
    // packaged auto-updater (electron-updater) is available — keep them in sync.
    trace.enter("configure-env", `port=${apiPort}`);
    process.env.MRP_API_PORT = String(apiPort);
    process.env.MRP_APP_VERSION = app.getVersion();
    process.env.MRP_PACKAGED = app.isPackaged ? "1" : "0";

    trace.enter("create-manager");
    manager = createManager();
    trace.enter("register-ipc");
    // Lets the renderer seed its initial status on mount (avoids a missed event).
    ipcMain.handle("mrp:backend:get-status", () => lastBackendStatus);
    if (isDevApp) registerDevIpc();
    // Factory reset → restart: relaunch the whole app so the backend is respawned
    // and the renderer reloads. `app.quit()` first runs the graceful shutdown
    // (before-quit/will-quit) so the old backend is stopped before relaunch.
    ipcMain.handle("mrp:app:relaunch", () => {
      app.relaunch();
      app.quit();
      return true;
    });
    // Automation Mode: live blocker status + an immediate re-sync nudge
    // (the renderer calls sync after saving autopilot settings).
    ipcMain.handle("mrp:automation:status", () => automation.status());
    ipcMain.handle("mrp:automation:sync", async () => {
      await syncAutomation();
      return automation.status();
    });
    startAutomationSync();
    // Profiles: isolated data roots (own DB / logs / settings) under one install.
    // Switching (or creating) writes profile.json; the caller relaunches to apply.
    ipcMain.handle("mrp:profiles:get", () => ({
      active: activeProfile(),
      profiles: listProfiles(),
    }));
    ipcMain.handle("mrp:profiles:switch", (_event, name: string) => {
      const applied = setActiveProfile(name);
      return { ok: applied !== null, active: applied ?? activeProfile() };
    });

    // Startup-performance IPC: renderer marks (hydration / first API response)
    // + the measured history for the Developer Diagnostics waterfall.
    ipcMain.on("mrp:perf:mark", (_event, stage: string, ms?: number) => {
      if (stage !== "renderer-hydrated" && stage !== "first-api-response") return;
      if (rendererMarks.some((m) => m.stage === stage)) return; // once per launch
      rendererMarks.push({ stage, durationMs: typeof ms === "number" ? Math.round(ms) : 0 });
      trace.enter(stage, typeof ms === "number" ? `${Math.round(ms)}ms after page load` : undefined);
      persistStartupHistory();
      writeStartupReport();
    });
    ipcMain.handle("mrp:perf:startup", () => {
      const history = readStartupHistory();
      const latest = history.length ? history[history.length - 1] : null;
      return {
        launches: history.length,
        stats: computeStats(history),
        waterfall: latest ? waterfall(latest) : [],
        latest,
      };
    });

    // Show the window first (loading screen) so the user sees "Backend Starting"
    // immediately, then bring the backend up.
    await createWindow();
    sendBackendStatus(manager.status);

    // An update marker means we were relaunched by the installer: resume the
    // SAME update flow so the overlay narrates the post-install states and the
    // final report covers the whole journey.
    const savedFlow = readUpdateMarker();
    if (savedFlow) {
      updateFlow = UpdateFlow.resume(savedFlow);
      updateFlow.onEvent(sendFlowEvent);
      updateFlow.transition("waiting-for-installer", "installer finished — application relaunched");
      updateFlow.transition("starting-backend", "spawning the backend sidecar");
    }
    trace.enter("init-auto-updates");
    // Auto-update is non-essential: a failure here must never abort the launch.
    try {
      initAutoUpdates();
    } catch (err) {
      console.error("[auto-update] init crashed (non-fatal):", err);
    }

    trace.enter("backend-start");
    let healthy = await manager.start();
    trace.enter(healthy ? "backend-healthy" : "backend-failed");
    writeStartupReport();
    while (!healthy) {
      // Development Mode: never block on a modal or quit. Leave the window up so
      // the failure stays visible in the Developer Panel; the source-watcher +
      // "Restart Backend" button let the developer recover without a relaunch.
      if (isDevApp) {
        console.error("[dev] backend failed to start — see the Developer Panel; edit & save to retry");
        break;
      }
      if (!promptBackendFailure("The backend service failed to start.")) {
        app.quit();
        return;
      }
      healthy = await manager.start();
      trace.enter(healthy ? "backend-healthy" : "backend-failed");
      writeStartupReport();
    }
    if (healthy) trace.done();
    writeStartupReport();
    persistStartupHistory();

    if (savedFlow && updateFlow.active) {
      if (healthy) {
        updateFlow.transition("waiting-for-health", "health check passed");
        updateFlow.transition("opening-desktop");
        updateFlow.transition("ready", `updated to v${app.getVersion()}`);
      } else {
        updateFlow.fail("backend failed to start after the update");
      }
      try {
        writeFileSync(
          join(userPaths().logDir, "update-report.json"),
          JSON.stringify(updateFlow.report(), null, 2),
          "utf-8",
        );
      } catch (err) {
        console.error("[update-flow] could not write update-report.json:", err);
      }
      clearUpdateMarker();
    }

    // Development Mode: auto-restart the backend when its source changes (armed even
    // if the first start failed, so saving a fix brings the backend up).
    startBackendWatch();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) void createWindow();
    });
  };

  // Run the guarded startup. The internal try/catch names the failing stage; the
  // trailing .catch is the backstop so a rejection can never reach the global
  // unhandledRejection net (which would `process.exit(1)` with no window/report).
  app
    .whenReady()
    .then(() =>
      startup().catch((err: unknown) => fatalStartupError(err)),
    )
    .catch((err: unknown) => fatalStartupError(err));
}

void acquireSingleInstanceLock().then((locked) => {
  if (locked) {
    runPrimaryInstance();
  } else {
    // Another instance genuinely owns the lock (not just a slow teardown) —
    // it was asked to focus via "second-instance"; exit without a 2nd backend.
    trace.enter("single-instance-lock", "another instance owns the lock — exiting");
    app.quit();
  }
});

// All windows closed -> quit the app (drives the graceful shutdown below).
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// before-quit: stop crash-recovery so the imminent backend exit isn't "recovered".
app.on("before-quit", () => {
  manager?.markShuttingDown();
  backendWatcher?.close();
  backendWatcher = null;
});

// will-quit: defer the quit until the backend is gracefully stopped (then force-
// killed if it overruns). The cleanupRan guard lets the re-quit proceed.
app.on("will-quit", (event) => {
  if (cleanupRan) return;
  cleanupRan = true;
  event.preventDefault();
  // Release the sleep blocker FIRST — it must never outlive the app.
  automation.dispose("app quitting");
  if (automationTimer) clearInterval(automationTimer);
  void (manager?.stop() ?? Promise.resolve()).finally(() => app.exit(0));
});

/**
 * A fatal crash that bypassed the startup guard (uncaughtException /
 * unhandledRejection). Best-effort and never re-throws: kill the sidecar, record
 * the failing stage, flush the startup report, and — if no window ever painted —
 * surface a native error box so the crash is visible rather than a silent exit.
 */
function reportFatalCrash(label: string, err: unknown): void {
  console.error(`[main] ${label}:`, err);
  try {
    automation.dispose("fatal crash");
  } catch {
    /* best effort */
  }
  try {
    manager?.forceKillSync();
  } catch {
    /* best effort */
  }
  if (!isSmoke) {
    try {
      trace.fail(err);
      writeStartupReport();
      if (!windowShown) {
        const msg = err instanceof Error ? err.message : String(err);
        dialog.showErrorBox(
          "Momentum Lab crashed during startup",
          `${label} at "${trace.current ?? "?"}":\n${msg}`,
        );
      }
    } catch {
      /* a broken reporter must not mask the original crash */
    }
  }
}

// Last-resort safety nets for paths that bypass the quit events — a main-process
// crash, an explicit process.exit, etc. (A hard kill of Electron or a system
// shutdown that skips even these is covered by the backend's parent watchdog.)
process.on("exit", () => {
  try {
    automation.dispose("process exit");
  } catch {
    /* the OS drops the blocker with the process anyway */
  }
  manager?.forceKillSync();
});
process.on("uncaughtException", (err) => {
  reportFatalCrash("uncaught exception", err);
  process.exit(1);
});
process.on("unhandledRejection", (reason) => {
  reportFatalCrash("unhandled rejection", reason);
  process.exit(1);
});
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"] as const) {
  process.on(sig, () => {
    manager?.forceKillSync();
    process.exit(0);
  });
}
