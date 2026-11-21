import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { EntryLine, PreviewLine } from "../api/types";
import { budgetLineLabel, grantLabel, useCatalogs } from "../catalog/useCatalogs";
import { onDocumentsChanged } from "../lib/events";
import { day, money } from "../lib/format";
import { useShell } from "../shell/tabs";

interface Row {
  date: string;
  debit: string;
  credit: string;
  amount: string;
  grant: string;
  source?: string;
}

/** Dt/Kt al documentului: înregistrările reale sau, dacă nu e înregistrat, previzualizarea după reguli. */
export function PostingView({ route, documentId, title }: { route: string; documentId: string; title: string }) {
  const { orgId } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [isPreview, setIsPreview] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const base = `/organizations/${orgId}`;
    try {
      const doc = await api<{ is_posted: boolean | null }>(`${base}/${route}/${documentId}`);
      if (doc.is_posted) {
        const code = new Map(catalogs.accounts.map((a) => [a.id, a.code]));
        const entries = await api<EntryLine[]>(`${base}/documents/${documentId}/entries`);
        setRows(
          entries.map((e) => ({
            date: e.entry_date,
            debit: code.get(e.debit_account_id) ?? "?",
            credit: code.get(e.credit_account_id) ?? "?",
            amount: e.amount,
            grant: e.budget_line_id ? budgetLineLabel(catalogs.grants, e.budget_line_id) : grantLabel(catalogs.grants, e.grant_id),
          })),
        );
        setIsPreview(false);
      } else {
        const preview = await api<PreviewLine[]>(`${base}/${route}/${documentId}/preview`, { method: "POST" });
        setRows(
          preview.map((p) => ({
            date: p.entry_date,
            debit: p.debit_account,
            credit: p.credit_account,
            amount: p.amount,
            grant: p.budget_line_id ? budgetLineLabel(catalogs.grants, p.budget_line_id) : grantLabel(catalogs.grants, p.grant_id),
            source: p.source_ref,
          })),
        );
        setIsPreview(true);
      }
    } catch (e) {
      setRows([]);
      setError((e as Error).message);
    }
  }, [orgId, route, documentId, catalogs]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => onDocumentsChanged(route, load), [route, load]);

  const total = (rows ?? []).reduce((s, r) => s + Number(r.amount), 0);

  return (
    <>
      <h1>Înregistrări contabile ({title})</h1>
      <div className="bar">
        <button className="b" onClick={load}>
          Actualizează
        </button>
      </div>
      {isPreview && <div className="hint">Documentul nu este înregistrat: acestea sunt înregistrările pe care le-ar genera regulile.</div>}
      {error && <div className="error">{error}</div>}
      {rows && rows.length > 0 && (
        <>
          <table className="grid">
            <thead>
              <tr>
                <th>Data</th>
                <th>Dt</th>
                <th>Kt</th>
                <th className="num">Suma</th>
                <th>Grant / linie</th>
                {isPreview && <th>Sursa regulii</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{day(r.date)}</td>
                  <td>{r.debit}</td>
                  <td>{r.credit}</td>
                  <td className="num">{money(r.amount)}</td>
                  <td>{r.grant}</td>
                  {isPreview && <td className="muted">{r.source}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="totals">
            <span>
              Total Dt = Kt: <b>{money(total)}</b>
            </span>
          </div>
        </>
      )}
    </>
  );
}
