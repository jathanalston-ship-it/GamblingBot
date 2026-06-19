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

import { app, BrowserWindow, dialog, shell } from "electron";

const API_HOST = "127.0.0.1";
const isDev = process.env.NODE_ENV === "development";

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
  }
  backend = spawn(cmd, args, { cwd, env, stdio: "inherit" });
  backend.on("exit", (code) => {
    if (code && code !== 0) console.error(`[backend] exited with code ${code}`);
  });
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
  win.once("ready-to-show", () => win?.show());
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
    apiPort = isDev ? Number(process.env.MRP_API_PORT ?? 8000) : await freePort();
    // The preload reads MRP_API_PORT to build the API base URL — keep them in sync.
    process.env.MRP_API_PORT = String(apiPort);

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

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) void createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("quit", () => {
  backend?.kill();
  backend = null;
});
