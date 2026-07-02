import type { ReactNode } from "react";

export function PageTitle({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-slate-100">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-[13px] text-slate-500">{subtitle}</p> : null}
      </div>
      {children}
    </div>
  );
}

export function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-surface-edge border-t-accent" />
      Loading…
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-card border border-bear/30 bg-bear/10 p-4 text-sm text-bear">
      Failed to load: {message}
      <div className="mt-1 text-xs text-slate-500">
        Is the backend running? Start it with <code>python -m momentum.api</code>.
      </div>
    </div>
  );
}
