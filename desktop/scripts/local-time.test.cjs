/**
 * Contract tests for the renderer's time policy (mirrors renderer/src/lib/format.ts).
 *
 * The renderer's rule: backend timestamps are UTC; offset-less ISO strings MUST
 * be parsed as UTC (append "Z"), then rendered with Intl in the OS timezone and
 * locale. These tests pin the platform behaviors that rule depends on, under a
 * forced non-UTC process timezone (TZ is set before the first Date use).
 */
process.env.TZ = "America/Los_Angeles";

const assert = require("node:assert");

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`  ok  ${name}`);
    passed += 1;
  } catch (err) {
    console.error(`  FAIL ${name}: ${err.message}`);
    failed += 1;
  }
}

/* --- mirrors of the pure helpers in renderer/src/lib/format.ts --- */
const HAS_OFFSET = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;
const parseUtc = (iso) => new Date(HAS_OFFSET.test(iso) ? iso : `${iso}Z`);
const countdown = (seconds) => {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
};

/* --- UTC parsing ------------------------------------------------- */
test("offset-less backend timestamps are parsed as UTC, not local", () => {
  const d = parseUtc("2026-07-01T19:30:00"); // what SQLite round-trips
  assert.strictEqual(d.toISOString(), "2026-07-01T19:30:00.000Z");
});

test("naive Date parsing would have shifted the instant (the bug this guards)", () => {
  const naive = new Date("2026-07-01T19:30:00"); // parsed as LOCAL (LA = UTC-7)
  const utc = parseUtc("2026-07-01T19:30:00");
  assert.strictEqual(naive.getTime() - utc.getTime(), 7 * 3600 * 1000);
});

test("timestamps that already carry an offset are untouched", () => {
  assert.strictEqual(
    parseUtc("2026-07-01T15:30:00-04:00").toISOString(),
    "2026-07-01T19:30:00.000Z",
  );
  assert.strictEqual(parseUtc("2026-07-01T19:30:00Z").toISOString(), "2026-07-01T19:30:00.000Z");
});

/* --- local rendering under the OS timezone ----------------------- */
test("UTC instant renders in the process (OS) timezone", () => {
  const d = parseUtc("2026-07-01T19:30:00"); // 19:30 UTC = 12:30 PDT
  const hour = new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false }).format(d);
  assert.strictEqual(Number(hour), 12);
});

/* --- locale-aware 12/24-hour + date formats ----------------------- */
test("locale decides 12-hour vs 24-hour", () => {
  const d = parseUtc("2026-07-01T19:30:00");
  const us = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(d);
  const gb = new Intl.DateTimeFormat("en-GB", { hour: "numeric", minute: "2-digit" }).format(d);
  assert.match(us, /12:30\s?PM/i); // 12-hour
  assert.strictEqual(gb, "12:30"); // 24-hour
});

test("locale decides date layout", () => {
  const d = parseUtc("2026-06-22T12:00:00");
  const us = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(d);
  const gb = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(d);
  assert.strictEqual(us, "Jun 22, 2026");
  assert.strictEqual(gb, "22 Jun 2026");
});

/* --- market time + DST ------------------------------------------- */
test("market time renders in America/New_York with the derived abbreviation", () => {
  const summer = parseUtc("2026-07-01T13:32:00Z");
  const winter = parseUtc("2026-01-15T14:32:00Z");
  const fmt = (d) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZoneName: "short",
    }).format(d);
  assert.match(fmt(summer), /09:32\s?EDT/);
  assert.match(fmt(winter), /09:32\s?EST/);
});

test("DST transition day: 09:30 ET moves by one UTC hour", () => {
  const fmt = (iso) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(parseUtc(iso));
  assert.strictEqual(fmt("2026-03-06T14:30:00Z"), "09:30"); // EST Friday
  assert.strictEqual(fmt("2026-03-09T13:30:00Z"), "09:30"); // EDT Monday
});

/* --- OS timezone detection ---------------------------------------- */
test("the OS timezone is detectable (what useSystemTimezone polls)", () => {
  assert.strictEqual(Intl.DateTimeFormat().resolvedOptions().timeZone, "America/Los_Angeles");
});

/* --- countdowns ---------------------------------------------------- */
test("countdown formatting", () => {
  assert.strictEqual(countdown(45), "45s");
  assert.strictEqual(countdown(192), "3m 12s");
  assert.strictEqual(countdown(8040), "2h 14m");
  assert.strictEqual(countdown(-5), "0s");
  assert.strictEqual(countdown(null), "—");
});

console.log(`\n${passed}/${passed + failed} passed`);
process.exit(failed === 0 ? 0 : 1);
