/**
 * A distribution histogram for R-multiples (or any signed series). Bars left of
 * zero are losses (red), right are wins (green) — so positive skew is visible at
 * a glance: a few tall bars far to the right.
 */
export function Histogram({
  values,
  bins = 13,
  height = 160,
}: {
  values: number[];
  bins?: number;
  height?: number;
}) {
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length === 0) {
    return <div className="py-8 text-center text-sm text-slate-500">No data to plot.</div>;
  }

  const lo = Math.min(...clean, 0);
  const hi = Math.max(...clean, 0);
  const span = hi - lo || 1;
  const width = span / bins;
  const counts = new Array<number>(bins).fill(0);
  for (const v of clean) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / width)));
    counts[idx] += 1;
  }
  const maxCount = Math.max(...counts) || 1;

  const W = 760;
  const H = height;
  const padX = 8;
  const padBottom = 18;
  const plotW = W - padX * 2;
  const plotH = H - padBottom;
  const barW = plotW / bins;
  const zeroX = padX + ((0 - lo) / span) * plotW;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="R-multiple distribution">
      {counts.map((c, i) => {
        const binLo = lo + i * width;
        const h = (c / maxCount) * (plotH - 4);
        const win = binLo + width / 2 >= 0;
        return (
          <rect
            key={i}
            x={padX + i * barW + 1}
            y={plotH - h}
            width={Math.max(1, barW - 2)}
            height={h}
            className={win ? "fill-bull/70" : "fill-bear/70"}
          />
        );
      })}
      {/* zero line */}
      <line x1={zeroX} y1={0} x2={zeroX} y2={plotH} className="stroke-slate-500" strokeDasharray="3 3" />
      <text x={zeroX} y={H - 4} textAnchor="middle" className="fill-slate-500 text-[10px]">
        0R
      </text>
      <text x={padX} y={H - 4} className="fill-slate-500 text-[10px]">
        {lo.toFixed(1)}R
      </text>
      <text x={W - padX} y={H - 4} textAnchor="end" className="fill-slate-500 text-[10px]">
        {hi.toFixed(1)}R
      </text>
    </svg>
  );
}
