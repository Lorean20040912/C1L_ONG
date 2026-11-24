import { useState } from "react";
import { api } from "../api/client";
import type { Counterparty } from "../api/types";
import { useShell } from "../shell/tabs";

/** Selecția contrapartidei, cu crearea rapidă a uneia noi (ca „Creare” din câmpul 1C). */
export function CounterpartyField({
  id,
  value,
  options,
  onChange,
  onCreated,
  disabled,
}: {
  id: string;
  value: string;
  options: Counterparty[];
  onChange: (id: string) => void;
  onCreated: (cp: Counterparty) => void;
  disabled?: boolean;
}) {
  const { orgId } = useShell();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [idno, setIdno] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setError(null);
    try {
      const cp = await api<Counterparty>(`/organizations/${orgId}/counterparties`, {
        method: "POST",
        body: { name: name.trim(), idno: idno.trim() || null },
      });
      onCreated(cp);
      setCreating(false);
      setName("");
      setIdno("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div>
      <div className="ref">
        <select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          <option value="">— alegeți —</option>
          {options.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.idno ? ` (IDNO ${c.idno})` : ""}
            </option>
          ))}
        </select>
        {!disabled && (
          <button type="button" className="b" onClick={() => setCreating((c) => !c)} title="Contrapartidă nouă">
            +
          </button>
        )}
      </div>
      {creating && (
        <div className="card inline-form">
          {error && <div className="error">{error}</div>}
          <input aria-label="Denumirea contrapartidei" placeholder="Denumirea" value={name} onChange={(e) => setName(e.target.value)} />
          <input aria-label="IDNO" placeholder="IDNO (13 cifre)" value={idno} onChange={(e) => setIdno(e.target.value)} inputMode="numeric" />
          <button type="button" className="b primary" disabled={!name.trim()} onClick={create}>
            Creează
          </button>
        </div>
      )}
    </div>
  );
}
