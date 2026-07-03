#!/usr/bin/env node
/**
 * Command Center evidence generator: renders the BUILT renderer bundle in real
 * Chromium (Playwright) with a mocked desktop bridge and a mocked backend API
 * serving realistic Command Center payloads, then screenshots the terminal in
 * its two key states (active book / fresh install) into docs/screenshots/.
 *
 * Run after `npm run build`:  node scripts/command-center-screenshots.cjs
 */

const http = require("node:http");
const { readFileSync, existsSync, mkdirSync } = require("node:fs");
const { join, extname } = require("node:path");

const DIST = join(__dirname, "..", "renderer", "dist");
const OUT = join(__dirname, "..", "..", "docs", "screenshots");
const CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const API = "http://127.0.0.1:59999";

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
  window.localStorage.setItem("mrp:onboarding:done", new Date().toISOString());
  window.__marks = [];
  window.mrp = {
    apiBaseUrl: "${API}",
    version: "0.0.0-cc-evidence",
    packaged: true,
    updater: {
      check: async () => ({ version: null }),
      download: async () => true,
      install: async () => true,
      diagnostics: async () => ({}),
      onEvent: () => () => {},
      onFlow: () => () => {},
    },
    perf: {
      mark: (stage, ms) => window.__marks.push({ stage, ms }),
      startup: async () => ({ launches: 0, stats: [], waterfall: [], latest: null }),
    },
    onBackendStatus: (cb) => { setTimeout(() => cb("healthy"), 0); return () => {}; },
    getBackendStatus: async () => "healthy",
    automation: {
      status: async () => ({ automationActive: true, sleepPrevented: true, preventSleepSetting: true, blockerId: 1 }),
      sync: async () => ({ automationActive: true, sleepPrevented: true, preventSleepSetting: true, blockerId: 1 }),
    },
    profiles: { get: async () => ({ active: "default", profiles: ["default"] }) },
  };
