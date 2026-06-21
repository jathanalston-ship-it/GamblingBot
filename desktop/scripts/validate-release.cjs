#!/usr/bin/env node
"use strict";
/**
 * Automated release validation CLI — launches the PACKAGED app and verifies it
 * actually starts before the release may be published.
 *
 *   node desktop/scripts/validate-release.cjs \
 *     --exe "release-validate/MomentumLab-Portable/Momentum Lab.exe" \
 *     --out desktop/release/release-validation.json
 *
 * Validates the PORTABLE build: identical binaries to the installer, but it writes
 * its state (and the startup report) into `MomentumLab-Data` beside the executable,
 * so the report location is deterministic. Launches the app, waits for it to come
 * up, probes /health, grades the seven criteria, writes `release-validation.json`
 * and exits 0 (pass) or 1 (fail). A failure fails the CI step → the release is not
 * published.
 *
 * Cross-platform; intended for Windows CI (where the packaged build runs).
 */
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const { runValidation } = require("./release-validation.cjs");

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) args[a.slice(2)] = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
  }
  return args;
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch {
    return null; // missing or mid-write — the poller retries
  }
}

function killTree(child) {
  if (!child || child.exitCode !== null) return;
  const pid = child.pid;
  try {
    if (process.platform === "win32" && pid) {
      spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { stdio: "ignore" });
    } else if (pid) {
      child.kill("SIGKILL");
    }
  } catch {
    /* best effort */
  }
}

(async () => {
  const args = parseArgs(process.argv);
  const exe = args.exe;
  if (!exe) {
    console.error("usage: validate-release.cjs --exe <path to executable> [--out <file>] [--timeout <ms>]");
    process.exit(2);
  }
  const exeDir = path.dirname(exe);
  const dataDir = args.data || path.join(exeDir, "MomentumLab-Data");
  const logDir = path.join(dataDir, "logs");
  const reportPath = path.join(logDir, "startup-report.json");
  const backendReportPath = path.join(logDir, "backend-startup.json");
  const outPath = args.out || path.join(exeDir, "release-validation.json");
  const timeoutMs = Number(args.timeout) || 120000;

  // Clean any state from a prior run so we validate THIS launch's report.
  try {
    fs.rmSync(dataDir, { recursive: true, force: true });
  } catch {
    /* nothing to clean */
  }
  fs.mkdirSync(path.dirname(outPath), { recursive: true });

  let child = null;
  const result = await runValidation({
    exePath: exe,
    timeoutMs,
    pollMs: 1000,
    spawnFn: () => {
      child = spawn(exe, [], { stdio: "ignore", windowsHide: true });
      child.on("error", (err) => console.error(`[validate] spawn error: ${err.message}`));
      return child;
    },
    fetchFn: (url) => fetch(url),
    readReport: () => readJson(reportPath),
    readBackendReport: () => readJson(backendReportPath),
    writeOut: (obj) => fs.writeFileSync(outPath, JSON.stringify(obj, null, 2), "utf-8"),
    killTree,
    log: (m) => console.error(`[validate] ${m}`),
  });

  console.error(`\n[validate] ${result.ok ? "PASS ✓" : "FAIL ✗"} — wrote ${outPath}`);
  for (const c of result.checks) {
    console.error(`  ${c.ok ? "ok  " : "FAIL"} ${c.name} — ${c.detail}`);
  }
  if (result.startupFailure) {
    console.error(`  startup failure: ${result.startupFailure.stage} — ${result.startupFailure.message}`);
  }
  process.exit(result.ok ? 0 : 1);
})().catch((err) => {
  console.error("[validate] fatal:", err);
  process.exit(1);
});
