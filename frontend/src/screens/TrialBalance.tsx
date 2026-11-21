import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useCatalogs } from "../catalog/useCatalogs";
import { onDocumentsChanged } from "../lib/events";
import { money } from "../lib/format";
import { useShell } from "../shell/tabs";

interface Row {
  account_id: string;
  code: string;
  name: string;
  opening_debit: string;
  opening_credit: string;
  turnover_debit: string;
  turnover_credit: string;
  closing_debit: string;
  closing_credit: string;
}
type Key = Exclude<keyof Row, "account_id" | "code" | "name">;
const COLS: Key[] = ["opening_debit", "opening_credit", "turnover_debit", "turnover_credit", "closing_debit", "closing_credit"];

/** Balanța de verificare (OSV): sold inițial, rulaje, sold final pe conturi. */
export function TrialBalance() {
  const { orgId } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const year = new Date().getFullYear();
  const [from, setFrom] = useState(`${year}-01`);
  const [to, setTo] = useState(`${year}-12`);
  const [grantId, setGrantId] = useState("");
  const [data, setData] = useState<{ rows: Row[]; totals: Record<Key, string> } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams({ date_from: `${from}-01`, date_to: `${to}-01` });
    if (grantId) params.set("grant_id", grantId);
    setError(null);
    api<{ rows: Row[]; totals: Record<Key, string> }>(`/organizations/${orgId}/reports/trial-balance?${params}`)
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [orgId, from, to, grantId]);

  useEffect(load, [load]);
  useEffect(() => onDocumentsChanged("invoices", load), [load]);

  return (
    <>
      <h1>Balanța de verificare (OSV)</h1>
      <div className="bar">
        <input className="b" type="month" aria-label="De la" value={from} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        <span className="muted">—</span>
        <input className="b" type="month" aria-label="Până la" value={to} onChange={(e) => e.target.value && setTo(e.target.value)} />
        <select className="b" aria-label="Grantul" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
          <option value="">Toate granturile</option>
          {catalogs.grants.map((g) => (
            <option key={g.id} value={g.id}>
              {g.code}
            </option>
          ))}
        </select>
        <button className="b primary" onClick={load}>
          Generează
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {data && (
        <table className="grid">
          <thead>
            <tr>
              <th rowSpan={2}>Cont</th>
              <th rowSpan={2}>Denumire</th>
              <th colSpan={2} className="num">Sold inițial</th>
              <th colSpan={2} className="num">Rulaj</th>
              <th colSpan={2} className="num">Sold final</th>
            </tr>
            <tr>
              {COLS.map((c, i) => (
                <th key={c} className="num">{i % 2 ? "Kt" : "Dt"}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.account_id}>
                <td>{r.code}</td>
                <td>{r.name}</td>
                {COLS.map((c) => (
                  <td key={c} className="num">{Number(r[c]) ? money(r[c]) : ""}</td>
                ))}
              </tr>
            ))}
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">Nu sunt înregistrări în perioadă.</td>
              </tr>
            )}
            <tr className="total-row">
              <td colSpan={2}>Total</td>
              {COLS.map((c) => (
                <td key={c} className="num">{money(data.totals[c])}</td>
              ))}
            </tr>
          </tbody>
        </table>
      )}
    </>
  );
}
