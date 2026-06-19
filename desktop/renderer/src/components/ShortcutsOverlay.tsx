const ROWS: [string, string][] = [
  ["⌘K / Ctrl-K", "command palette"],
  ["1 – 8", "jump to a pipeline stage"],
  ["g p / g a / g s", "Portfolio / Analytics / Settings"],
  ["j / k", "next / previous candidate (Scan)"],
  ["⏎", "drill the selection (Scan → Conviction)"],
  ["?", "toggle this overlay"],
  ["Esc", "close overlay / palette"],
];

export function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-[28rem] rounded-lg border border-surface-border bg-surface-raised p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Keyboard shortcuts</h2>
        <table className="w-full text-sm">
          <tbody>
            {ROWS.map(([keys, what]) => (
              <tr key={keys} className="border-b border-surface-border/40">
                <td className="py-1.5 pr-4 font-mono text-xs text-accent">{keys}</td>
                <td className="py-1.5 text-slate-300">{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
