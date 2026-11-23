import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { BankFormat } from "../../api/types";
import { useAction } from "../../lib/useAction";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const FILE_TYPES = ["txt", "dbf", "dbo", "xml", "csv"];
const EMPTY = { bank_name: "", file_type: "csv", direction: "import" as BankFormat["direction"], encoding: "cp1251", layout: "{}" };

/** Profiluri bănci: formatele de import al extraselor și de export al ordinelor de plată (cele standard se copiază, nu se modifică). */
export function BankProfiles() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<BankFormat[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState<string | null>(null);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/bank-formats`;

  const load = useCallback(() => {
    api<BankFormat[]>(base).then(setRows).catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const fill = (f: BankFormat, copy: boolean) => {
    setEditId(copy ? null : f.id);
    setForm({ bank_name: copy ? `${f.bank_name} (copie)` : f.bank_name, file_type: f.file_type, direction: f.direction, encoding: f.encoding, layout: JSON.stringify(f.layout, null, 2) });
  };

  const save = () =>
    run(async () => {
      if (!form.bank_name.trim()) throw new Error("Completați denumirea băncii");
      let layout: unknown;
      try {
        layout = JSON.parse(form.layout);
      } catch {
        throw new Error("Structura fișierului (layout) nu este JSON valid");
      }
      if (layout === null || typeof layout !== "object" || Array.isArray(layout)) throw new Error("Structura fișierului trebuie să fie un obiect JSON");
      await api(editId ? `${base}/${editId}` : base, {
        method: editId ? "PUT" : "POST",
        body: { bank_name: form.bank_name.trim(), file_type: form.file_type, direction: form.direction, encoding: form.encoding.trim() || "cp1251", layout },
      });
      setForm(EMPTY);
      setEditId(null);
      load();
      return "Profilul a fost salvat.";
    });
  const remove = (f: BankFormat) =>
    run(async () => {
      if (!window.confirm(`Ștergeți profilul „${f.bank_name}”?`)) return;
      await api(`${base}/${f.id}`, { method: "DELETE" });
      load();
      return "Profilul a fost șters.";
    });

  return (
    <>
      <h1>Profiluri bănci</h1>
      <ReadOnlyNote show={!editable} what="profilurile le modifică administratorul sau contabilul-șef" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Banca</th>
            <th>Direcția</th>
            <th>Fișier</th>
            <th>Codificare</th>
            <th>Origine</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => (
            <tr key={f.id}>
              <td>{f.bank_name}</td>
              <td>{f.direction === "import" ? "import extras" : "export ordine"}</td>
              <td>{f.file_type}</td>
              <td>{f.encoding}</td>
              <td>{f.is_standard ? "standard" : "al organizației"}</td>
              <td>
                {editable && (
                  <>
                    {!f.is_standard && (
                      <button className="b" onClick={() => fill(f, false)}>
                        Modifică
                      </button>
                    )}{" "}
                    <button className="b" onClick={() => fill(f, true)}>
                      Copiază
                    </button>{" "}
                    {!f.is_standard && (
                      <button className="b" onClick={() => remove(f)} disabled={busy}>
                        Șterge
                      </button>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                Nu sunt profiluri.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{editId ? "Modificare profil" : "Profil nou"}</h2>
          <div className="form">
            <label htmlFor="bp-name">Banca</label>
            <input id="bp-name" value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} />
            <label htmlFor="bp-dir">Direcția</label>
            <select id="bp-dir" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as BankFormat["direction"] })}>
              <option value="import">import extras</option>
              <option value="export">export ordine de plată</option>
            </select>
            <label htmlFor="bp-type">Tip fișier</label>
            <select id="bp-type" value={form.file_type} onChange={(e) => setForm({ ...form, file_type: e.target.value })}>
              {FILE_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            <label htmlFor="bp-enc">Codificare</label>
            <input id="bp-enc" value={form.encoding} onChange={(e) => setForm({ ...form, encoding: e.target.value })} />
            <label htmlFor="bp-layout">Structura (JSON)</label>
            <textarea id="bp-layout" rows={10} spellCheck={false} value={form.layout} onChange={(e) => setForm({ ...form, layout: e.target.value })} />
          </div>
          <div className="hint">Cel mai simplu: „Copiază” un profil standard și ajustați câmpurile din structură.</div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Salvează
            </button>
            {(editId || form.bank_name) && (
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
