import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Adjustment } from "../../api/fix6";
import { grantLabel, useCatalogs } from "../../catalog/useCatalogs";
import { day, money, parseAmount, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";
import { Messages, ReadOnlyNote } from "../admin/Messages";

/** Ajustarea perioadei: înregistrare Dt/Kt la sfârșitul perioadei, cu stornare automată în luna următoare (opțional). */
export function PeriodAdjustments() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<Adjustment[]>([]);
  const [date, setDate] = useState(today());
  const [description, setDescription] = useState("");
  const [debit, setDebit] = useState("");
  const [credit, setCredit] = useState("");
  const [amount, setAmount] = useState("");
  const [grantId, setGrantId] = useState("");
  const [reverse, setReverse] = useState(false);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/period-adjustments`;

  const load = useCallback(() => {
    api<Adjustment[]>(base).then(setRows).catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const accounts = catalogs.accounts.filter((a) => !a.is_group);
  const save = () =>
    run(async () => {
      const sum = parseAmount(amount);
      if (description.trim().length < 3) throw new Error("Descrieți ajustarea");
      if (!debit || !credit) throw new Error("Alegeți contul debitor și contul creditor");
      if (debit === credit) throw new Error("Contul debitor și cel creditor trebuie să fie diferite");
      if (!sum || Number(sum) <= 0) throw new Error("Suma trebuie să fie pozitivă, cu cel mult 2 zecimale");
      await api(base, {
        method: "POST",
        body: {
          adjustment_date: date, description: description.trim(), debit_account_id: debit, credit_account_id: credit,
          amount: sum, grant_id: grantId || null, reverse_next_month: reverse,
        },
      });
      setDescription("");
      setAmount("");
      setReverse(false);
      load();
      return "Ajustarea a fost înregistrată.";
    });
  const cancel = (a: Adjustment) =>
    run(async () => {
      await api(`${base}/${a.id}/cancel`, { method: "POST" });
      load();
      return "Ajustarea a fost anulată.";
    });

  const opts = (
    <>
      <option value="">— alegeți —</option>
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>
          {a.code} {a.name}
        </option>
      ))}
    </>
  );

  return (
    <>
      <h1>Ajustarea perioadei</h1>
      <ReadOnlyNote show={!editable} what="ajustările le înregistrează contabilul" />
      <Messages error={error} info={info} />
      {editable && (
        <section>
          <h2>Ajustare nouă</h2>
          <div className="form">
            <label htmlFor="aj-date">Data</label>
            <input id="aj-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <label htmlFor="aj-desc">Descrierea</label>
            <input id="aj-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="ex. cheltuieli angajate, neprimite încă" />
            <label htmlFor="aj-d">Debit (Dt)</label>
            <select id="aj-d" value={debit} onChange={(e) => setDebit(e.target.value)}>
              {opts}
            </select>
            <label htmlFor="aj-k">Credit (Kt)</label>
            <select id="aj-k" value={credit} onChange={(e) => setCredit(e.target.value)}>
              {opts}
            </select>
            <label htmlFor="aj-sum">Suma</label>
            <input id="aj-sum" className="num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <label htmlFor="aj-grant">Grant</label>
            <select id="aj-grant" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
              <option value="">— fără grant —</option>
              {catalogs.grants.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.code} {g.title}
                </option>
              ))}
            </select>
            <label htmlFor="aj-rev">Stornare în luna următoare</label>
            <input id="aj-rev" type="checkbox" checked={reverse} onChange={(e) => setReverse(e.target.checked)} />
          </div>
          <div className="bar">
            <button className="b primary" onClick={save} disabled={busy}>
              Înregistrează
            </button>
          </div>
        </section>
      )}
      <h2>Ajustări</h2>
      <table className="grid">
        <thead>
          <tr>
            <th>Data</th>
            <th>Descrierea</th>
            <th>Dt</th>
            <th>Kt</th>
            <th className="num">Suma</th>
            <th>Grant</th>
            <th>Stornare</th>
            <th>Starea</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{day(a.adjustment_date)}</td>
              <td>{a.description}</td>
              <td>{a.debit_account}</td>
              <td>{a.credit_account}</td>
              <td className="num">{money(a.amount)}</td>
              <td>{grantLabel(catalogs.grants, a.grant_id)}</td>
              <td>{a.reversal_date ? day(a.reversal_date) : ""}</td>
              <td>{a.status === "posted" ? "înregistrată" : "anulată"}</td>
              <td>
                {editable && a.status === "posted" && (
                  <button className="b" onClick={() => cancel(a)} disabled={busy}>
                    Anulează
                  </button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={9} className="muted">
                Nu sunt ajustări.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
