#!/usr/bin/env node
"use strict";
/**
 * Regression guard for the electron-updater import.
 *
 * electron-updater is CommonJS: `autoUpdater` is a LAZY named export (a getter)
 * and there is NO default export. A default import (`import x from "electron-updater";
 * const { autoUpdater } = x`) compiles to `electron_updater_1.default` — which is
 * undefined and crashes the PACKAGED app at startup (caught by release validation).
 *
 * This asserts the COMPILED main.js resolves the updater by its named export and
 * never via `.default`, so the bug can't silently come back.
 *
 * Prerequisite: `npm run build:electron` (compiles dist-electron/main.js).
 */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const main = fs.readFileSync(path.join(__dirname, "..", "dist-electron", "main.js"), "utf-8");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("uses the named electron-updater export (the lazy getter)", () => {
  assert.ok(
    main.includes("electron_updater_1.autoUpdater"),
    "main.js should resolve autoUpdater by its named export",
  );
});

test("never resolves electron-updater via .default (undefined → crash)", () => {
  assert.ok(
    !main.includes("electron_updater_1.default"),
    "main.js must not access electron_updater_1.default (no default export exists)",
  );
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
