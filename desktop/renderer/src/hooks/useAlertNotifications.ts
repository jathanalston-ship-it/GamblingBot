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

interface NotificationPrefs {
  enabled: boolean;
  min_severity: string;
  muted_kinds: string[];
}

const POLL_MS = 60_000; // matches the daemon's scan cadence
const LAST_SEEN_KEY = "mrp:alerts:last-seen-id";
const MAX_PER_POLL = 5; // never blast a backlog

const SEVERITY_RANK: Record<string, number> = { info: 0, warning: 1, critical: 2 };

function lastSeen(): number {
  const raw = window.localStorage.getItem(LAST_SEEN_KEY);
  const n = raw ? Number(raw) : Number.NaN;
  return Number.isFinite(n) ? n : -1;
}

function remember(id: number): void {
  window.localStorage.setItem(LAST_SEEN_KEY, String(id));
}

/**
 * OS-level notifications for important alerts — trade managed (stop-loss /
 * take-profit), stop or target reached, regime change.
 *
 * Polls `/alerts` on the scan cadence and fires a system Notification for
 * each alert newer than the last one seen (persisted, so a restart doesn't
 * re-notify). The first run on a fresh install only sets the baseline.
 * Honors the user's notification preferences (Settings → Notifications):
 * a global on/off switch, a severity floor, and per-kind mutes.
 */
export function useAlertNotifications(): void {
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async (): Promise<void> => {
      let rows: AlertRow[];
      let prefs: NotificationPrefs = { enabled: true, min_severity: "warning", muted_kinds: [] };
      try {
        rows = await apiGet<AlertRow[]>("/alerts?limit=20");
        prefs = await apiGet<NotificationPrefs>("/settings/notifications");
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
      const floor = SEVERITY_RANK[prefs.min_severity] ?? 1;
      const muted = new Set(prefs.muted_kinds ?? []);
      const fresh = rows
        .filter(
          (r) =>
            r.id > seen && (SEVERITY_RANK[r.severity] ?? 0) >= floor && !muted.has(r.kind),
        )
        .sort((a, b) => a.id - b.id)
        .slice(-MAX_PER_POLL);
      remember(newestId);

      if (!prefs.enabled || fresh.length === 0 || typeof Notification === "undefined") return;
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
