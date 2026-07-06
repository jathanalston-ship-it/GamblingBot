/**
 * Auto-updater user preferences — a pure core plus a thin fs wrapper.
 *
 * Stored as JSON beside the app's other per-user state (readable even when the
 * backend is down — updates are an Electron-side concern), so the choice
 * survives restarts. The default is fully automatic: check on launch → prompt
 * once with the size/space → download & install. Turning auto-update off, or
 * skipping a specific version, falls back to the manual Updates screen.
 */
import { readFileSync, writeFileSync } from "node:fs";

export interface UpdatePreferences {
  /** Master switch: when false the app never auto-prompts (manual fallback only). */
  autoUpdate: boolean;
  /** A version the user chose to skip; not re-prompted until a newer one appears. */
  skippedVersion: string | null;
}

export const DEFAULT_UPDATE_PREFERENCES: UpdatePreferences = {
  autoUpdate: true,
  skippedVersion: null,
};

/** Parse persisted JSON into validated preferences (defaults on anything odd). */
export function parsePreferences(raw: string): UpdatePreferences {
  try {
    const parsed = JSON.parse(raw) as Partial<UpdatePreferences>;
    return {
      autoUpdate: typeof parsed.autoUpdate === "boolean" ? parsed.autoUpdate : true,
      skippedVersion: typeof parsed.skippedVersion === "string" ? parsed.skippedVersion : null,
    };
  } catch {
    return { ...DEFAULT_UPDATE_PREFERENCES };
  }
}

/**
 * Should the user be prompted to install this version? No when auto-update is
 * off, or when they explicitly skipped exactly this version.
 */
export function shouldPrompt(prefs: UpdatePreferences, version: string): boolean {
  if (!prefs.autoUpdate) return false;
  if (prefs.skippedVersion !== null && prefs.skippedVersion === version) return false;
  return true;
}

/** Read preferences from disk, returning defaults when the file is missing/bad. */
export function readPreferences(path: string): UpdatePreferences {
  try {
    return parsePreferences(readFileSync(path, "utf-8"));
  } catch {
    return { ...DEFAULT_UPDATE_PREFERENCES };
  }
}

/** Persist preferences (pretty JSON). Best-effort; the caller guards. */
export function writePreferences(path: string, prefs: UpdatePreferences): void {
  writeFileSync(path, JSON.stringify(prefs, null, 2), "utf-8");
}
