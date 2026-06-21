/**
 * StartupTrace — a forensic record of the Electron main-process startup path.
 *
 * The packaged app gives the user no terminal, so a launch that dies before the
 * window appears (blue cursor, then nothing) is otherwise invisible. This records
 * every startup *stage* with timestamps so the timeline can be logged live, folded
 * into the startup diagnostic report, and — crucially — name the exact stage a
 * failure occurred at (e.g. "free-port", "create-window") instead of vanishing.
 *
 * Deliberately free of any `electron` import and clock-injectable, so it is a pure,
 * unit-testable value object (matching backend-manager.ts). main.ts is the thin
 * host that calls `enter()` at each stage and `fail()` / `done()` at the end.
 */

/** The ordered stages of a packaged launch, start → window painted → backend up. */
export type StartupStage =
  | "module-init"
  | "single-instance-lock"
  | "app-ready"
  | "free-port"
  | "configure-env"
  | "create-manager"
  | "register-ipc"
  | "create-window"
  | "load-renderer"
  | "window-shown"
  | "init-auto-updates"
  | "backend-start"
  | "backend-healthy"
  | "backend-failed"
  | "ready";

/** One entry in the startup timeline: a stage and when it was entered. */
export interface StartupTimelineEntry {
  stage: StartupStage;
  at: string; // ISO timestamp
  sinceStartMs: number; // monotonic delta from the first stage
  sincePrevMs: number; // time spent in the previous stage
  detail?: string;
}

/** The captured failure (stage + error), if the startup did not complete. */
export interface StartupFailure {
  stage: StartupStage;
  at: string;
  message: string;
  stack: string | null;
}

/** A JSON-able snapshot of the whole startup trace, for the diagnostic report. */
export interface StartupTraceReport {
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  reachedWindow: boolean;
  completed: boolean;
  currentStage: StartupStage | null;
  timeline: StartupTimelineEntry[];
  failure: StartupFailure | null;
}

export class StartupTrace {
  private readonly now: () => number;
  private readonly logFn: (line: string) => void;
  private readonly entries: StartupTimelineEntry[] = [];
  private startMs: number | null = null;
  private prevMs: number | null = null;
  private finishedMs: number | null = null;
  private _current: StartupStage | null = null;
  private _failure: StartupFailure | null = null;
  private _completed = false;

  constructor(opts: { now?: () => number; log?: (line: string) => void } = {}) {
    this.now = opts.now ?? Date.now;
    this.logFn = opts.log ?? (() => {});
  }

  /** Mark entry into a new startup stage; logs `→ stage (+Nms)` and records it. */
  enter(stage: StartupStage, detail?: string): void {
    const t = this.now();
    if (this.startMs === null) this.startMs = t;
    const sinceStartMs = t - this.startMs;
    const sincePrevMs = this.prevMs === null ? 0 : t - this.prevMs;
    this.prevMs = t;
    this._current = stage;
    const entry: StartupTimelineEntry = {
      stage,
      at: new Date(t).toISOString(),
      sinceStartMs,
      sincePrevMs,
      ...(detail !== undefined ? { detail } : {}),
    };
    this.entries.push(entry);
    this.logFn(
      `[startup] → ${stage} (+${sinceStartMs}ms, ${sincePrevMs}ms in prev)` +
        (detail ? ` ${detail}` : ""),
    );
  }

  /** True once the renderer has actually painted (window became visible). */
  get reachedWindow(): boolean {
    return this.entries.some((e) => e.stage === "window-shown");
  }

  get current(): StartupStage | null {
    return this._current;
  }

  get failure(): StartupFailure | null {
    return this._failure;
  }

  /** Record a startup failure at the current stage (idempotent — first wins). */
  fail(err: unknown): void {
    if (this._failure) return;
    const t = this.now();
    this.finishedMs = t;
    // Only a real Error carries a meaningful stack; a thrown string/value gets a
    // null stack (a synthetic one would just point back into this method).
    const error = err instanceof Error ? err : null;
    this._failure = {
      stage: this._current ?? "module-init",
      at: new Date(t).toISOString(),
      message: error ? error.message || String(err) : String(err),
      stack: error?.stack ?? null,
    };
    this.logFn(`[startup] ✗ FAILED at stage "${this._failure.stage}": ${this._failure.message}`);
  }

  /** Mark a clean startup completion (backend healthy, app interactive). */
  done(): void {
    if (this._completed) return;
    this._completed = true;
    this.finishedMs = this.now();
    this.enter("ready");
  }

  get timeline(): StartupTimelineEntry[] {
    return [...this.entries];
  }

  /** A one-line human summary of the timeline, for the log file. */
  summary(): string {
    const parts = this.entries.map((e) => `${e.stage}@+${e.sinceStartMs}ms`);
    const tail = this._failure
      ? ` FAILED@${this._failure.stage}: ${this._failure.message}`
      : this._completed
        ? " OK"
        : " (incomplete)";
    return parts.join(" → ") + tail;
  }

  toReport(): StartupTraceReport {
    const durationMs =
      this.startMs !== null && this.finishedMs !== null ? this.finishedMs - this.startMs : null;
    return {
      startedAt: this.startMs !== null ? new Date(this.startMs).toISOString() : null,
      finishedAt: this.finishedMs !== null ? new Date(this.finishedMs).toISOString() : null,
      durationMs,
      reachedWindow: this.reachedWindow,
      completed: this._completed,
      currentStage: this._current,
      timeline: this.timeline,
      failure: this._failure,
    };
  }
}
