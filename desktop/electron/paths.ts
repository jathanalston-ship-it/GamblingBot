/**
 * Where the app keeps its writable state (database, logs, editable settings).
 *
 * Pure resolver (no `electron` import) so it is unit-testable; main.ts supplies the
 * electron-derived inputs. Three modes, in priority order:
 *
 *   • Development Mode (`npm run dev-app`)  → `<repo>/.dev`        (isolated, git-ignored)
 *   • Portable build (extracted zip)        → `<exeDir>/MomentumLab-Data`  (beside the exe)
 *   • Installed / packaged                  → the per-user `userData` dir
 *
 * The portable case is what lets a release-candidate zip run with no installer and
 * write its startup logs beside the executable, while staying byte-identical to the
 * installer build (same binaries — only the data root differs).
 */
import { join } from "node:path";

/** The marker file shipped only inside the portable zip (beside the executable). */
export const PORTABLE_MARKER = "MomentumLab.portable";

/** The folder created beside a portable executable to hold its data + logs. */
export const PORTABLE_DATA_DIR = "MomentumLab-Data";

export interface PathInputs {
  isDevApp: boolean;
  isPortable: boolean;
  repoRoot: string;
  exeDir: string;
  userDataDir: string;
}

/** Resolve the writable root directory for the current run mode. */
export function resolveDataRoot(p: PathInputs): string {
  if (p.isDevApp) return join(p.repoRoot, ".dev");
  if (p.isPortable) return join(p.exeDir, PORTABLE_DATA_DIR);
  return p.userDataDir;
}

// ---------------------------------------------------------------------------
// Profiles — separate, fully isolated data roots under one install.
//
// The base root holds `profile.json` ({"active": name}) plus the default
// profile's data; every non-default profile lives under `profiles/<name>/`
// with its own database, logs and settings. Switching profiles is a relaunch
// (the backend is spawned with the new root), so state can never bleed.
// ---------------------------------------------------------------------------

/** The default profile: data lives directly in the base root (back-compat). */
export const DEFAULT_PROFILE = "default";

/** File in the base root recording which profile is active. */
export const PROFILE_FILE = "profile.json";

/** Subdirectory of the base root holding the non-default profiles. */
export const PROFILES_DIR = "profiles";

/** Normalize a user-typed profile name to a safe directory name (or null). */
export function sanitizeProfileName(name: string): string | null {
  const cleaned = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-_ ]/g, "")
    .replace(/\s+/g, "-")
    .slice(0, 40);
  return cleaned.length > 0 ? cleaned : null;
}

/** The writable root for a profile: the base root itself for "default". */
export function profileDataRoot(baseRoot: string, profile: string): string {
  const name = sanitizeProfileName(profile) ?? DEFAULT_PROFILE;
  if (name === DEFAULT_PROFILE) return baseRoot;
  return join(baseRoot, PROFILES_DIR, name);
}
