#!/usr/bin/env node
/**
 * Unit tests for the BackendManager lifecycle.
 *
 * Plain-Node tests (matching the smoke.cjs pattern — the desktop has no test
 * runner): the manager is dependency-injected (spawn / fetch / clock / delay), so
 * we drive every lifecycle path with fakes and assert state transitions. No
 * Electron, no real backend, no network.
 *
 * Prerequisite: `npm run build:electron` (compiles dist-electron/backend-manager.js).
 */
"use strict";

const assert = require("node:assert");
const { EventEmitter } = require("node:events");
const { BackendManager } = require("../dist-electron/backend-manager.js");

let lastProc = null;

class FakeProc extends EventEmitter {
  constructor() {
    super();
    this.stdout = new EventEmitter();
    this.stderr = new EventEmitter();
    this.pid = 4242;
    this.exitCode = null;
    this.signals = [];
    this.exitOnSigterm = false;
  }
  kill(sig) {
    this.signals.push(sig);
    if (sig === "SIGTERM" && this.exitOnSigterm) this.simulateExit(0, sig);
    if (sig === "SIGKILL") this.simulateExit(137, sig);
    return true;
  }
  simulateExit(code, signal) {
    if (this.exitCode !== null) return;
    this.exitCode = code;
    this.emit("exit", code, signal ?? null);
  }
}

