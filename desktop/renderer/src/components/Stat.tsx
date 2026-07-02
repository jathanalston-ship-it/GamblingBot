import type { ReactNode } from "react";

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-card border border-surface-border bg-surface-raised px-4 py-3 shadow-card">
      <div className="overline">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums leading-tight text-slate-100">
        {value}
      </div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-slate-500">{hint}</div> : null}
    </div>
  );
}
