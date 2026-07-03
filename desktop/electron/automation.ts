/**
 * Automation Mode — keep the machine awake while Auto Pilot runs.
 *
 * Wraps Electron's `powerSaveBlocker` with the guarantees the trading loop
 * needs:
 *
 *   • `prevent-app-suspension` mode: the OS will NOT enter system sleep, so
 *     the CPU, timers, networking, the scheduler and the backend keep
 *     running — but the DISPLAY may still sleep, the screen saver may run
 *     and the user may lock the machine (none of those pause processes).
 *   • Exactly one blocker, ever: repeated syncs reuse the active blocker
 *     (no leaks); turning automation off (or disabling prevent-sleep)
 *     releases it.
 *   • Released on quit and on crash-path teardown ('will-quit' + process
 *     'exit'); if the process dies harder than that, the OS itself drops
 *     the blocker with the process — a blocker can never outlive the app.
 *
 * Pure module (no `electron` import): main.ts injects the real
 * `powerSaveBlocker`, so the whole lifecycle is unit-testable in plain Node.
 */

/** The subset of Electron's powerSaveBlocker this module needs (injectable). */
export interface SleepBlocker {
  start(type: "prevent-app-suspension" | "prevent-display-sleep"): number;
  stop(id: number): void;
  isStarted(id: number): boolean;
}

export interface AutomationStatus {
  /** Auto Pilot is on (per the backend settings). */
  automationActive: boolean;
  /** A power-save blocker is currently held. */
  sleepPrevented: boolean;
  /** The user's prevent-sleep preference (Settings → Automation). */
  preventSleepSetting: boolean;
  blockerId: number | null;
}

export class AutomationManager {
  private blockerId: number | null = null;
  private automationActive = false;
  private preventSleepSetting = true;

  constructor(
    private readonly blocker: SleepBlocker,
    private readonly log: (line: string) => void = () => undefined,
  ) {}

  /**
   * Reconcile the blocker with the desired state. Idempotent: calling this
   * any number of times holds at most ONE blocker.
   */
  sync(automationActive: boolean, preventSleep: boolean): AutomationStatus {
    this.automationActive = automationActive;
    this.preventSleepSetting = preventSleep;
    const shouldBlock = automationActive && preventSleep;

    if (shouldBlock && !this.isBlocking()) {
      this.blockerId = this.blocker.start("prevent-app-suspension");
      this.log(
        `[automation] Automation Mode Active — Sleep Prevented (blocker ${this.blockerId})`,
      );
    } else if (!shouldBlock && this.isBlocking()) {
      this.release("automation stopped");
    }
    return this.status();
  }

  /** Release the blocker unconditionally (quit / crash teardown). */
  dispose(reason = "app quitting"): void {
    this.release(reason);
  }

  isBlocking(): boolean {
    return this.blockerId !== null && this.blocker.isStarted(this.blockerId);
  }

  status(): AutomationStatus {
    return {
      automationActive: this.automationActive,
      sleepPrevented: this.isBlocking(),
      preventSleepSetting: this.preventSleepSetting,
      blockerId: this.isBlocking() ? this.blockerId : null,
    };
  }

  private release(reason: string): void {
    if (this.blockerId !== null) {
      try {
        if (this.blocker.isStarted(this.blockerId)) {
          this.blocker.stop(this.blockerId);
        }
      } finally {
        this.log(`[automation] sleep blocker ${this.blockerId} released (${reason})`);
        this.blockerId = null;
      }
    }
  }
}
