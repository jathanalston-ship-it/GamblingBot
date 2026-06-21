#!/usr/bin/env node
/**
 * Unit tests for StartupTrace (the forensic startup timeline).
 *
 * Plain-Node tests (matching backend-manager.test.cjs): the trace is clock-
 * injectable, so we drive the timeline deterministically and assert the report it
 * produces — especially that a failure NAMES the stage it died at (the whole point
 * of the instrument).
 *
 * Prerequisite: `npm run build:electron` (compiles dist-electron/startup-trace.js).
 */
"use strict";

const assert = require("node:assert");
const { StartupTrace } = require("../dist-electron/startup-trace.js");

/** A controllable monotonic clock. */
function fakeClock(start = 1_000) {
  let t = start;
  return {
    now: () => t,
    advance: (ms) => {
      t += ms;
    },
  };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("records ordered stages with monotonic deltas", () => {
  const clock = fakeClock();
  const tr = new StartupTrace({ now: clock.now });
  tr.enter("module-init");
  clock.advance(5);
  tr.enter("app-ready");
  clock.advance(20);
  tr.enter("free-port");

  const r = tr.toReport();
  assert.deepStrictEqual(
    r.timeline.map((e) => e.stage),
    ["module-init", "app-ready", "free-port"],
  );
  assert.strictEqual(r.timeline[0].sinceStartMs, 0);
  assert.strictEqual(r.timeline[1].sinceStartMs, 5);
  assert.strictEqual(r.timeline[2].sinceStartMs, 25);
  assert.strictEqual(r.timeline[2].sincePrevMs, 20, "time spent in the previous stage");
  assert.strictEqual(r.currentStage, "free-port");
});

test("a failure names the stage it died at", () => {
  const clock = fakeClock();
  const tr = new StartupTrace({ now: clock.now });
  tr.enter("app-ready");
  tr.enter("free-port");
  clock.advance(3);
  tr.fail(new Error("EADDRINUSE: port scan failed"));

  const r = tr.toReport();
  assert.ok(r.failure, "should have a failure record");
  assert.strictEqual(r.failure.stage, "free-port", "blames the stage that was active");
  assert.match(r.failure.message, /EADDRINUSE/);
  assert.strictEqual(r.completed, false);
  assert.strictEqual(r.reachedWindow, false, "died before the window");
});

test("fail() is idempotent — the first failure wins", () => {
  const tr = new StartupTrace();
  tr.enter("create-window");
  tr.fail(new Error("first"));
  tr.enter("load-renderer");
  tr.fail(new Error("second"));
  const r = tr.toReport();
  assert.strictEqual(r.failure.message, "first");
  assert.strictEqual(r.failure.stage, "create-window");
});

test("reachedWindow flips once the window is shown", () => {
  const tr = new StartupTrace();
  tr.enter("create-window");
  assert.strictEqual(tr.reachedWindow, false);
  tr.enter("window-shown");
  assert.strictEqual(tr.reachedWindow, true);
  assert.strictEqual(tr.toReport().reachedWindow, true);
});

test("done() marks completion and a measurable duration", () => {
  const clock = fakeClock();
  const tr = new StartupTrace({ now: clock.now });
  tr.enter("module-init");
  clock.advance(42);
  tr.enter("backend-healthy");
  clock.advance(8);
  tr.done();

  const r = tr.toReport();
  assert.strictEqual(r.completed, true);
  assert.strictEqual(r.durationMs, 50, "first stage → done");
  assert.strictEqual(r.failure, null);
  assert.strictEqual(r.timeline[r.timeline.length - 1].stage, "ready");
});

test("accepts non-Error throwables (string/unknown)", () => {
  const tr = new StartupTrace();
  tr.enter("configure-env");
  tr.fail("plain string boom");
  const r = tr.toReport();
  assert.strictEqual(r.failure.message, "plain string boom");
  assert.strictEqual(r.failure.stack, null);
});

test("summary() is a single-line, greppable timeline", () => {
  const clock = fakeClock();
  const tr = new StartupTrace({ now: clock.now });
  tr.enter("app-ready");
  clock.advance(10);
  tr.enter("create-window");
  tr.fail(new Error("loadFile ENOENT"));
  const s = tr.summary();
  assert.match(s, /app-ready@\+0ms/);
  assert.match(s, /create-window@\+10ms/);
  assert.match(s, /FAILED@create-window: loadFile ENOENT/);
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
