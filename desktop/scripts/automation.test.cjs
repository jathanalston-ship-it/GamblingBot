#!/usr/bin/env node
/**
 * Integration tests for Automation Mode's sleep-blocker lifecycle.
 *
 * Runs the compiled AutomationManager (dist-electron/automation.js) against a
 * fake powerSaveBlocker that counts every start/stop, proving:
 *   • the blocker starts when Auto Pilot starts
 *   • the blocker stops when Auto Pilot stops
 *   • repeated starts NEVER leak blockers (one active id, ever)
 *   • the crash path (dispose) cleans up
 *   • quit releases the blocker (and a double-release is harmless)
 *
 * Prerequisite: `npm run build:electron` (compiles dist-electron/automation.js).
 */
"use strict";

const assert = require("node:assert");
const { AutomationManager } = require("../dist-electron/automation.js");

/** A fake powerSaveBlocker that records every call. */
function fakeBlocker() {
  const state = { nextId: 1, active: new Set(), starts: 0, stops: 0 };
  return {
    state,
    start(type) {
      assert.strictEqual(type, "prevent-app-suspension"); // display may sleep
      state.starts += 1;
      const id = state.nextId++;
      state.active.add(id);
      return id;
    },
    stop(id) {
      state.stops += 1;
      state.active.delete(id);
    },
    isStarted(id) {
      return state.active.has(id);
    },
  };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("blocker starts when Auto Pilot starts", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  const status = mgr.sync(true, true);
  assert.strictEqual(status.automationActive, true);
  assert.strictEqual(status.sleepPrevented, true);
  assert.strictEqual(blocker.state.active.size, 1);
});

test("blocker stops when Auto Pilot stops", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  mgr.sync(true, true);
  const status = mgr.sync(false, true);
  assert.strictEqual(status.sleepPrevented, false);
  assert.strictEqual(blocker.state.active.size, 0);
  assert.strictEqual(blocker.state.stops, 1);
});

test("multiple starts do not leak blockers", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  for (let i = 0; i < 25; i++) mgr.sync(true, true); // 25 “starts”
  assert.strictEqual(blocker.state.starts, 1); // exactly ONE acquisition
  assert.strictEqual(blocker.state.active.size, 1);
  mgr.sync(false, true);
  mgr.sync(true, true); // a genuine restart acquires a fresh one
  assert.strictEqual(blocker.state.starts, 2);
  assert.strictEqual(blocker.state.active.size, 1);
});

test("crash path (dispose) cleans up", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  mgr.sync(true, true);
  mgr.dispose("fatal crash"); // what reportFatalCrash / process.exit call
  assert.strictEqual(blocker.state.active.size, 0);
  assert.strictEqual(mgr.isBlocking(), false);
});

test("blocker released on quit; double release is harmless", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  mgr.sync(true, true);
  mgr.dispose("app quitting"); // will-quit
  mgr.dispose("process exit"); // the exit safety net fires too
  assert.strictEqual(blocker.state.active.size, 0);
  assert.strictEqual(blocker.state.stops, 1); // stopped exactly once
});

test("prevent-sleep OFF never acquires a blocker", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  const status = mgr.sync(true, false); // autopilot on, user opted out
  assert.strictEqual(status.automationActive, true);
  assert.strictEqual(status.sleepPrevented, false);
  assert.strictEqual(blocker.state.starts, 0);
});

test("turning the setting off mid-run releases the blocker", () => {
  const blocker = fakeBlocker();
  const mgr = new AutomationManager(blocker);
  mgr.sync(true, true);
  const status = mgr.sync(true, false);
  assert.strictEqual(status.sleepPrevented, false);
  assert.strictEqual(blocker.state.active.size, 0);
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
