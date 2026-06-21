/**
 * Electron main process for Momentum Lab.
 *
 * Responsibilities:
 *   1. Spawn the FastAPI backend as a private, loopback-only sidecar.
 *   2. Wait for the backend's /health before showing the window.
 *   3. Create the BrowserWindow (Vite dev server in dev, built files in prod).
 *   4. Tear the sidecar down on quit.
 *
 * Production installability:
 *   - The SQLite database and logs live under app.getPath("userData") — a
 *     per-user, writable location — never under Program Files.
 *   - A free TCP port is chosen at launch so a busy 8000 never blocks startup.
 *   - A single-instance lock prevents a second backend if the app is opened twice.
 *   - A failed backend shows a dialog instead of a blank window.
 *
 * Security: contextIsolation on, nodeIntegration off; the renderer talks to the
 * backend only over http://127.0.0.1:<port> via the typed preload bridge.
 */
import { ChildProcess, spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
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

const API_HOST = "127.0.0.1";
const isDev = process.env.NODE_ENV === "development";
// CI startup validation: boot the window from the built renderer WITHOUT the
// backend, confirm it paints, print a sentinel and exit. Set by `npm run smoke`.
const isSmoke = process.env.MRP_SMOKE === "1";

let backend: ChildProcess | null = null;
let win: BrowserWindow | null = null;
let apiPort = 8000;

// --- backend startup-reliability state ------------------------------------- //
const MAX_START_ATTEMPTS = 2; // initial bring-up tries before asking the user
const STARTUP_TIMEOUT_MS = 30_000; // health-poll budget per attempt
const MAX_RUNTIME_RESTARTS = 3; // crash-recovery cap once the window is up
const BACKEND_LOG_LINES = 120; // ring buffer of captured backend output

const backendLog: string[] = [];
let backendExited = false; // set by the current backend's error/exit events
let shuttingDown = false; // true once the app is intentionally quitting
let recoveryEnabled = false; // true once the window is up (enables crash respawn)
let runtimeRestarts = 0;
let restartTimer: NodeJS.Timeout | null = null;

function pushBackendLog(chunk: string): void {
  for (const raw of chunk.split(/\r?\n/)) {
    const line = raw.trimEnd();
    if (!line) continue;
    backendLog.push(line);
    if (backendLog.length > BACKEND_LOG_LINES) backendLog.shift();
    console.error(`[backend] ${line}`);
  }
}

/** The last few lines of backend output — the actual cause to show the user. */
function backendTail(n = 18): string {
  return backendLog.slice(-n).join("\n") || "(no backend output was captured)";
}


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

function startBackend(): void {
  const { cmd, args, cwd } = backendCommand();
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    MRP_API_HOST: API_HOST,
    MRP_API_PORT: String(apiPort),
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

  backendExited = false;
  try {
    // Pipe (not inherit) so we can capture the cause of a failed start and show it.
    backend = spawn(cmd, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
  } catch (err) {
    backendExited = true;
    pushBackendLog(`[spawn failed] ${String((err as Error)?.message ?? err)}`);
    return;
  }

  backend.stdout?.on("data", (b: Buffer) => pushBackendLog(b.toString()));
  backend.stderr?.on("data", (b: Buffer) => pushBackendLog(b.toString()));
  // 'error' fires when the binary is missing or cannot be executed (no throw).
  backend.on("error", (err) => {
    backendExited = true;
    pushBackendLog(`[spawn error] ${err.message}`);
  });
  backend.on("exit", (code, signal) => {
    backendExited = true;
    if (code && code !== 0) pushBackendLog(`[backend exited] code=${code} signal=${signal ?? "-"}`);
    // Crash recovery: respawn if the app isn't quitting and the window is up.
    if (recoveryEnabled && !shuttingDown) scheduleBackendRestart();
  });
}

/**
 * Stop the backend sidecar — killing the whole process TREE.
 *
 * `child.kill()` only signals the immediate PID, but the packaged backend
 * (`mrp-backend.exe`, a PyInstaller binary) spawns a child of its own. Killing
 * just the parent orphans that child, which keeps holding the loopback port and
 * locking files in the install directory — which is what makes the next
 * installer fail with "Momentum Lab cannot be closed". So on Windows we use
 * `taskkill /T` to take down the entire tree.
 */
function stopBackend(): void {
  const proc = backend;
  backend = null;
  if (!proc || proc.killed) return;
  const pid = proc.pid;
  if (process.platform === "win32" && pid) {
    try {
      spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
      return;
    } catch {
      /* fall through to a plain kill */
    }
  }
  try {
    proc.kill();
  } catch {
    /* already gone */
  }
}

async function waitForBackend(timeoutMs = STARTUP_TIMEOUT_MS): Promise<void> {
  const base = `http://${API_HOST}:${apiPort}`;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // Fail fast: don't keep polling a port whose process already died.
    if (backendExited) throw new Error("backend process exited before becoming healthy");
    try {
      const res = await fetch(`${base}/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("backend did not become healthy within the startup timeout");
}

/** Spawn + health-verify the backend, retrying a few times. */
async function bringUpBackend(): Promise<boolean> {
  for (let attempt = 1; attempt <= MAX_START_ATTEMPTS; attempt++) {
    startBackend();
    try {
      await waitForBackend();
      return true;
    } catch (err) {
      pushBackendLog(`[startup] attempt ${attempt}/${MAX_START_ATTEMPTS} failed: ${String(err)}`);
      stopBackend(); // recovery is off during bring-up, so this won't auto-respawn
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  return false;
}

/** A modal "Retry / Quit" dialog showing the captured backend error. */
function promptBackendFailure(headline: string): boolean {
  if (shuttingDown) return false;
  const logHint = app.isPackaged ? `\n\nDetails: ${join(userPaths().logDir, "mrp.log")}` : "";
  const choice = dialog.showMessageBoxSync({
    type: "error",
    title: "Momentum Lab",
    message: headline,
    detail: `${backendTail()}${logHint}`,
    buttons: ["Retry", "Quit"],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  return choice === 0;
}

/** Crash recovery once the window is up: respawn (bounded), reload on success. */
function scheduleBackendRestart(): void {
  if (restartTimer || shuttingDown) return;
  if (runtimeRestarts >= MAX_RUNTIME_RESTARTS) {
    if (promptBackendFailure("The backend stopped and could not be restarted.")) {
      runtimeRestarts = 0;
      scheduleBackendRestart();
    } else {
      app.quit();
    }
    return;
  }
  runtimeRestarts++;
  restartTimer = setTimeout(async () => {
    restartTimer = null;
    if (shuttingDown) return;
    startBackend();
    try {
      await waitForBackend();
      runtimeRestarts = 0;
      win?.webContents.reload(); // re-fetch data so stale "backend down" errors clear
    } catch {
      stopBackend(); // its exit event re-enters scheduleBackendRestart (bounded)
    }
  }, 800);
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

/**
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
    // Never let a wiring failure leave the screen with a dead IPC channel.
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

    // Bring the backend up, retrying; if it still fails, let the user Retry or Quit
    // (with the captured error) instead of dropping them into a blank/500 window.
    while (!(await bringUpBackend())) {
      if (!promptBackendFailure("The backend service failed to start.")) {
        app.quit();
        return;
      }
    }

    await createWindow();
    recoveryEnabled = true; // window is up — auto-respawn the backend if it crashes
    initAutoUpdates();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) void createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Tear the sidecar down on every shutdown path (normal close, "Restart &
// install", or the failed-startup quit above) so it can never be orphaned.
// `shuttingDown` first, so the backend's exit event doesn't trigger crash recovery.
function shutdown(): void {
  shuttingDown = true;
  if (restartTimer) {
    clearTimeout(restartTimer);
    restartTimer = null;
  }
  stopBackend();
}
app.on("before-quit", shutdown);
app.on("quit", shutdown);
app.on("will-quit", shutdown);
