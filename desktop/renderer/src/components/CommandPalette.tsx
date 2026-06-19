import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

interface Cmd {
  label: string;
  hint: string;
  run: () => void;
}

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo<Cmd[]>(() => {
    const go = (path: string) => () => {
      navigate(path);
      onClose();
    };
    return [
      { label: "Scan", hint: "stage 1", run: go("/scan") },
      { label: "Candidates", hint: "stage 2", run: go("/candidates") },
      { label: "Conviction", hint: "stage 3", run: go("/conviction") },
      { label: "Analogs", hint: "stage 4", run: go("/analogs") },
      { label: "Backtest", hint: "stage 5", run: go("/backtest") },
      { label: "Replay", hint: "stage 6", run: go("/replay") },
      { label: "Paper", hint: "stage 7", run: go("/paper") },
      { label: "Live", hint: "stage 8 · gated", run: go("/live") },
      { label: "Portfolio", hint: "utility", run: go("/portfolio") },
      { label: "Analytics", hint: "utility", run: go("/analytics") },
      { label: "Settings", hint: "utility", run: go("/settings") },
    ];
  }, [navigate, onClose]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? commands.filter((c) => c.label.toLowerCase().includes(s)) : commands;
  }, [q, commands]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useEffect(() => {
    setI(0);
  }, [q]);

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setI((x) => Math.min(x + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setI((x) => Math.max(x - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      filtered[i]?.run();
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-28"
      onClick={onClose}
    >
      <div
        className="w-[40rem] overflow-hidden rounded-lg border border-surface-border bg-surface-raised shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="Search stages, actions…"
          className="w-full bg-transparent px-4 py-3 text-sm text-slate-200 outline-none placeholder:text-slate-500"
        />
        <div className="max-h-80 overflow-auto border-t border-surface-border">
          {filtered.map((c, idx) => (
            <button
              key={c.label}
              onClick={() => c.run()}
              onMouseEnter={() => setI(idx)}
              className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                idx === i ? "bg-accent/15 text-accent" : "text-slate-300"
              }`}
            >
              <span>{c.label}</span>
              <span className="text-xs text-slate-500">{c.hint}</span>
            </button>
          ))}
          {filtered.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-slate-500">No matches</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
