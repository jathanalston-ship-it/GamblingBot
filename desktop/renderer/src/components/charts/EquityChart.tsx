/**
 * Equity curve with an optional drawdown underlay.
 *
 * Top band: the equity line (filled). Bottom band: the underwater/drawdown curve
 * (drawdown is expected as a non-positive fraction, e.g. -0.12 for -12%).
 */
export function EquityChart({
  points,
  height = 220,
}: {
  points: { label: string; equity: number; drawdown?: number | null }[];
  height?: number;
}) {
  if (points.length < 2) {
    return <div className="py-10 text-center text-sm text-slate-500">Not enough data to chart.</div>;
  }

  const W = 760;
  const padX = 8;
  const padTop = 8;
  const ddH = 52; // height reserved for the drawdown strip
  const eqH = height - ddH - padTop - 18;

  const eq = points.map((p) => p.equity);
  const eqMin = Math.min(...eq);
  const eqMax = Math.max(...eq);
  const eqSpan = eqMax - eqMin || 1;
  const x = (i: number): number => padX + (i / (points.length - 1)) * (W - padX * 2);
  const yEq = (v: number): number => padTop + (1 - (v - eqMin) / eqSpan) * eqH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${yEq(p.equity)}`).join(" ");
  const area = `${line} L ${x(points.length - 1)} ${padTop + eqH} L ${x(0)} ${padTop + eqH} Z`;

  const dd = points.map((p) => (typeof p.drawdown === "number" ? p.drawdown : 0));
  const ddMin = Math.min(-0.0001, ...dd); // most-negative drawdown
  const ddTop = padTop + eqH + 18;
  const yDd = (v: number): number => ddTop + (v / ddMin) * ddH;
  const ddArea =
    `M ${x(0)} ${ddTop} ` +
    dd.map((v, i) => `L ${x(i)} ${yDd(v)}`).join(" ") +
    ` L ${x(points.length - 1)} ${ddTop} Z`;

  const up = points[points.length - 1].equity >= points[0].equity;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" role="img" aria-label="Equity curve">
      <path d={area} className={up ? "fill-bull/10" : "fill-bear/10"} />
      <path d={line} className={up ? "stroke-bull" : "stroke-bear"} fill="none" strokeWidth={1.5} />
      {/* drawdown strip */}
      <line x1={padX} y1={ddTop} x2={W - padX} y2={ddTop} className="stroke-surface-border" />
      <path d={ddArea} className="fill-bear/25" />
      <text x={padX} y={ddTop - 4} className="fill-slate-500 text-[10px]">
        equity {points[0].label} → {points[points.length - 1].label}
      </text>
      <text x={padX} y={height - 4} className="fill-slate-500 text-[10px]">
        drawdown (min {(ddMin * 100).toFixed(1)}%)
      </text>
    </svg>
  );
}
