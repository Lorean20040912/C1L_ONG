import { useState } from "react";
import { api, downloadFile } from "../../api/client";
import type { DonorPackage as Pkg } from "../../api/fix6";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Pachet pentru donator: pe fiecare linie de buget — execuția și documentele justificative (cele fără scan sunt semnalate). */
export function DonorPackage() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [grantId, setGrantId] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [pkg, setPkg] = useState<Pkg | null>(null);
  const { busy, error, run } = useAction();
  const q = dateTo ? `?date_to=${dateTo}` : "";

  const build = () =>
    run(async () => {
      if (!grantId) throw new Error("Alegeți grantul");
      setPkg(await api<Pkg>(`/organizations/${orgId}/grants/${grantId}/donor-package${q}`));
    });
  const exportCsv = () =>
    run(async () => {
      await downloadFile(`/organizations/${orgId}/grants/${grantId}/donor-package/csv${q}`, "pachet-donator.csv");
    });

  return (
    <>
      <h1>Pachet pentru donator</h1>
      <div className="bar">
        <label>
          Grant{" "}
          <select value={grantId} onChange={(e) => { setGrantId(e.target.value); setPkg(null); }} aria-label="Grant">
            <option value="">— alegeți —</option>
            {catalogs.grants.map((g) => (
              <option key={g.id} value={g.id}>
                {g.code} {g.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Cheltuieli până la <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <button className="b primary" onClick={build} disabled={busy || !grantId}>
          Formează pachetul
        </button>
        <button className="b" onClick={exportCsv} disabled={busy || !pkg}>
          Descarcă CSV
        </button>
      </div>
      <Messages error={error} info={null} />
      {pkg && (
        <>
          <h2>
            {pkg.grant_code} {pkg.title}
          </h2>
          <div className={pkg.missing_files ? "hint warn" : "hint"}>
            Planificat {money(pkg.total_planned)}, cheltuit {money(pkg.total_spent)} {pkg.currency}.{" "}
            {pkg.missing_files ? `${pkg.missing_files} documente justificative nu au scan atașat.` : "Toate documentele au scan atașat."}
          </div>
          <table className="grid">
            <thead>
              <tr>
                <th>Linia de buget</th>
                <th>Documentul</th>
                <th>Data</th>
                <th>Furnizorul</th>
                <th className="num">Suma</th>
                <th>Scan</th>
              </tr>
            </thead>
            <tbody>
              {pkg.lines.flatMap((l) => [
                <tr key={l.budget_line_id}>
                  <td>
                    <b>
                      {l.code} {l.name}
                    </b>
                  </td>
                  <td colSpan={3}>
                    planificat {money(l.planned)} · rest {money(l.remaining)}
                  </td>
                  <td className="num">
                    <b>{money(l.spent)}</b>
                  </td>
                  <td>{l.missing_files ? `${l.missing_files} lipsă` : ""}</td>
                </tr>,
                ...l.documents.map((d) => (
                  <tr key={`${l.budget_line_id}:${d.document_id}`}>
                    <td />
                    <td>
                      <button className="link" onClick={() => openTab({ id: `dtkt:${d.document_id}`, title: `Dt/Kt ${d.doc_number ?? ""}`.trim(), kind: "dtkt", params: { documentId: d.document_id } })}>
                        {d.doc_number || "fără număr"}
                      </button>
                    </td>
                    <td>{day(d.doc_date)}</td>
                    <td>{d.counterparty}</td>
                    <td className="num">{money(d.amount)}</td>
                    <td>{d.has_file ? "da" : <span className="warn">lipsește</span>}</td>
                  </tr>
                )),
              ])}
              {pkg.lines.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    Grantul nu are linii de buget.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
