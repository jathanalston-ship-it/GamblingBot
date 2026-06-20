#!/usr/bin/env node
/**
 * Electron startup validation.
 *
 * Launches the BUILT app in smoke mode (MRP_SMOKE=1): the main process creates
 * the window from the built renderer with no backend, waits for the first paint,
 * prints `MRP_SMOKE_OK`, and exits 0. This script asserts that sentinel + a clean
 * exit; anything else fails (non-zero), so CI catches a renderer/main that won't
 * boot.
 *
 * Requires a display — run under Xvfb in CI:  xvfb-run -a npm run smoke
 * Prerequisite: `npm run build` (so dist-electron/ and renderer/dist/ exist).
 */
"use strict";

const { spawn } = require("node:child_process");

const electronPath = require("electron"); // resolves to the Electron executable path
const TIMEOUT_MS = 60_000;

const child = spawn(electronPath, ["."], {
  env: { ...process.env, MRP_SMOKE: "1", NODE_ENV: "production" },
  stdio: ["ignore", "pipe", "pipe"],
});

let output = "";
child.stdout.on("data", (d) => {
  output += d.toString();
  process.stdout.write(d);
});
child.stderr.on("data", (d) => {
  output += d.toString();
  process.stderr.write(d);
});

const timer = setTimeout(() => {
  console.error("smoke: TIMEOUT — Electron did not report startup in time");
  child.kill("SIGKILL");
  process.exit(1);
}, TIMEOUT_MS);

child.on("error", (err) => {
  clearTimeout(timer);
  console.error(`smoke: failed to launch Electron — ${err.message}`);
  process.exit(1);
});

child.on("exit", (code) => {
  clearTimeout(timer);
  const sawSentinel = output.includes("MRP_SMOKE_OK");
  if (sawSentinel && code === 0) {
    console.log("smoke: OK — Electron started and rendered the UI");
    process.exit(0);
  }
  console.error(`smoke: FAILED (exit=${code}, sentinel=${sawSentinel})`);
  process.exit(1);
});
