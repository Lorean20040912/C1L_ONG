import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { DebtMove, SupplierDebts as Report, SupplierDebtRow } from "../../api/treasury";
import { useCatalogs } from "../../catalog/useCatalogs";
import { day, money, today } from "../../lib/format";
import { useShell } from "../../shell/tabs";
import { Messages } from "../admin/Messages";

const csvCell = (v: string) => `"${v.replace(/"/g, '""')}"`;

/** Datorii față de furnizori: sold pe 521 pe furnizori, cu vechimea datoriei și documentele care o formează. */
export function SupplierDebts() {
  const { orgId, openTab } = useShell();
  const { catalogs } = useCatalogs(orgId);
  const year = today().slice(0, 4);
  const [from, setFrom] = useState(`${year}-01-01`);
  const [to, setTo] = useState(today());
  const [supplier, setSupplier] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [report, setReport] = useState<Report | null>(null);
  const [open, setOpen] = useState<SupplierDebtRow | null>(null);
  const [moves, setMoves] = useState<DebtMove[]>([]);
  const [error, setError] = useState<string | null>(null);
  const base = `/organizations/${orgId}/treasury/reports`;

  const load = useCallback(() => {
    setError(null);
    if (from > to) return setError("Data de început e după data de sfârșit");
    const qs = new URLSearchParams({ date_from: from, date_to: to });
    if (supplier) qs.set("counterparty_id", supplier);
    api<Report>(`${base}/supplier-debts?${qs}`).then(setReport, (e: Error) => setError(e.message));
  }, [base, from, to, supplier]);
  useEffect(load, [load]);

  const showMoves = (r: SupplierDebtRow) => {
    setOpen(r);
    const qs = new URLSearchParams({ date_from: from, date_to: to });
    if (r.counterparty_id) qs.set("counterparty_id", r.counterparty_id);
    api<DebtMove[]>(`${base}/supplier-debts/moves?${qs}`).then(setMoves, (e: Error) => setError(e.message));
  };
  const openDoc = (m: DebtMove) => {
    const route = m.doc_type === "invoice" ? { kind: "invoice" as const, id: `invoice:${m.document_id}` } : null;
    if (route) openTab({ id: route.id, title: `Factura ${m.doc_number ?? ""}`, kind: "invoice", params: { documentId: m.document_id } });
    else openTab({ id: `dtkt:${m.document_id}`, title: `Dt/Kt: ${m.doc_number ?? ""}`, kind: "dtkt", params: { route: "documents", documentId: m.document_id } });
  };
  const rows = (report?.rows ?? []).filter((r) => !onlyOpen || Number(r.closing) !== 0);
  const exportCsv = () => {
    const head = ["Furnizor", "IDNO", "Sold inițial", "Debit", "Credit", "Sold final", "0-30 zile", "31-60", "61-90", ">90"];
    const lines = [head, ...rows.map((r) => [r.name, r.idno ?? "", r.opening, r.debit, r.credit, r.closing, r.age_0_30, r.age_31_60, r.age_61_90, r.age_over_90])];
    const blob = new Blob(["﻿" + lines.map((l) => l.map(csvCell).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `datorii-furnizori-${to}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div>
      <h1>Datorii față de furnizori</h1>
      <div className="bar">
        <label>
          De la <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          La data <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <select aria-label="Furnizor" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
          <option value="">Toți furnizorii</option>
          {catalogs.counterparties.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <label>
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> doar cu sold
        </label>
        <button className="b" onClick={load}>
          Actualizează
        </button>
        <button className="b" onClick={exportCsv} disabled={rows.length === 0}>
          Export CSV
        </button>
      </div>
      <Messages error={error} info={null} />
      {!report && !error && <p className="muted">Se încarcă…</p>}
      {report && (
        <table className="grid">
          <thead>
            <tr>
              <th>Furnizor</th>
              <th>IDNO</th>
              <th className="num">Sold inițial</th>
              <th className="num">Debit</th>
              <th className="num">Credit</th>
              <th className="num">Sold final</th>
              <th className="num">0–30 zile</th>
              <th className="num">31–60</th>
              <th className="num">61–90</th>
              <th className="num">&gt;90</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.counterparty_id ?? "none"} tabIndex={0} className={open === r ? "sel" : ""} onClick={() => showMoves(r)} onKeyDown={(e) => e.key === "Enter" && showMoves(r)}>
                <td>{r.name}</td>
                <td>{r.idno}</td>
                <td className="num">{money(r.opening)}</td>
                <td className="num">{money(r.debit)}</td>
                <td className="num">{money(r.credit)}</td>
                <td className="num">
                  <b>{money(r.closing)}</b>
                </td>
                <td className="num">{money(r.age_0_30)}</td>
                <td className="num">{money(r.age_31_60)}</td>
                <td className="num">{money(r.age_61_90)}</td>
                <td className="num">{money(r.age_over_90)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={10} className="muted">
                  Nu sunt datorii față de furnizori în perioada aleasă.
                </td>
              </tr>
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={2}>
                  <b>Total</b>
                </td>
                <td className="num">{money(report.total_opening)}</td>
                <td className="num">{money(report.total_debit)}</td>
                <td className="num">{money(report.total_credit)}</td>
                <td className="num">
                  <b>{money(report.total_closing)}</b>
                </td>
                <td colSpan={4} />
              </tr>
            </tfoot>
          )}
        </table>
      )}
      <p className="footer-note">Sold creditor = datorie față de furnizor. Vechimea se calculează cronologic: plățile sting cele mai vechi facturi. Clic pe un furnizor arată documentele.</p>
      {open && (
        <>
          <h2>Mișcări: {open.name}</h2>
          <table className="grid">
            <thead>
              <tr>
                <th>Data</th>
                <th>Document</th>
                <th>Conținut</th>
                <th className="num">Debit (plăți)</th>
                <th className="num">Credit (facturi)</th>
              </tr>
            </thead>
            <tbody>
              {moves.map((m, i) => (
                <tr key={i} tabIndex={0} onDoubleClick={() => openDoc(m)} onKeyDown={(e) => e.key === "Enter" && openDoc(m)}>
                  <td>{day(m.entry_date)}</td>
                  <td>{m.doc_number}</td>
                  <td>{m.description}</td>
                  <td className="num">{Number(m.debit) ? money(m.debit) : ""}</td>
                  <td className="num">{Number(m.credit) ? money(m.credit) : ""}</td>
                </tr>
              ))}
              {moves.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    Nu sunt mișcări în perioadă.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
