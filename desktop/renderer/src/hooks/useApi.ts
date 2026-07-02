import { useCallback, useEffect, useState } from "react";

import { apiGet, onApiMutation } from "../api/client";

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

/* ------------------------------------------------------------------ */
/* Stale-while-revalidate cache                                        */
/*                                                                     */
/* Navigating back to a screen renders the last known data INSTANTLY   */
/* (no spinner) while a background revalidation replaces it. Entries   */
/* are keyed by path; the cache is bounded and in-memory only, so a    */
/* reload starts clean and mutations show after the next revalidate.   */
/* ------------------------------------------------------------------ */
interface CacheEntry {
  data: unknown;
  updatedAt: number;
}

const CACHE_MAX = 120;
const cache = new Map<string, CacheEntry>();
// Concurrent mounts of the same path share one request (top bar + status bar +
// a view all asking for the same snapshots = one network round-trip).
const inflight = new Map<string, Promise<unknown>>();

function fetchShared<T>(path: string): Promise<T> {
  const pending = inflight.get(path);
  if (pending) return pending as Promise<T>;
  const req = apiGet<T>(path).finally(() => inflight.delete(path));
  inflight.set(path, req as Promise<unknown>);
  return req;
}

function cachePut(path: string, data: unknown): void {
  if (cache.size >= CACHE_MAX && !cache.has(path)) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.delete(path); // re-insert to refresh LRU order
  cache.set(path, { data, updatedAt: Date.now() });
}

/** Drop every cached response (used after mutations that change many screens). */
export function invalidateApiCache(): void {
  cache.clear();
}

// Any successful POST/PUT invalidates all cached reads — a mutation can touch
// many screens (a scan rewrites nearly everything), and correctness beats reuse.
onApiMutation(invalidateApiCache);

/** Fetch `path` on mount (and on demand via `reload`), optionally polling.
 *  Cached responses render immediately; a background refetch then updates. */
export function useApi<T>(path: string, options: ApiOptions = {}): ApiState<T> {
  const { refreshMs } = options;
  const cached = cache.get(path);
  const [data, setData] = useState<T | null>((cached?.data as T | undefined) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(cached === undefined);
  const [updatedAt, setUpdatedAt] = useState<number | null>(cached?.updatedAt ?? null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    const hit = cache.get(path);
    if (hit !== undefined) {
      // Serve stale immediately; revalidate silently below.
      setData(hit.data as T);
      setUpdatedAt(hit.updatedAt);
      setLoading(false);
    } else {
      setLoading(true);
    }
    setError(null);
    fetchShared<T>(path)
      .then((d) => {
        cachePut(path, d);
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
