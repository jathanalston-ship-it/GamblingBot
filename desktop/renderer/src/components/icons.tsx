/** Minimal 16px stroke icon set (hand-rolled, no dependency). */

const PATHS: Record<string, string> = {
  home: "M2.5 8 8 3l5.5 5M4 7.5V13h3v-3h2v3h3V7.5",
  radar: "M8 8l4.2-3M8 14A6 6 0 1 1 8 2a6 6 0 0 1 0 12ZM8 11a3 3 0 1 1 0-6",
  list: "M5.5 4h8M5.5 8h8M5.5 12h8M2.5 4h.01M2.5 8h.01M2.5 12h.01",
  gauge: "M3.5 12.5a6 6 0 1 1 9 0M8 9.5 10.8 6M8 9.5h.01",
  target: "M8 14A6 6 0 1 1 8 2a6 6 0 0 1 0 12ZM8 11a3 3 0 1 1 0-6M8 8h.01",
  layers: "M8 2.5 14 6 8 9.5 2 6l6-3.5ZM3 9l5 3 5-3M3 12l5 3 5-3",
  pulse: "M1.5 8h3l1.5-4 3 8 1.5-4h3",
  clock: "M8 5v3.5l2.5 1.5M8 14A6 6 0 1 1 8 2a6 6 0 0 1 0 12Z",
  briefcase: "M2.5 6h11v7h-11V6ZM5.5 6V4.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V6M2.5 9.5h11",
  chart: "M2.5 13.5h11M4.5 10v3.5M8 6v7.5M11.5 3v10.5",
  flask: "M6 2.5h4M6.8 2.5v4L3.5 12a1.5 1.5 0 0 0 1.3 2.2h6.4a1.5 1.5 0 0 0 1.3-2.2L9.2 6.5v-4",
  replay: "M3 8a5 5 0 1 0 1.5-3.5M3 2.5V5h2.5",
  scale: "M8 3v10M8 3l4 2.5M8 3 4 5.5M2 10.5 4 6l2 4.5a2 2 0 0 1-4 0ZM10 10.5 12 6l2 4.5a2 2 0 0 1-4 0Z",
  audit: "M6 2.5h6.5V11L10 13.5H6a1.5 1.5 0 0 1-1.5-1.5V4A1.5 1.5 0 0 1 6 2.5ZM7 6h4M7 8.5h4",
  heart: "M2 8h2.5l1.5-3 2.5 6 1.5-3H13M8 13.5C4 10.5 2 8.6 2 6.3 2 4.6 3.3 3.5 4.8 3.5c1.2 0 2.4.7 3.2 1.9.8-1.2 2-1.9 3.2-1.9 1.5 0 2.8 1.1 2.8 2.8 0 2.3-2 4.2-6 7.2Z",
  gear: "M8 10.5A2.5 2.5 0 1 0 8 5.5a2.5 2.5 0 0 0 0 5ZM13 8c0-.4 0-.8-.1-1.2l1.4-1-1.2-2.1-1.6.6a5 5 0 0 0-2-1.2L9.2 1.4H6.8l-.3 1.7a5 5 0 0 0-2 1.2l-1.6-.6-1.2 2.1 1.4 1a5 5 0 0 0 0 2.4l-1.4 1 1.2 2.1 1.6-.6a5 5 0 0 0 2 1.2l.3 1.7h2.4l.3-1.7a5 5 0 0 0 2-1.2l1.6.6 1.2-2.1-1.4-1c.1-.4.1-.8.1-1.2Z",
  download: "M8 2.5v7M5 7l3 3 3-3M3 12.5h10",
  wrench: "M9.5 4.5a3 3 0 0 1 4-2.8L11 4.2l.8 1.4L14.2 5A3 3 0 0 1 10 8.5L5 13.5a1.4 1.4 0 0 1-2-2l5-5a3 3 0 0 1 1.5-2Z",
  check: "M3 8.5 6.5 12 13 4",
  crosshair: "M8 1.5V4M8 12v2.5M1.5 8H4M12 8h2.5M8 12a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z",
};

export function Icon({ name, className = "" }: { name: string; className?: string }) {
  const d = PATHS[name];
  if (!d) return null;
  return (
    <svg
      viewBox="0 0 16 16"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden
    >
      <path d={d} />
    </svg>
  );
}
