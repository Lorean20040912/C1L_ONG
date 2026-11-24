// Iconița din jurnale, ca în 1C: ✓ înregistrat, ○ neînregistrat, ✕ marcat pentru ștergere.
export function StatusIcon({ posted, deleted }: { posted: boolean | null; deleted?: boolean | null }) {
  if (deleted) return <span className="st del" title="Marcat pentru ștergere">✕</span>;
  if (posted) return <span className="st ok" title="Înregistrat">✓</span>;
  return <span className="st no" title="Neînregistrat">○</span>;
}
