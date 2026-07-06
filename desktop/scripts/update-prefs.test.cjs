#!/usr/bin/env node
/**
 * Tests for the auto-update preferences (dist-electron/update-prefs.js):
 *   • parsePreferences validates and falls back to safe defaults
 *   • shouldPrompt honours the master switch and the skipped version
 *   • read/write round-trips through a real temp file
 */

const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  DEFAULT_UPDATE_PREFERENCES,
  parsePreferences,
  shouldPrompt,
  readPreferences,
  writePreferences,
} = require(path.join(__dirname, "..", "dist-electron", "update-prefs.js"));

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

console.log("update-prefs.test.cjs");

test("defaults are fully automatic with nothing skipped", () => {
  assert.strictEqual(DEFAULT_UPDATE_PREFERENCES.autoUpdate, true);
  assert.strictEqual(DEFAULT_UPDATE_PREFERENCES.skippedVersion, null);
});

test("parsePreferences validates and falls back on anything odd", () => {
  assert.deepStrictEqual(parsePreferences('{"autoUpdate":false,"skippedVersion":"1.2.3"}'), {
    autoUpdate: false,
    skippedVersion: "1.2.3",
  });
  // Bad JSON → defaults.
  assert.deepStrictEqual(parsePreferences("not json"), {
    autoUpdate: true,
    skippedVersion: null,
  });
  // Wrong types → per-field defaults.
  assert.deepStrictEqual(parsePreferences('{"autoUpdate":"yes","skippedVersion":7}'), {
    autoUpdate: true,
    skippedVersion: null,
  });
  // Partial → the missing field defaults.
  assert.deepStrictEqual(parsePreferences('{"autoUpdate":false}'), {
    autoUpdate: false,
    skippedVersion: null,
  });
});

test("shouldPrompt honours the master switch and skipped version", () => {
  assert.strictEqual(shouldPrompt({ autoUpdate: true, skippedVersion: null }, "1.0.0"), true);
  assert.strictEqual(shouldPrompt({ autoUpdate: false, skippedVersion: null }, "1.0.0"), false);
  // Exactly the skipped version → no prompt; a different version → prompt.
  assert.strictEqual(shouldPrompt({ autoUpdate: true, skippedVersion: "1.0.0" }, "1.0.0"), false);
  assert.strictEqual(shouldPrompt({ autoUpdate: true, skippedVersion: "1.0.0" }, "1.0.1"), true);
});

test("read/write round-trips through disk; missing file → defaults", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mrp-prefs-"));
  const file = path.join(dir, "update-prefs.json");
  // Missing file → defaults.
  assert.deepStrictEqual(readPreferences(file), {
    autoUpdate: true,
    skippedVersion: null,
  });
  writePreferences(file, { autoUpdate: false, skippedVersion: "9.9.9" });
  assert.deepStrictEqual(readPreferences(file), {
    autoUpdate: false,
    skippedVersion: "9.9.9",
  });
  fs.rmSync(dir, { recursive: true, force: true });
});

process.exit(process.exitCode ?? 0);
