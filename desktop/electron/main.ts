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
import { copyFileSync, existsSync, mkdirSync, readFileSync, watch, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, join } from "node:path";

import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  type MenuItemConstructorOptions,
  shell,
} from "electron";
import electronUpdater from "electron-updater";

import { BackendManager, type BackendStatus } from "./backend-manager";
import { PORTABLE_MARKER, resolveDataRoot } from "./paths";
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

/**
 * Per-user, writable paths for the database, logs and editable config.
 *
 * Development Mode isolates everything under a visible, git-ignored `<repo>/.dev`;
 * a portable build uses `<exeDir>/MomentumLab-Data` (beside the executable); the
 * installed app uses the per-user `userData` directory. (See `paths.ts`.)
 */
function userPaths(): { root: string; dataDir: string; logDir: string; dbUrl: string } {
  const root = resolveDataRoot({
    isDevApp,
    isPortable: isPortable(),
    repoRoot: repoRoot(),
    exeDir: app.isPackaged ? dirname(app.getPath("exe")) : repoRoot(),
    userDataDir: app.getPath("userData"),
  });
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
  return {
    cmd: join(process.resourcesPath, "backend", binary),
    args: [],
    cwd: process.resourcesPath,
  };
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

let updaterReady = false;

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
  const { autoUpdater } = electronUpdater;

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
  ipcMain.handle("mrp:update:install", () => {
    // Defer so the IPC reply is flushed before the app quits to install.
    setImmediate(() => autoUpdater.quitAndInstall());
    return true;
  });

  try {
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;

    autoUpdater.on("checking-for-update", () => sendUpdateEvent("checking", null));
    autoUpdater.on("update-available", (info) =>
      sendUpdateEvent("available", { version: info.version }),
    );
    autoUpdater.on("update-not-available", (info) =>
      sendUpdateEvent("not-available", { version: info.version }),
    );
    autoUpdater.on("download-progress", (p) =>
      sendUpdateEvent("progress", {
        percent: p.percent,
        transferred: p.transferred,
        total: p.total,
      }),
    );
    autoUpdater.on("update-downloaded", (info) =>
      sendUpdateEvent("downloaded", { version: info.version }),
    );
    autoUpdater.on("error", (err) =>
      sendUpdateEvent("error", { message: String(err?.message ?? err) }),
    );

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
// starting a second backend.
if (!app.requestSingleInstanceLock()) {
  // Another instance holds the lock — focusing it is handled by the primary via
  // "second-instance"; this one exits without starting a second backend.
  trace.enter("single-instance-lock", "another instance owns the lock — exiting");
  app.quit();
} else {
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

    // Show the window first (loading screen) so the user sees "Backend Starting"
    // immediately, then bring the backend up.
    await createWindow();
    sendBackendStatus(manager.status);
    trace.enter("init-auto-updates");
    initAutoUpdates();

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
process.on("exit", () => manager?.forceKillSync());
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
