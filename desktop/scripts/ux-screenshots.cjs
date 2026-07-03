#!/usr/bin/env node
/**
 * UX evidence generator: renders the BUILT renderer bundle in real Chromium
 * (Playwright) with a mocked desktop bridge, then
 *
 *   1. measures renderer load + React hydration (3 runs, real numbers), and
 *   2. screenshots the seamless-update overlay in its key states
 *      (installing / long-running reassurance / ready / failure recovery)
 *      into docs/screenshots/.
 *
 * Run after `npm run build`:  node scripts/ux-screenshots.cjs
 */

const http = require("node:http");
const { readFileSync, existsSync, mkdirSync } = require("node:fs");
const { join, extname } = require("node:path");

const DIST = join(__dirname, "..", "renderer", "dist");
const OUT = join(__dirname, "..", "..", "docs", "screenshots");
const CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
};

function serveDist() {
  const server = http.createServer((req, res) => {
    const path = req.url === "/" ? "/index.html" : req.url.split("?")[0];
    const file = join(DIST, path);
    if (existsSync(file)) {
      res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
      res.end(readFileSync(file));
    } else {
      res.writeHead(404);
      res.end();
    }
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

const BRIDGE_MOCK = `
  window.__marks = [];
  window.mrp = {
    apiBaseUrl: "http://127.0.0.1:59999",
    version: "0.0.0-ux-audit",
    packaged: true,
    updater: {
      check: async () => ({ version: null }),
      download: async () => true,
      install: async () => true,
      diagnostics: async () => ({}),
      onEvent: () => () => {},
      onFlow: (cb) => { window.__emitFlow = cb; return () => {}; },
    },
    perf: {
      mark: (stage, ms) => window.__marks.push({ stage, ms }),
      startup: async () => ({ launches: 0, stats: [], waterfall: [], latest: null }),
    },
    onBackendStatus: (cb) => { setTimeout(() => cb("healthy"), 0); return () => {}; },
    getBackendStatus: async () => "healthy",
    automation: {
      status: async () => ({ automationActive: false, sleepPrevented: false, preventSleepSetting: true, blockerId: null }),
      sync: async () => ({ automationActive: false, sleepPrevented: false, preventSleepSetting: true, blockerId: null }),
    },
    profiles: { get: async () => ({ active: "default", profiles: ["default"] }) },
  };
`;

function flowEvent(state, overrides = {}) {
  const labels = {
    "stopping-backend": "Backend shutting down…",
    "waiting-for-installer": "Waiting for installer…",
    ready: "Ready",
    failed: "Update failed",
  };
  return {
    state,
    label: labels[state] ?? state,
    expects: state === "waiting-for-installer" ? "10–30 seconds" : "usually 1–5 seconds",
    detail: null,
    progress: null,
    sequence: 1,
    sinceStartMs: 1000,
    inStateMs: 0,
    error: null,
    ...overrides,
  };
}

async function main() {
  const { chromium } = require("playwright-core");
  mkdirSync(OUT, { recursive: true });
  const server = await serveDist();
  const base = `http://127.0.0.1:${server.address().port}/`;

  const browser = await chromium.launch({ executablePath: CHROMIUM, headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  // Fail every backend API call fast — the renderer's error/empty states are
  // the supported no-backend path (same as the CI smoke test).
  await context.route("http://127.0.0.1:59999/**", (route) => route.abort("connectionrefused"));
  await context.addInitScript(BRIDGE_MOCK);

  // ── 1. Renderer load + hydration timings (3 runs, measured) ──────────────
  const timings = [];
  for (let run = 0; run < 3; run++) {
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "load" });
    await page.waitForFunction(() => window.__marks && window.__marks.length > 0, null, {
      timeout: 15_000,
    });
    const t = await page.evaluate(() => {
      const nav = performance.getEntriesByType("navigation")[0];
      const hydrated = window.__marks.find((m) => m.stage === "renderer-hydrated");
      return {
        domContentLoadedMs: Math.round(nav.domContentLoadedEventEnd),
        loadMs: Math.round(nav.loadEventEnd),
        hydratedMs: hydrated ? Math.round(hydrated.ms) : null,
      };
    });
    timings.push(t);
    await page.close();
  }
  console.log("renderer timings (3 runs):", JSON.stringify(timings));

  // ── 2. Update-overlay screenshots ────────────────────────────────────────
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.error("[page]", msg.text().slice(0, 200));
  });
  await page.goto(base, { waitUntil: "load" });
  await page.waitForSelector("#root > *", { timeout: 15_000 });
  // The overlay registers its flow listener from AppShell's mount effect.
  await page.waitForFunction(() => typeof window.__emitFlow === "function", null, {
    timeout: 15_000,
  });

  const shots = [
    ["update-installing", flowEvent("stopping-backend", { detail: "buttons disabled", inStateMs: 800 })],
    // inStateMs 6.5s puts the local ticker past the 5s reassurance threshold.
    ["update-reassurance", flowEvent("waiting-for-installer", { inStateMs: 6_500 })],
    ["update-ready", flowEvent("ready", { detail: "updated to v0.0.103" })],
    ["update-recovery", flowEvent("failed", { error: "The installer did not finish (exit code 1)." })],
  ];
  for (const [name, event] of shots) {
    await page.evaluate((e) => window.__emitFlow && window.__emitFlow(e), event);
    await page.waitForSelector('[data-testid="update-overlay"]', { timeout: 5_000 });
    await page.waitForTimeout(900); // let the local ticker + reassurance render
    await page.screenshot({ path: join(OUT, `${name}.png`) });
    console.log(`screenshot: docs/screenshots/${name}.png`);
  }

  await browser.close();
  server.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
