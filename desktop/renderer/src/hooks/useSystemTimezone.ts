import { useEffect, useState } from "react";

/**
 * The operating system's current IANA timezone, kept live.
 *
 * Chromium re-resolves `Intl.DateTimeFormat().resolvedOptions().timeZone` when
 * the OS timezone changes; polling it lets React re-render everything that
 * displays wall-clock time — no application restart, no manual configuration.
 */
export function useSystemTimezone(pollMs = 5_000): string {
  const [tz, setTz] = useState<string>(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
  );

  useEffect(() => {
    const id = window.setInterval(() => {
      const current = Intl.DateTimeFormat().resolvedOptions().timeZone;
      setTz((prev) => (prev === current ? prev : current));
    }, pollMs);
    return () => window.clearInterval(id);
  }, [pollMs]);

  return tz;
}
