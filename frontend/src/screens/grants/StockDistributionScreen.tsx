import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Distribution, PreviewRow } from "../../api/grants";
import { grantLabel, useCatalogs } from "../../catalog/useCatalogs";
import { day, money, parseAmount, today } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { Messages, ReadOnlyNote } from "../admin/Messages";
import { POSTING_ROLES, can, useShell } from "../../shell/tabs";

/** Distribuirea stocurilor cumpărate din grant: Dt 716 — Kt 211 și Dt 537 (535) — Kt 616 (docs/11 §2.3). */
export function StockDistributionScreen() {
  const { orgId, role } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [rows, setRows] = useState<Distribution[]>([]);
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [date, setDate] = useState(today());
  const [grantId, setGrantId] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [deferred, setDeferred] = useState(false);
  const { busy, error, info, run, setError } = useAction();
  const editable = can(role, POSTING_ROLES);
  const base = `/organizations/${orgId}/stock-distributions`;

  const load = useCallback(() => {
    api<Distribution[]>(base)
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, [base, setError]);
  useEffect(load, [load]);

  const body = () => {
    const parsed = parseAmount(amount);
    if (!grantId) throw new Error("Alegeți grantul");
    if (parsed === null) throw new Error("Suma nu este validă");
    return { doc_date: date, grant_id: grantId, amount: parsed, description: description.trim(), from_deferred: deferred };
  };
  const showPreview = () => run(async () => setPreview(await api<PreviewRow[]>(`${base}/preview`, { method: "POST", body: body() })));
  const save = () =>
    run(async () => {
      await api(base, { method: "POST", body: body() });
      setPreview(null);
      setAmount("");
      setDescription("");
      load();
      return "Distribuirea a fost înregistrată.";
    });
  const cancel = (d: Distribution) =>
    run(async () => {
      await api(`${base}/${d.document_id}`, { method: "DELETE" });
      load();
      return "Distribuirea a fost anulată.";
    });

  return (
    <>
      <h1>Distribuirea stocurilor</h1>
      <ReadOnlyNote show={!editable} what="distribuirile le înregistrează contabilul" />
      <Messages error={error} info={info} />
      <table className="grid">
        <thead>
          <tr>
            <th>Nr.</th>
            <th>Data</th>
            <th>Grant</th>
            <th className="num">Suma</th>
            <th>Descrierea</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.document_id}>
              <td>{d.doc_number}</td>
              <td>{day(d.doc_date)}</td>
              <td>{grantLabel(catalogs.grants, d.grant_id)}</td>
              <td className="num">{money(d.amount)}</td>
              <td>{d.description}</td>
              <td>
                {editable && (
                  <button className="b" onClick={() => cancel(d)} disabled={busy}>
                    Anulează
                  </button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                Nu sunt distribuiri.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {editable && (
        <section>
          <h2>Distribuire nouă</h2>
          <div className="form">
            <label htmlFor="sd-date">Data</label>
            <input id="sd-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <label htmlFor="sd-grant">Grantul</label>
            <select id="sd-grant" value={grantId} onChange={(e) => setGrantId(e.target.value)}>
              <option value="">— alegeți —</option>
              {catalogs.grants.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.code} {g.title}
                </option>
              ))}
            </select>
            <label htmlFor="sd-amount">Valoarea distribuită</label>
            <input id="sd-amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <label htmlFor="sd-desc">Descrierea</label>
            <input id="sd-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="ex. mobilier predat beneficiarilor" />
            <label htmlFor="sd-def">Din venituri anticipate</label>
            <input id="sd-def" type="checkbox" checked={deferred} onChange={(e) => setDeferred(e.target.checked)} />
          </div>
          <div className="hint">Linia de buget nu se repetă: cheltuiala a fost numărată la achiziția stocului.</div>
          <div className="bar">
            <button className="b" onClick={showPreview} disabled={busy}>
              Previzualizare
            </button>
            <button className="b primary" onClick={save} disabled={busy || !description.trim()}>
              Înregistrează
            </button>
          </div>
          {preview && (
            <table className="grid">
              <thead>
                <tr>
                  <th>Dt</th>
                  <th>Kt</th>
                  <th className="num">Suma</th>
                  <th>Sursa regulii</th>
                </tr>
              </thead>
              <tbody>
                {preview.map((p, i) => (
                  <tr key={i}>
                    <td>{p.debit_account}</td>
                    <td>{p.credit_account}</td>
                    <td className="num">{money(p.amount)}</td>
                    <td className="muted">{p.source_ref}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  );
}
