// Small display formatters shared across views.

export const pct = (v: number | null | undefined, digits = 1): string =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;

export const num = (v: number | null | undefined, digits = 2): string =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

export const money = (v: number | null | undefined): string =>
  v == null
    ? "—"
    : v.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      });

export const date = (v: string | null | undefined): string => (v ? v.slice(0, 10) : "—");

export const signed = (v: number | null | undefined, digits = 2): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
