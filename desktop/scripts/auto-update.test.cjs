#!/usr/bin/env node
/**
 * Tests for the auto-update sizing + prompt logic (dist-electron/auto-update.js):
 *   • estimateDownloadBytes sums artifact sizes and ignores bad/missing ones
 *   • recommendedFreeBytes covers download + install headroom + margin
 *   • formatBytes renders friendly units (and "unknown" for a non-positive size)
 *   • buildUpdatePrompt assembles the payload the confirmation prompt renders
 */

const assert = require("node:assert");
const path = require("node:path");

const {
  estimateDownloadBytes,
  recommendedFreeBytes,
  formatBytes,
  buildUpdatePrompt,
  MIN_INSTALL_HEADROOM_BYTES,
  SAFETY_MARGIN_BYTES,
} = require(path.join(__dirname, "..", "dist-electron", "auto-update.js"));

const MB = 1024 * 1024;

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

console.log("auto-update.test.cjs");

test("estimateDownloadBytes sums artifact sizes, ignoring bad/missing ones", () => {
  assert.strictEqual(
    estimateDownloadBytes({ version: "1.0.0", files: [{ size: 10 }, { size: 20 }] }),
    30,
  );
  // Missing / null / non-positive sizes are ignored, not counted.
  assert.strictEqual(
    estimateDownloadBytes({
      version: "1.0.0",
      files: [{ size: 100 }, {}, { size: null }, { size: 0 }, { size: -5 }],
    }),
    100,
  );
  assert.strictEqual(estimateDownloadBytes({ version: "1.0.0" }), 0);
  assert.strictEqual(estimateDownloadBytes({ version: "1.0.0", files: [] }), 0);
});

test("recommendedFreeBytes = download + max(2×download, floor) + margin", () => {
  // Large download: 2× dominates the floor.
  const big = 90 * MB;
  assert.strictEqual(recommendedFreeBytes(big), big + big * 2 + SAFETY_MARGIN_BYTES);
  // Small download: the install-headroom floor dominates.
  const small = 10 * MB;
  assert.strictEqual(
    recommendedFreeBytes(small),
    small + MIN_INSTALL_HEADROOM_BYTES + SAFETY_MARGIN_BYTES,
  );
  // Unknown size → 0 (the prompt says "unknown" rather than guessing).
  assert.strictEqual(recommendedFreeBytes(0), 0);
  assert.strictEqual(recommendedFreeBytes(-1), 0);
  // Always strictly larger than the download itself.
  assert.ok(recommendedFreeBytes(big) > big);
});

test("formatBytes renders friendly units and handles unknown", () => {
  assert.strictEqual(formatBytes(0), "unknown");
  assert.strictEqual(formatBytes(-5), "unknown");
  assert.strictEqual(formatBytes(NaN), "unknown");
  assert.strictEqual(formatBytes(500), "500 B");
  assert.strictEqual(formatBytes(2048), "2 KB");
  assert.strictEqual(formatBytes(90 * MB), "90 MB");
  assert.strictEqual(formatBytes(1.5 * 1024 * MB), "1.5 GB");
});

test("buildUpdatePrompt assembles the confirmation payload (size known)", () => {
  const prompt = buildUpdatePrompt({
    version: "0.0.107",
    releaseName: "Momentum Lab v0.0.107",
    files: [{ size: 90 * MB }],
  });
  assert.strictEqual(prompt.version, "0.0.107");
  assert.strictEqual(prompt.releaseName, "Momentum Lab v0.0.107");
  assert.strictEqual(prompt.downloadBytes, 90 * MB);
  assert.strictEqual(prompt.downloadLabel, "90 MB");
  assert.strictEqual(prompt.sizeKnown, true);
  assert.strictEqual(prompt.recommendedFreeBytes, recommendedFreeBytes(90 * MB));
  assert.strictEqual(prompt.recommendedFreeLabel, formatBytes(recommendedFreeBytes(90 * MB)));
});

test("buildUpdatePrompt reports unknown size when metadata carries no sizes", () => {
  const prompt = buildUpdatePrompt({ version: "0.0.108" });
  assert.strictEqual(prompt.sizeKnown, false);
  assert.strictEqual(prompt.downloadBytes, 0);
  assert.strictEqual(prompt.downloadLabel, "unknown");
  assert.strictEqual(prompt.recommendedFreeLabel, "unknown");
  assert.strictEqual(prompt.releaseName, null);
});

process.exit(process.exitCode ?? 0);
