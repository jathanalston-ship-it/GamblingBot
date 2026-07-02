// Small display formatters shared across views.
//
// Time policy (docs/TIME.md): the backend stores/serves UTC; SQLite round-trips
// drop the "+00:00" suffix, so an offset-less ISO string MUST be interpreted as
// UTC — `new Date(iso)` would parse it as *local* time and silently shift every
// displayed timestamp by the user's UTC offset. All rendering goes through
// these helpers, which convert to the OS timezone and use the OS locale (which
// also decides 12-hour vs 24-hour clocks). Formatters are created per call so
// an OS timezone change is picked up without a restart.

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

export const signed = (v: number | null | undefined, digits = 2): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;

export const fmtAge = (minutes: number | null): string => {
  if (minutes == null) return "unknown";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 60 * 24) return `${(minutes / 60).toFixed(1)}h`;
  return `${(minutes / (60 * 24)).toFixed(1)}d`;
};

/* ------------------------------------------------------------------ */
/* Timestamps — UTC in, local timezone + OS locale out                 */
/* ------------------------------------------------------------------ */

const HAS_OFFSET = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** Parse a backend timestamp as the UTC instant it is (offset-less ⇒ UTC). */
export const parseUtc = (iso: string): Date =>
  new Date(HAS_OFFSET.test(iso) ? iso : `${iso}Z`);

const valid = (d: Date): boolean => !Number.isNaN(d.getTime());

/** Locale-formatted calendar date, in the user's local timezone.
 *  Date-only values (e.g. trading-day `as_of`) are calendar dates — rendered
 *  as-is, never timezone-shifted across midnight. */
export const date = (v: string | null | undefined): string => {
  if (!v) return "—";
  if (DATE_ONLY.test(v)) {
    const [y, m, d] = v.split("-").map(Number);
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
      new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1),
    );
  }
  const parsed = parseUtc(v);
  return valid(parsed)
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parsed)
    : "—";
};

/** Local wall-clock time; the OS locale decides 12-hour vs 24-hour. */
export const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const parsed = parseUtc(iso);
  return valid(parsed)
    ? new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(parsed)
    : "—";
};

/** Full local date + time (locale-aware). */
export const dateTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const parsed = parseUtc(iso);
  return valid(parsed)
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        parsed,
      )
    : "—";
};

/** A time in an explicit IANA zone with its abbreviation (e.g. "09:32 EDT"). */
export const timeInZone = (d: Date, timeZone: string): string =>
  new Intl.DateTimeFormat(undefined, {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(d);

/** Compact countdown: "2h 14m", "3m 12s", "45s". */
export const countdown = (seconds: number | null | undefined): string => {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec.toString().padStart(2, "0")}s`;
  return `${sec}s`;
};
