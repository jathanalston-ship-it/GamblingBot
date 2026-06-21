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
