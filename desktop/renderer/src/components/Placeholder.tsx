export function Placeholder({ stage, note }: { stage: string; note?: string }) {
  return (
    <div className="p-8">
      <h1 className="text-lg font-semibold text-slate-200">{stage}</h1>
      <p className="mt-2 max-w-xl text-sm text-slate-500">
        {note ??
          "Planned for the next build slice. The shell, navigation and the " +
            "Scan → Conviction → Analogs research loop are live now."}
      </p>
    </div>
  );
}
