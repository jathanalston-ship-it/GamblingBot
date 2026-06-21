/**
 * BackendManager — Electron owns the FastAPI backend lifecycle.
 *
 * Responsibilities:
 *   • Launch: detect an already-running backend (adopt it) or spawn one, then wait
 *     for GET /health, retrying a bounded number of times.
 *   • Status: emit "starting" / "healthy" / "failed" / "restarting" / "stopped" so the
 *     renderer can show a loading screen until healthy.
 *   • Crash recovery: respawn (bounded) if the backend dies after it was healthy.
 *   • Shutdown: graceful signal → wait → force-kill the whole process tree.
 *
 * Deliberately free of any `electron` import and fully dependency-injectable
 * (spawn / fetch / clock / delay / log), so the lifecycle is unit-testable in plain
 * Node. Electron wiring (status → renderer, dialogs) lives in main.ts via listeners.
 */
import { ChildProcess, spawn as nodeSpawn, spawnSync } from "node:child_process";

export type BackendStatus = "starting" | "healthy" | "failed" | "restarting" | "stopped";

/**
 * A structured record of how the backend came up, for the startup diagnostic
 * report written to disk. Owns the things only the launcher can see: the
 * executable it spawned, the PID, how long start → healthy took, the final
 * health status, whether an already-running backend was adopted, and the tail of
 * any captured startup exceptions. Configuration / database path come from the
 * launch environment (filled in by main.ts).
 */
export interface StartupDiagnostics {
  executable: string;
  args: string[];
  cwd: string;
  pid: number | null;
  adopted: boolean;
  attempts: number;
  status: BackendStatus;
  healthUrl: string;
  startedAt: string | null;
  healthyAt: string | null;
  startupDurationMs: number | null;
  errorTail: string | null;
}

type SpawnFn = (
  cmd: string,
  args: string[],
  opts: { cwd: string; env: NodeJS.ProcessEnv; stdio: ["ignore", "pipe", "pipe"] },
) => ChildProcess;
type FetchFn = (url: string) => Promise<{ ok: boolean }>;

export interface BackendManagerOptions {
  host: string;
  port: number;
  command: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  startupTimeoutMs?: number;
  pollIntervalMs?: number;
  startAttempts?: number;
  shutdownTimeoutMs?: number;
  restartDelayMs?: number;
  maxRestarts?: number;
  logTailLines?: number;
  // injected for tests:
  spawnFn?: SpawnFn;
  fetchFn?: FetchFn;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
  log?: (line: string) => void;
}

export class BackendManager {
  readonly host: string;
  readonly port: number;
  private readonly command: string;
  private readonly args: string[];
  private readonly cwd: string;
  private readonly env: NodeJS.ProcessEnv;
  private readonly startupTimeoutMs: number;
  private readonly pollIntervalMs: number;
  private readonly startAttempts: number;
  private readonly shutdownTimeoutMs: number;
  private readonly restartDelayMs: number;
  private readonly maxRestarts: number;
  private readonly logTailLines: number;
  private readonly spawnFn: SpawnFn;
  private readonly fetchFn: FetchFn;
  private readonly now: () => number;
  private readonly delay: (ms: number) => Promise<void>;
  private readonly logFn: (line: string) => void;

  private proc: ChildProcess | null = null;
  private _status: BackendStatus = "stopped";
  private exited = false;
  private adopted = false; // reused a backend we didn't start — never kill it
  private shuttingDown = false;
  private recoveryEnabled = false;
  private restarting = false;
  private restarts = 0;
  private attempts = 0;
  private startedAtMs: number | null = null;
  private healthyAtMs: number | null = null;
  private readonly logBuf: string[] = [];

  private statusCbs: ((s: BackendStatus) => void)[] = [];
  private restartedCbs: (() => void)[] = [];
  private giveUpCbs: (() => void)[] = [];

