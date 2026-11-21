import { useState } from "react";
import { api } from "../api/client";
import { useCatalogs } from "../catalog/useCatalogs";
import { notifyDocumentsChanged } from "../lib/events";
import { money, parseAmount, today } from "../lib/format";
import { useAction } from "../lib/useAction";
import { useShell } from "../shell/tabs";

interface Row {
  key: number;
  debit: string;
  credit: string;
  amount: string;
  grant: string;
  description: string;
}
let n = 0;
const empty = (): Row => ({ key: ++n, debit: "", credit: "", amount: "", grant: "", description: "" });

/** Operațiune contabilă manuală: rânduri Dt/Kt scrise direct (corecții, solduri, cazuri fără document dedicat). */
export function ManualOperation({ tabId }: { tabId: string }) {
  const { orgId, closeTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [number, setNumber] = useState("");
  const [date, setDate] = useState(today());
  const [rows, setRows] = useState<Row[]>([empty()]);
  const [posted, setPosted] = useState(false);
  const { busy, error, info, run } = useAction();
  const accounts = catalogs.accounts.filter((a) => !a.is_group);
  const set = (k: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === k ? { ...r, ...patch } : r)));
  const total = rows.reduce((s, r) => s + Number(parseAmount(r.amount) ?? 0), 0);

  const post = (close: boolean) =>
    run(async () => {
      const lines = rows.map((r, i) => {
        const amount = parseAmount(r.amount);
        if (!r.debit || !r.credit || !amount) throw new Error(`Rândul ${i + 1}: completați Dt, Kt și suma`);
        return { debit_account_id: r.debit, credit_account_id: r.credit, amount, grant_id: r.grant || null, description: r.description || null };
      });
      const base = `/organizations/${orgId}/documents`;
      const doc = await api<{ id: string }>(base, { method: "POST", body: { type: "other", doc_number: number || null, doc_date: date } });
      // dacă înregistrarea e refuzată, documentul rămâne neînregistrat și apare în verificările lunii
      await api(`${base}/${doc.id}/post`, { method: "POST", body: { lines } });
      setPosted(true);
      notifyDocumentsChanged("invoices");
      if (close) closeTab(tabId, { force: true });
      return "Operațiunea a fost înregistrată.";
    });

  return (
    <>
      <h1>Operațiune manuală {posted && <span className="badge ok">înregistrată</span>}</h1>
      <div className="bar">
        <button className="b primary" disabled={busy || posted} onClick={() => post(true)}>
          Înregistrează și închide
        </button>
        <button className="b" disabled={busy || posted} onClick={() => post(false)}>
          Înregistrează
        </button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {info && <div className="hint">{info}</div>}
      <div className="form">
        <label htmlFor={`${tabId}-nr`}>Număr</label>
        <input id={`${tabId}-nr`} value={number} disabled={posted} onChange={(e) => setNumber(e.target.value)} />
        <label htmlFor={`${tabId}-d`}>Data</label>
        <input id={`${tabId}-d`} type="date" value={date} disabled={posted} onChange={(e) => setDate(e.target.value)} />
      </div>
      <table className="grid edit">
        <thead>
          <tr>
            <th>N</th>
            <th>Dt</th>
            <th>Kt</th>
            <th className="num">Suma</th>
            <th>Grant</th>
            <th>Conținut</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.key}>
              <td>{i + 1}</td>
              {(["debit", "credit"] as const).map((side) => (
                <td key={side}>
                  <select aria-label={`${side === "debit" ? "Dt" : "Kt"} rând ${i + 1}`} value={r[side]} disabled={posted} onChange={(e) => set(r.key, { [side]: e.target.value })}>
                    <option value="">—</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id} title={a.name}>{a.code}</option>
                    ))}
                  </select>
                </td>
              ))}
              <td className="num">
                <input aria-label={`Suma rând ${i + 1}`} className="num" value={r.amount} disabled={posted} onChange={(e) => set(r.key, { amount: e.target.value })} />
              </td>
              <td>
                <select aria-label={`Grant rând ${i + 1}`} value={r.grant} disabled={posted} onChange={(e) => set(r.key, { grant: e.target.value })}>
                  <option value="">—</option>
                  {catalogs.grants.map((g) => (
                    <option key={g.id} value={g.id}>{g.code}</option>
                  ))}
                </select>
              </td>
              <td>
                <input aria-label={`Conținut rând ${i + 1}`} value={r.description} disabled={posted} onChange={(e) => set(r.key, { description: e.target.value })} />
              </td>
              <td>
                {!posted && rows.length > 1 && (
                  <button className="x-btn" aria-label={`Șterge rândul ${i + 1}`} onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>×</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!posted && (
        <div className="bar" style={{ marginTop: 8 }}>
          <button className="b" onClick={() => setRows((rs) => [...rs, empty()])}>Adaugă rând</button>
        </div>
      )}
      <div className="totals"><span>Total Dt = Kt: <b>{money(total)}</b></span></div>
    </>
  );
}
