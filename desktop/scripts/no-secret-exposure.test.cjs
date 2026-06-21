#!/usr/bin/env node
"use strict";
/**
 * Guard: the renderer bridge must NEVER expose secrets.
 *
 * The Electron preload is the only surface the sandboxed renderer can see
 * (contextIsolation on, nodeIntegration off). This asserts the COMPILED preload
 * never references a secret env var and never bulk-exposes process.env — so a
 * provider API key / token can't leak into the renderer. The backend (main.ts)
 * legitimately receives process.env; only the preload is checked here.
 *
 * Prerequisite: `npm run build:electron` (compiles dist-electron/preload.js).
 */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const SECRET_ENV_VARS = [
  "ALPACA_API_KEY",
  "ALPACA_API_SECRET",
  "POLYGON_API_KEY",
  "BROKER_API_KEY",
  "BROKER_API_SECRET",
  "MRP_UPDATE_TOKEN",
  "GH_TOKEN",
  "GITHUB_TOKEN",
];

const dir = path.join(__dirname, "..", "dist-electron");
const preload = fs.readFileSync(path.join(dir, "preload.js"), "utf-8");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("preload references no secret env var", () => {
  for (const name of SECRET_ENV_VARS) {
    assert.ok(!preload.includes(name), `preload.js must not reference ${name}`);
  }
});

test("preload does not bulk-expose process.env", () => {
  // No `...process.env`, `process.env)` passed wholesale, or `env: process.env`.
  assert.ok(!/\.\.\.process\.env/.test(preload), "preload must not spread process.env");
  assert.ok(
    !/exposeInMainWorld\([^)]*process\.env\s*\)/.test(preload),
    "preload must not expose process.env to the renderer",
  );
});

test("preload only reads the known non-secret env vars", () => {
  const reads = [...preload.matchAll(/process\.env\.([A-Z0-9_]+)/g)].map((m) => m[1]);
  const allowed = new Set([
    "MRP_API_PORT",
    "MRP_APP_VERSION",
    "MRP_PACKAGED",
    "MRP_DEV_APP",
    "npm_package_version",
  ]);
  for (const name of reads) {
    assert.ok(allowed.has(name), `preload reads an unexpected env var: ${name}`);
  }
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
