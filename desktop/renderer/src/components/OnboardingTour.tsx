import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const SEEN_KEY = "mrp:onboarding:done";
/** Settings (or anything else) can re-open the tour by dispatching this event. */
export const TOUR_EVENT = "mrp:tour:start";

interface Step {
  title: string;
  body: string;
  route?: string;
  routeLabel?: string;
}

const STEPS: Step[] = [
  {
    title: "Welcome to Momentum Lab",
    body:
      "This app finds momentum-breakout setups, scores how convinced it is, sizes the risk, " +
      "and manages every paper trade automatically — take-profits, stop-losses and plain-language " +
      "reports on why it acted. Real market data, paper money: nothing here ever touches a live " +
      "brokerage account. This one-minute tour shows the path from raw data to a managed trade.",
  },
  {
    title: "1 · Connect market data",
    body:
      "Pick a data provider under Settings → Data Provider. Yahoo Finance works out of the box " +
      "with no account; Alpaca or Polygon give faster, richer data if you have free API keys. " +
      "You can also load a deterministic sample dataset from Settings to explore every screen " +
      "before running anything live.",
    route: "/settings",
    routeLabel: "Open Settings",
  },
  {
    title: "2 · Choose what to scan",
    body:
      "Settings → Scanner Universe decides which stocks the scanner watches: the built-in " +
      "default list, a full index like the S&P 500, one sector, or your own pasted watchlist. " +
      "The selection sticks and every scan uses it.",
    route: "/settings",
    routeLabel: "Open Settings",
  },
  {
    title: "3 · Run a scan",
    body:
      "The Scanner pulls fresh bars, screens the universe for momentum breakouts, and scores " +
      "each candidate with an explainable 0-100 conviction. While the market is open the " +
      "built-in daemon rescans automatically every minute — you never have to press the button " +
      "again after the first one.",
    route: "/scan",
    routeLabel: "Open Scanner",
  },
  {
    title: "4 · Start at the Command Center",
    body:
      "The Command Center is the daily landing page: current market regime, the strongest " +
      "setups for today / this week / this month, portfolio heat and the live activity feed. " +
      "When you just want to know “what looks good right now?”, look here first.",
    route: "/command-center",
    routeLabel: "Open Command Center",
  },
  {
    title: "5 · Take a trade and let the system manage it",
    body:
      "Click any symbol to see its trade plan — entry, stop, targets and suggested size. " +
      "“Take paper trade” opens it in the paper account, and from then on the system watches it " +
      "on every scan: raising stops, scaling out at targets, closing on a stop hit — each action " +
      "explained and delivered as an OS notification. The Trades screen shows every position's " +
      "health and history. That's the whole loop — enjoy!",
    route: "/trades",
    routeLabel: "Open Trades",
  },
];

/**
 * First-run guided tour: a lightweight modal sequence walking a new user from
 * “connect data” to “take a managed paper trade”. Shows once (localStorage);
 * Settings can relaunch it via the TOUR_EVENT custom event.
 */
export function OnboardingTour() {
  const [open, setOpen] = useState<boolean>(() => !window.localStorage.getItem(SEEN_KEY));
  const [step, setStep] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const relaunch = () => {
      setStep(0);
      setOpen(true);
    };
    window.addEventListener(TOUR_EVENT, relaunch);
    return () => window.removeEventListener(TOUR_EVENT, relaunch);
  }, []);

  const finish = useCallback(() => {
    window.localStorage.setItem(SEEN_KEY, new Date().toISOString());
    setOpen(false);
  }, []);

  if (!open) return null;

  const current = STEPS[step];
  const last = step === STEPS.length - 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div className="w-full max-w-lg rounded-lg border border-surface-border bg-surface-raised p-6 shadow-2xl">
        <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">
          Getting started · {step + 1} / {STEPS.length}
        </div>
        <h2 className="mb-3 text-lg font-semibold text-slate-100">{current.title}</h2>
        <p className="mb-5 text-sm leading-relaxed text-slate-300">{current.body}</p>

        <div className="mb-5 flex gap-1.5">
          {STEPS.map((_, i) => (
            <button
              key={i}
              aria-label={`step ${i + 1}`}
              onClick={() => setStep(i)}
              className={`h-1.5 flex-1 rounded-full ${i <= step ? "bg-accent" : "bg-surface-border"}`}
            />
          ))}
        </div>

        <div className="flex items-center justify-between">
          <button onClick={finish} className="btn-quiet px-3 py-1.5 text-xs text-slate-400">
            Skip tour
          </button>
          <div className="flex items-center gap-2">
            {current.route ? (
              <button
                onClick={() => {
                  navigate(current.route ?? "/");
                  if (last) finish();
                }}
                className="btn-ghost px-3 py-1.5 text-xs"
              >
                {current.routeLabel}
              </button>
            ) : null}
            {step > 0 ? (
              <button onClick={() => setStep(step - 1)} className="btn-ghost px-3 py-1.5 text-xs">
                Back
              </button>
            ) : null}
            <button
              onClick={() => (last ? finish() : setStep(step + 1))}
              className="btn-primary px-4 py-1.5 text-xs"
            >
              {last ? "Finish" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
