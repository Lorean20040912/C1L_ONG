import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { day, money, today } from "../lib/format";
import { useAction } from "../lib/useAction";
import { Messages } from "./admin/Messages";
import { POSTING_ROLES, can, useShell } from "../shell/tabs";

interface Entry {
  id: number;
  document_id: string;
  entry_date: string;
  kind: "income" | "expense";
  category: string;
  amount: string;
  is_deductible: boolean;
  description: string | null;
}
interface Journal {
  entries: Entry[];
  income: string;
  expense: string;
  deductible_expense: string;
  result: string;
}

/** Registrul-jurnal de venituri și cheltuieli (partida simplă, ÎI / GȚ). */
export function SimpleJournal() {
  const { orgId, role } = useShell();
  const [data, setData] = useState<Journal | null>(null);
  const [from, setFrom] = useState(`${new Date().getFullYear()}-01-01`);
  const [to, setTo] = useState(today());
  const [form, setForm] = useState({ document_id: "", entry_date: today(), kind: "income", category: "", amount: "", is_deductible: true });
  const { busy, error, run } = useAction();
  const base = `/organizations/${orgId}/simple-ledger`;
  const editable = can(role, POSTING_ROLES);

  const load = useCallback(
    () =>
      api<Journal>(`${base}?date_from=${from}&date_to=${to}`)
        .then(setData)
        .catch(() => setData(null)),
    [base, from, to],
  );
  useEffect(() => {
    load();
  }, [load]);

  const add = () =>
    run(async () => {
      await api(`${base}/entries`, { method: "POST", body: form });
      setForm({ ...form, category: "", amount: "" });
      await load();
    });
  const remove = (id: number) =>
    run(async () => {
      await api(`${base}/entries/${id}`, { method: "DELETE" });
      await load();
    });

  return (
    <>
      <h1>Registru-jurnal de venituri și cheltuieli</h1>
      <Messages error={error} info={null} />
      <div className="bar">
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="De la" />
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Până la" />
      </div>
      {editable && (
        <div className="form">
          <label htmlFor="sj-doc">Id document</label>
          <input id="sj-doc" value={form.document_id} onChange={(e) => setForm({ ...form, document_id: e.target.value })} />
          <label htmlFor="sj-date">Data</label>
          <input id="sj-date" type="date" value={form.entry_date} onChange={(e) => setForm({ ...form, entry_date: e.target.value })} />
          <label htmlFor="sj-kind">Tipul</label>
          <select id="sj-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="income">Venit (încasare)</option>
            <option value="expense">Cheltuială (plată)</option>
          </select>
          <label htmlFor="sj-cat">Categoria</label>
          <input id="sj-cat" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <label htmlFor="sj-amt">Suma</label>
          <input id="sj-amt" value={form.amount} inputMode="decimal" onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <label htmlFor="sj-ded">Deductibilă</label>
          <input id="sj-ded" type="checkbox" checked={form.is_deductible} onChange={(e) => setForm({ ...form, is_deductible: e.target.checked })} />
          <button className="b primary" disabled={busy || !form.document_id || !form.category || !form.amount} onClick={add}>
            Adaugă
          </button>
        </div>
      )}
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Categoria</th>
            <th className="num">Venit</th>
            <th className="num">Cheltuială</th>
            <th>Deductibilă</th>
            {editable && <th />}
          </tr>
        </thead>
        <tbody>
          {data?.entries.map((e) => (
            <tr key={e.id}>
              <td>{day(e.entry_date)}</td>
              <td>{e.category}</td>
              <td className="num">{e.kind === "income" ? money(e.amount) : ""}</td>
              <td className="num">{e.kind === "expense" ? money(e.amount) : ""}</td>
              <td>{e.kind === "expense" ? (e.is_deductible ? "da" : "nu") : ""}</td>
              {editable && (
                <td>
                  <button className="b" disabled={busy} onClick={() => remove(e.id)}>
                    Șterge
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
        {data && (
          <tfoot>
            <tr>
              <th colSpan={2}>Total</th>
              <th className="num">{money(data.income)}</th>
              <th className="num">{money(data.expense)}</th>
              <th colSpan={editable ? 2 : 1}>
                Deductibile: {money(data.deductible_expense)} · Rezultat: {money(data.result)}
              </th>
            </tr>
          </tfoot>
        )}
      </table>
    </>
  );
}
