#!/usr/bin/env node
"use strict";
/**
 * Unit tests for release validation (the startup verification suite).
 *
 * Plain-Node tests (matching backend-manager / startup-trace / paths suites). The
 * evaluator is pure and the runner is dependency-injected (spawn / fetch / clock /
 * fs), so the whole gate is tested offline — including a healthy launch (publish)
 * and a never-launches launch (block), without Electron or a real packaged build.
 */

const assert = require("node:assert");
const {
  evaluateValidation,
  runValidation,
  redactUrl,
  CHECK_NAMES,
} = require("./release-validation.cjs");

/** A startup-report.json from a fully healthy launch. */
function healthyReport() {
  return {
    appVersion: "0.0.46",
    packaged: true,
    portable: true,
    platform: "win32",
    host: "127.0.0.1",
    port: 51234,
    healthUrl: "http://127.0.0.1:51234/health",
    databaseUrl: "sqlite:///C:/x/MomentumLab-Data/data/momentum.db",
    startup: {
      completed: true,
      reachedWindow: true,
      currentStage: "ready",
      failure: null,
      timeline: [
        { stage: "module-init" },
        { stage: "app-ready" },
        { stage: "create-window" },
        { stage: "load-renderer" },
        { stage: "window-shown" },
        { stage: "backend-healthy" },
        { stage: "ready" },
      ],
    },
    backend: { status: "healthy", pid: 4242, adopted: false },
  };
}

const servingBackend = () => ({ status: "serving", database_url: "sqlite:///C:/x/.../momentum.db" });
const okHealth = () => ({ ok: true, status: 200 });

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("a healthy launch passes all seven checks", () => {
  const r = evaluateValidation({
    report: healthyReport(),
    backendReport: servingBackend(),
    health: okHealth(),
  });
  assert.strictEqual(r.ok, true);
  assert.deepStrictEqual(
    r.checks.map((c) => c.name),
    CHECK_NAMES,
  );
  assert.ok(r.checks.every((c) => c.ok));
});

test("a missing report fails (a release that cannot launch)", () => {
  const r = evaluateValidation({ report: null, backendReport: null, health: null });
  assert.strictEqual(r.ok, false);
  const byName = Object.fromEntries(r.checks.map((c) => [c.name, c.ok]));
  assert.strictEqual(byName.electron_started, false);
  assert.strictEqual(byName.startup_report_generated, false);
});

test("backend that never goes healthy fails backend_started", () => {
  const rep = healthyReport();
  rep.backend.status = "failed";
  const r = evaluateValidation({ report: rep, backendReport: null, health: { ok: false, status: 0 } });
  assert.strictEqual(r.ok, false);
  const byName = Object.fromEntries(r.checks.map((c) => [c.name, c.ok]));
  assert.strictEqual(byName.backend_started, false);
  assert.strictEqual(byName.health_endpoint, false);
});

test("renderer that never paints fails renderer_loaded", () => {
  const rep = healthyReport();
  rep.startup.reachedWindow = false;
  rep.startup.timeline = rep.startup.timeline.filter((e) => e.stage !== "window-shown");
  const r = evaluateValidation({ report: rep, backendReport: servingBackend(), health: okHealth() });
  assert.strictEqual(Object.fromEntries(r.checks.map((c) => [c.name, c.ok])).renderer_loaded, false);
  assert.strictEqual(r.ok, false);
});

test("redactUrl strips credentials from any URL (public artifact safety)", () => {
  assert.strictEqual(
    redactUrl("postgresql://user:s3cr3t@db.example.com/momentum"),
    "postgresql://***@db.example.com/momentum",
  );
  // SQLite paths and loopback URLs are unchanged (no credentials).
  assert.strictEqual(redactUrl("sqlite:///C:/x/momentum.db"), "sqlite:///C:/x/momentum.db");
  assert.strictEqual(redactUrl("http://127.0.0.1:51234/health"), "http://127.0.0.1:51234/health");
  assert.strictEqual(redactUrl(null), null);
});

test("database_accessible detail never leaks DB credentials", () => {
  const rep = healthyReport();
  const r = evaluateValidation({
    report: rep,
    backendReport: { status: "serving", database_url: "postgres://u:p4ss@h/db" },
    health: okHealth(),
  });
  const detail = r.checks.find((c) => c.name === "database_accessible").detail;
  assert.ok(!detail.includes("p4ss"), "the DB password must be redacted in the artifact");
  assert.ok(detail.includes("***@"), "redaction marker present");
});

test("backend serving but DB not opened fails database_accessible", () => {
  const r = evaluateValidation({
    report: healthyReport(),
    backendReport: { status: "failed", database_url: null },
    health: okHealth(),
  });
  assert.strictEqual(Object.fromEntries(r.checks.map((c) => [c.name, c.ok])).database_accessible, false);
});

test("runValidation: healthy launch → ok=true, app torn down", async () => {
  // The report only appears after a couple of polls (backend warming up).
  let polls = 0;
  let killed = false;
  let written = null;
  const t = { v: 0 };
  const res = await runValidation({
    exePath: "/fake/Momentum Lab.exe",
    timeoutMs: 60000,
    pollMs: 1000,
    now: () => t.v,
    delay: async (ms) => {
      t.v += ms;
    },
    spawnFn: () => ({ pid: 999, exitCode: null }),
    readReport: () => (++polls >= 3 ? healthyReport() : null),
    readBackendReport: () => servingBackend(),
    fetchFn: async () => okHealth(),
    writeOut: (obj) => {
      written = obj;
    },
    killTree: () => {
      killed = true;
    },
  });
  assert.strictEqual(res.ok, true, "healthy launch validates");
  assert.ok(written && written.ok === true, "release-validation.json written with ok=true");
  assert.strictEqual(written.checks.length, 7);
  assert.ok(killed, "the app is always torn down");
  assert.strictEqual(written.portable, true);
});

test("runValidation: app never writes a report → ok=false (blocked)", async () => {
  let written = null;
  const t = { v: 0 };
  const res = await runValidation({
    exePath: "/fake/Momentum Lab.exe",
    timeoutMs: 50,
    pollMs: 10,
    now: () => t.v,
    delay: async (ms) => {
      t.v += ms;
    },
    spawnFn: () => ({ pid: 999, exitCode: null }),
    readReport: () => null, // never comes up
    readBackendReport: () => null,
    fetchFn: async () => ({ ok: false, status: 0 }),
    writeOut: (obj) => {
      written = obj;
    },
    killTree: () => {},
  });
  assert.strictEqual(res.ok, false, "a release that cannot launch must fail");
  assert.ok(written && written.ok === false);
  assert.strictEqual(
    Object.fromEntries(written.checks.map((c) => [c.name, c.ok])).electron_started,
    false,
  );
});

test("runValidation: launch throws → ok=false, never hangs", async () => {
  let written = null;
  const res = await runValidation({
    exePath: "/missing.exe",
    timeoutMs: 1000,
    pollMs: 10,
    now: () => 0,
    delay: async () => {},
    spawnFn: () => {
      throw new Error("ENOENT");
    },
    readReport: () => null,
    fetchFn: async () => ({ ok: false, status: 0 }),
    writeOut: (obj) => {
      written = obj;
    },
  });
  assert.strictEqual(res.ok, false);
  assert.match(written.launchError, /ENOENT/);
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
