import { useEffect, useRef, useState } from "react";

/**
 * Live difference visualization: shows the previous value beside the new one
 * with a direction arrow, and flashes (green = upgrade, red = downgrade,
 * orange = caution metrics like health drops) whenever the value changes.
 * Changes are never hidden — the previous value stays visible.
 */
export function DeltaValue({
  value,
  previous,
  digits = 0,
  warn = false,
  suffix = "",
}: {
  value: number | null | undefined;
  previous?: number | null;
  digits?: number;
  warn?: boolean;
  suffix?: string;
}) {
  const [flash, setFlash] = useState<string>("");
  const last = useRef<number | null | undefined>(value);

  useEffect(() => {
    if (last.current != null && value != null && value !== last.current) {
      const up = value > last.current;
      setFlash(up ? "flash-up" : warn ? "flash-warn" : "flash-down");
      const id = window.setTimeout(() => setFlash(""), 1300);
      return () => window.clearTimeout(id);
    }
    last.current = value;
    return undefined;
  }, [value, warn]);

  useEffect(() => {
    last.current = value;
  }, [value]);

  const prev = previous ?? null;
  const changed = prev != null && value != null && Math.abs(value - prev) > 1e-9;
  const up = changed && value != null && prev != null && value > prev;

  return (
    <span className={`inline-flex items-baseline gap-1 rounded px-0.5 tabular-nums ${flash}`}>
      {changed ? (
        <>
          <span className="text-xs text-slate-500 line-through">
            {prev != null ? prev.toFixed(digits) : "—"}
          </span>
          <span className={up ? "text-emerald-400" : warn ? "text-amber-400" : "text-bear"}>
            {up ? "↑" : "↓"}
          </span>
        </>
      ) : null}
      <span className="font-semibold text-slate-100">
        {value != null ? `${value.toFixed(digits)}${suffix}` : "—"}
      </span>
    </span>
  );
}
