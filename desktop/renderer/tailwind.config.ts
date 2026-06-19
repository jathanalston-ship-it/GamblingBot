import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0b1220",
          raised: "#131c2e",
          border: "#1f2a3d",
        },
        accent: { DEFAULT: "#3b82f6", muted: "#1d4ed8" },
        bull: "#22c55e",
        bear: "#ef4444",
        neutral: "#eab308",
      },
    },
  },
  plugins: [],
} satisfies Config;
