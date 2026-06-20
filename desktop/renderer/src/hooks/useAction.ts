import { useCallback, useRef, useState } from "react";

import { apiGet, apiPost } from "../api/client";
import type { Job } from "../api/types";

const POLL_MS = 800;
const TERMINAL = new Set(["succeeded", "failed"]);

export interface ActionState {
  job: Job | null;
  running: boolean;
  start: (body?: unknown) => Promise<void>;
  reset: () => void;
}

/**
 * Trigger a backend action (POST), then poll `GET /actions/jobs/{id}` until the
 * job reaches a terminal state — exposing live progress and success/failure.
 */
export function useAction(path: string, onDone?: (job: Job) => void): ActionState {
  const [job, setJob] = useState<Job | null>(null);
  const [running, setRunning] = useState(false);
  const cancelled = useRef(false);

  const start = useCallback(
    async (body?: unknown) => {
      cancelled.current = false;
      setRunning(true);
      setJob(null);
      try {
        let current = await apiPost<Job>(path, body ?? {});
        setJob(current);
        while (!TERMINAL.has(current.status) && !cancelled.current) {
          await new Promise((r) => setTimeout(r, POLL_MS));
          current = await apiGet<Job>(`/actions/jobs/${current.id}`);
          setJob(current);
        }
        if (!cancelled.current) onDone?.(current);
      } catch (e: unknown) {
        setJob({
          id: "",
          kind: "",
          status: "failed",
          progress: 0,
          message: "",
          result: null,
          error: e instanceof Error ? e.message : String(e),
          created_at: "",
          finished_at: null,
        });
      } finally {
        setRunning(false);
      }
    },
    [path, onDone],
  );

  const reset = useCallback(() => {
    cancelled.current = true;
    setJob(null);
  }, []);

  return { job, running, start, reset };
}
