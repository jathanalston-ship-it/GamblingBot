/** A tiny inline line chart for a short numeric series (e.g. conviction over time). */
export function Sparkline({
  values,
  width = 96,
  height = 24,
  className = "stroke-accent",
}: {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
}) {
  if (values.length < 2) return <span className="text-xs text-slate-600">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 2;
  const step = (width - pad * 2) / (values.length - 1);
  const y = (v: number): number => height - pad - ((v - min) / span) * (height - pad * 2);
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"} ${pad + i * step} ${y(v)}`).join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden>
      <path d={d} className={`fill-none ${className}`} strokeWidth={1.5} />
    </svg>
  );
}