  constructor(o: BackendManagerOptions) {
    this.host = o.host;
    this.port = o.port;
    this.command = o.command;
    this.args = o.args;
    this.cwd = o.cwd;
    this.env = o.env;
    this.startupTimeoutMs = o.startupTimeoutMs ?? 30_000;
    this.pollIntervalMs = o.pollIntervalMs ?? 300;
    this.startAttempts = o.startAttempts ?? 2;
    this.shutdownTimeoutMs = o.shutdownTimeoutMs ?? 5_000;
    this.restartDelayMs = o.restartDelayMs ?? 800;
    this.maxRestarts = o.maxRestarts ?? 3;
    this.logTailLines = o.logTailLines ?? 120;
    this.spawnFn = o.spawnFn ?? (nodeSpawn as SpawnFn);
    this.fetchFn = o.fetchFn ?? ((url: string) => fetch(url));
    this.now = o.now ?? Date.now;
    this.delay = o.delay ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));
    this.logFn = o.log ?? (() => {});
  }

  // -- observation -------------------------------------------------------- //
  get status(): BackendStatus {
    return this._status;
  }
  get healthUrl(): string {
    return `http://${this.host}:${this.port}/health`;
  }
  get logTail(): string {
    return this.logBuf.join("\n") || "(no backend output was captured)";
  }

  /** The launcher's view of how the backend came up (for the startup report). */
  get diagnostics(): StartupDiagnostics {
    const errorLines = this.logBuf.filter((l) => /\b(error|exception|traceback|exit|failed)\b/i.test(l));
    const duration =
      this.startedAtMs !== null && this.healthyAtMs !== null
        ? this.healthyAtMs - this.startedAtMs
        : null;
    return {
      executable: this.command,
      args: [...this.args],
      cwd: this.cwd,
      pid: this.adopted ? null : (this.proc?.pid ?? null),
      adopted: this.adopted,
      attempts: this.attempts,
      status: this._status,
      healthUrl: this.healthUrl,
      startedAt: this.startedAtMs !== null ? new Date(this.startedAtMs).toISOString() : null,
      healthyAt: this.healthyAtMs !== null ? new Date(this.healthyAtMs).toISOString() : null,
      startupDurationMs: duration,
      errorTail: errorLines.length ? errorLines.slice(-20).join("\n") : null,
    };
  }
  onStatus(cb: (s: BackendStatus) => void): void {
    this.statusCbs.push(cb);
  }
  onRestarted(cb: () => void): void {
    this.restartedCbs.push(cb);
  }
  onGiveUp(cb: () => void): void {
    this.giveUpCbs.push(cb);
  }

  private setStatus(s: BackendStatus): void {
    if (this._status === s) return;
    this._status = s;
    this.logFn(`status → ${s}`);
    for (const cb of this.statusCbs) cb(s);
  }
  private pushLog(chunk: string): void {
    for (const raw of chunk.split(/\r?\n/)) {
      const line = raw.trimEnd();
      if (!line) continue;
      this.logBuf.push(line);
      if (this.logBuf.length > this.logTailLines) this.logBuf.shift();
      this.logFn(`[backend] ${line}`);
    }
  }

  // -- health ------------------------------------------------------------- //
  async probeHealth(): Promise<boolean> {
    try {
      const res = await this.fetchFn(this.healthUrl);
      return !!res.ok;
    } catch {
      return false;
    }
  }

  private async waitForHealth(): Promise<boolean> {
    const deadline = this.now() + this.startupTimeoutMs;
    while (this.now() < deadline) {
      if (this.exited) return false; // fail fast — don't poll a dead process
      if (await this.probeHealth()) return true;
      await this.delay(this.pollIntervalMs);
    }
    return false;
  }

  // -- launch ------------------------------------------------------------- //
  /** Bring the backend up: adopt an already-running one, else spawn + verify. */
  async start(): Promise<boolean> {
    this.shuttingDown = false;
    if (this.startedAtMs === null) this.startedAtMs = this.now();
    this.setStatus("starting");

    // 1. already running? (a leftover sidecar or a dev server) — adopt it.
    if (await this.probeHealth()) {
      this.adopted = true;
      this.recoveryEnabled = false; // we don't own it, so we don't restart/kill it
      this.healthyAtMs = this.now();
      this.logFn("adopted an already-running backend");
      this.setStatus("healthy");
      return true;
    }

    // 2. spawn + health-verify, retrying.
    for (let attempt = 1; attempt <= this.startAttempts; attempt++) {
      this.attempts++;
      this.spawnProcess();
      if (await this.waitForHealth()) {
        this.recoveryEnabled = true;
        this.restarts = 0;
        this.healthyAtMs = this.now();
        this.setStatus("healthy");
        return true;
      }
      this.logFn(`start attempt ${attempt}/${this.startAttempts} failed`);
      await this.killTree(this.proc, true);
      this.proc = null;
      await this.delay(500);
    }
    this.setStatus("failed");
    return false;
  }

  private spawnProcess(): void {
    this.exited = false;
    try {
      this.proc = this.spawnFn(this.command, this.args, {
        cwd: this.cwd,
        env: this.env,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (err) {
      this.exited = true;
      this.pushLog(`[spawn failed] ${String((err as Error)?.message ?? err)}`);
      return;
    }
    this.proc.stdout?.on("data", (b: Buffer) => this.pushLog(b.toString()));
    this.proc.stderr?.on("data", (b: Buffer) => this.pushLog(b.toString()));
    this.proc.on("error", (err) => {
      this.exited = true;
      this.pushLog(`[spawn error] ${err.message}`);
    });
    this.proc.on("exit", (code, signal) => {
      this.exited = true;
      if (code && code !== 0) this.pushLog(`[exit] code=${code} signal=${signal ?? "-"}`);
      if (this.recoveryEnabled && !this.shuttingDown && !this.adopted) void this.scheduleRestart();
    });
  }

  // -- crash recovery ----------------------------------------------------- //
  private async scheduleRestart(): Promise<void> {
    if (this.restarting || this.shuttingDown) return;
    if (this.restarts >= this.maxRestarts) {
      this.setStatus("failed");
      for (const cb of this.giveUpCbs) cb();
      return;
    }
    this.restarting = true;
    this.restarts++;
    this.setStatus("restarting");
    await this.delay(this.restartDelayMs);
    this.restarting = false;
    if (this.shuttingDown) return;

    this.spawnProcess();
    if (await this.waitForHealth()) {
      this.restarts = 0;
      this.setStatus("healthy");
      for (const cb of this.restartedCbs) cb();
    } else {
      // force the dud; its exit event re-enters scheduleRestart (bounded).
      await this.killTree(this.proc, true);
      this.proc = null;
    }
  }

  // -- shutdown ----------------------------------------------------------- //
  markShuttingDown(): void {
    this.shuttingDown = true;
  }

  /**
   * Stop the backend we own and start a fresh one (development hot-reload).
   *
   * Used by the dev source-watcher to pick up Python changes: crash-recovery is
   * suppressed so the deliberate stop isn't "recovered", the old tree is torn
   * down, then a clean spawn + health-verify runs. An adopted (externally-owned)
   * backend is not killed — we just re-probe it.
   */
  async restart(): Promise<boolean> {
    this.recoveryEnabled = false;
    await this.stop();
    this.adopted = false;
    this.shuttingDown = false;
    this.restarts = 0;
    this.healthyAtMs = null;
    return this.start();
  }

  /** Graceful stop → wait → force-kill the tree. Adopted backends are left alone. */
  async stop(): Promise<void> {
    this.shuttingDown = true;
    const proc = this.proc;
    this.proc = null;
    if (this.adopted || !proc || proc.exitCode !== null) {
      this.setStatus("stopped");
      return;
    }
    const exited = new Promise<void>((resolve) => proc.once("exit", () => resolve()));
    await this.killTree(proc, false); // 1. graceful
    await Promise.race([exited, this.delay(this.shutdownTimeoutMs)]);
    if (proc.exitCode === null) {
      await this.killTree(proc, true); // 2. force the whole tree
      await Promise.race([exited, this.delay(2_000)]);
    }
    this.setStatus("stopped");
  }

  /** Synchronous force-kill — the last-resort net for process exit / crashes. */
  forceKillSync(): void {
    const proc = this.proc;
    if (this.adopted || !proc || proc.exitCode !== null) return;
    const pid = proc.pid;
    try {
      if (process.platform === "win32" && pid) {
        spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
      } else {
        proc.kill("SIGKILL");
      }
    } catch {
      /* best effort */
    }
  }

  private async killTree(proc: ChildProcess | null, force: boolean): Promise<void> {
    if (!proc || proc.exitCode !== null) return;
    const pid = proc.pid;
    try {
      if (process.platform === "win32" && pid) {
        // `taskkill /T` takes down the PyInstaller child too; without /F it asks
        // for a graceful close first.
        const args = force
          ? ["/pid", String(pid), "/T", "/F"]
          : ["/pid", String(pid), "/T"];
        nodeSpawn("taskkill", args, { stdio: "ignore" });
      } else {
        proc.kill(force ? "SIGKILL" : "SIGTERM");
      }
    } catch {
      /* best effort */
    }
  }
}
