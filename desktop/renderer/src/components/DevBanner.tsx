/**
 * The "DEVELOPMENT MODE" banner — a persistent, unmissable strip shown only when
 * the app is launched via `npm run dev-app` (`window.mrp.dev`). It makes it obvious
 * the running app is a from-source dev build (isolated `.dev` state, hot reload,
 * Developer Panel) and not the packaged installer, and links straight to the panel.
 */
import { Link } from "react-router-dom";

export function DevBanner() {
  if (!window.mrp?.dev) return null;
  return (
    <div className="flex items-center justify-center gap-3 bg-amber-500/90 px-3 py-1 text-center text-xs font-semibold tracking-wide text-black">
      <span className="inline-flex h-2 w-2 animate-pulse rounded-full bg-black/70" />
      DEVELOPMENT MODE — running from source · hot reload · isolated .dev data
      <Link to="/developer" className="underline underline-offset-2 hover:opacity-80">
        Developer Panel
      </Link>
    </div>
  );
}
