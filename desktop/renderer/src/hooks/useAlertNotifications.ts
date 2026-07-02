import { useEffect, useRef } from "react";

import { apiGet } from "../api/client";

interface AlertRow {
  id: number;
  ts: string | null;
  symbol: string | null;
  severity: string; // info | warning | critical
  kind: string;
  title: string;
  description: string;
}

const POLL_MS = 60_000; // matches the daemon's scan cadence
const LAST_SEEN_KEY = "mrp:alerts:last-seen-id";
const MAX_PER_POLL = 5; // never blast a backlog

function lastSeen(): number {
  const raw = window.localStorage.getItem(LAST_SEEN_KEY);
  const n = raw ? Number(raw) : Number.NaN;
  return Number.isFinite(n) ? n : -1;
}

function remember(id: number): void {
  window.localStorage.setItem(LAST_SEEN_KEY, String(id));
}

/**
 * OS-level notifications for important alerts (warning/critical) — trade
 * managed (stop-loss / take-profit), stop or target reached, regime change.
 *
 * Polls `/alerts` on the scan cadence and fires a system Notification for
 * each alert newer than the last one seen (persisted, so a restart doesn't
 * re-notify). The first run on a fresh install only sets the baseline.
 */
export function useAlertNotifications(): void {
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async (): Promise<void> => {
      let rows: AlertRow[];
      try {
        rows = await apiGet<AlertRow[]>("/alerts?limit=20");
      } catch {
        return; // backend restarting — try again next tick
      }
      if (cancelled || rows.length === 0) return;

      const newestId = Math.max(...rows.map((r) => r.id));
      const seen = lastSeen();
      if (seen < 0) {
        remember(newestId); // fresh install: baseline only, no back-notifying
        return;
      }
      const fresh = rows
        .filter((r) => r.id > seen && (r.severity === "critical" || r.severity === "warning"))
        .sort((a, b) => a.id - b.id)
        .slice(-MAX_PER_POLL);
      remember(newestId);

      if (fresh.length === 0 || typeof Notification === "undefined") return;
      if (Notification.permission === "default") {
        try {
          await Notification.requestPermission();
        } catch {
          return;
        }
      }
      if (Notification.permission !== "granted") return;
      for (const alert of fresh) {
        new Notification(alert.title, {
          body: alert.description,
          tag: `mrp-alert-${alert.id}`, // OS-level dedupe
        });
      }
    };

    void poll();
    timer.current = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      cancelled = true;
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, []);
}
