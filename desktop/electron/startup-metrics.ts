/**
 * Startup performance metrics — measured timings only, never assumptions.
 *
 * Every launch's StartupTrace timeline (plus the backend's own boot
 * timings and the renderer's hydration/first-API marks) is appended to a
 * rolling history file. From that history this module computes, per stage:
 * average, median, 95th percentile and worst-case — and classifies each
 * stage against the responsiveness tiers (100 / 250 / 500 / 1000 ms) so
 * the Developer Diagnostics waterfall can highlight where startup time
 * actually goes.
 *
 * Pure (no `electron`/`fs` imports) so it is unit-testable; main.ts owns
 * reading/writing the history file.
 */

import type { StartupTraceReport } from "./startup-trace";

export interface StageSample {
  stage: string;
  durationMs: number;
}

export interface LaunchRecord {
  at: string; // ISO — when the launch started
  totalMs: number | null;
  completed: boolean;
  stages: StageSample[];
}

export type Tier = "ok" | "over100" | "over250" | "over500" | "over1000";

export interface StageStats {
  stage: string;
  count: number;
  avgMs: number;
  medianMs: number;
  p95Ms: number;
  worstMs: number;
  lastMs: number;
  tier: Tier; // classified on the MEDIAN — typical behaviour, not one outlier
}

export interface WaterfallRow {
  stage: string;
  startMs: number;
  durationMs: number;
  tier: Tier;
}

export const HISTORY_CAP = 50;

export function tierFor(ms: number): Tier {
  if (ms > 1000) return "over1000";
  if (ms > 500) return "over500";
  if (ms > 250) return "over250";
  if (ms > 100) return "over100";
  return "ok";
}

/**
 * Convert a StartupTrace report into a launch record. In the trace, each
 * timeline entry's `sincePrevMs` is the time spent in the PREVIOUS stage,
 * so stage `i`'s duration is entry `i+1`'s `sincePrevMs` (the final stage
 * has no successor and contributes 0 — it is the "done" marker).
 */
export function recordFromTrace(
  report: StartupTraceReport,
  extraStages: StageSample[] = [],
): LaunchRecord {
  const stages: StageSample[] = [];
  for (let i = 0; i < report.timeline.length - 1; i++) {
    stages.push({
      stage: report.timeline[i].stage,
      durationMs: report.timeline[i + 1].sincePrevMs,
    });
  }
  return {
    at: report.startedAt ?? new Date(0).toISOString(),
    totalMs: report.durationMs,
    completed: report.completed,
    stages: [...stages, ...extraStages],
  };
}

export function appendHistory(
  history: LaunchRecord[],
  record: LaunchRecord,
  cap: number = HISTORY_CAP,
): LaunchRecord[] {
  return [...history, record].slice(-cap);
}

function percentile(sorted: number[], fraction: number): number {
  if (!sorted.length) return 0;
  // Nearest-rank (ceiling) — never under-reports the tail.
  const rank = Math.ceil(fraction * sorted.length);
  return sorted[Math.min(Math.max(rank - 1, 0), sorted.length - 1)];
}

/** Per-stage stats across the history, ordered by the newest launch's order. */
export function computeStats(history: LaunchRecord[]): StageStats[] {
  if (!history.length) return [];
  const samples = new Map<string, number[]>();
  for (const launch of history) {
    for (const { stage, durationMs } of launch.stages) {
      const list = samples.get(stage) ?? [];
      list.push(durationMs);
      samples.set(stage, list);
    }
  }
  const latest = history[history.length - 1];
  const order: string[] = [];
  for (const { stage } of latest.stages) if (!order.includes(stage)) order.push(stage);
  for (const stage of samples.keys()) if (!order.includes(stage)) order.push(stage);

  return order.map((stage) => {
    const values = samples.get(stage) ?? [];
    const sorted = [...values].sort((a, b) => a - b);
    const avg = sorted.length ? sorted.reduce((a, b) => a + b, 0) / sorted.length : 0;
    const median = percentile(sorted, 0.5);
    const last = latest.stages.filter((s) => s.stage === stage).at(-1)?.durationMs ?? 0;
    return {
      stage,
      count: sorted.length,
      avgMs: Math.round(avg * 10) / 10,
      medianMs: median,
      p95Ms: percentile(sorted, 0.95),
      worstMs: sorted.length ? sorted[sorted.length - 1] : 0,
      lastMs: last,
      tier: tierFor(median),
    };
  });
}

/** The latest launch as waterfall rows (cumulative start offsets). */
export function waterfall(record: LaunchRecord): WaterfallRow[] {
  let cursor = 0;
  return record.stages.map(({ stage, durationMs }) => {
    const row = { stage, startMs: cursor, durationMs, tier: tierFor(durationMs) };
    cursor += durationMs;
    return row;
  });
}
