/**
 * Auto-update sizing + prompt logic — pure, Electron-free and unit-tested.
 *
 * The overhauled updater checks for a newer release on launch and, when it finds
 * one, asks the user ONCE — showing the download size and how much disk space to
 * have free — before it downloads and installs automatically. The maths behind
 * that prompt lives here so it is testable without Electron (see
 * scripts/auto-update.test.cjs), matching the pure-logic pattern of
 * update-flow.ts / startup-metrics.ts.
 */

/** One artifact in an electron-updater `UpdateInfo` (only `size` matters here). */
export interface UpdateFileLike {
  size?: number | null;
}

/** The subset of electron-updater's `UpdateInfo` the prompt needs. */
export interface UpdateInfoLike {
  version: string;
  files?: UpdateFileLike[] | null;
  releaseName?: string | null;
  releaseDate?: string | null;
}

// NSIS unpacks/installs roughly twice the compressed installer; on top of the
// download we keep during install, recommend that plus a floor and a margin so
// an update can never fail halfway for lack of disk space. Conservative on
// purpose — the number is advisory, shown so the user can plan.
export const MIN_INSTALL_HEADROOM_BYTES = 150 * 1024 * 1024; // 150 MB floor
export const SAFETY_MARGIN_BYTES = 250 * 1024 * 1024; // 250 MB margin
const INSTALL_HEADROOM_MULTIPLIER = 2;

/** Total bytes to download for this update (sum of artifact sizes; 0 if unknown). */
export function estimateDownloadBytes(info: UpdateInfoLike): number {
  let total = 0;
  for (const file of info.files ?? []) {
    if (typeof file.size === "number" && file.size > 0) total += file.size;
  }
  return total;
}

/**
 * Disk space we recommend the user has free before updating: the downloaded
 * installer (kept during install) + the unpacked/installed app (~2× the
 * compressed download, with a floor) + a safety margin. Returns 0 when the
 * download size is unknown (the prompt then says so rather than guess).
 */
export function recommendedFreeBytes(downloadBytes: number): number {
  if (downloadBytes <= 0) return 0;
  const installHeadroom = Math.max(
    Math.round(downloadBytes * INSTALL_HEADROOM_MULTIPLIER),
    MIN_INSTALL_HEADROOM_BYTES,
  );
  return downloadBytes + installHeadroom + SAFETY_MARGIN_BYTES;
}

/** Human-readable bytes ("164 MB", "1.2 GB"); "unknown" for a non-positive size. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // Whole numbers for B/KB and for anything ≥100; one decimal otherwise.
  const rounded = value >= 100 || unit <= 1 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unit]}`;
}

/** The payload the confirmation prompt renders (all display strings pre-formatted). */
export interface UpdatePrompt {
  version: string;
  releaseName: string | null;
  downloadBytes: number;
  downloadLabel: string;
  recommendedFreeBytes: number;
  recommendedFreeLabel: string;
  /** False when the release metadata carried no sizes (prompt says "unknown"). */
  sizeKnown: boolean;
}

/** Build the confirmation-prompt payload from an `update-available` info object. */
export function buildUpdatePrompt(info: UpdateInfoLike): UpdatePrompt {
  const downloadBytes = estimateDownloadBytes(info);
  const recommended = recommendedFreeBytes(downloadBytes);
  const sizeKnown = downloadBytes > 0;
  return {
    version: info.version,
    releaseName: info.releaseName ?? null,
    downloadBytes,
    downloadLabel: formatBytes(downloadBytes),
    recommendedFreeBytes: recommended,
    recommendedFreeLabel: sizeKnown ? formatBytes(recommended) : "unknown",
    sizeKnown,
  };
}
