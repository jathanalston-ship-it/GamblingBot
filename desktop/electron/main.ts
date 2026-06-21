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
  backend = spawn(cmd, args, { cwd, env, stdio: "inherit" });
  backend.on("exit", (code) => {
    if (code && code !== 0) console.error(`[backend] exited with code ${code}`);
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

async function waitForBackend(timeoutMs = 60_000): Promise<void> {
  const base = `http://${API_HOST}:${apiPort}`;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("backend did not become healthy in time");
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

    startBackend();
    try {
      await waitForBackend();
    } catch (err) {
      dialog.showErrorBox(
        "Momentum Lab",
        `The backend service failed to start.\n\n${String(err)}\n\n` +
          "Please reopen the app. If the problem persists, reinstall Momentum Lab.",
      );
      app.quit();
      return;
    }
    await createWindow();
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
app.on("before-quit", stopBackend);
app.on("quit", stopBackend);
app.on("will-quit", stopBackend);
