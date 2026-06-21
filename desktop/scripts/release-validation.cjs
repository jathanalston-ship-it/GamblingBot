"use strict";
/**
 * Release validation — the startup verification suite that gates a release.
 *
 * `evaluateValidation` is a PURE function: given the launched app's on-disk startup
 * report (`startup-report.json`, written by desktop/electron/main.ts), the backend's
 * own report (`backend-startup.json`) and a live `/health` probe, it grades the seven
 * release-gating criteria. `runValidation` is the thin, dependency-injected runner
 * (spawn / fetch / clock / fs injected) that launches the packaged app, waits for it
 * to come up (or time out), probes health, evaluates and writes `release-validation.json`.
 *
 * A release that cannot launch fails here (ok=false → non-zero exit) and is never
 * published. Both halves are unit-tested in release-validation.test.cjs.
 */

/**
 * Strip any embedded credentials from a URL (`scheme://user:pass@host` →
 * `scheme://***@host`). This report is uploaded as a PUBLIC release asset, so no
 * URL it carries (DB URL, health URL) may ever leak a credential.
 */
function redactUrl(url) {
  if (typeof url !== "string" || !url) return url;
  return url.replace(/(\/\/)[^/@\s]+@/g, "$1***@");
}

/** The seven checks, in the order the release requires them. */
const CHECK_NAMES = [
  "electron_started",
  "backend_started",
  "health_endpoint",
  "window_created",
  "renderer_loaded",
  "database_accessible",
  "startup_report_generated",
];

/**
 * Grade the seven criteria from the collected evidence.
 * @returns {{ ok: boolean, checks: {name:string, ok:boolean, detail:string}[] }}
 */
function evaluateValidation(input) {
  const report = (input && input.report) || null;
  const backendReport = (input && input.backendReport) || null;
  const health = (input && input.health) || null;
  const startup = report && report.startup ? report.startup : null;
  const timeline = startup && Array.isArray(startup.timeline) ? startup.timeline : [];
  const stages = new Set(timeline.map((e) => e && e.stage));
  const backend = report && report.backend ? report.backend : null;
  const healthUrl = (input && input.healthUrl) || (report && report.healthUrl) || null;

  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok: !!ok, detail: String(detail) });

  // 1. Electron starts — the main process ran far enough to record app-ready.
  add(
    "electron_started",
    !!report && stages.has("app-ready"),
    report ? `reached stage "${(startup && startup.currentStage) || "?"}"` : "no startup report",
  );

  // 2. Backend starts — the sidecar spawned and reached healthy.
  add(
    "backend_started",
    !!backend && backend.status === "healthy",
    backend ? `status=${backend.status} pid=${backend.pid}` : "no backend diagnostics",
  );

  // 3. Health endpoint passes — a live GET /health returned 200.
  add(
    "health_endpoint",
    !!health && health.ok === true,
    health ? `HTTP ${health.status} @ ${redactUrl(healthUrl) || "?"}` : "not probed",
  );

  // 4. Window created — BrowserWindow construction executed.
  add(
    "window_created",
    stages.has("create-window"),
    stages.has("create-window") ? "BrowserWindow created" : "no create-window stage",
  );

  // 5. Renderer loads — the renderer painted (window-shown), i.e. the UI is up.
  add(
    "renderer_loaded",
    stages.has("window-shown") || !!(startup && startup.reachedWindow === true),
    stages.has("window-shown") ? "renderer painted (window-shown)" : "window never shown",
  );

  // 6. Database accessible — the backend opened + reconciled the DB before serving.
  // The URL is redacted: this report is uploaded as a PUBLIC release asset, and a
  // DATABASE_URL could (in other deployments) embed credentials.
  const dbOk = backendReport
    ? backendReport.status === "serving" && !!backendReport.database_url
    : !!(report && report.databaseUrl) && !!backend && backend.status === "healthy";
  add(
    "database_accessible",
    dbOk,
    backendReport
      ? `backend status=${backendReport.status} db=${redactUrl(backendReport.database_url) || "?"}`
      : `db=${redactUrl(report && report.databaseUrl) || "unknown"}`,
  );

  // 7. Startup report generated — the report exists and the run completed (reached ready).
  add(
    "startup_report_generated",
    !!report && !!startup && startup.completed === true,
    report ? `completed=${startup && startup.completed}` : "report missing",
  );

  const ok = checks.every((c) => c.ok);
  return { ok, checks };
}

/** Has the app reached a terminal startup state (healthy, completed or failed)? */
function isTerminal(report) {
  if (!report || !report.startup) return false;
  const s = report.startup;
  const b = report.backend;
  return (
    s.completed === true ||
    !!s.failure ||
    !!(b && (b.status === "healthy" || b.status === "failed"))
  );
}

/**
 * Launch the packaged app, wait for it to come up (or time out), probe health,
 * evaluate the criteria and write `release-validation.json`. Always tears the app
 * down. Returns the written result object (with `.ok`).
 */
async function runValidation(o) {
  const log = o.log || (() => {});
  const now = o.now || Date.now;
  const delay = o.delay || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const timeoutMs = o.timeoutMs || 120000;
  const pollMs = o.pollMs || 1000;
  const readReport = o.readReport;
  const readBackendReport = o.readBackendReport || (() => null);

  log(`launching ${o.exePath}`);
  let child = null;
  let launchError = null;
  try {
    child = o.spawnFn();
  } catch (err) {
    launchError = String((err && err.message) || err);
    log(`launch failed: ${launchError}`);
  }

  const deadline = now() + timeoutMs;
  let report = null;
  if (!launchError) {
    while (now() < deadline) {
      report = readReport();
      if (isTerminal(report)) break;
      await delay(pollMs);
    }
  }

  // Live health probe via the port the app recorded in its report.
  let health = null;
  const healthUrl = report && report.healthUrl;
  if (healthUrl) {
    try {
      const res = await o.fetchFn(healthUrl);
      health = { ok: !!res.ok, status: res.status || 0 };
    } catch (err) {
      health = { ok: false, status: 0, error: String((err && err.message) || err) };
    }
  }

  const backendReport = report ? readBackendReport() : null;
  const evald = evaluateValidation({ report, backendReport, health, healthUrl });

  const result = {
    validatedAt: new Date(now()).toISOString(),
    ok: evald.ok,
    exe: o.exePath,
    appVersion: report ? report.appVersion : null,
    packaged: report ? report.packaged : null,
    portable: report ? report.portable : null,
    platform: report ? report.platform : null,
    healthUrl: redactUrl(healthUrl) || null,
    launchError,
    checks: evald.checks,
    startupTimeline: report && report.startup ? report.startup.timeline : null,
    startupFailure: report && report.startup ? report.startup.failure : null,
    backendStatus: report && report.backend ? report.backend.status : null,
  };
  o.writeOut(result);
  if (o.killTree) o.killTree(child);
  return result;
}

module.exports = { evaluateValidation, runValidation, isTerminal, redactUrl, CHECK_NAMES };
