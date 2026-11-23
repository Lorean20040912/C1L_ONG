import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CounterpartyFull } from "../../api/fix6";
import { refreshCatalogs } from "../../catalog/useCatalogs";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

const EMPTY = { name: "", idno: "", vat_code: "", bank_code: "", address: "" };

/** Contrapartide: furnizori, donatori, clienți — căutare după denumire sau IDNO, adăugare, modificare, ștergere. */
export function CounterpartiesScreen() {
  const { orgId, role } = useShell();
  const [rows, setRows] = useState<CounterpartyFull[]>([]);
  const [q, setQ] = useState("");
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState<string | null>(null);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/counterparties`;

  const load = useCallback(() => {
    api<CounterpartyFull[]>(`${base}${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [base, q, setError]);
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  const save = () =>
    run(async () => {
      const name = form.name.trim();
      const idno = form.idno.trim();
      if (!name) throw new Error("Completați denumirea");
      if (idno && !/^\d{13}$/.test(idno)) throw new Error("IDNO are 13 cifre");
      const body = {
        name, idno: idno || null, vat_code: form.vat_code.trim() || null,
        bank_code: form.bank_code.trim() || null, address: form.address.trim() || null,
      };
      await api(editId ? `${base}/${editId}` : base, { method: editId ? "PUT" : "POST", body });
      setForm(EMPTY);
      setEditId(null);
      refreshCatalogs(orgId);
      load();
      return "Contrapartida a fost salvată.";
    });
  const remove = (c: CounterpartyFull) =>
    run(async () => {
      if (!window.confirm(`Ștergeți contrapartida „${c.name}”?`)) return;
      await api(`${base}/${c.id}`, { method: "DELETE" });
      refreshCatalogs(orgId);
      load();
      return "Contrapartida a fost ștearsă.";
    });
  const edit = (c: CounterpartyFull) => {
    setEditId(c.id);
    setForm({ name: c.name, idno: c.idno ?? "", vat_code: c.vat_code ?? "", bank_code: c.bank_code ?? "", address: c.address ?? "" });
  };

  return (
    <>
      <h1>Contrapartide</h1>
      <ReadOnlyNote show={!editable} what="contrapartidele le modifică contabilul" />
      <div className="bar">
        <input placeholder="Căutare după denumire sau IDNO" aria-label="Căutare contrapartide" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Denumirea</th>
            <th>IDNO</th>
            <th>Cod TVA</th>
            <th>Cod bancă</th>
            <th>Adresa</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td>{c.idno}</td>
              <td>{c.vat_code}</td>
              <td>{c.bank_code}</td>
              <td>{c.address}</td>
              <td>
                {editable && (
                  <>
                    <button className="b" onClick={() => edit(c)}>
                      Modifică
                    </button>{" "}
                    <button className="b" onClick={() => remove(c)} disabled={busy}>
                      Șterge
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                Nu sunt contrapartide.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>{editId ? "Modificare" : "Contrapartidă nouă"}</h2>
          <div className="form">
            <label htmlFor="cp-name">Denumirea</label>
            <input id="cp-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label htmlFor="cp-idno">IDNO</label>
            <input id="cp-idno" value={form.idno} maxLength={13} onChange={(e) => setForm({ ...form, idno: e.target.value })} />
            <label htmlFor="cp-vat">Cod TVA</label>
            <input id="cp-vat" value={form.vat_code} onChange={(e) => setForm({ ...form, vat_code: e.target.value })} />
            <label htmlFor="cp-bank">Cod bancă</label>
            <input id="cp-bank" value={form.bank_code} onChange={(e) => setForm({ ...form, bank_code: e.target.value })} />
            <label htmlFor="cp-addr">Adresa</label>
            <input id="cp-addr" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
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