`;

/* ---------------------------------------------------------------- */
/* Realistic backend payloads (shape-identical to the live services) */
/* ---------------------------------------------------------------- */

const NOW = new Date();
const iso = (minAgo) => new Date(NOW.getTime() - minAgo * 60_000).toISOString();

const CLOCK = {
  state: "regular",
  utc: NOW.toISOString(),
  market_time: NOW.toISOString(),
  market_tz: "EDT",
  next_market_open: new Date(NOW.getTime() + 17.5 * 3_600_000).toISOString(),
  next_market_close: new Date(NOW.getTime() + 3.2 * 3_600_000).toISOString(),
  next_premarket: new Date(NOW.getTime() + 12 * 3_600_000).toISOString(),
  seconds_to_market_open: 17.5 * 3600,
  seconds_to_market_close: 3.2 * 3600,
  seconds_to_premarket: 12 * 3600,
  seconds_to_next_scan: 42,
  daemon_running: true,
};

const HUD = {
  clock: CLOCK,
  health: {
    backend: { status: "green", detail: "API process answering" },
    scheduler: { status: "green", detail: "daemon running (214 cycles)" },
    automation: { status: "green", detail: "Auto Pilot enabled" },
    broker: { status: "green", detail: "paper venue answering (equity 104,318)" },
    data_provider: { status: "green", detail: "Provider: yfinance; Data age: 4m" },
  },
  timestamps: {
    latest_bar: iso(4),
    latest_scan: iso(2),
    latest_portfolio_update: iso(2),
  },
  account: {
    starting_balance: 100000,
    equity: 104318.4,
    cash: 61240.15,
    buying_power: 61240.15,
    today_realized_pnl: 412.3,
    unrealized_pnl: 1866.25,
    realized_pnl_total: 2452.15,
    open_positions: 2,
    closed_today: 1,
    win_rate: 0.42,
    avg_winner: 1240.5,
    avg_loser: -388.2,
    profit_factor: 2.31,
    expectancy_r: 0.62,
    largest_winner: 4820.0,
    largest_loser: -940.0,
    max_drawdown: -0.048,
    exposure: 43078.25,
    exposure_pct: 41.3,
    risk_used: 1892.4,
    max_risk_allowed: 5215.92,
    portfolio_heat_pct: 1.81,
    heat_cap_pct: 5,
  },
  market: {
    regime: "bullish",
    regime_score: 71.4,
    confidence: 0.83,
    breadth_pct: 63.5,
    posture: "risk_on",
    as_of: NOW.toISOString().slice(0, 10),
    indexes: [
      { symbol: "SPY", last: 618.42, change_pct: 0.62, as_of: NOW.toISOString() },
      { symbol: "QQQ", last: 552.18, change_pct: 0.91, as_of: NOW.toISOString() },
      { symbol: "DIA", last: 442.7, change_pct: 0.18, as_of: NOW.toISOString() },
      { symbol: "IWM", last: 228.05, change_pct: -0.24, as_of: NOW.toISOString() },
    ],
    spy_realized_vol_pct: 14.2,
  },
  generated_at: NOW.toISOString(),
};

const BOT = {
  state: "managing",
  state_label: "MANAGING",
  enabled: true,
  activity: "Managing 2 positions. Next scan in 42s.",
  market_state: "regular",
  open_positions: 2,
  managed_positions: 2,
  manual_positions: 0,
  last_scan_at: iso(2),
  last_error: null,
  last_cycle: { entered: 1, managed: 2, closed: 0, candidates: 12 },
  last_completed_action: {
    at: iso(2),
    message: "NVDA — raised stop to 178.40 after target 1 scale-out",
  },
  next_action: { label: "next scan", seconds: 42, at: iso(-1) },
};

const trade = (over) => ({
  trade_uid: "uid-" + over.symbol,
  run_id: "scan-20260703",
  symbol: over.symbol,
  recommended_at: iso(3 * 24 * 60),
  instrument: "shares",
  quantity: 120,
  entry_price: 100,
  stop_price: 94,
  targets: [
    { label: "T1", price: 112, hit: false },
    { label: "T2", price: 124, hit: false },
  ],
  conviction_score: 78,
  conviction_band: "HIGH",
  regime: "bullish",
  sector: "Technology",
  thesis: "Momentum breakout on rising relative volume",
  current_thesis_strength: 74,
  current_health_score: 81,
  trade_health: "Strong",
  status: "open",
  management_mode: "managed",
  latest_action: "Holding — thesis intact",
  latest_reason:
    "Conviction steady at 78 (HIGH); price 6.2% above entry with rising volume; stop honored at 94.00.",
  last_evaluated_at: iso(2),
  closed_at: null,
  close_reason: null,
  journal_trade_id: 1,
  realized_r: null,
  realized_pnl: null,
  realized_at: null,
  last_price: 106.2,
  unrealized_r: 1.03,
  unrealized_pnl: 744,
  distance_to_stop_pct: 11.5,
  ...over,
});

const TRADES = [
  trade({ symbol: "NVDA", entry_price: 172.4, stop_price: 164.1, last_price: 183.9, quantity: 55, journal_trade_id: 1, unrealized_pnl: 632.5, unrealized_r: 1.39, targets: [{ label: "T1", price: 189.2, hit: false }, { label: "T2", price: 205.9, hit: false }] }),
  trade({ symbol: "PLTR", entry_price: 148.7, stop_price: 139.2, last_price: 161.1, quantity: 100, journal_trade_id: 2, conviction_score: 84, conviction_band: "EXTREME", unrealized_pnl: 1240, unrealized_r: 1.31, current_health_score: 68, trade_health: "Stable", management_mode: "manual", latest_action: "Scale Out", latest_reason: "ATR expanded 1.8×; consider taking a third off into strength at 1.3R." }),
  trade({ symbol: "AVGO", journal_trade_id: null, quantity: null, entry_price: 289.5, stop_price: 274.6, conviction_score: 71, trade_health: "Stable", latest_action: "Ready — awaiting breakout over 295.20", last_price: null, unrealized_pnl: null, unrealized_r: null }),
];

const ALERTS = [
  { id: 1, ts: iso(6), run_id: "scan-20260703", symbol: "PLTR", severity: "warning", kind: "trade_managed", title: "scale-out advised at 1.3R", description: "ATR expansion 1.8×; thesis intact." },
  { id: 2, ts: iso(14), run_id: "scan-20260703", symbol: "NVDA", severity: "info", kind: "autopilot_entry", title: "Auto Pilot entry (55 sh, risk $456)", description: null },
  { id: 3, ts: iso(31), run_id: "scan-20260703", symbol: null, severity: "info", kind: "regime", title: "Regime upgraded to bullish (confidence 83%)", description: null },
];

const ACTIVITY = [
  { id: 11, ts: iso(2), run_id: "scan-20260703", symbol: "NVDA", category: "management", text: "raised stop to 178.40 after target-1 scale-out", payload: null },
  { id: 10, ts: iso(2), run_id: "scan-20260703", symbol: null, category: "scan", text: "scan completed — 12 candidates, 2 positions regraded", payload: null },
  { id: 9, ts: iso(42), run_id: "scan-20260703", symbol: "PLTR", category: "override", text: "user converted PLTR to manual management", payload: null },
];

const AUDIT = [
  { id: 21, event_type: "user_override", ts: iso(42), run_id: null, symbol: "PLTR", entity_type: "tracked_trade", summary: "user converted PLTR to manual (bot advises only)" },
  { id: 20, event_type: "order_filled", ts: iso(120), run_id: "scan-20260703", symbol: "NVDA", entity_type: "order", summary: "BUY 55 NVDA @ 172.40 filled (paper)" },
];

const ROUTES = {
  "/daemon/clock": CLOCK,
  "/command-center/hud": HUD,
  "/command-center/autopilot": BOT,
  "/trade-lifecycle": TRADES,
  "/alerts": ALERTS,
  "/activity": ACTIVITY,
  "/audit": AUDIT,
};

async function main() {
  const { chromium } = require("playwright-core");
  mkdirSync(OUT, { recursive: true });
  const server = await serveDist();
  const base = `http://127.0.0.1:${server.address().port}/`;

  const browser = await chromium.launch({ executablePath: CHROMIUM, headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });

  let empty = false;
  await context.route(`${API}/**`, (route) => {
    const path = new URL(route.request().url()).pathname;
    const hit = ROUTES[path];
    if (hit !== undefined) {
      const body = empty && (path === "/trade-lifecycle" || path === "/alerts" || path === "/activity" || path === "/audit")
        ? []
        : hit;
      route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    } else {
      route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    }
  });
  await context.addInitScript(BRIDGE_MOCK);

  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.error("[page]", msg.text().slice(0, 200));
  });

  // Active book: positions, watchlist, alerts, mission log all populated.
  await page.goto(base, { waitUntil: "load" });
  await page.waitForSelector("text=Active Trade Manager", { timeout: 15_000 });
  await page.waitForSelector("text=NVDA", { timeout: 15_000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(OUT, "command-center-active.png"), fullPage: true });
  console.log("screenshot: docs/screenshots/command-center-active.png");

  // Fresh install: no positions yet — empty states must still answer the four questions.
  empty = true;
  await page.reload({ waitUntil: "load" });
  await page.waitForSelector("text=Active Trade Manager", { timeout: 15_000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(OUT, "command-center-empty.png"), fullPage: true });
  console.log("screenshot: docs/screenshots/command-center-empty.png");

  await browser.close();
  server.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
