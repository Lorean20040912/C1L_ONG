import { useCallback, useEffect, useState } from "react";
import { api, download } from "../../api/client";
import { day, money } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { useShell } from "../../shell/tabs";

interface Row {
  document_id: string;
  entry_date: string;
  doc_number: string | null;
  counterparty: string | null;
  counterparty_idno: string | null;
  vat_code: string | null;
  rate: string;
  base: string;
  vat: string;
  total: string;
  is_posted: boolean;
}
interface Report {
  vat_payer: boolean;
  rows: Row[];
  by_rate: { rate: string; base: string; vat: string; documents: number }[];
  by_month: { month: string; base: string; vat: string }[];
  base_total: string;
  vat_total: string;
  posted_vat_total: string;
}

/** Registrul (jurnalul) TVA al achizițiilor și decontul pe cote, din facturile primite. */
export function VatScreen() {
  const { orgId, openTab } = useShell();
  const year = new Date().getFullYear();
  const [from, setFrom] = useState(`${year}-01-01`);
  const [to, setTo] = useState(`${year}-12-31`);
  const [rate, setRate] = useState("");
  const [data, setData] = useState<Report | null>(null);
  const { error, run } = useAction();

  const params = useCallback(() => {
    const p = new URLSearchParams({ date_from: from, date_to: to });
    if (rate !== "") p.set("rate", rate);
    return p;
  }, [from, to, rate]);

  const load = useCallback(() => {
    run(async () => setData(await api<Report>(`/organizations/${orgId}/reports/vat?${params()}`)));
  }, [orgId, params, run]);
  useEffect(load, [load]);

  return (
    <>
      <h1>TVA: jurnal și decont</h1>
      <div className="bar">
        <input className="b" type="date" aria-label="De la" value={from} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        <span className="muted">—</span>
        <input className="b" type="date" aria-label="Până la" value={to} onChange={(e) => e.target.value && setTo(e.target.value)} />
        <select className="b" aria-label="Cota" value={rate} onChange={(e) => setRate(e.target.value)}>
          <option value="">Toate cotele</option>
          {["0", "8", "12", "20"].map((r) => (
            <option key={r} value={r}>
              {r}%
            </option>
          ))}
        </select>
        <button className="b primary" onClick={load}>
          Generează
        </button>
        <button className="b" onClick={() => run(() => download(`/organizations/${orgId}/reports/vat.xlsx?${params()}`, "jurnal-tva.xlsx"))}>
          Excel
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {data && !data.vat_payer && <p className="muted">Organizația nu este înregistrată plătitoare de TVA (data se setează în „Date pentru rapoarte”); cifrele sunt orientative.</p>}
      {data && (
        <>
          <h3>Decont pe cote</h3>
          <table className="grid">
            <thead>
              <tr>
                <th className="num">Cota %</th>
                <th className="num">Documente</th>
                <th className="num">Baza impozabilă</th>
                <th className="num">TVA</th>
              </tr>
            </thead>
            <tbody>
              {data.by_rate.map((t) => (
                <tr key={t.rate}>
                  <td className="num">{Number(t.rate)}</td>
                  <td className="num">{t.documents}</td>
                  <td className="num">{money(t.base)}</td>
                  <td className="num">{money(t.vat)}</td>
                </tr>
              ))}
              <tr>
                <td colSpan={2}>
                  <b>Total (TVA deductibilă din achiziții)</b>
                </td>
                <td className="num">
                  <b>{money(data.base_total)}</b>
                </td>
                <td className="num">
                  <b>{money(data.vat_total)}</b>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">Din care în documente înregistrate: {money(data.posted_vat_total)}.</p>
          {data.by_month.length > 1 && (
            <>
              <h3>Pe luni</h3>
              <table className="grid">
                <thead>
                  <tr>
                    <th>Luna</th>
                    <th className="num">Baza</th>
                    <th className="num">TVA</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_month.map((m) => (
                    <tr key={m.month}>
                      <td>{m.month.slice(0, 7)}</td>
                      <td className="num">{money(m.base)}</td>
                      <td className="num">{money(m.vat)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3>Jurnalul TVA (achiziții)</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>Data</th>
                <th>Document</th>
                <th>Furnizor</th>
                <th>IDNO</th>
                <th>Cod TVA</th>
                <th className="num">Cota %</th>
                <th className="num">Baza</th>
                <th className="num">TVA</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={`${r.document_id}:${r.rate}`}>
                  <td>{day(r.entry_date)}</td>
                  <td>
                    <button
                      className="link"
                      onClick={() => openTab({ id: `invoice:${r.document_id}`, title: `Factură primită ${r.doc_number ?? ""}`, kind: "invoice", params: { documentId: r.document_id } })}
                    >
                      {r.doc_number ?? "—"}
                    </button>
                    {!r.is_posted && <span className="muted"> · neînregistrat</span>}
                  </td>
                  <td>{r.counterparty}</td>
                  <td>{r.counterparty_idno}</td>
                  <td>{r.vat_code}</td>
                  <td className="num">{Number(r.rate)}</td>
                  <td className="num">{money(r.base)}</td>
                  <td className="num">{money(r.vat)}</td>
                  <td className="num">{money(r.total)}</td>
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="muted">
                    Nicio factură în perioadă.
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
