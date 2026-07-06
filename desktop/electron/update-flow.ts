/**
 * UpdateFlow — the explicit state machine behind "Restart & install".
 *
 * The application must NEVER appear frozen: every step of the update
 * lifecycle (check → download → verify → restart → install → relaunch →
 * healthy) is an explicit state with a label, status text, optional
 * progress, per-state timing and a log line — streamed to the renderer so
 * the Update screen always says exactly what is happening.
 *
 * The machine survives the restart: main.ts serializes it to a marker file
 * before `quitAndInstall()`, and the next launch resumes it (same start
 * epoch, prior states intact) so the post-install states (starting-backend
 * → waiting-for-health → opening-desktop → ready) complete the SAME flow
 * and the final report covers the whole journey — including every
 * operation that took more than 250 ms.
 *
 * Pure and clock-injectable (no `electron` import) so it is unit-testable,
 * matching startup-trace.ts / automation.ts.
 */

export type UpdateFlowState =
  | "idle"
  | "checking-for-updates"
  | "downloading-update"
  | "verifying-update"
  | "preparing-restart"
  | "stopping-backend"
  | "waiting-for-shutdown"
  | "launching-installer"
  | "waiting-for-installer"
  | "starting-backend"
  | "waiting-for-health"
  | "opening-desktop"
  | "ready"
  | "failed";

/** Human strings per state: what is happening + roughly how long it takes. */
export const STATE_TEXT: Record<UpdateFlowState, { label: string; expects: string }> = {
  idle: { label: "Idle", expects: "" },
  "checking-for-updates": { label: "Checking for updates…", expects: "usually under 3 seconds" },
  "downloading-update": { label: "Downloading update…", expects: "depends on your connection" },
  "verifying-update": { label: "Verifying update…", expects: "usually under 2 seconds" },
  "preparing-restart": { label: "Preparing restart…", expects: "under 1 second" },
  "stopping-backend": { label: "Backend shutting down…", expects: "usually 1–5 seconds" },
  "waiting-for-shutdown": { label: "Waiting for shutdown…", expects: "up to 7 seconds" },
  "launching-installer": { label: "Installer launching…", expects: "a few seconds" },
  "waiting-for-installer": {
    label: "Waiting for installer…",
    expects: "10–30 seconds — the window closes while the installer runs",
  },
  "starting-backend": { label: "Backend starting…", expects: "usually 2–8 seconds" },
  "waiting-for-health": { label: "Loading workspace…", expects: "usually 1–5 seconds" },
  "opening-desktop": { label: "Opening dashboard…", expects: "under 2 seconds" },
  ready: { label: "Ready", expects: "" },
  failed: { label: "Update failed", expects: "" },
};

export interface UpdateFlowEvent {
  state: UpdateFlowState;
  label: string;
  expects: string;
  detail: string | null;
  progress: number | null; // 0..1 when determinate (download), else null
  sequence: number;
  sinceStartMs: number;
  inStateMs: number;
  error: string | null;
  /**
   * True for an UNATTENDED (automatic) update — check → prompt-confirmed →
   * download → install with no further clicks. The overlay uses this to narrate
   * the download/verify phases too; a manual download (from the Updates screen,
   * where the user watches inline progress) leaves this false so the overlay
   * stays hidden until the restart sequence.
   */
  unattended: boolean;
}

export interface UpdateFlowLogEntry {
  at: string; // ISO
  state: UpdateFlowState;
  message: string;
}

interface StateVisit {
  state: UpdateFlowState;
  enteredAtEpoch: number;
  detail: string | null;
}

export interface UpdateFlowReport {
  startedAt: string | null;
  finishedAt: string | null;
  totalMs: number | null;
  completed: boolean;
  failedAt: UpdateFlowState | null;
  error: string | null;
  states: { state: UpdateFlowState; label: string; durationMs: number; detail: string | null }[];
  /** Every operation over the responsiveness budget (250 ms), slowest first. */
  slowOperations: { state: UpdateFlowState; label: string; durationMs: number }[];
  log: UpdateFlowLogEntry[];
}

export interface SerializedUpdateFlow {
  version: 1;
  startedAtEpoch: number;
  visits: StateVisit[];
  log: UpdateFlowLogEntry[];
  progress: number | null;
  error: string | null;
  /** Whether this is an unattended (automatic) update — see UpdateFlowEvent. */
  unattended?: boolean;
}

export const SLOW_OPERATION_MS = 250;
export const REASSURANCE_AFTER_MS = 5_000;

/** Should the UI add "still working — safe to leave running" reassurance? */
export function needsReassurance(state: UpdateFlowState, msInState: number): boolean {
  if (state === "ready" || state === "idle" || state === "failed") return false;
  return msInState >= REASSURANCE_AFTER_MS;
}

export type FlowListener = (event: UpdateFlowEvent) => void;

export class UpdateFlow {
  private visits: StateVisit[] = [];
  private logEntries: UpdateFlowLogEntry[] = [];
  private progressValue: number | null = null;
  private errorMessage: string | null = null;
  private unattendedFlag = false;
  private sequence = 0;
  private listeners: FlowListener[] = [];