function makeManager(opts = {}) {
  const statuses = [];
  const restarted = [];
  const gaveUp = [];
  const state = { healthy: opts.healthy ?? false, spawns: 0 };

  const m = new BackendManager({
    host: "127.0.0.1",
    port: 9999,
    command: "fake",
    args: [],
    cwd: ".",
    env: {},
    startupTimeoutMs: opts.startupTimeoutMs ?? 100,
    pollIntervalMs: 1,
    startAttempts: opts.startAttempts ?? 2,
    shutdownTimeoutMs: opts.shutdownTimeoutMs ?? 20,
    restartDelayMs: 0,
    maxRestarts: opts.maxRestarts ?? 3,
    delay: () => Promise.resolve(),
    now: opts.now,
    fetchFn: async () => ({ ok: state.healthy }),
    spawnFn: () => {
      state.spawns += 1;
      lastProc = new FakeProc();
      if (opts.healthyOnSpawn) state.healthy = true; // backend "comes up" instantly
      return lastProc;
    },
    log: () => {},
  });
  m.onStatus((s) => statuses.push(s));
  m.onRestarted(() => restarted.push(true));
  m.onGiveUp(() => gaveUp.push(true));
  return { m, statuses, restarted, gaveUp, state };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// 1. Adopt an already-running backend (no spawn).
test("adopts an already-running backend without spawning", async () => {
  const { m, statuses, state } = makeManager({ healthy: true });
  const ok = await m.start();
  assert.strictEqual(ok, true);
  assert.strictEqual(state.spawns, 0, "must not spawn when one is already running");
  assert.deepStrictEqual(statuses, ["starting", "healthy"]);
});

// 2. Cold start: probe fails, spawn, then /health becomes ok.
test("cold start spawns and reaches healthy", async () => {
  const { m, statuses, state } = makeManager({ healthy: false, healthyOnSpawn: true });
  const ok = await m.start();
  assert.strictEqual(ok, true);
  assert.strictEqual(state.spawns, 1);
  assert.deepStrictEqual(statuses, ["starting", "healthy"]);
});

// 3. Start failure: never healthy -> status "failed" after the attempts.
test("reports failed when the backend never becomes healthy", async () => {
  let t = 0;
  const now = () => (t += 30); // advance the clock so the health wait times out fast
  const { m, statuses, state } = makeManager({ healthy: false, startAttempts: 2, now });
  const ok = await m.start();
  assert.strictEqual(ok, false);
  assert.strictEqual(state.spawns, 2, "should retry the configured number of times");
  assert.strictEqual(statuses[0], "starting");
  assert.strictEqual(statuses[statuses.length - 1], "failed");
});

// 4. Graceful shutdown: SIGTERM, the process exits, no force needed.
test("graceful stop sends SIGTERM and resolves when the process exits", async () => {
  const { m, statuses } = makeManager({ healthy: false, healthyOnSpawn: true });
  await m.start();
  lastProc.exitOnSigterm = true;
  await m.stop();
  assert.deepStrictEqual(lastProc.signals, ["SIGTERM"], "graceful only — no SIGKILL");
  assert.strictEqual(statuses[statuses.length - 1], "stopped");
});

// 5. Force after timeout: process ignores SIGTERM -> SIGKILL.
test("force-kills the tree if graceful overruns the timeout", async () => {
  const { m } = makeManager({ healthy: false, healthyOnSpawn: true, shutdownTimeoutMs: 5 });
  await m.start();
  lastProc.exitOnSigterm = false; // ignore graceful
  await m.stop();
  assert.deepStrictEqual(lastProc.signals, ["SIGTERM", "SIGKILL"]);
});

// 6. Crash recovery: a healthy backend dies -> restarting -> healthy + reload signal.
test("recovers (restart) when a healthy backend crashes", async () => {
  const { m, statuses, restarted, state } = makeManager({ healthy: false, healthyOnSpawn: true });
  await m.start();
  assert.strictEqual(state.spawns, 1);
  const crashed = lastProc;
  crashed.simulateExit(1); // unexpected death
  await new Promise((r) => setTimeout(r, 5)); // let the async restart settle
  assert.strictEqual(state.spawns, 2, "should respawn after a crash");
  assert.ok(statuses.includes("restarting"));
  assert.strictEqual(statuses[statuses.length - 1], "healthy");
  assert.deepStrictEqual(restarted, [true]);
});

// 7. Adopted backend is never killed on stop.
test("does not kill an adopted backend on stop", async () => {
  const { m } = makeManager({ healthy: true });
  await m.start();
  await m.stop();
  // no process was spawned; nothing to assert beyond a clean resolve + no throw
  assert.strictEqual(m.status, "stopped");
});

// 8. Startup diagnostics are recorded on a cold start (for the startup report).
test("records startup diagnostics on a cold start", async () => {
  const { m } = makeManager({ healthy: false, healthyOnSpawn: true });
  await m.start();
  const d = m.diagnostics;
  assert.strictEqual(d.status, "healthy");
  assert.strictEqual(d.adopted, false);
  assert.strictEqual(d.attempts, 1);
  assert.strictEqual(d.pid, 4242, "should report the spawned PID");
  assert.strictEqual(d.executable, "fake");
  assert.ok(typeof d.startupDurationMs === "number", "duration should be measured");
  assert.ok(d.startedAt && d.healthyAt, "both timestamps should be set");
});

// 9. An adopted backend reports a null PID (we did not spawn it).
test("diagnostics mark an adopted backend with a null PID", async () => {
  const { m } = makeManager({ healthy: true });
  await m.start();
  const d = m.diagnostics;
  assert.strictEqual(d.adopted, true);
  assert.strictEqual(d.pid, null);
  assert.strictEqual(d.status, "healthy");
});

// 10. A failed start captures an error tail for the diagnostic report.
test("diagnostics capture an error tail when start fails", async () => {
  let t = 0;
  const now = () => (t += 30);
  const { m } = makeManager({ healthy: false, startAttempts: 1, now });
  await m.start();
  const d = m.diagnostics;
  assert.strictEqual(d.status, "failed");
  assert.ok(d.errorTail, "should capture exit/error lines on failure");
});

// 11. Dev hot-reload restart: stop the owned backend and spawn a fresh one.
test("restart() stops the current backend and starts a new one", async () => {
  const { m, statuses, state } = makeManager({ healthy: false, healthyOnSpawn: true });
  await m.start();
  assert.strictEqual(state.spawns, 1);
  const first = lastProc;
  first.exitOnSigterm = true; // graceful stop succeeds
  state.healthy = false; // the old backend is down until the fresh spawn comes up

  const ok = await m.restart();
  assert.strictEqual(ok, true, "restart should reach healthy again");
  assert.strictEqual(state.spawns, 2, "a fresh backend was spawned");
  assert.ok(first.signals.includes("SIGTERM"), "the old backend was stopped");
  assert.strictEqual(statuses[statuses.length - 1], "healthy");
  assert.notStrictEqual(lastProc, first, "the manager tracks the new process");
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try {
      await fn();
      console.log(`  ok  ${name}`);
    } catch (err) {
      failed += 1;
      console.error(`FAIL  ${name}\n      ${err && err.message}`);
    }
  }
  console.log(`\n${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
