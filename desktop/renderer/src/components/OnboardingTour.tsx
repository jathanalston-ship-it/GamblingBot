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
      "This app trades one simple, tested idea: buy leading stocks as they break out to new " +
      "highs while the market is rising, risk a small fixed amount on each, and hold until the " +
      "trend breaks. It uses real market prices and paper money — nothing here ever touches a " +
      "real brokerage account.",
  },
  {
    title: "1 · Today tells you what to do",
    body:
      "The Today screen answers four questions: is the market in an uptrend (is it OK to buy)? " +
      "What do you own and how is it doing? Which stocks are buy signals today? And what has the " +
      "app done? Prices load automatically when the app opens; “Scan now” refreshes them.",
    route: "/",
    routeLabel: "Open Today",
  },
  {
    title: "2 · A buy signal is a complete trade",
    body:
      "Every signal comes with the number of shares to buy, the stop price where it is sold if " +
      "wrong, and the dollars you lose if that happens (about half a percent of the account). " +
      "Press Buy to open it in the paper account.",
    route: "/signals",
    routeLabel: "Open Buy signals",
  },
  {
    title: "3 · The app does the selling",
    body:
      "Once you own a stock, the app checks it on every scan and sells it at the stop, or when " +
      "it closes below its 50-day low. There is no profit target — winners are held for as long " +
      "as the trend lasts. You can always sell early yourself from Positions.",
    route: "/positions",
    routeLabel: "Open Positions",
  },
  {
    title: "4 · Or let Auto Pilot do the buying too",
    body:
      "Switch on Auto Pilot (on the Today screen) and the app also buys each day's signals when " +
      "the market opens. Most trades will be small losses and a few will be large winners, so " +
      "the rules only work if every signal is taken — which is what Auto Pilot is for.",
    route: "/",
    routeLabel: "Open Today",
  },
  {
    title: "5 · Check the evidence",
    body:
      "Results runs these exact rules over the last twenty years of real prices and compares them " +
      "with simply holding the S&P 500 — honestly, including where they do worse. Your own paper " +
      "results build up on the same screen. Everything else lives under Advanced in the sidebar.",
    route: "/results",
    routeLabel: "Open Results",
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
