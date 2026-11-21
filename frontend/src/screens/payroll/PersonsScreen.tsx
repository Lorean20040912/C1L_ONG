import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Person } from "../../api/payroll";
import { day } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const EMPTY = { full_name: "", idnp: "", birth_date: "", cpas: "" };

/** Catalogul „Persoane fizice”: angajați, prestatori, locatori (IDNP criptat în BD). */
export function PersonsScreen() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<Person[] | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY);
  const { busy, error, info, run } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/persons`;

  const load = useCallback(() => {
    api<Person[]>(base).then(setRows, () => setRows([]));
  }, [base]);
  useEffect(load, [load]);

  const edit = (p: Person | null) => {
    setEditId(p?.id ?? null);
    setForm(EMPTY);
    if (!p) return;
    // IDNP-ul complet se cere doar pentru formularul de editare
    run(async () => {
      const full = await api<Person>(`${base}/${p.id}`);
      setForm({ full_name: full.full_name, idnp: full.idnp ?? "", birth_date: full.birth_date ?? "", cpas: full.cpas ?? "" });
    });
  };

  const save = () =>
    run(async () => {
      const body = {
        full_name: form.full_name.trim(),
        idnp: form.idnp.trim(),
        birth_date: form.birth_date || null,
        cpas: form.cpas.trim() || null,
      };
      await api(editId ? `${base}/${editId}` : base, { method: editId ? "PUT" : "POST", body });
      edit(null);
      load();
      return "Persoana a fost salvată.";
    });

  const remove = (p: Person) =>
    run(async () => {
      if (!window.confirm(`Ștergeți persoana ${p.full_name}?`)) return;
      await api(`${base}/${p.id}`, { method: "DELETE" });
      load();
      return "Persoana a fost ștearsă.";
    });

  return (
    <>
      <h1>Persoane fizice</h1>
      <ReadOnlyNote show={!editable} what="persoanele le introduce contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Numele, prenumele</th>
            <th>IDNP</th>
            <th>CPAS</th>
            <th>Data nașterii</th>
            {editable && <th />}
          </tr>
        </thead>
        <tbody>
          {rows?.map((p) => (
            <tr key={p.id} onDoubleClick={() => editable && edit(p)}>
              <td>{p.full_name}</td>
              <td>{p.idnp_masked}</td>
              <td>{p.cpas}</td>
              <td>{day(p.birth_date)}</td>
              {editable && (
                <td>
                  <button className="b" onClick={() => edit(p)}>
                    Modifică
                  </button>{" "}
                  <button className="b" onClick={() => remove(p)} disabled={busy}>
                    Șterge
                  </button>
                </td>
              )}
            </tr>
          ))}
          {rows?.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Nu sunt persoane fizice.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{editId ? "Modificarea persoanei" : "Persoană nouă"}</h2>
          <div className="form">
            <label htmlFor="p-name">Numele, prenumele</label>
            <input id="p-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="Popescu Ion" />
            <label htmlFor="p-idnp">IDNP</label>
            <input id="p-idnp" value={form.idnp} maxLength={13} onChange={(e) => setForm({ ...form, idnp: e.target.value.replace(/\D/g, "") })} />
            <label htmlFor="p-cpas">CPAS</label>
            <input id="p-cpas" value={form.cpas} onChange={(e) => setForm({ ...form, cpas: e.target.value })} />
            <label htmlFor="p-birth">Data nașterii</label>
            <input id="p-birth" type="date" value={form.birth_date} onChange={(e) => setForm({ ...form, birth_date: e.target.value })} />
          </div>
          <div className="hint">Numele de familie se scrie primul: în plata cumulată destinația se scurtează la „Popescu I.” sau „Popescu”.</div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy || form.idnp.length !== 13 || form.full_name.trim().length < 2}>
              Salvează
            </button>
            {editId && (
              <button className="b" onClick={() => edit(null)}>
                Renunță
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}
