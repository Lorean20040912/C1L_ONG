import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CalcType } from "../../api/fix6";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const EMPTY = { code: "", name: "", kind: "accrual" as CalcType["kind"], taxable: true, social_base: true, is_active: true };

/** Tipuri de calcul salarial: câștiguri (acumulări) și rețineri, cu bazele de impozitare. */
export function CalcTypes() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<CalcType[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState<string | null>(null);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/payroll-calc-types`;

  const load = useCallback(() => {
    api<CalcType[]>(base).then(setRows).catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const save = () =>
    run(async () => {
      if (!form.code.trim() || form.name.trim().length < 2) throw new Error("Completați codul și denumirea");
      const body = { ...form, code: form.code.trim(), name: form.name.trim() };
      await api(editId ? `${base}/${editId}` : base, { method: editId ? "PUT" : "POST", body });
      setForm(EMPTY);
      setEditId(null);
      load();
      return "Tipul de calcul a fost salvat.";
    });
  const remove = (r: CalcType) =>
    run(async () => {
      if (!window.confirm(`Ștergeți tipul „${r.name}”?`)) return;
      await api(`${base}/${r.id}`, { method: "DELETE" });
      load();
      return "Tipul de calcul a fost șters.";
    });
  const standard = () =>
    run(async () => {
      await api(`${base}/standard`, { method: "POST" });
      load();
      return "Tipurile uzuale au fost adăugate.";
    });
  const edit = (r: CalcType) => {
    setEditId(r.id);
    setForm({ code: r.code, name: r.name, kind: r.kind, taxable: r.taxable, social_base: r.social_base, is_active: r.is_active });
  };

  return (
    <>
      <h1>Tipuri de calcul</h1>
      <ReadOnlyNote show={!editable} what="tipurile de calcul le modifică administratorul sau contabilul-șef" />
      <Messages error={error} info={info} />
      {editable && (
        <div className="bar">
          <button className="b" onClick={standard} disabled={busy}>
            Adaugă tipurile uzuale
          </button>
        </div>
      )}
      <table className="grid">
        <thead>
          <tr>
            <th>Cod</th>
            <th>Denumirea</th>
            <th>Felul</th>
            <th>Impozabil</th>
            <th>Bază contribuții</th>
            <th>Activ</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.code}</td>
              <td>{r.name}</td>
              <td>{r.kind === "accrual" ? "câștig" : "reținere"}</td>
              <td>{r.taxable ? "da" : "nu"}</td>
              <td>{r.social_base ? "da" : "nu"}</td>
              <td>{r.is_active ? "da" : "nu"}</td>
              <td>
                {editable && (
                  <>
                    <button className="b" onClick={() => edit(r)}>
                      Modifică
                    </button>{" "}
                    <button className="b" onClick={() => remove(r)} disabled={busy}>
                      Șterge
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                Nu sunt tipuri de calcul. Folosiți „Adaugă tipurile uzuale”.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{editId ? "Modificare" : "Tip nou"}</h2>
          <div className="form">
            <label htmlFor="ct-code">Cod</label>
            <input id="ct-code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
            <label htmlFor="ct-name">Denumirea</label>
            <input id="ct-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label htmlFor="ct-kind">Felul</label>
            <select id="ct-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as CalcType["kind"] })}>
              <option value="accrual">câștig (acumulare)</option>
              <option value="deduction">reținere</option>
            </select>
            <label htmlFor="ct-tax">Impozabil</label>
            <input id="ct-tax" type="checkbox" checked={form.taxable} onChange={(e) => setForm({ ...form, taxable: e.target.checked })} />
            <label htmlFor="ct-soc">Bază pentru contribuții</label>
            <input id="ct-soc" type="checkbox" checked={form.social_base} onChange={(e) => setForm({ ...form, social_base: e.target.checked })} />
            <label htmlFor="ct-act">Activ</label>
            <input id="ct-act" type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          </div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Salvează
            </button>
            {editId && (
              <button className="b" onClick={() => { setEditId(null); setForm(EMPTY); }}>
                Renunță
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}
