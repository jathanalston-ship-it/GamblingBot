#!/usr/bin/env node
/**
 * Tests for the seamless-update state machine (dist-electron/update-flow.js):
 *   • transitions carry labels/details and stream to listeners
 *   • per-state timings are measured with an injected clock
 *   • the report lists EVERY operation over 250ms, slowest first
 *   • serialize/resume survives the installer restart with timings intact
 *   • failure captures the error and the recovery state
 *   • the >5s reassurance threshold behaves
 */

const assert = require("node:assert");
const path = require("node:path");

const {
  UpdateFlow,
  needsReassurance,
  SLOW_OPERATION_MS,
  STATE_TEXT,
} = require(path.join(__dirname, "..", "dist-electron", "update-flow.js"));

function clock(startAt = 0) {
  let now = startAt;
  return { now: () => now, advance: (ms) => (now += ms) };
}

function test(name, fn) {
  try {
    fn();
    console.log(`  ok - ${name}`);
  } catch (err) {
    console.error(`  FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

console.log("update-flow.test.cjs");

test("transitions stream events with labels, details and timings", () => {
  const c = clock(1_000);
  const flow = new UpdateFlow(c.now);
  const events = [];
  flow.onEvent((e) => events.push(e));

  flow.transition("preparing-restart", "buttons disabled");
  c.advance(120);
  flow.transition("stopping-backend");

  assert.strictEqual(events.length, 2);
  assert.strictEqual(events[0].state, "preparing-restart");
  assert.strictEqual(events[0].detail, "buttons disabled");
  assert.strictEqual(events[1].label, STATE_TEXT["stopping-backend"].label);
  assert.strictEqual(events[1].sinceStartMs, 120);
  assert.ok(flow.active);
});

test("download progress is determinate and clamped", () => {
  const flow = new UpdateFlow(clock().now);
  flow.transition("downloading-update");
  flow.setProgress(0.42);
  assert.strictEqual(flow.snapshot().progress, 0.42);
  flow.setProgress(7);
  assert.strictEqual(flow.snapshot().progress, 1);
  flow.transition("verifying-update");
  assert.strictEqual(flow.snapshot().progress, null); // progress resets per state
});

test("the report lists every operation over 250ms, slowest first", () => {
  const c = clock();
  const flow = new UpdateFlow(c.now);
  flow.transition("preparing-restart");
  c.advance(40); // fast — must NOT appear
  flow.transition("stopping-backend");
  c.advance(3_200); // slow
  flow.transition("launching-installer");
  c.advance(900); // slow
  flow.transition("starting-backend");
  c.advance(5_000); // slowest
  flow.transition("ready");

  const report = flow.report();
  assert.strictEqual(report.completed, true);
  assert.strictEqual(report.totalMs, 40 + 3_200 + 900 + 5_000);
  const slow = report.slowOperations;
  assert.deepStrictEqual(
    slow.map((s) => s.state),
    ["starting-backend", "stopping-backend", "launching-installer"],
  );
  assert.ok(slow.every((s) => s.durationMs > SLOW_OPERATION_MS));
  assert.ok(!slow.some((s) => s.state === "preparing-restart")); // 40ms is fine
  assert.ok(report.log.length >= 5); // every transition logged
});

test("serialize/resume survives the installer restart with timings intact", () => {
  const before = clock(10_000);
  const flow = new UpdateFlow(before.now);
  flow.transition("preparing-restart");
  before.advance(500);
  flow.transition("stopping-backend");
  before.advance(2_000);
  flow.transition("launching-installer");
  const saved = JSON.parse(JSON.stringify(flow.serialize())); // through disk

  // ...installer runs, app restarts 15s later...
  const after = clock(10_000 + 500 + 2_000 + 15_000);
  const resumed = UpdateFlow.resume(saved, after.now);
  assert.ok(resumed.active);
  resumed.transition("waiting-for-installer", "app relaunched");
  after.advance(100);
  resumed.transition("starting-backend");
  after.advance(4_000);
  resumed.transition("ready", "updated");

  const report = resumed.report();
  assert.strictEqual(report.completed, true);
  // The whole journey, INCLUDING the 15s the installer took, is measured.
  assert.strictEqual(report.totalMs, 500 + 2_000 + 15_000 + 100 + 4_000);
  const installer = report.states.find((s) => s.state === "launching-installer");
  assert.strictEqual(installer.durationMs, 15_000);
  assert.ok(report.slowOperations.some((s) => s.state === "launching-installer"));
});

test("failure captures the error and ends the flow", () => {
  const flow = new UpdateFlow(clock().now);
  flow.transition("stopping-backend");
  flow.fail(new Error("installer exited 1"));
  assert.strictEqual(flow.state, "failed");
  assert.ok(!flow.active);
  const report = flow.report();
  assert.strictEqual(report.completed, false);
  assert.strictEqual(report.error, "installer exited 1");
  assert.ok(report.log.some((l) => l.message.includes("FAILED")));
});

test("reassurance appears after 5s in a working state, never when done", () => {
  assert.strictEqual(needsReassurance("waiting-for-installer", 4_999), false);
  assert.strictEqual(needsReassurance("waiting-for-installer", 5_000), true);
  assert.strictEqual(needsReassurance("stopping-backend", 60_000), true);
  assert.strictEqual(needsReassurance("ready", 60_000), false);
  assert.strictEqual(needsReassurance("failed", 60_000), false);
  assert.strictEqual(needsReassurance("idle", 60_000), false);
});

test("a broken listener never breaks the flow", () => {
  const flow = new UpdateFlow(clock().now);
  flow.onEvent(() => {
    throw new Error("listener bug");
  });
  flow.transition("preparing-restart"); // must not throw
  assert.strictEqual(flow.state, "preparing-restart");
});

test("unattended flag: defaults false, emits on change, rides through snapshots", () => {
  const flow = new UpdateFlow(clock().now);
  assert.strictEqual(flow.unattended, false);
  assert.strictEqual(flow.snapshot().unattended, false);

  const events = [];
  flow.onEvent((e) => events.push(e));
  flow.setUnattended(true);
  assert.strictEqual(flow.unattended, true);
  assert.strictEqual(events.length, 1); // change emits
  assert.strictEqual(events[0].unattended, true);

  flow.setUnattended(true); // idempotent — no extra emit
  assert.strictEqual(events.length, 1);

  flow.transition("downloading-update");
  assert.strictEqual(flow.snapshot().unattended, true);
});

test("unattended flag survives serialize/resume across the restart", () => {
  const flow = new UpdateFlow(clock().now);
  flow.setUnattended(true);
  flow.transition("downloading-update");
  const saved = JSON.parse(JSON.stringify(flow.serialize()));
  assert.strictEqual(saved.unattended, true);

  const resumed = UpdateFlow.resume(saved);
  assert.strictEqual(resumed.unattended, true);
  assert.strictEqual(resumed.snapshot().unattended, true);

  // A legacy marker without the field resumes as attended (false), not undefined.
  const legacy = { ...saved };
  delete legacy.unattended;
  assert.strictEqual(UpdateFlow.resume(legacy).unattended, false);
});

process.exit(process.exitCode ?? 0);
