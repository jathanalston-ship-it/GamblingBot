import type { ReactNode } from "react";

export type Tone = "bull" | "bear" | "neutral" | "default";

const TONES: Record<Tone, string> = {
  bull: "bg-bull/10 text-bull ring-bull/30",
  bear: "bg-bear/10 text-bear ring-bear/30",
  neutral: "bg-neutral/10 text-neutral ring-neutral/30",
  default: "bg-surface-border/60 text-slate-300 ring-surface-edge/50",
};

export function regimeTone(regime: string): Tone {
  const r = regime.toLowerCase();
  if (r.startsWith("bull")) return "bull";
  if (r.startsWith("bear")) return "bear";
  if (r.startsWith("neutral")) return "neutral";
  return "default";
}

export function Badge({ children, tone = "default" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ring-1 ring-inset ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