  constructor(
    private readonly now: () => number = () => Date.now(),
    startedAtEpoch: number | null = null,
  ) {
    this.startedAtEpoch = startedAtEpoch;
  }

  private startedAtEpoch: number | null;

  onEvent(listener: FlowListener): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((l) => l !== listener);
    };
  }

  get state(): UpdateFlowState {
    return this.visits.length ? this.visits[this.visits.length - 1].state : "idle";
  }

  get active(): boolean {
    return this.visits.length > 0 && this.state !== "ready" && this.state !== "failed";
  }

  get unattended(): boolean {
    return this.unattendedFlag;
  }

  /** Mark this flow as an unattended (automatic) update; emits so the UI reacts. */
  setUnattended(value: boolean): void {
    if (this.unattendedFlag === value) return;
    this.unattendedFlag = value;
    this.emit();
  }

  /** Enter a state (idempotent for repeats), log it, notify listeners. */
  transition(state: UpdateFlowState, detail?: string): void {
    const at = this.now();
    if (this.startedAtEpoch === null) this.startedAtEpoch = at;
    if (this.state !== state) {
      this.visits.push({ state, enteredAtEpoch: at, detail: detail ?? null });
    } else if (detail) {
      this.visits[this.visits.length - 1].detail = detail;
    }
    if (state !== "downloading-update") this.progressValue = null;
    this.log(detail ? `${STATE_TEXT[state].label} — ${detail}` : STATE_TEXT[state].label);
    this.emit();
  }

  /** Determinate progress for the current state (e.g. download percent). */
  setProgress(fraction: number, detail?: string): void {
    this.progressValue = Math.max(0, Math.min(1, fraction));
    if (detail) this.log(detail);
    this.emit();
  }

  fail(error: unknown, detail?: string): void {
    this.errorMessage = error instanceof Error ? error.message : String(error);
    this.log(`FAILED: ${this.errorMessage}${detail ? ` (${detail})` : ""}`);
    this.transition("failed", detail);
  }

  log(message: string): void {
    this.logEntries.push({
      at: new Date(this.now()).toISOString(),
      state: this.state,
      message,
    });
  }

  snapshot(): UpdateFlowEvent {
    const at = this.now();
    const current = this.visits.length ? this.visits[this.visits.length - 1] : null;
    const text = STATE_TEXT[this.state];
    return {
      state: this.state,
      label: text.label,
      expects: text.expects,
      detail: current?.detail ?? null,
      progress: this.progressValue,
      sequence: this.sequence,
      sinceStartMs: this.startedAtEpoch === null ? 0 : at - this.startedAtEpoch,
      inStateMs: current === null ? 0 : at - current.enteredAtEpoch,
      error: this.errorMessage,
      unattended: this.unattendedFlag,
    };
  }

  report(): UpdateFlowReport {
    const at = this.now();
    const finished = this.state === "ready" || this.state === "failed";
    const states = this.visits.map((visit, index) => {
      const next = this.visits[index + 1];
      return {
        state: visit.state,
        label: STATE_TEXT[visit.state].label,
        durationMs: (next ? next.enteredAtEpoch : at) - visit.enteredAtEpoch,
        detail: visit.detail,
      };
    });
    const slow = states
      .filter(
        (s) => s.durationMs > SLOW_OPERATION_MS && s.state !== "ready" && s.state !== "failed",
      )
      .sort((a, b) => b.durationMs - a.durationMs)
      .map(({ state, label, durationMs }) => ({ state, label, durationMs }));
    return {
      startedAt: this.startedAtEpoch === null ? null : new Date(this.startedAtEpoch).toISOString(),
      finishedAt: finished ? new Date(at).toISOString() : null,
      totalMs: this.startedAtEpoch === null ? null : at - this.startedAtEpoch,
      completed: this.state === "ready",
      failedAt: this.state === "failed" ? this.state : null,
      error: this.errorMessage,
      states,
      slowOperations: slow,
      log: [...this.logEntries],
    };
  }

  /** Persist across the quit → installer → relaunch boundary. */
  serialize(): SerializedUpdateFlow {
    return {
      version: 1,
      startedAtEpoch: this.startedAtEpoch ?? this.now(),
      visits: [...this.visits],
      log: [...this.logEntries],
      progress: this.progressValue,
      error: this.errorMessage,
      unattended: this.unattendedFlag,
    };
  }

  static resume(saved: SerializedUpdateFlow, now: () => number = () => Date.now()): UpdateFlow {
    const flow = new UpdateFlow(now, saved.startedAtEpoch);
    flow.visits = [...saved.visits];
    flow.logEntries = [...saved.log];
    flow.progressValue = saved.progress;
    flow.errorMessage = saved.error;
    flow.unattendedFlag = saved.unattended ?? false;
    return flow;
  }

  private emit(): void {
    this.sequence += 1;
    const event = this.snapshot();
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        /* a broken listener must never break the flow */
      }
    }
  }
}
