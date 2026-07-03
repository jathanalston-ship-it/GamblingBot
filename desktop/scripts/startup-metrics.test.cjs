#!/usr/bin/env node
/**
 * Tests for the startup-performance metrics (dist-electron/startup-metrics.js):
 *   • trace timelines convert to stage durations correctly
 *   • history is capped and stats (avg/median/p95/worst) are right
 *   • responsiveness tiers classify 100/250/500/1000ms boundaries
 *   • the waterfall accumulates start offsets
 */

const assert = require("node:assert");
const path = require("node:path");

const {
  recordFromTrace,
  appendHistory,
  computeStats,
  waterfall,
  tierFor,
  HISTORY_CAP,
} = require(path.join(__dirname, "..", "dist-electron", "startup-metrics.js"));

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

console.log("startup-metrics.test.cjs");

function traceReport() {
  // sincePrevMs on entry i = time spent in stage i-1.
  return {
    startedAt: "2026-07-03T12:00:00.000Z",
    finishedAt: "2026-07-03T12:00:05.000Z",
    durationMs: 5000,
    reachedWindow: true,
    completed: true,
    currentStage: "ready",
    timeline: [
      { stage: "module-init", at: "", sinceStartMs: 0, sincePrevMs: 0 },
      { stage: "app-ready", at: "", sinceStartMs: 80, sincePrevMs: 80 },
      { stage: "create-window", at: "", sinceStartMs: 200, sincePrevMs: 120 },
      { stage: "backend-start", at: "", sinceStartMs: 600, sincePrevMs: 400 },
      { stage: "backend-healthy", at: "", sinceStartMs: 4_600, sincePrevMs: 4_000 },
      { stage: "ready", at: "", sinceStartMs: 4_650, sincePrevMs: 50 },
    ],
    failure: null,
  };
}

test("recordFromTrace maps stage durations from the NEXT entry", () => {
  const record = recordFromTrace(traceReport(), [
    { stage: "backend:sqlite-init", durationMs: 35 },
  ]);
  const byStage = Object.fromEntries(record.stages.map((s) => [s.stage, s.durationMs]));
  assert.strictEqual(byStage["module-init"], 80);
  assert.strictEqual(byStage["app-ready"], 120);
  assert.strictEqual(byStage["create-window"], 400);
  assert.strictEqual(byStage["backend-start"], 4_000);
  assert.strictEqual(byStage["backend-healthy"], 50);
  assert.strictEqual(byStage["backend:sqlite-init"], 35);
  assert.strictEqual(record.totalMs, 5000);
  assert.strictEqual(record.completed, true);
});

test("history is capped", () => {
  let history = [];
  for (let i = 0; i < HISTORY_CAP + 10; i++) {
    history = appendHistory(history, { at: String(i), totalMs: i, completed: true, stages: [] });
  }
  assert.strictEqual(history.length, HISTORY_CAP);
  assert.strictEqual(history[0].at, "10"); // oldest dropped
});

test("stats compute avg/median/p95/worst per stage", () => {
  const launches = [100, 200, 300, 400, 1_000].map((ms, i) => ({
    at: String(i),
    totalMs: ms,
    completed: true,
    stages: [{ stage: "backend-start", durationMs: ms }],
  }));
  const stats = computeStats(launches);
  const s = stats.find((x) => x.stage === "backend-start");
  assert.strictEqual(s.count, 5);
  assert.strictEqual(s.avgMs, 400);
  assert.strictEqual(s.medianMs, 300);
  assert.strictEqual(s.worstMs, 1_000);
  assert.strictEqual(s.p95Ms, 1_000);
  assert.strictEqual(s.lastMs, 1_000);
  assert.strictEqual(s.tier, "over250"); // classified on the median
});

test("tiers classify the 100/250/500/1000 boundaries", () => {
  assert.strictEqual(tierFor(100), "ok");
  assert.strictEqual(tierFor(101), "over100");
  assert.strictEqual(tierFor(250), "over100");
  assert.strictEqual(tierFor(251), "over250");
  assert.strictEqual(tierFor(500), "over250");
  assert.strictEqual(tierFor(501), "over500");
  assert.strictEqual(tierFor(1_000), "over500");
  assert.strictEqual(tierFor(1_001), "over1000");
});

test("waterfall accumulates start offsets", () => {
  const rows = waterfall({
    at: "x",
    totalMs: 700,
    completed: true,
    stages: [
      { stage: "a", durationMs: 100 },
      { stage: "b", durationMs: 400 },
      { stage: "c", durationMs: 200 },
    ],
  });
  assert.deepStrictEqual(
    rows.map((r) => [r.stage, r.startMs, r.durationMs]),
    [
      ["a", 0, 100],
      ["b", 100, 400],
      ["c", 500, 200],
    ],
  );
  assert.strictEqual(rows[1].tier, "over250");
});

test("empty history computes no stats", () => {
  assert.deepStrictEqual(computeStats([]), []);
});

process.exit(process.exitCode ?? 0);
