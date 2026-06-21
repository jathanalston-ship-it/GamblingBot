#!/usr/bin/env node
/**
 * Unit tests for resolveDataRoot (the writable-state root resolver).
 *
 * Plain-Node tests (matching backend-manager.test.cjs / startup-trace.test.cjs).
 * The resolver is pure, so we assert the mode → root mapping that decides where the
 * database, logs and settings live — including the portable build writing beside
 * the executable.
 *
 * Prerequisite: `npm run build:electron` (compiles dist-electron/paths.js).
 */
"use strict";

const assert = require("node:assert");
const { join } = require("node:path");
const { resolveDataRoot, PORTABLE_MARKER, PORTABLE_DATA_DIR } = require("../dist-electron/paths.js");

const base = {
  isDevApp: false,
  isPortable: false,
  repoRoot: "/repo",
  exeDir: "/extracted/MomentumLab-Portable",
  userDataDir: "/home/u/.config/Momentum Lab",
};

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("installed build uses the per-user userData dir", () => {
  assert.strictEqual(resolveDataRoot(base), base.userDataDir);
});

test("portable build writes beside the executable", () => {
  const root = resolveDataRoot({ ...base, isPortable: true });
  assert.strictEqual(root, join(base.exeDir, PORTABLE_DATA_DIR));
});

test("dev-app uses <repo>/.dev and wins over portable", () => {
  const root = resolveDataRoot({ ...base, isDevApp: true, isPortable: true });
  assert.strictEqual(root, join(base.repoRoot, ".dev"));
});

test("exposes a stable marker + data-dir name", () => {
  assert.strictEqual(PORTABLE_MARKER, "MomentumLab.portable");
  assert.strictEqual(PORTABLE_DATA_DIR, "MomentumLab-Data");
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
