import { useEffect, useState } from "react";

function rel(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
}

/** A live "updated Ns ago" chip that turns amber once the data is stale. */
export function Freshness({
  updatedAt,
  staleMs = 90_000,
}: {
  updatedAt: number | null;
  staleMs?: number;
}) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (updatedAt == null) return null;
  const age = Date.now() - updatedAt;
  const stale = age > staleMs;
  return (
    <span
      className={`flex items-center gap-1.5 text-xs ${stale ? "text-amber-400" : "text-slate-500"}`}
      title={`Last updated ${new Date(updatedAt).toLocaleTimeString()}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${stale ? "bg-amber-400" : "bg-bull"}`} />
      {stale ? "stale" : "live"} · updated {rel(age)}
    </span>
  );
}
