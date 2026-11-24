import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { InvoiceJournal, InvoiceJournalRow } from "../../api/treasury";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, today } from "../../lib/format";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";
import { StatusIcon } from "../StatusIcon";

const csvCell = (v: string) => `"${v.replace(/"/g, '""')}"`;

/** Jurnalul facturilor fiscale primite: facturile pe perioadă, cu TVA pe cote și totaluri. */
export function ReceivedInvoices() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const [from, setFrom] = useState(`${today().slice(0, 4)}-01-01`);
  const [to, setTo] = useState(today());
  const [supplier, setSupplier] = useState("");
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [journal, setJournal] = useState<InvoiceJournal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${orgId}/treasury/reports/received-invoices`;

  const load = useCallback(() => {
    setError(null);
    if (from && to && from > to) return setError("Data de început e după data de sfârșit");
    const qs = new URLSearchParams();
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (supplier) qs.set("counterparty_id", supplier);
    if (state) qs.set("posted", state === "posted" ? "true" : "false");
    if (q.trim()) qs.set("q", q.trim());
    api<InvoiceJournal>(`${base}?${qs}`).then(setJournal, (e: Error) => setError(e.message));
  }, [base, from, to, supplier, state, q]);
  useEffect(load, [load]);

  const open = (r: InvoiceJournalRow) => openTab({ id: `invoice:${r.document_id}`, title: `Factura ${r.series ?? ""}${r.doc_number ?? ""}`, kind: "invoice", params: { documentId: r.document_id } });
  const exportCsv = () => {
    if (!journal) return;
    const head = ["Data", "Seria", "Număr", "Furnizor", "IDNO", "Cod TVA", "Total", "Fără TVA", "TVA", "Înregistrată"];
    const rows = journal.rows.map((r) => [day(r.doc_date), r.series ?? "", r.doc_number ?? "", r.counterparty_name ?? "", r.idno ?? "", r.vat_code ?? "", r.total, r.net, r.vat, r.is_posted ? "da" : "nu"]);
    const blob = new Blob(["﻿" + [head, ...rows].map((l) => l.map(csvCell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `facturi-fiscale-primite-${to || "toate"}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div>
      <h1>Facturi fiscale primite</h1>
      <div className="bar">
        <label>
          De la <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          Până la <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <select aria-label="Furnizor" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
          <option value="">Toți furnizorii</option>
          {catalogs.counterparties.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select aria-label="Starea" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Toate</option>
          <option value="posted">Înregistrate</option>
          <option value="draft">Neînregistrate</option>
        </select>
        <input aria-label="Căutare" placeholder="Serie, număr, furnizor…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="b" onClick={exportCsv} disabled={!journal || journal.rows.length === 0}>
          Export CSV
        </button>
      </div>
      <Messages error={error} info={null} />
      {!journal && !error && <p className="muted">Se încarcă…</p>}
      {journal && (
        <>
          <table className="grid">
            <thead>
              <tr>
                <th style={{ width: 24 }} />
                <th>Data</th>
                <th>Seria, nr.</th>
                <th>Furnizor</th>
                <th>IDNO</th>
                <th>Cod TVA</th>
                <th>e-Factura</th>
                <th className="num">Total</th>
                <th className="num">Fără TVA</th>
                <th className="num">TVA</th>
              </tr>
            </thead>
            <tbody>
              {journal.rows.map((r) => (
                <tr key={r.document_id} tabIndex={0} onDoubleClick={() => open(r)} onKeyDown={(e) => e.key === "Enter" && open(r)}>
                  <td>
                    <StatusIcon posted={r.is_posted} />
                  </td>
                  <td>{day(r.doc_date)}</td>
                  <td>
                    {r.series ?? ""} {r.doc_number}
                  </td>
                  <td>{r.counterparty_name}</td>
                  <td>{r.idno}</td>
                  <td>{r.vat_code}</td>
                  <td>{r.e_invoice_id}</td>
                  <td className="num">{money(r.total)}</td>
                  <td className="num">{money(r.net)}</td>
                  <td className="num">{money(r.vat)}</td>
                </tr>
              ))}
              {journal.rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="muted">
                    Nu sunt facturi pentru filtrele alese.
                  </td>
                </tr>
              )}
            </tbody>
            {journal.rows.length > 0 && (
              <tfoot>
                <tr>
                  <td colSpan={7}>
                    <b>Total ({journal.rows.length})</b>
                  </td>
                  <td className="num">
                    <b>{money(journal.total)}</b>
                  </td>
                  <td className="num">{money(journal.net)}</td>
                  <td className="num">{money(journal.vat)}</td>
                </tr>
              </tfoot>
            )}
          </table>
          {journal.by_rate.length > 0 && (
            <>
              <h2>TVA pe cote</h2>
              <table className="grid" style={{ maxWidth: 420 }}>
                <thead>
                  <tr>
                    <th>Cota</th>
                    <th className="num">Baza</th>
                    <th className="num">TVA</th>
                  </tr>
                </thead>
                <tbody>
                  {journal.by_rate.map((r) => (
                    <tr key={r.vat_rate}>
                      <td>{Number(r.vat_rate) ? `${Number(r.vat_rate)}%` : "fără TVA"}</td>
                      <td className="num">{money(r.base)}</td>
                      <td className="num">{money(r.vat)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
      <p className="footer-note">Suma rândului facturii include TVA; TVA se extrage din cota indicată pe rând. Dublu clic deschide factura.</p>
    </div>
  );
}
