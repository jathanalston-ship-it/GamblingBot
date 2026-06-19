import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

const STAGES = [
  "/scan",
  "/candidates",
  "/conviction",
  "/analogs",
  "/backtest",
  "/replay",
  "/paper",
  "/live",
];

function isEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.isContentEditable
  );
}

/** Global power-user keys: ⌘K palette, ? shortcuts, 1–8 stages, g-prefixed utilities. */
export function useGlobalKeys(opts: { onPalette: () => void; onShortcuts: () => void }): void {
  const navigate = useNavigate();
  const palette = useRef(opts.onPalette);
  const shortcuts = useRef(opts.onShortcuts);
  palette.current = opts.onPalette;
  shortcuts.current = opts.onShortcuts;

  useEffect(() => {
    let gPending = false;
    let gTimer = 0;

    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        palette.current();
        return;
      }
      if (isEditable(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;

      if (e.key === "?") {
        e.preventDefault();
        shortcuts.current();
        return;
      }
      if (gPending) {
        gPending = false;
        if (e.key === "p") navigate("/portfolio");
        else if (e.key === "a") navigate("/analytics");
        else if (e.key === "s") navigate("/settings");
        return;
      }
      if (e.key === "g") {
        gPending = true;
        window.clearTimeout(gTimer);
        gTimer = window.setTimeout(() => {
          gPending = false;
        }, 600);
        return;
      }
      if (e.key >= "1" && e.key <= "8") {
        navigate(STAGES[Number(e.key) - 1]);
      }
    }

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(gTimer);
    };
  }, [navigate]);
}
