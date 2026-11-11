import type { ReactNode } from "react";

/** Whole dollars with thousands separators ("$12,340"); "—" when unknown. */
export function usd(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A share price: always two decimals. */
export function price(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A percentage that is ALREADY in percent units (12.3 → "12.3%"). */
export function percent(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

/** A fraction shown as a percentage (0.123 → "12.3%"). */
export function fraction(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function gainTone(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-slate-300";
  return v > 0 ? "text-bull" : "text-bear";
}

/** Signed dollars, coloured: "+$420" green / "−$180" red. */
export function Gain({ value, digits = 0 }: { value: number | null | undefined; digits?: number }) {
  if (value == null || !Number.isFinite(value)) return <span className="text-slate-500">—</span>;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return (
    <span className={`tabular-nums ${gainTone(value)}`}>
      {sign}
      {usd(Math.abs(value), digits)}
    </span>
  );
}

export function GainPct({ value }: { value: number | null | undefined }) {
  if (value == null || !Number.isFinite(value)) return <span className="text-slate-500">—</span>;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return (
    <span className={`tabular-nums ${gainTone(value)}`}>
      {sign}
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}

/** A titled block with an optional one-line explanation and a right-side action. */
export function Section({
  title,
  hint,
  action,
  children,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mt-7">
      <div className="mb-2.5 flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div>
          <h2 className="text-[15px] font-semibold text-slate-100">{title}</h2>
          {hint ? <p className="mt-0.5 text-[13px] leading-snug text-slate-400">{hint}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`overflow-hidden rounded-card border border-surface-border bg-surface-raised shadow-card ${className}`}
    >
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <Panel>
      <div className="px-5 py-6 text-[13px] leading-relaxed text-slate-400">{children}</div>
    </Panel>
  );
}

/** A labelled number tile. */
export function Figure({
  label,
  value,
  sub,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-xl font-semibold tabular-nums text-slate-100">{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[12px] text-slate-500">{sub}</div> : null}
    </div>
  );
}

export const TH = "px-4 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-slate-500";
export const TH_R = `${TH} text-right`;
export const TD = "px-4 py-2.5 align-middle text-[13px]";
export const TD_R = `${TD} text-right tabular-nums`;
