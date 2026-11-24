import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Department } from "../../api/fix6";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const EMPTY = { name: "", parent_id: "", cuatm: "" };

/** Subdiviziuni: ierarhia filialelor / birourilor; codul CUATM al localității intră în anexa IPC21. */
export function DepartmentsScreen() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<Department[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState<string | null>(null);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/departments`;

  const load = useCallback(() => {
    api<Department[]>(base).then(setRows).catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  // lista în ordine ierarhică, cu adâncimea pentru indentare
  const tree = useMemo(() => {
    const out: { d: Department; depth: number }[] = [];
    const walk = (parent: string | null, depth: number, seen: Set<string>) => {
      for (const d of rows.filter((r) => r.parent_id === parent)) {
        if (seen.has(d.id)) continue;
        seen.add(d.id);
        out.push({ d, depth });
        walk(d.id, depth + 1, seen);
      }
    };
    const ids = new Set(rows.map((r) => r.id));
    walk(null, 0, new Set());
    for (const r of rows) if (r.parent_id && !ids.has(r.parent_id)) out.push({ d: r, depth: 0 });
    return out;
  }, [rows]);

  const save = () =>
    run(async () => {
      if (form.name.trim().length < 2) throw new Error("Completați denumirea");
      if (form.cuatm && !/^\d{7}$/.test(form.cuatm)) throw new Error("Codul CUATM are 7 cifre");
      await api(editId ? `${base}/${editId}` : base, {
        method: editId ? "PUT" : "POST",
        body: { name: form.name.trim(), parent_id: form.parent_id || null, cuatm: form.cuatm || null },
      });
      setForm(EMPTY);
      setEditId(null);
      load();
      return "Subdiviziunea a fost salvată.";
    });
  const remove = (d: Department) =>
    run(async () => {
      if (!window.confirm(`Ștergeți subdiviziunea „${d.name}”?`)) return;
      await api(`${base}/${d.id}`, { method: "DELETE" });
      load();
      return "Subdiviziunea a fost ștearsă.";
    });

  return (
    <>
      <h1>Subdiviziuni</h1>
      <ReadOnlyNote show={!editable} what="subdiviziunile le modifică contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Denumirea</th>
            <th>CUATM</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tree.map(({ d, depth }) => (
            <tr key={d.id}>
              <td style={{ paddingLeft: 8 + depth * 20 }}>{d.name}</td>
              <td>{d.cuatm}</td>
              <td>
                {editable && (
                  <>
                    <button className="b" onClick={() => { setEditId(d.id); setForm({ name: d.name, parent_id: d.parent_id ?? "", cuatm: d.cuatm ?? "" }); }}>
                      Modifică
                    </button>{" "}
                    <button className="b" onClick={() => remove(d)} disabled={busy}>
                      Șterge
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                Nu sunt subdiviziuni.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{editId ? "Modificare" : "Subdiviziune nouă"}</h2>
          <div className="form">
            <label htmlFor="sd-name">Denumirea</label>
            <input id="sd-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label htmlFor="sd-parent">Subordonată lui</label>
            <select id="sd-parent" value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })}>
              <option value="">— nivel superior —</option>
              {rows.filter((r) => r.id !== editId).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <label htmlFor="sd-cuatm">Cod CUATM</label>
            <input id="sd-cuatm" value={form.cuatm} maxLength={7} onChange={(e) => setForm({ ...form, cuatm: e.target.value })} />
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
