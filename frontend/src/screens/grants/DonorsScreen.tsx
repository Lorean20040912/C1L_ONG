import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Donor } from "../../api/grants";
import { useAction } from "../../lib/useAction";
import { Messages, ReadOnlyNote } from "../admin/Messages";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";

/** Catalogul donatorilor (folosit și de ONG17, rândurile 013 / 019). */
export function DonorsScreen() {
  const { orgId, role } = useShell();
  const [donors, setDonors] = useState<Donor[]>([]);
  const [name, setName] = useState("");
  const [country, setCountry] = useState("");
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/donors`;

  const load = useCallback(() => {
    api<Donor[]>(base)
      .then(setDonors)
      .catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const add = () =>
    run(async () => {
      await api(base, { method: "POST", body: { name: name.trim(), country: country.trim() || null } });
      setName("");
      setCountry("");
      load();
      return "Donatorul a fost adăugat.";
    });
  const remove = (d: Donor) =>
    run(async () => {
      await api(`${base}/${d.id}`, { method: "DELETE" });
      load();
      return "Donatorul a fost șters.";
    });

  return (
    <>
      <h1>Donatori</h1>
      <ReadOnlyNote show={!editable} what="donatorii îi adaugă contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Denumirea</th>
            <th>Țara</th>
            <th className="num">Granturi</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {donors.map((d) => (
            <tr key={d.id}>
              <td>{d.name}</td>
              <td>{d.country}</td>
              <td className="num">{d.grants_count}</td>
              <td>
                {editable && d.grants_count === 0 && (
                  <button className="b" onClick={() => remove(d)} disabled={busy}>
                    Șterge
                  </button>
                )}
              </td>
            </tr>
          ))}
          {donors.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                Nu sunt donatori.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>Donator nou</h2>
          <div className="form">
            <label htmlFor="d-name">Denumirea</label>
            <input id="d-name" value={name} onChange={(e) => setName(e.target.value)} />
            <label htmlFor="d-country">Țara</label>
            <input id="d-country" value={country} onChange={(e) => setCountry(e.target.value)} />
          </div>
          <div className="bar">
            <button className="b primary" onClick={add} disabled={busy || !name.trim()}>
              Adaugă donatorul
            </button>
          </div>
        </section>
      )}
    </>
  );
}
