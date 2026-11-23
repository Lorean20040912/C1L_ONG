import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { GrantPurchase } from "../../api/fix6";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money } from "../../lib/format";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

/** Achiziții pe granturi: rândurile facturilor înregistrate, pe grant și linie de buget. */
export function GrantPurchases() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [grantId, setGrantId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<GrantPurchase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (from && to && from > to) {
      setError("Data de început depășește data de sfârșit");
      return;
    }
    setError(null);
    const q = new URLSearchParams();
    if (grantId) q.set("grant_id", grantId);
    if (from) q.set("date_from", from);
    if (to) q.set("date_to", to);
    api<GrantPurchase[]>(`/organizations/${orgId}/reports/grant-purchases?${q}`)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [orgId, grantId, from, to]);
  useEffect(load, [load]);

  const total = (rows ?? []).reduce((s, r) => s + Number(r.amount), 0);
  const byGrant = new Map<string, number>();
  for (const r of rows ?? []) byGrant.set(r.grant_code, (byGrant.get(r.grant_code) ?? 0) + Number(r.amount));

  return (
    <>
      <h1>Achiziții pe granturi</h1>
      <div className="bar">
        <label>
          Grant{" "}
          <select value={grantId} onChange={(e) => setGrantId(e.target.value)} aria-label="Grant">
            <option value="">toate</option>
            {catalogs.grants.map((g) => (
              <option key={g.id} value={g.id}>
                {g.code} {g.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          De la <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          Până la <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      <Messages error={error} info={null} />
      {rows && (
        <table className="grid">
          <thead>
            <tr>
              <th>Grant</th>
              <th>Linia de buget</th>
              <th>Data</th>
              <th>Factura</th>
              <th>Furnizorul</th>
              <th>Denumirea</th>
              <th className="num">Suma</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.document_id}:${i}`}>
                <td>{r.grant_code}</td>
                <td>{r.budget_line}</td>
                <td>{day(r.doc_date)}</td>
                <td>
                  <button
                    className="link"
                    onClick={() => openTab({ id: `invoice:${r.document_id}`, title: `Factura ${r.doc_number ?? ""}`.trim(), kind: "invoice", params: { documentId: r.document_id } })}
                  >
                    {r.doc_number || "fără număr"}
                  </button>
                </td>
                <td>{r.counterparty}</td>
                <td>{r.description}</td>
                <td className="num">{money(r.amount)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  Nu sunt achiziții înregistrate pe linii de buget în perioada aleasă.
                </td>
              </tr>
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              {[...byGrant.entries()].map(([code, sum]) => (
                <tr key={code}>
                  <td colSpan={6}>Total {code}</td>
                  <td className="num">{money(sum)}</td>
                </tr>
              ))}
              <tr>
                <td colSpan={6}>
                  <b>Total</b>
                </td>
                <td className="num">
                  <b>{money(total)}</b>
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      )}
    </>
  );
}
