import type { Grant } from "../api/types";

/** Linia de buget, grupată pe granturi (proiectul vine din linie). */
export function BudgetLineSelect({
  grants,
  value,
  onChange,
  disabled,
  label,
}: {
  grants: Grant[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <select aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      <option value="">—</option>
      {grants.map((g) => (
        <optgroup key={g.id} label={`${g.code} ${g.title}`}>
          {g.budget_lines.map((l) => (
            <option key={l.id} value={l.id}>
              {g.code} / {l.code} {l.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
