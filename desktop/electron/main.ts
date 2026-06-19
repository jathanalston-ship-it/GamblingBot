/**
 * Electron main process.
 *
 * Responsibilities:
 *   1. Spawn the FastAPI backend as a private, loopback-only sidecar.
 *   2. Wait for the backend's /health before showing the window.
 *   3. Create the BrowserWindow (Vite dev server in dev, built files in prod).
 *   4. Tear the sidecar down on quit.
 *
 * Security: contextIsolation on, nodeIntegration off; the renderer talks to the
 * backend only over http://127.0.0.1:<port> and only via the typed preload bridge.
 */
import { ChildProcess, spawn } from "node:child_process";
import { join } from "node:path";

import { app, BrowserWindow, shell } from "electron";

const API_HOST = "127.0.0.1";
const API_PORT = Number(process.env.MRP_API_PORT ?? 8000);
const API_BASE = `http://${API_HOST}:${API_PORT}`;
const isDev = process.env.NODE_ENV === "development";

let backend: ChildProcess | null = null;
let win: BrowserWindow | null = null;

/** Resolve the backend command: bundled binary in prod, `python -m momentum.api` in dev. */
function backendCommand(): { cmd: string; args: string[]; cwd: string } {
  if (isDev) {
    const python = process.env.MRP_PYTHON ?? "python3";
    const repoRoot = join(__dirname, "..", "..");
    return { cmd: python, args: ["-m", "momentum.api"], cwd: repoRoot };
  }
  // packaged: a PyInstaller one-file binary shipped under resources/backend/
  const binary = process.platform === "win32" ? "mrp-backend.exe" : "mrp-backend";
  return { cmd: join(process.resourcesPath, "backend", binary), args: [], cwd: process.resourcesPath };
}

function startBackend(): void {
  const { cmd, args, cwd } = backendCommand();
  backend = spawn(cmd, args, {
    cwd,
    env: {
      ...process.env,
      MRP_API_HOST: API_HOST,
      MRP_API_PORT: String(API_PORT),
      PYTHONPATH: isDev ? join(cwd, "src") : process.env.PYTHONPATH ?? "",
    },
    stdio: "inherit",
  });
  backend.on("exit", (code) => {
    if (code && code !== 0) console.error(`[backend] exited with code ${code}`);
  });
}

async function waitForBackend(timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${API_BASE}/health`);
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
    title: "Momentum Research Platform",
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // open external links in the OS browser, not inside the app
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    await win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    await win.loadFile(join(__dirname, "..", "renderer", "index.html"));
  }
  win.once("ready-to-show", () => win?.show());
}

app.whenReady().then(async () => {
  startBackend();
  try {
    await waitForBackend();
  } catch (err) {
    console.error(err);
  }
  await createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("quit", () => {
  backend?.kill();
  backend = null;
});
