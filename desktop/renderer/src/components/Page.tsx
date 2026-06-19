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
    <div className="mb-5 flex items-end justify-between">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
        {subtitle ? <p className="text-sm text-slate-500">{subtitle}</p> : null}
      </div>
      {children}
    </div>
  );
}

export function Loading() {
  return <div className="py-10 text-center text-sm text-slate-500">Loading…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-bear/40 bg-bear/10 p-4 text-sm text-bear">
      Failed to load: {message}
      <div className="mt-1 text-xs text-slate-500">
        Is the backend running? Start it with <code>python -m momentum.api</code>.
      </div>
    </div>
  );
}
