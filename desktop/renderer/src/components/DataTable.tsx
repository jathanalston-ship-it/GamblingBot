import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  render?: (row: T) => ReactNode;
}

interface Props<T extends Record<string, unknown>> {
  columns: Column<T>[];
  rows: T[];
  empty?: string;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  rows,
  empty = "No data.",
}: Props<T>) {
  if (rows.length === 0) {
    return <div className="py-8 text-center text-sm text-slate-500">{empty}</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-surface-border text-left text-xs uppercase tracking-wide text-slate-400">
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-3 py-2 font-medium ${c.align === "right" ? "text-right" : ""}`}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-surface-border/50 hover:bg-surface/40">
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-3 py-2 ${c.align === "right" ? "text-right tabular-nums" : ""}`}
                >
                  {c.render ? c.render(row) : String(row[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
