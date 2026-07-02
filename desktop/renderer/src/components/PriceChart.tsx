import { useApi } from "../hooks/useApi";
import { date as fmtDate, num } from "../lib/format";
import { ErrorBox, Loading } from "./Page";

interface Bar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

interface BarsPayload {
  symbol: string;
  source: string;
  bars: Bar[];
}

export interface Overlay {
  label: string;
  price: number;
  kind: "entry" | "stop" | "target";
}

const OVERLAY_COLOR: Record<Overlay["kind"], string> = {
  entry: "#3b82f6",
  stop: "#ef4444",
  target: "#22c55e",
};

/**
 * Real OHLC candlesticks with entry/stop/target overlays, from `/bars/{symbol}`
 * (cache-first, live fallback). Pure SVG — no chart library.
 */
export function PriceChart({
  symbol,
  overlays = [],
  days = 180,
  height = 220,
}: {
  symbol: string;
  overlays?: Overlay[];
  days?: number;
  height?: number;
}) {
  const { data, error, loading } = useApi<BarsPayload>(`/bars/${symbol}?days=${days}`);

  if (loading) return <Loading />;
  if (error) return <ErrorBox message={`chart unavailable: ${error}`} />;
  const bars = (data?.bars ?? []).slice(-140);
  if (bars.length < 2) {
    return <div className="py-6 text-center text-xs text-slate-500">not enough bars to chart</div>;
  }

  const width = 720;
  const padL = 48;
  const padR = 8;
  const padY = 10;
  const plotW = width - padL - padR;
  const plotH = height - padY * 2;

  const prices = bars.flatMap((b) => [b.high, b.low]).concat(overlays.map((o) => o.price));
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const y = (p: number): number => padY + plotH - ((p - min) / span) * plotH;
  const step = plotW / bars.length;
  const candleW = Math.max(1.5, step * 0.6);

  const first = bars[0];
  const last = bars[bars.length - 1];

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={`${symbol} price chart`}
      >
        {/* price gridlines */}
        {[0.25, 0.5, 0.75].map((f) => {
          const price = min + span * f;
          return (
            <g key={f}>
              <line
                x1={padL}
                x2={width - padR}
                y1={y(price)}
                y2={y(price)}
                stroke="#1f2a3d"
                strokeWidth={1}
              />
              <text x={4} y={y(price) + 3} fontSize={9} fill="#64748b">
                {num(price, price >= 100 ? 0 : 2)}
              </text>
            </g>
          );
        })}

        {/* candles */}
        {bars.map((b, i) => {
          const cx = padL + i * step + step / 2;
          const up = b.close >= b.open;
          const color = up ? "#22c55e" : "#ef4444";
          const top = y(Math.max(b.open, b.close));
          const bodyH = Math.max(1, Math.abs(y(b.open) - y(b.close)));
          return (
            <g key={b.ts}>
              <line x1={cx} x2={cx} y1={y(b.high)} y2={y(b.low)} stroke={color} strokeWidth={1} />
              <rect
                x={cx - candleW / 2}
                y={top}
                width={candleW}
                height={bodyH}
                fill={color}
                opacity={0.9}
              />
            </g>
          );
        })}

        {/* overlays: entry / stop / targets */}
        {overlays
          .filter((o) => o.price >= min && o.price <= max)
          .map((o, i) => (
            <g key={i}>
              <line
                x1={padL}
                x2={width - padR}
                y1={y(o.price)}
                y2={y(o.price)}
                stroke={OVERLAY_COLOR[o.kind]}
                strokeWidth={1.2}
                strokeDasharray={o.kind === "target" ? "4 3" : undefined}
                opacity={0.85}
              />
              <text
                x={width - padR - 2}
                y={y(o.price) - 3}
                fontSize={9}
                fill={OVERLAY_COLOR[o.kind]}
                textAnchor="end"
              >
                {o.label} {num(o.price, 2)}
              </text>
            </g>
          ))}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-600">
        <span>{fmtDate(first ? first.ts : null)}</span>
        <span>
          {data?.source === "live" ? "pulled live" : data?.source} · {bars.length} bars
        </span>
        <span>{fmtDate(last ? last.ts : null)}</span>
      </div>
    </div>
  );
}
