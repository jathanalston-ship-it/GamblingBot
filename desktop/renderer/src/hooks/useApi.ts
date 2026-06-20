import { useCallback, useEffect, useState } from "react";

import { apiGet } from "../api/client";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  /** Epoch ms of the last successful fetch (for freshness/stale indicators). */
  updatedAt: number | null;
}

export interface ApiOptions {
  /** Poll the endpoint on this interval (ms). Omit to fetch once. */
  refreshMs?: number;
}

/** Fetch `path` on mount (and on demand via `reload`), optionally polling. */
export function useApi<T>(path: string, options: ApiOptions = {}): ApiState<T> {
  const { refreshMs } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiGet<T>(path)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setUpdatedAt(Date.now());
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, tick]);

  // Background polling (does not toggle the `loading` spinner — it's a refresh).
  useEffect(() => {
    if (!refreshMs || refreshMs <= 0) return;
    const id = window.setInterval(() => setTick((t) => t + 1), refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs]);

  return { data, error, loading, reload, updatedAt };
}
