import type { ReactNode } from "react";

export type Tone = "bull" | "bear" | "neutral" | "default";

const TONES: Record<Tone, string> = {
  bull: "bg-bull/15 text-bull",
  bear: "bg-bear/15 text-bear",
  neutral: "bg-neutral/15 text-neutral",
  default: "bg-surface-border text-slate-300",
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
    <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium capitalize ${TONES[tone]}`}>
      {children}
    </span>
  );
}
