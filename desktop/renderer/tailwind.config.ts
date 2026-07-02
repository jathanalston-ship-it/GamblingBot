import type { Config } from "tailwindcss";

/**
 * Momentum Lab design tokens — a dark trading-terminal system.
 *
 * Semantic, not literal: views say `bull`/`bear`/`accent`/`surface-*`, never a
 * raw hex, so the whole app retunes from this one file.
 *
 * Chart-mark colors (`chart.*`) are a CVD-validated set (six-checks validator,
 * dark surface): text-grade `bull`/`bear` are intentionally brighter than the
 * mark-grade fills — text wears text tokens, marks wear the validated palette.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: {
          sunken: "#060a13", // app background wells (nav, page)
          DEFAULT: "#0a101c", // base canvas
          raised: "#0f1726", // cards, bars
          border: "#1c2739", // hairlines
          edge: "#2a3850", // emphasized borders (inputs, active elements)
        },
        accent: { DEFAULT: "#4f8ef7", soft: "#3b82f6", muted: "#1d4ed8" },
        bull: "#34d399", // text-grade up / good
        bear: "#f87171", // text-grade down / bad
        neutral: "#fbbf24", // text-grade caution
        chart: {
          up: "#059669", // validated mark fills (dark surface)
          down: "#ef4444",
          line: "#3b82f6",
          warn: "#d97706",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.35)",
        pop: "0 8px 30px rgb(0 0 0 / 0.45)",
      },
      borderRadius: {
        card: "0.75rem",
      },
    },
  },
  plugins: [],
} satisfies Config;
