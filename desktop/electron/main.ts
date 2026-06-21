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
import { mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";

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

const API_HOST = "127.0.0.1";
const isDev = process.env.NODE_ENV === "development";
// CI startup validation: boot the window from the built renderer WITHOUT the
// backend, confirm it paints, print a sentinel and exit. Set by `npm run smoke`.
const isSmoke = process.env.MRP_SMOKE === "1";
const SHUTDOWN_TIMEOUT_MS = 5_000; // graceful window before force-killing the tree

let win: BrowserWindow | null = null;
let apiPort = 8000;
let manager: BackendManager | null = null;
let lastBackendStatus: BackendStatus = "starting";
let cleanupRan = false;

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

/** Per-user, writable paths for the database and logs (created if missing). */
function userPaths(): { dbUrl: string; logDir: string } {
  const userData = app.getPath("userData");
  const dataDir = join(userData, "data");
  const logDir = join(userData, "logs");
  mkdirSync(dataDir, { recursive: true });
  mkdirSync(logDir, { recursive: true });
  // SQLAlchemy SQLite URL wants forward slashes, even on Windows.
  const dbPath = join(dataDir, "momentum.db").replace(/\\/g, "/");
  return { dbUrl: `sqlite:///${dbPath}`, logDir };
}

/** Resolve the backend command: bundled binary in prod, `python -m momentum.api` in dev. */
function backendCommand(): { cmd: string; args: string[]; cwd: string } {
  if (isDev) {
    const python = process.env.MRP_PYTHON ?? "python3";
    const repoRoot = join(__dirname, "..", "..");
    return { cmd: python, args: ["-m", "momentum.api"], cwd: repoRoot };
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
  if (!isDev) {
    const { dbUrl, logDir } = userPaths();
    env.DATABASE_URL = process.env.DATABASE_URL ?? dbUrl;
    env.MRP_LOG_DIR = process.env.MRP_LOG_DIR ?? logDir;
    // Writable home for user-editable settings (provider choice -> settings.yaml,
    // API keys -> .env). The bundled config/ templates are read-only.
    env.MRP_USER_DIR = process.env.MRP_USER_DIR ?? app.getPath("userData");
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
  if (isSmoke || !manager) return;
  try {
    const { dbUrl, logDir } = userPaths();
    const report = {
      ts: new Date().toISOString(),
      appVersion: app.getVersion(),
      packaged: app.isPackaged,
      platform: process.platform,
      host: API_HOST,
      port: apiPort,
      healthUrl: `http://${API_HOST}:${apiPort}/health`,
      databaseUrl: isDev ? process.env.DATABASE_URL ?? null : dbUrl,
      logDir,
      backendReport: join(logDir, "backend-startup.json"),
      backend: manager.diagnostics,
    };
    writeFileSync(join(logDir, "startup-report.json"), JSON.stringify(report, null, 2), "utf-8");
    console.error(
      `[startup] status=${report.backend.status} ` +
        `pid=${report.backend.pid ?? "-"} ` +
        `adopted=${report.backend.adopted} ` +
        `duration=${report.backend.startupDurationMs ?? "-"}ms ` +
        `exe=${report.backend.executable}`,
    );
  } catch (err) {
    console.error("[startup] failed to write startup report:", err);
  }
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

  if (isDev) {
    await win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    await win.loadFile(join(__dirname, "..", "renderer", "dist", "index.html"));
  }
  win.once("ready-to-show", () => {
    win?.show();
    if (isSmoke) {
      // The renderer mounted from the built bundle — report success and exit 0.
      console.log("MRP_SMOKE_OK");
      app.exit(0);
    }
  });
}

// Single-instance: a second launch focuses the existing window instead of
// starting a second backend.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
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

    apiPort = isDev ? Number(process.env.MRP_API_PORT ?? 8000) : await freePort();
    // The preload reads these to build the API base URL and to know whether the
    // packaged auto-updater (electron-updater) is available — keep them in sync.
    process.env.MRP_API_PORT = String(apiPort);
    process.env.MRP_APP_VERSION = app.getVersion();
    process.env.MRP_PACKAGED = app.isPackaged ? "1" : "0";

    manager = createManager();
    // Lets the renderer seed its initial status on mount (avoids a missed event).
    ipcMain.handle("mrp:backend:get-status", () => lastBackendStatus);
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
    initAutoUpdates();

    let healthy = await manager.start();
    writeStartupReport();
    while (!healthy) {
      if (!promptBackendFailure("The backend service failed to start.")) {
        app.quit();
        return;
      }
      healthy = await manager.start();
      writeStartupReport();
    }

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) void createWindow();
    });
  });
}

// All windows closed -> quit the app (drives the graceful shutdown below).
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// before-quit: stop crash-recovery so the imminent backend exit isn't "recovered".
app.on("before-quit", () => manager?.markShuttingDown());

// will-quit: defer the quit until the backend is gracefully stopped (then force-
// killed if it overruns). The cleanupRan guard lets the re-quit proceed.
app.on("will-quit", (event) => {
  if (cleanupRan) return;
  cleanupRan = true;
  event.preventDefault();
  void (manager?.stop() ?? Promise.resolve()).finally(() => app.exit(0));
});

// Last-resort safety nets for paths that bypass the quit events — a main-process
// crash, an explicit process.exit, etc. (A hard kill of Electron or a system
// shutdown that skips even these is covered by the backend's parent watchdog.)
process.on("exit", () => manager?.forceKillSync());
process.on("uncaughtException", (err) => {
  console.error("[main] uncaught exception:", err);
  manager?.forceKillSync();
  process.exit(1);
});
process.on("unhandledRejection", (reason) => {
  console.error("[main] unhandled rejection:", reason);
  manager?.forceKillSync();
  process.exit(1);
});
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"] as const) {
  process.on(sig, () => {
    manager?.forceKillSync();
    process.exit(0);
  });
}
