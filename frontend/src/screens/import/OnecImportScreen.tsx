import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { readXmlFile } from "../../lib/xmlFile";
import { useAction } from "../../lib/useAction";
import { day, money } from "../../lib/format";
import { ADMIN_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

interface Difference {
  account_code: string;
  onec: string;
  app: string;
  difference: string;
}
interface Reconciliation {
  date: string;
  accounts: number;
  matched: number;
  differences: Difference[];
  ok: boolean;
}
interface Run {
  id: string;
  status: string | null;
  stats: Record<string, Record<string, number | string>> | null;
  reconciliation: Reconciliation | null;
  started_at: string | null;
}
interface OpeningBalance {
  account_code: string;
  account_name: string;
  balance_date: string;
  debit: string;
  credit: string;
}

const STATUS: Record<string, string> = { pending: "în așteptare", running: "în lucru", done: "terminat", failed: "eșuat" };

/** Migrarea din 1C: încărcarea exportului XML, istoricul rulărilor, soldurile inițiale și reconcilierea balanței. */
export function OnecImportScreen() {
  const { orgId, role } = useShell();
  const [runs, setRuns] = useState<Run[]>([]);
  const [balances, setBalances] = useState<OpeningBalance[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const { busy, error, info, run } = useAction();
  const allowed = can(role, ADMIN_ROLES);
  const base = `/organizations/${orgId}/onec-import`;

  const load = useCallback(async () => {
    setRuns(await api<Run[]>(`${base}/runs`).catch(() => []));
    setBalances(await api<OpeningBalance[]>(`${base}/opening-balances`).catch(() => []));
  }, [base]);
  useEffect(() => {
    load();
  }, [load]);

  const upload = () =>
    run(async () => {
      if (!file) throw new Error("Alegeți fișierul XML exportat din 1C");
      const xml = await readXmlFile(file);
      const res = await api<Run>(`${base}/runs`, { method: "POST", body: { xml } }).finally(load);
      const rec = res.reconciliation;
      return rec
        ? rec.ok
          ? `Import terminat. Reconciliere: toate cele ${rec.accounts} conturi coincid la ${day(rec.date)}.`
          : `Import terminat. Reconciliere: ${rec.differences.length} conturi cu diferențe.`
        : "Import terminat (fără balanță de control în fișier).";
    });

  const last = runs.find((r) => r.reconciliation)?.reconciliation;

  return (
    <>
      <h1>Import din 1C</h1>
      <Messages error={error} info={info} />
      <ReadOnlyNote show={!allowed} what="importul este permis administratorului și contabilului-șef" />
      {allowed && (
        <div className="form">
          <label htmlFor="o-file">Export XML din 1C</label>
          <input id="o-file" type="file" accept=".xml,text/xml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="bar">
            <button className="b primary" disabled={busy || !file} onClick={upload}>
              Importă
            </button>
          </div>
          <div className="hint">Repetarea importului nu creează dubluri: obiectele se regăsesc după GUID-ul din 1C.</div>
        </div>
      )}

      <h2>Reconcilierea balanței</h2>
      {last ? (
        <table className="grid">
          <thead>
            <tr>
              <th>Cont</th>
              <th className="num">1C (Dt−Kt)</th>
              <th className="num">Aplicația</th>
              <th className="num">Diferența</th>
            </tr>
          </thead>
          <tbody>
            {last.differences.map((d) => (
              <tr key={d.account_code}>
                <td>{d.account_code}</td>
                <td className="num">{money(d.onec)}</td>
                <td className="num">{money(d.app)}</td>
                <td className="num">{money(d.difference)}</td>
              </tr>
            ))}
            {last.differences.length === 0 && (
              <tr>
                <td colSpan={4}>
                  Balanța coincide pe toate cele {last.accounts} conturi la {day(last.date)}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      ) : (
        <div className="muted">Nicio reconciliere încă.</div>
      )}

      <h2>Soldurile inițiale importate</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Cont</th>
            <th>Denumire</th>
            <th className="num">Debit</th>
            <th className="num">Credit</th>
          </tr>
        </thead>
        <tbody>
          {balances.map((b, i) => (
            <tr key={i}>
              <td>{day(b.balance_date)}</td>
              <td>{b.account_code}</td>
              <td>{b.account_name}</td>
              <td className="num">{money(b.debit)}</td>
              <td className="num">{money(b.credit)}</td>
            </tr>
          ))}
          {balances.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Nu sunt solduri importate.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <h2>Rulările de import</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>Începută</th>
            <th>Stare</th>
            <th>Rezultat</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>{day(r.started_at)}</td>
              <td>{STATUS[r.status ?? ""] ?? r.status}</td>
              <td>
                {r.stats?.error
                  ? String(r.stats.error)
                  : r.stats
                    ? `conturi noi: ${r.stats.accounts?.created ?? 0}, contrapartide: ${
                        Number(r.stats.counterparties?.created ?? 0) + Number(r.stats.counterparties?.updated ?? 0)
                      }, solduri: ${r.stats.opening_balances?.rows ?? 0}`
                    : ""}
              </td>
            </tr>
          ))}
          {runs.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                Nu au fost importuri.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
