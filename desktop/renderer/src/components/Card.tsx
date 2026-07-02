import type { ReactNode } from "react";

export function Card({
  title,
  action,
  children,
  flush = false,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  /** No body padding — for tables and charts that bleed to the edge. */
  flush?: boolean;
}) {
  return (
    <section className="overflow-hidden rounded-card border border-surface-border bg-surface-raised shadow-card">
      {title ? (
        <header className="flex items-center justify-between gap-3 border-b border-surface-border/70 px-4 py-2.5">
          <h2 className="text-[13px] font-semibold text-slate-200">{title}</h2>
          {action}
        </header>
      ) : null}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}
