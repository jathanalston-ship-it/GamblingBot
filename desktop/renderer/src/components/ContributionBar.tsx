export function ContributionBar({ value, max }: { value: number; max: number }) {
  const w = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2 w-40 rounded bg-surface">
      <div className="h-2 rounded bg-accent" style={{ width: `${w}%` }} />
    </div>
  );
}
